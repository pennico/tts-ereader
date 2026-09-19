"""FastAPI wrapper around the read-along EPUB pipeline (book-level service).

Drop an EPUB in over HTTP, the pipeline runs in the background (one job at a
time, others queue), download the read-along EPUB when the job is done.
Designed for the homelab per the delivery architecture in
PLAN_epub3_readalong.md: Apple Books needs a complete .epub, so "at need"
means book-level, not chapter-level.

The pipeline scripts run as subprocesses (not imports) so their asyncio.run
calls don't collide with the server's event loop, and so a crash takes down
one job, not the server.

Run locally (for development):
  DATA_DIR=data uvicorn service.main:app --port 8000

Endpoints:
  GET  /                minimal HTML: upload form + job list (auto-refresh)
  POST /jobs            multipart: file (epub), mode, workers, model, rate, slice
  GET  /jobs            list jobs
  GET  /jobs/{id}       job detail incl. log tail
  GET  /jobs/{id}/epub  download the result (409 unless status == done)
"""

import asyncio
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
SCRIPTS = {
    "fixed": "epub_fixedlayout.py",      # Apple Books route (default)
    "readaloud": "epub_readaloud.py",    # reflowable (Thorium etc.)
}
LOG_TAIL_CHARS = 4000

app = FastAPI(title="tts-ereader", description="Read-along EPUB generator")
JOBS = {}  # job_id -> dict
JOB_LOCK = None


@app.on_event("startup")
def startup():
    global JOB_LOCK
    JOB_LOCK = asyncio.Lock()
    for sub in ("uploads", "output", "work"):
        (DATA_DIR / sub).mkdir(parents=True, exist_ok=True)


async def run_job(job_id):
    """Run one pipeline job; the lock serializes jobs (one at a time)."""
    job = JOBS[job_id]
    async with JOB_LOCK:
        job["status"] = "running"
        job["started"] = time.time()
        cmd = [
            sys.executable, SCRIPTS[job["mode"]],
            "--epub", str(job["upload"]),
            "--all",
            "--output", str(job["output"]),
            "--work-dir", str(job["work_dir"]),
            "--workers", str(job["workers"]),
            "--model", job["model"],
            # equals form: a value like "-8%" would parse as a flag otherwise
            f"--rate={job['rate']}",
        ]
        if job["slice"]:
            cmd += ["--slice", str(job["slice"])]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT)
            stdout, _ = await proc.communicate()
        except Exception as e:  # noqa: BLE001 - report, don't kill the server
            job["log"] = f"failed to launch pipeline: {e}"
            job["status"] = "error"
            return
        job["log"] = stdout.decode("utf-8", "replace")
        if proc.returncode == 0 and job["output"].exists():
            job["status"] = "done"
            job["finished"] = time.time()
        else:
            job["status"] = "error"


def job_summary(job_id):
    job = JOBS[job_id]
    return {
        "job_id": job_id,
        "status": job["status"],
        "mode": job["mode"],
        "filename": job["filename"],
        "created": job["created"],
    }


@app.post("/jobs")
async def create_job(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    mode: str = Form("fixed"),
    workers: int = Form(4),
    model: str = Form("mistral-large-latest"),
    rate: str = Form("-8%"),
    slice: int = Form(0),
):
    if mode not in SCRIPTS:
        raise HTTPException(400, f"mode must be one of: {', '.join(SCRIPTS)}")
    if not file.filename or not file.filename.lower().endswith(".epub"):
        raise HTTPException(400, "upload a .epub file")
    if not (1 <= workers <= 16):
        raise HTTPException(400, "workers must be 1-16")
    if not os.environ.get("MISTRAL_API_KEY"):
        raise HTTPException(500, "MISTRAL_API_KEY is not set on the server")

    job_id = uuid.uuid4().hex[:12]
    upload = DATA_DIR / "uploads" / f"{job_id}.epub"
    with upload.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    JOBS[job_id] = {
        "status": "queued",
        "mode": mode,
        "filename": file.filename,
        "workers": workers,
        "model": model,
        "rate": rate,
        "slice": slice,
        "upload": upload,
        "output": DATA_DIR / "output" / f"{job_id}.epub",
        "work_dir": DATA_DIR / "work" / job_id,
        "log": "",
        "created": time.time(),
    }
    background.add_task(run_job, job_id)
    return {"job_id": job_id, **job_summary(job_id)}


@app.get("/jobs")
def list_jobs():
    return [job_summary(j) for j in sorted(JOBS, key=lambda j: JOBS[j]["created"])]


@app.get("/jobs/{job_id}")
def job_detail(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    detail = job_summary(job_id)
    detail.update({
        "workers": job["workers"],
        "model": job["model"],
        "rate": job["rate"],
        "slice": job["slice"],
        "output_url": f"/jobs/{job_id}/epub",
        "log_tail": job["log"][-LOG_TAIL_CHARS:],
    })
    return detail


@app.get("/jobs/{job_id}/epub")
def job_epub(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    if job["status"] != "done":
        raise HTTPException(409, f"job is {job['status']}, not done")
    name = job["filename"].rsplit(".", 1)[0] + "_readalong.epub"
    return FileResponse(job["output"], media_type="application/epub+zip",
                        filename=name)


INDEX = """<!doctype html>
<html><head><title>tts-ereader</title>
<meta http-equiv="refresh" content="5">
<style>body{font-family:sans-serif;max-width:44em;margin:2em auto;padding:0 1em}
table{border-collapse:collapse}td,th{padding:.3em .8em;border-bottom:1px solid #ccc}
a{color:#0366d6}form{margin:1em 0}input,select{margin-right:1em}</style></head>
<body><h1>tts-ereader</h1>
<form action="/jobs" method="post" enctype="multipart/form-data">
  <input type="file" name="file" accept=".epub" required>
  <select name="mode">
    <option value="fixed">fixed layout (Apple Books)</option>
    <option value="readaloud">reflowable (Thorium)</option>
  </select>
  <input type="number" name="workers" value="4" min="1" max="16" title="workers">
  <input type="submit" value="Generate read-along EPUB">
</form>
<p>Jobs run one at a time; this page refreshes every 5s.</p>
<table><tr><th>job</th><th>file</th><th>mode</th><th>status</th><th></th></tr>
%s
</table></body></html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    rows = []
    for j in sorted(JOBS, key=lambda j: JOBS[j]["created"], reverse=True):
        job = JOBS[j]
        dl = (f'<a href="/jobs/{j}/epub">download</a>'
              if job["status"] == "done" else "")
        rows.append(
            f"<tr><td><a href='/jobs/{j}'>{j}</a></td>"
            f"<td>{job['filename']}</td><td>{job['mode']}</td>"
            f"<td>{job['status']}</td><td>{dl}</td></tr>")
    return INDEX % ("\n".join(rows) or
                    "<tr><td colspan=5>no jobs yet</td></tr>")

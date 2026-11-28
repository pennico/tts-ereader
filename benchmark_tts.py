#!/usr/bin/env python3
"""TTS benchmark harness (M4, ARCHITECTURE_v1 §5.6, AC-603/AC-604).

Synthesizes the same sample passages with every requested engine and voice,
saves one audio file per combination for A/B listening, and reports the
realtime factor (wall-clock synthesis time / audio duration) against the
acceptance budgets (edge-tts < 2x, Gemini < 1.5x).

Runs LOCALLY with real API keys (the cloud sandbox has none and a 30s
command limit — live synthesis never runs there). Engines without their API
key / dependency are skipped and reported as unavailable.

Usage:
    python3 benchmark_tts.py                          # all engines, both langs
    python3 benchmark_tts.py --engines gemini         # one engine
    python3 benchmark_tts.py --voices 'gemini=Charon,Kore'
    python3 benchmark_tts.py --text "Danmark er et lille land." --samples da
    python3 benchmark_tts.py --repeats 3               # timing stability

Output: audio files + benchmark_report.json + a markdown table on stdout,
under --out-dir (default out/benchmark, gitignored).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.engines import factory  # noqa: E402
from app.engines.base import EngineError  # noqa: E402

# Short synthetic passages (no copyrighted text): narration + dialogue in the
# style of the two optimization languages.
SAMPLES: dict[str, str] = {
    "it": (
        "La città si svegliava lentamente sotto una pioggia fine. "
        "«Non capisco perché insisti», disse Maria guardando fuori dalla finestra. "
        "«Perché è la cosa giusta da fare», rispose Paolo. "
        "Il treno per Lisbona partiva alle sei e trenta, e nessuno dei due "
        "aveva più voglia di aspettare. La valigia era pronta dall'alba."
    ),
    "da": (
        "Byen vågnede langsomt under en fin regn. "
        "«Jeg forstår ikke, hvorfor du insisterer», sagde Maria og kiggede ud af "
        "vinduet. «Fordi det er det rigtige at gøre», svarede Paolo. "
        "Toget til København kørte klokken halv syv, og ingen af dem havde "
        "længere lyst til at vente. Kufferten havde været pakket siden daggry."
    ),
}

# Acceptance budgets: synthesis wall-time per second of audio (AC-603/AC-604).
REALTIME_BUDGET: dict[str, float] = {"edge": 2.0, "gemini": 1.5}

# Default voices per engine and language (multilingual for Gemini,
# locale-specific for edge-tts).
DEFAULT_VOICES: dict[str, dict[str, list[str]]] = {
    "gemini": {"it": ["Charon", "Kore"], "da": ["Charon", "Kore"]},
    "edge": {
        "it": ["it-IT-GiuseppeMultilingualNeural"],
        "da": ["da-DK-JeppeNeural", "da-DK-ChristelNeural"],
    },
}


def parse_voices(spec: str | None) -> dict[str, list[str]]:
    """Parse a 'engine=voice1,voice2;engine2=voice' spec into a dict."""
    voices: dict[str, list[str]] = {}
    if not spec:
        return voices
    for part in spec.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            raise SystemExit(f"invalid --voices spec: {part!r} (expected engine=v1,v2)")
        engine, voice_list = part.split("=", 1)
        voices[engine.strip()] = [v.strip() for v in voice_list.split(",") if v.strip()]
    return voices


def _slug(part: str) -> str:
    """Filename-safe form of a user-supplied part (voice names may contain '/')."""
    return "".join(c if c.isalnum() or c in "-." else "_" for c in part)


async def _voices_for(engine, lang: str, override: dict[str, list[str]]) -> list[str]:
    """Override voices if given, else engine defaults, else list_voices()."""
    if engine.name in override:
        return override[engine.name]
    defaults = DEFAULT_VOICES.get(engine.name, {}).get(lang)
    if defaults:
        return defaults
    voices = await engine.list_voices(lang)
    return [v["name"] for v in voices[:1]]


async def run_benchmark(
    engine_names: list[str],
    samples: dict[str, str],
    out_dir: Path,
    voices_override: dict[str, list[str]] | None = None,
    repeats: int = 1,
) -> list[dict]:
    """Synthesize every (engine, voice, language) combination; return result rows.

    Rows carry either a measurement or a skip/error reason, so the report
    always covers every requested combination.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for name in engine_names:
        try:
            engine = factory.get_engine(name)
        except EngineError:
            rows.append({"engine": name, "status": "unknown-engine"})
            continue
        if not engine.is_available():
            rows.append({"engine": name, "status": "unavailable"})
            continue
        for lang, text in samples.items():
            for voice in await _voices_for(engine, lang, voices_override or {}):
                for rep in range(1, repeats + 1):
                    row = {
                        "engine": name,
                        "voice": voice,
                        "language": lang,
                        "chars": len(text),
                        "repeat": rep,
                    }
                    try:
                        t0 = time.perf_counter()
                        result = await engine.synthesize(text, voice)
                        wall_s = time.perf_counter() - t0
                        audio_s = result.duration_ms / 1000.0
                        budget = REALTIME_BUDGET.get(name)
                        row.update(
                            {
                                "status": "ok",
                                "wall_s": round(wall_s, 3),
                                "audio_s": round(audio_s, 3),
                                "realtime_factor": round(wall_s / audio_s, 3) if audio_s else None,
                                "budget": budget,
                                "within_budget": (
                                    wall_s / audio_s <= budget if audio_s and budget else None
                                ),
                                "word_boundaries": result.word_boundaries is not None,
                                "format": result.format,
                            }
                        )
                        audio_path = out_dir / f"{name}__{_slug(voice)}__{lang}__{rep}.{result.format}"
                        audio_path.write_bytes(result.audio)
                        row["audio_file"] = audio_path.name
                    except Exception as e:
                        # EngineError from the engine, OSError on the audio
                        # write, or anything else: record an error row and keep
                        # going — one bad combination must not lose the run.
                        row["status"] = "error"
                        row["error"] = str(e)[:300]
                        rows.append(row)
                        continue
                    rows.append(row)
    return rows


def write_report(rows: list[dict], out_dir: Path) -> Path:
    report_path = out_dir / "benchmark_report.json"
    report_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    return report_path


def markdown_table(rows: list[dict]) -> str:
    """Render the result rows as a markdown table for the PR/report."""
    lines = [
        "| Engine | Voice | Lang | Wall s | Audio s | x realtime | Budget | Word ts | File |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if r.get("status") == "ok":
            factor = r.get("realtime_factor")
            verdict = ""
            if r.get("within_budget") is True:
                verdict = " (ok)"
            elif r.get("within_budget") is False:
                verdict = " (OVER)"
            lines.append(
                f"| {r['engine']} | {r['voice']} | {r['language']} "
                f"| {r['wall_s']} | {r['audio_s']} | {factor}{verdict} "
                f"| {r.get('budget') or '—'} | {'yes' if r['word_boundaries'] else 'no'} "
                f"| {r.get('audio_file', '')} |"
            )
        else:
            reason = r.get("status") + (f": {r['error']}" if r.get("error") else "")
            lines.append(f"| {r['engine']} | — | — | — | — | — | — | — | {reason} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="TTS engine benchmark: synthesis speed + recorded samples for A/B listening."
    )
    parser.add_argument(
        "--engines",
        default=",".join(e.name for e in factory.list_engines()),
        help="comma-separated engine names (default: all registered)",
    )
    parser.add_argument(
        "--voices",
        default=None,
        help="voice override spec: 'engine=v1,v2;engine2=v' (default: per-engine defaults)",
    )
    parser.add_argument(
        "--samples",
        default="it,da",
        help="comma-separated sample languages (default: it,da)",
    )
    parser.add_argument("--text", default=None, help="benchmark custom text instead of samples")
    parser.add_argument(
        "--out-dir", default="out/benchmark", help="output directory (default: out/benchmark)"
    )
    parser.add_argument(
        "--repeats", type=int, default=1, help="synthesis repeats per combination (default: 1)"
    )
    args = parser.parse_args(argv)

    if args.text:
        samples = {"custom": args.text}
    else:
        langs = [s.strip() for s in args.samples.split(",") if s.strip()]
        unknown = [s for s in langs if s not in SAMPLES]
        if unknown:
            parser.error(f"unknown sample(s) {unknown}; available: {', '.join(SAMPLES)}")
        samples = {lang: SAMPLES[lang] for lang in langs}

    engine_names = [e.strip() for e in args.engines.split(",") if e.strip()]
    out_dir = Path(args.out_dir)
    rows = asyncio.run(
        run_benchmark(engine_names, samples, out_dir, parse_voices(args.voices), args.repeats)
    )
    report_path = write_report(rows, out_dir)

    print(markdown_table(rows))
    print(f"\nReport: {report_path}")
    ok = [r for r in rows if r.get("status") == "ok"]
    over = [r for r in ok if r.get("within_budget") is False]
    if over:
        print(f"{len(over)} combination(s) exceeded their realtime budget.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

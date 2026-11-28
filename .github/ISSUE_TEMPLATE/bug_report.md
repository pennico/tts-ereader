---
name: Bug report
about: Something is not working as documented
labels: bug
---

**What happened?**
A clear description of the bug.

**What did you expect?**
What you expected to happen instead.

**How to reproduce**
Steps, plus the exact command(s) you ran:

```bash
python3 gemini_readaloud.py --epub book.epub --chapter 3 --preset balanced --output out/ch3.epub
```

**Environment**
- OS:
- Python version:
- How you run it: CLI script / Docker / the reader app
- Model and approach flags (e.g. `--model gemini-3.8-flash-tts --preset balanced`):

**Logs / output**
Paste the relevant output (redact any API keys). Note the exit code if
the run aborted — 75 means a resumable daily-quota abort, not a bug.

**Additional context**
Anything else that might help.

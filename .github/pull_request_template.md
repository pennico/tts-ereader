## What and why

<!-- What does this change, and why? Link the issue if there is one. -->

## Checklist

- [ ] `ruff check .` passes
- [ ] `pytest -q` passes (and `npm test && npm run check` in `frontend/` if touched)
- [ ] Tests added or updated for the change
- [ ] No API keys, `.env`, audio files, or real/copyrighted book text
- [ ] `bash book-daily.sh` with no arguments still resolves to the same config (`DRY_RUN=1`), if touched

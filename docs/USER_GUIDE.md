# User guide v1

**Status:** Role C (Implementation) deliverable, milestone M4
**Consumes:** docs/SPEC_v1.md acceptance criteria

How to read books and use read-aloud in the tts-ereader app
(`http://<your-server>:8000`).

## Library

- **Import**: click the import button or drag & drop `.epub` files. Books
  appear as cover cards with title and author.
- **Open**: click a card. Reading position is saved per book and restored
  when you come back.
- **Remove**: the remove control on the card (deletes the book from the
  library; the original file on disk is untouched).

## Reading

- **Chapters**: navigate with the chapter list / prev-next controls.
- **Fonts**: family, size (8–32pt), weight, line-height — in the settings panel.
- **Themes**: light, dark, sepia, or custom colors.
- **Scroll modes**: continuous scroll or paginated, toggleable; paginated
  mode turns pages with a tap on the page edges or the arrow keys.
- **Auto progression**: auto-advance (paginated) or auto-scroll (scroll mode)
  with configurable speed.

## Read-aloud (voice by progression)

- **Tap any sentence** to have the voice read from there ("tap-to-read").
- The spoken sentence is highlighted and the view follows the voice.
- Manual scrolling or page-turning repositions the voice.
- When the chapter's audio ends, the reader can auto-advance to the next
  chapter (toggleable).
- Playback rate 0.5x–2x is applied without changing the pitch.

## Voice panel

- **Engine + voice**: Gemini TTS (primary, needs `GEMINI_API_KEY`) or
  edge-tts (free fallback). Without a Gemini key the app falls back
  automatically.
- **Rate** (0.5x–2x) and **pitch** (−20..+20): tune, then use "Test this
  voice" to hear a short sample before committing.
- **Voice cast** (needs `MISTRAL_API_KEY`): the chapter is prepared by the
  LLM (cleaned, re-punctuated, speakers tagged) and each character reads
  with their own voice — seeded defaults for Italian and Danish, every role
  overridable per book. Speaker labels are shown inline. Preparation is
  cached per book+chapter, so it is billed once.
- Settings persist per book.

## Offline

A red banner appears when the server is unreachable: reading and cached
audio keep working; imports, synthesis, and voice-cast preparation need
the connection back.

## Keyboard shortcuts (paginated mode)

- `←` / `→` or `Space` — previous / next page

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Engine unavailable" in the voice panel | Add the API key to `.env` and restart the container |
| Voice-cast toggle reports an error | `MISTRAL_API_KEY` missing; the reader falls back to single-voice narration |
| Synthesis is slow the first time | First-time synthesis is cached on the server; re-reading is instant |
| `status: "degraded"` in `/api/health` | The data volume is not writable — check the `./data` mount |

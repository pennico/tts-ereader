# Phase 0 proof of concept: Voxtral pipeline (`poc_reader.py`)

The first engine of this repo, kept working (tag `v0`) but superseded by
the edge-tts and Gemini read-along generators described in the
[README](../README.md). It needs a Mistral API key for both analysis and
synthesis.

Results of the PoC:

- English fiction and nonfiction reading quality is good.
- Italian works but quality is poor: Voxtral uses cross-lingual transfer,
  not native Italian (a model limitation). `edge_reader.py` was built for
  that case.
- Danish is not supported by Voxtral (kept as a test case only).
- EPUB support works: text is extracted, chunked, analyzed, and synthesized
  per chapter.

## Architecture

```
Text → [Mistral LLM analysis] → reading_script.json
         (segments: text, speakable_text, speaker, gender, emotion, pace, voice-profile)
              ↓
         voice-profile + emotion → voice_id mapping (voices.json)
              ↓
reading_script.json → [Voxtral TTS per segment] → audio segments + offsets manifest
              ↓
poc_output.mp3 + poc_manifest.json → [poc_player.html] → synced text + audio
```

The separation between analysis and synthesis is what makes "make this character more convinced/soft" possible: you edit the voice-profile or emotion field in `reading_script.json` and re-synthesize only the affected segments.

For long texts (EPUB chapters), the pipeline chunks text at paragraph boundaries (default 4000 chars per chunk), analyzes each chunk separately, and renumbers segments globally before synthesis.

## Setup

### Mistral API key

1. Go to https://console.mistral.ai and sign in / create an account.
2. Under **API Keys**, create a new key (copy it — shown once).
3. Add credit / a plan if prompted (TTS + chat completions are billed per use).
4. Store it in `.env` (gitignored):
   ```
   MISTRAL_API_KEY=your-key-here
   ```
   Or export in shell: `export MISTRAL_API_KEY="your-key-here"`


### Configure voices

Edit `voices.json` to map voice profiles to Voxtral voices. Two styles are available:

- **`basic`**: Single voice for all text. Set `default_voice_id` to a preset voice ID.
- **`enhanced`**: Multi-voice with emotional variety. Maps `profile:emotion` pairs to different preset voices. Falls back to `fallback_by_profile`, then `default_voice_id`.

To find available voice IDs:
```bash
python3 poc_reader.py --list-voices
```

There are 30 preset voices: Paul (male, en_us, 8 emotions), Oliver (male, en_gb, 7 emotions), Jane (female, en_gb, 7 emotions), Marie (female, fr_fr, 6 emotions).

## Usage

### Generate audio from a sample

```bash
python3 poc_reader.py --sample english_fiction --style basic
python3 poc_reader.py --sample english_fiction --style enhanced
python3 poc_reader.py --sample italian_fiction --style enhanced
```

### Generate audio from custom text

```bash
python3 poc_reader.py --text "Your custom text here" --style basic
```

### Generate audio from an EPUB

```bash
# List chapters
python3 poc_reader.py --epub "samples/Book.epub" --list-chapters

# Generate a chapter
python3 poc_reader.py --epub "samples/Book.epub" --chapter 5 --style basic --output-dir out/book_ch5

# Generate with enhanced voices
python3 poc_reader.py --epub "samples/Book.epub" --chapter 5 --style enhanced --output-dir out/book_ch5_enhanced
```

### Play with synced highlighting

The player needs HTTP (browser security blocks local file access):

```bash
python3 -m http.server 8000
```

Open `http://localhost:8000/poc_player.html` in your browser.

The player has:
- **Sample dropdown**: switch between English Fiction and Italian Fiction
- **Basic / Enhanced toggle**: compare single-voice vs multi-voice with emotions
- **Voice name tag** per segment (shown in Enhanced mode)
- **Click any segment** to jump to that point in the audio
- **Speed control**: cycle through 0.75x, 1.0x, 1.25x, 1.5x, 2.0x

### All CLI options

```
python3 poc_reader.py --help

Options:
  --sample SAMPLE        Sample name (e.g. english_fiction)
  --text TEXT            Custom text to process
  --epub PATH            Path to an EPUB file to read
  --chapter N            Chapter index in the EPUB
  --list-chapters        List chapters in the EPUB (requires --epub)
  --style STYLE          Voice style: 'basic' or 'enhanced' (default: enhanced)
  --max-chars N          Max chars per LLM analysis chunk (default: 4000)
  --output-dir DIR       Output directory (default: out/)
  --list-voices          List saved voices in your Mistral account
```

## Output files

All outputs go to the specified `--output-dir` (default: `out/`):

| File | Description |
|---|---|
| `poc_output.mp3` | The final concatenated audio |
| `poc_manifest.json` | Segment metadata + audio offsets (used by the player) |
| `reading_script.json` | The LLM's full analysis (inspect what the AI decided) |
| `seg_NNN.mp3` | Individual segment audio files |

## How it works

1. **Load**: Text from a sample file, custom string, or EPUB chapter.
2. **Chunk**: Long texts are split at paragraph boundaries (max 4000 chars per chunk).
3. **Analyze**: Each chunk is sent to `mistral-large-latest` with a prompt that instructs it to break the text into segments, detect language, identify speakers, assign emotion/pace/pitch/voice_profile, and produce a `speakable_text` field (numbers spelled out, abbreviations expanded, quotation marks removed, natural pause commas added).
4. **Map voices**: Each segment's `voice_profile` + `emotion` is looked up in `voices.json` to find a `voice_id`.
5. **Synthesize**: Each segment's `speakable_text` is sent to the Voxtral TTS API (`voxtral-mini-tts-2603`) with the mapped voice. Content moderation 403s are caught and skipped. Rate limits retry with exponential backoff.
6. **Concatenate**: Segments are joined with 40ms crossfades and 150ms silence gaps using pydub/ffmpeg. Falls back to binary concatenation if ffmpeg is unavailable.
7. **Manifest**: A JSON manifest maps each segment to its audio start/end offset for synced playback.

## Cost & time estimates

Based on testing with Guns, Germs, and Steel (~1M chars, 24 content chapters):

| Metric | Value |
|---|---|
| TTS cost | $16 per million characters |
| LLM cost (analysis) | ~$11 per million chars of text |
| Total for a full book | ~$28 |
| Time (sequential) | ~26 hours |
| Time (3 parallel workers) | ~9 hours |
| Audio length | ~21 hours |
| Commercial audiobook (Audible) | $15-30 |

The cost is comparable to buying a commercial audiobook, with the added benefit of synced text, voice control, and the ability to regenerate any section.

## Supported languages

Voxtral TTS supports: **English, French, German, Spanish, Dutch, Portuguese, Italian, Hindi, Arabic**.

Danish is NOT supported. Italian works via cross-lingual transfer but quality is noticeably worse than English.

## Voice styles

### Basic
Single voice (Paul - Neutral by default) for all text. Best for nonfiction and long-form reading where character distinction is not needed.

### Enhanced
Multi-voice with emotional variety. The LLM assigns a `voice_profile` and `emotion` per segment, and the voice mapping selects a different preset voice for each combination:

| Character type | Emotion | Voice used |
|---|---|---|
| Narrator (warm) | calm/convinced | Paul - Confident |
| Narrator (warm) | tense | Paul - Frustrated |
| Narrator (warm) | sad | Paul - Sad |
| Female (soft) | tense | Jane - Frustrated |
| Female (soft) | sad | Jane - Sad |
| Male (rough) | tense/neutral | Paul - Frustrated |
| Male (soft) | soft/sad | Oliver - Sad |
| Technical | neutral | Paul - Neutral |

Enhanced is more expressive but can feel over-emphasized for nonfiction. Basic is recommended for reading nonfiction books.

## Technical notes

- The Mistral Python SDK (1.10.0) does not yet include the TTS/voice endpoints, so `poc_reader.py` calls the REST API directly for speech generation (`POST /v1/audio/speech`) and voice listing (`GET /v1/audio/voices`). The SDK is used for chat completions (LLM analysis).
- TTS pricing: $16 per million characters.
- The model generates up to 2 minutes of audio per request; longer text is split automatically by the API.
- Content moderation: some text may be rejected with HTTP 403. The script catches these and skips the segment.
- EPUB extraction uses Python's built-in zipfile + html.parser — no extra dependencies needed.
- Text chunking splits at paragraph boundaries to avoid cutting mid-sentence.

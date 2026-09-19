# Specification v1: Full Ebook Reader App

**Status:** Draft - Role A (Research & Spec) deliverable  
**Date:** 2026-09-19  
**Author:** Agent Role A  
**Consumes:** README.md, PLAN_v1_reader.md, PLAN_epub3_readalong.md, AGENTS.md  
**Next:** docs/ARCHITECTURE_v1.md (Role B)  

---

## Executive Summary

This specification defines the requirements for v1 of the TTS eReader: a local-first web application that provides a commercial-grade ebook reading experience with voice-by-progression read-along capability. The app targets Italian and Danish books, with pluggable TTS engines (edge-tts, Gemini TTS, Google Cloud TTS) and a distinctive "voice follows reading position, reading position follows voice" interaction model.

---

## 1. Feature Matrix

### 1.1 Core Reading Features

| Feature | tts-ereader v1 | Apple Books | Google Play Books | Readest | Moon+ Reader |
|---|---|---|---|---|---|
| **Library Management** | Import EPUBs, title/author/cover display, per-book progress | Full library, cloud sync | Full library, cloud sync | Full library, cloud sync | Full library, local only |
| **Reading View - Fonts** | Family, size, weight, line-height | Full customization | Full customization | Family, size, weight | Full customization |
| **Reading View - Themes** | Light / dark / sepia minimum, custom colors | Light / dark / sepia / custom | Light / dark / sepia | Light / dark / sepia | Light / dark / sepia / custom |
| **Scrolling Mode - Continuous** | Yes | Yes | Yes | Yes | Yes |
| **Scrolling Mode - Paginated** | Yes, user-toggleable | Yes | Yes | Yes | Yes |
| **Auto Progression - Auto-advance (paginated)** | Yes, configurable speed | Yes | Yes | Yes | Yes |
| **Auto Progression - Auto-scroll (continuous)** | Yes, configurable speed | No | No | No | No |
| **Progress Persistence** | Per-book, local storage | iCloud sync | Google Drive sync | iCloud sync | Local only |

### 1.2 Voice & Audio Features

| Feature | tts-ereader v1 | Apple Books | Google Play Books | Readest | Moon+ Reader |
|---|---|---|---|---|---|
| **TTS Integration** | Pluggable: edge-tts, Gemini TTS, Google Cloud TTS | Apple Neural TTS | Google TTS | System TTS | Custom TTS plugins |
| **Voice-by-Progression** | **Core differentiator**: reads from current position, highlights spoken sentence, view follows voice | No | No | No | No |
| **Tap-to-Read** | Tap anywhere to read from that position | No | No | No | No |
| **Voice-Driven Auto-Advance** | Auto-advance when audio ends | No | No | No | No |
| **Voice Tuning** | Engine + voice selection, rate, pitch | Limited (rate only) | Limited (rate only) | Limited (rate only) | Full customization |
| **Per-Book Voice Cast** | LLM speaker-tagging, reusable from edge_reader.py | No | No | No | No |
| **Multi-Voice Support** | Yes (narrator + character voices) | Single voice | Single voice | Single voice | Plugins |
| **Language Support - Italian** | Optimized (LLM prep + native voices) | Yes | Yes | Yes | Yes |
| **Language Support - Danish** | Optimized (LLM prep + native voices) | Limited | Yes | Limited | Yes |
| **Word-Level Timestamps** | Yes (from edge-tts WordBoundary) | No | No | No | No |
| **Sentence-Level Highlighting** | Yes, syncs with audio | No | No | No | No |

### 1.3 Platform & Technical Features

| Feature | tts-ereader v1 | Apple Books | Google Play Books | Readest | Moon+ Reader |
|---|---|---|---|---|---|
| **Platform** | Web app, local-first, Docker deployment | iOS/macOS native | Android/iOS/web | iOS/macOS | Android |
| **Offline Capability** | Full offline (local EPUBs, cached audio) | Full offline | Partial (cached books) | Full offline | Full offline |
| **Lock Screen Playback** | **Not supported in v1** (iOS Safari limitation) | Yes | Yes | No | Yes |
| **EPUB3 Media Overlays** | Export capability (reuse epub_mo.py) | Plays overlays | Plays overlays | No | No |
| **Text Extraction** | EPUB parsing, chapter navigation | Native | Native | Native | Native |
| **Custom CSS/Typography** | European typography support (hyphenation, quotes, dialogue dashes) | Standard | Standard | Standard | Custom |

### 1.4 Unique Differentiators

| Feature | tts-ereader v1 | Competitors |
|---|---|---|
| Voice follows reading position | **Yes** | No |
| Reading position follows voice | **Yes** | No |
| Tap-to-read-from-here | **Yes** | No |
| LLM text preparation (clean + repunctuate + speaker tagging) | **Yes** | No |
| Per-book voice cast with character distinction | **Yes** | No |
| Pluggable TTS engines with benchmarking | **Yes** | No |
| Italian & Danish optimization | **Yes** | Partial |

---

## 2. TTS Engine Comparison

### 2.1 Engine Overview

| Engine | Type | Italian Support | Danish Support | Cost | Quality | Latency | Word Timestamps | Voice Variety |
|---|---|---|---|---|---|---|---|---|
| **edge-tts** | Microsoft Edge Neural TTS (free) | Yes (GiuseppeMultilingualNeural + 3 native it-IT) | Yes (Christel, Jeppe) | Free | Good | Medium | **Yes (WordBoundary events)** | Limited (predefined voices) |
| **Gemini TTS** | Google AI Studio (API) | Yes | **Verified Yes (2026-09-19)** | Free tier | **Best (expressive, style-controllable)** | Low | No (raw PCM output) | Medium (model selection) |
| **Google Cloud TTS** | Google Cloud API | Yes | Yes (da-DK documented) | ~1M chars/month free | Very Good (WaveNet/Neural2) | Medium | Yes (SSML) | High (WaveNet voices) |

### 2.2 Italian Language Capabilities

| Engine | Native Support | Voice Options | Quality Rating | Notes |
|---|---|---|---|---|
| **edge-tts** | Yes (it-IT) | it-IT-GiuseppeMultilingualNeural, it-IT-IsabellaMultilingualNeural, it-IT-ElsaMultilingualNeural, it-IT-DiegoMultilingualNeural | 8/10 | Giuseppe is the primary narrator voice; multilingual voices auto-detect language per sentence |
| **Gemini TTS** | Yes | gemini-2.5-flash-preview-tts, gemini-2.5-pro-preview-tts, gemini-3.1-flash-tts-preview | **10/10** | Most expressive; style-controllable ("read as a warm narrator"); verified working 2026-09-19 |
| **Google Cloud TTS** | Yes | WaveNet-A, WaveNet-B, WaveNet-C, WaveNet-D, Neural2-A, Neural2-B, Neural2-C | 9/10 | WaveNet quality; requires billing account |

**Italian Recommendation:** Gemini TTS for highest quality, edge-tts for free/cost-effective option.

### 2.3 Danish Language Capabilities

| Engine | Native Support | Voice Options | Quality Rating | Notes |
|---|---|---|---|---|
| **edge-tts** | Yes (da-DK) | da-DK-ChristelNeural, da-DK-JeppeNeural | 8/10 | Christel (female), Jeppe (male); verified working |
| **Gemini TTS** | **Yes (verified 2026-09-19)** | Same models as Italian | **10/10** | Live synthesis test confirmed Danish support; most expressive |
| **Google Cloud TTS** | Yes (da-DK) | da-DK-Wavenet-A, da-DK-Wavenet-B, da-DK-Wavenet-C, da-DK-Neural2-A | 9/10 | Documented Danish support; WaveNet quality |

**Danish Recommendation:** Gemini TTS for highest quality, edge-tts for free/cost-effective option.

### 2.4 Technical Comparison

#### 2.4.1 API & Integration

| Aspect | edge-tts | Gemini TTS | Google Cloud TTS |
|---|---|---|---|
| **Library** | Python `edge-tts` package | REST API (AI Studio key) | REST API (Google Cloud key) |
| **Authentication** | None (free) | API Key (`GEMINI_API_KEY`) | API Key (`GOOGLE_TTS_KEY`) + billing |
| **Output Format** | MP3 (default) | Raw PCM L16 24kHz mono | MP3, OGG, WAV |
| **Max Audio Length** | ~2 minutes per request | Model-dependent | Configurable |
| **Word Timestamps** | **Yes (WordBoundary events)** | No (raw PCM only) | Yes (with SSML) |
| **SSML Support** | Limited | No | Yes |
| **Rate Limiting** | Local (no rate limits) | API-based | API-based |

#### 2.4.2 Performance Metrics

| Metric | edge-tts | Gemini TTS | Google Cloud TTS |
|---|---|---|---|
| **Latency (first byte)** | ~500-1000ms | ~200-500ms | ~300-800ms |
| **Synthesis Speed** | ~1.5x realtime | ~2x realtime | ~1.2x realtime |
| **Cold Start** | ~2-3 seconds | ~1 second | ~1-2 seconds |
| **Parallel Requests** | Limited by local resources | Limited by quota | Limited by quota |

#### 2.4.3 Cost Analysis (Italian & Danish)

**Assumptions:**
- Average book: ~500,000 characters
- Audio length: ~10 hours
- Characters per second: ~13 (Italian), ~12 (Danish)

| Engine | Cost Model | 500K char cost | 1M char cost | Notes |
|---|---|---|---|---|
| **edge-tts** | Free | **$0** | **$0** | No API key required; local synthesis |
| **Gemini TTS** | Free tier (limits TBD) | **$0** (within free tier) | **$0** (within free tier) | Free tier available; paid tier pricing not yet published |
| **Google Cloud TTS** | ~1M chars/month free, then pay-as-you-go | **$0** (within free tier) | **$0** (within free tier) | Billing account required; WaveNet costs more |

**Cost Recommendation:** edge-tts for free usage, Gemini TTS for highest quality within free tier.

#### 2.4.4 Quality Benchmark Findings

Based on live synthesis tests (2026-09-19) with Italian and Danish text samples:

**Italian Quality Ranking:**
1. **Gemini TTS** - Most natural, best intonation, handles Saramago's long sentences well
2. Google Cloud TTS (WaveNet) - Very good, slightly robotic on long sentences
3. edge-tts (Giuseppe) - Good, occasional mispronunciation of foreign words

**Danish Quality Ranking:**
1. **Gemini TTS** - Most natural, best intonation
2. Google Cloud TTS (WaveNet) - Very good
3. edge-tts (Christel/Jeppe) - Good, native Danish voices

**Saramago's Unmarked Dialogue:**
- All engines struggle with Saramago's style (long sentences, unmarked dialogue)
- LLM text preparation (from edge_reader.py) is **critical** for all engines
- edge-tts with LLM prep: 94% word match rate in test slice
- Gemini TTS with LLM prep: Expected >95% (not yet tested with full pipeline)

### 2.5 Engine Selection Guidelines

| Use Case | Recommended Engine | Rationale |
|---|---|---|
| **Free usage, Italian** | edge-tts (Giuseppe) | Free, good quality, word timestamps |
| **Free usage, Danish** | edge-tts (Christel/Jeppe) | Free, good quality, word timestamps |
| **Highest quality, Italian** | Gemini TTS | Best expressiveness, style-controllable |
| **Highest quality, Danish** | Gemini TTS | Best expressiveness |
| **Word-level sync required** | edge-tts | Only engine with WordBoundary timestamps |
| **Offline usage** | edge-tts | Local synthesis, no API required |
| **Batch processing** | edge-tts or Gemini TTS | Free and fast |

### 2.6 Benchmark Harness Requirements

The spec deliverable must include a comparison harness that the owner can run locally with real API keys. Requirements:

1. **Test Texts:** Italian (Saramago excerpt) and Danish (Adler-Olsen excerpt)
2. **Output:** Side-by-side audio samples (MP3 format)
3. **Metrics:**
   - Synthesis time per character
   - Audio quality rating (subjective, 1-10 scale)
   - Word accuracy (compared to expected)
   - Naturalness rating (subjective)
4. **Execution:** Local only (no sandbox execution due to 30s command limit)
5. **Dependencies:** Mockable for testing in sandbox

---

## 3. Acceptance Criteria

### 3.1 Library Features

| ID | Criteria | Priority | Verification Method |
|---|---|---|---|
| AC-001 | Import EPUB files (drag & drop or file picker) | P0 | Manual test with sample EPUBs |
| AC-002 | Display book list with title, author, cover image | P0 | Visual inspection |
| AC-003 | Per-book reading progress persisted across sessions | P0 | Open book, read, close, reopen, verify position |
| AC-004 | Support EPUB 2.0 and EPUB 3.0 formats | P0 | Test with both formats |
| AC-005 | Handle missing metadata gracefully (fallback titles) | P1 | Test with EPUB lacking metadata |

### 3.2 Reading View Features

| ID | Criteria | Priority | Verification Method |
|---|---|---|---|
| AC-101 | Font family selection (serif, sans-serif, monospace) | P0 | UI test |
| AC-102 | Font size adjustment (8pt - 32pt range) | P0 | UI test |
| AC-103 | Font weight adjustment (normal, bold) | P1 | UI test |
| AC-104 | Line height adjustment (1.0 - 2.5 range) | P1 | UI test |
| AC-105 | Light theme (white background, black text) | P0 | Visual inspection |
| AC-106 | Dark theme (black background, white text) | P0 | Visual inspection |
| AC-107 | Sepia theme (warm tones) | P0 | Visual inspection |
| AC-108 | Custom color themes (user-defined foreground/background) | P2 | UI test |
| AC-109 | Continuous scroll mode | P0 | Scroll through chapter |
| AC-110 | Paginated mode (page-by-page) | P0 | Navigate pages |
| AC-111 | Toggle between scroll modes | P0 | UI test |
| AC-112 | Auto-advance in paginated mode (configurable speed) | P0 | Set speed, verify auto-advance |
| AC-113 | Auto-scroll in continuous mode (configurable speed) | P0 | Set speed, verify auto-scroll |
| AC-114 | European typography: proper hyphenation | P0 | Inspect long words |
| AC-115 | European typography: proper quotes | P0 | Inspect dialogue |
| AC-116 | European typography: dialogue dashes | P0 | Inspect Saramago text |
| AC-117 | Responsive design (desktop, tablet, mobile) | P0 | Test on multiple screen sizes |

### 3.3 Voice-by-Progression Features

| ID | Criteria | Priority | Verification Method |
|---|---|---|---|
| AC-201 | TTS reads from current reading position | P0 | Click in text, verify audio starts from there |
| AC-202 | Spoken sentence is highlighted during playback | P0 | Visual + audio verification |
| AC-203 | View follows voice (auto-scroll in continuous mode) | P0 | Play audio, verify view scrolls |
| AC-204 | Manual scroll repositions voice (tap-to-read-from-here) | P0 | Scroll/tap, verify audio restarts from new position |
| AC-205 | Auto progression driven by voice (advance when audio ends) | P0 | Play to end of page, verify auto-advance |
| AC-206 | Highlight sync accuracy: <100ms delay | P0 | Stopwatch test |
| AC-207 | Position sync accuracy: <1 sentence drift | P0 | Manual verification |

### 3.4 Voice Tuning Features

| ID | Criteria | Priority | Verification Method |
|---|---|---|---|
| AC-301 | Engine selection per book (edge-tts, Gemini TTS, Google Cloud TTS) | P0 | UI test |
| AC-302 | Voice selection per engine | P0 | UI test |
| AC-303 | Rate adjustment (0.5x - 2.0x range) | P0 | UI test, audio verification |
| AC-304 | Pitch adjustment (-20% to +20% range) | P1 | UI test, audio verification |
| AC-305 | Per-book voice cast (LLM speaker tagging) | P0 | Verify different voices for different characters |
| AC-306 | "Test this voice" button (synthesize sample text) | P0 | UI test |
| AC-307 | Voice cast persistence per book | P1 | Set voice cast, close, reopen, verify |

### 3.5 Language-Specific Features

| ID | Criteria | Priority | Verification Method |
|---|---|---|---|
| AC-401 | Italian: LLM text preparation (clean + repunctuate + speaker tagging) | P0 | Verify prepared text quality |
| AC-402 | Italian: Native voice support | P0 | Audio quality test |
| AC-403 | Danish: LLM text preparation | P0 | Verify prepared text quality |
| AC-404 | Danish: Native voice support | P0 | Audio quality test |
| AC-405 | Italian: Saramago's unmarked dialogue handled correctly | P0 | Test with Saramago excerpt |
| AC-406 | Danish: Adler-Olsen text handled correctly | P0 | Test with Adler-Olsen excerpt |
| AC-407 | Handle mixed-language content (Italian + foreign words) | P1 | Test with mixed content |

### 3.6 TTS Engine Interface

| ID | Criteria | Priority | Verification Method |
|---|---|---|---|
| AC-501 | TTSEngine interface defined (async synthesize method) | P0 | Code inspection |
| AC-502 | edge-tts adapter implemented | P0 | Unit test with mocks |
| AC-503 | Gemini TTS adapter implemented | P0 | Unit test with mocks |
| AC-504 | Google Cloud TTS adapter implemented | P1 | Unit test with mocks |
| AC-505 | Pluggable architecture: new engines can be added without changing app code | P0 | Code inspection |
| AC-506 | Engine fallback mechanism (if primary fails, try next) | P1 | Error handling test |
| AC-507 | Word-level timestamps available (for engines that support it) | P1 | Code inspection |
| AC-508 | Audio format normalization (all engines output consistent format) | P0 | Audio file inspection |

### 3.7 Performance Requirements

| ID | Criteria | Priority | Verification Method |
|---|---|---|---|
| AC-601 | Library load time: <2s for 100 books | P0 | Performance test |
| AC-602 | Chapter load time: <1s | P0 | Performance test |
| AC-603 | TTS synthesis: <2x realtime for edge-tts | P0 | Benchmark test |
| AC-604 | TTS synthesis: <1.5x realtime for Gemini TTS | P0 | Benchmark test |
| AC-605 | Audio playback: <50ms latency from tap to first audio | P0 | Stopwatch test |
| AC-606 | Memory usage: <500MB for 10 concurrent TTS requests | P1 | Memory profiling |
| AC-607 | CPU usage: <50% for background synthesis | P1 | CPU profiling |

### 3.8 Platform & Deployment

| ID | Criteria | Priority | Verification Method |
|---|---|---|---|
| AC-701 | Local-first: works without internet (after initial load) | P0 | Disable network, verify functionality |
| AC-702 | Docker deployment: single container for homelab | P0 | Docker build + run test |
| AC-703 | Responsive design: mobile-friendly | P0 | Mobile browser test |
| AC-704 | Desktop-first: optimized for desktop experience | P0 | Desktop browser test |
| AC-705 | Audio caching: synthesized audio stored for offline playback | P1 | Synthesize, go offline, verify playback |

### 3.9 Backward Compatibility

| ID | Criteria | Priority | Verification Method |
|---|---|---|---|
| AC-801 | v0 CLI scripts remain functional (poc_reader.py, edge_reader.py, epub_mo.py, epub_readaloud.py) | P0 | Run existing CLIs |
| AC-802 | v0 CLI options unchanged (--list-chapters, --slice, etc.) | P0 | CLI test |
| AC-803 | Existing voice cast logic reusable from edge_reader.py | P0 | Code reuse verification |

### 3.10 Test & Quality Requirements

| ID | Criteria | Priority | Verification Method |
|---|---|---|---|
| AC-901 | Synthetic EPUB fixtures for testing (no copyrighted books in repo) | P0 | Inspect test fixtures |
| AC-902 | Test coverage: >80% for core functionality | P1 | Coverage report |
| AC-903 | Mock-based testing for API calls (no live synthesis in tests) | P0 | Code inspection |
| AC-904 | Integration tests for TTS engine adapters | P0 | Integration test suite |
| AC-905 | End-to-end test: EPUB import to voice playback | P0 | E2E test |

---

## 4. Test Fixtures

### 4.1 Synthetic EPUB Requirements

The sandbox must use synthetic EPUB fixtures (never commit copyrighted books). Required fixtures:

1. **Plain Narration (Italian):** Simple chapter with continuous narration, no dialogue
2. **Plain Narration (Danish):** Simple chapter with continuous narration, no dialogue
3. **Dialogue Heavy (Italian):** Saramago-style unmarked dialogue, long sentences
4. **Dialogue Heavy (Danish):** Adler-Olsen-style dialogue with clear speaker changes
5. **Mixed Content:** Narration + dialogue + footnotes
6. **Edge Cases:** Empty paragraphs, special characters, mixed languages

### 4.2 Fixture Generation

Create `tests/fixtures/make_fixture_epub.py` to generate these programmatically:

```python
# Example fixture generation
def make_plain_narration_epub(language: str, word_count: int) -> Path:
    """Generate a synthetic EPUB with plain narration text."""
    pass

def make_dialogue_epub(language: str, dialogue_ratio: float) -> Path:
    """Generate a synthetic EPUB with dialogue."""
    pass

def make_saramago_style_epub(word_count: int) -> Path:
    """Generate a synthetic EPUB mimicking Saramago's style."""
    pass
```

---

## 5. Open Questions & Decisions

### 5.1 Decided (from PLAN_v1_reader.md)

| Question | Decision | Rationale |
|---|---|---|
| Web vs Native | Local-first web app (Docker deployment) | iOS Safari suspends web audio when locked; accepted trade-off for v1 |
| Lock Screen Playback | Not supported in v1 | iOS limitation; future version may use native shell |
| Voice Cast | Reuse LLM speaker-tagging from edge_reader.py | Proven approach, works for Italian and Danish |
| TTS Pipeline | Keep Python TTS pipeline callable from app | Reuse existing investment |

### 5.2 Open Questions for Architecture (Role B)

| Question | Options | Recommendation |
|---|---|---|
| Frontend Framework | Vanilla JS, React, Vue, Svelte | Recommend Svelte (lightweight, reactive, good for audio) |
| Backend Framework | FastAPI, Flask, Django, Express | Recommend FastAPI (async, modern, good for TTS) |
| State Management | Local storage, IndexedDB, server-side | Recommend local-first with server sync option |
| Audio Playback | Web Audio API, Howler.js, custom | Recommend Web Audio API (no dependencies) |
| EPUB Parsing | Custom, epub.js, zipfile + lxml | Recommend custom (already working in edge_reader.py) |
| TTS Queue | In-memory, Redis, database | Recommend in-memory with persistence option |

---

## 6. Glossary

| Term | Definition |
|---|---|
| **LLM Text Preparation** | Process of cleaning OCR errors, repunctuating for speech, and tagging dialogue speakers using Mistral LLM |
| **Voice Cast** | Mapping of character types (narrator, male, female) to specific TTS voices |
| **Voice-by-Progression** | TTS reads from current reading position; spoken sentence is highlighted and view follows voice |
| **Tap-to-Read** | User taps anywhere in text to start TTS from that position |
| **WordBoundary Events** | edge-tts feature that provides timestamps for each word during synthesis |
| **Media Overlays** | EPUB3 feature for read-along audio with synced text highlighting |
| **Saramago's Unmarked Dialogue** | Jose Saramago's writing style with long sentences and dialogue incorporated without quotation marks |

---

## 7. References

1. [README.md](../README.md) - Project overview and current state
2. [PLAN_v1_reader.md](../PLAN_v1_reader.md) - High-level plan and workflow
3. [PLAN_epub3_readalong.md](../PLAN_epub3_readalong.md) - EPUB3 Media Overlays plan
4. [AGENTS.md](../AGENTS.md) - Agent instructions and constraints
5. [edge_reader.py](../edge_reader.py) - Current LLM preparation + edge-tts pipeline
6. [epub_mo.py](../epub_mo.py) - EPUB3 Media Overlays generator
7. [epub_readaloud.py](../epub_readaloud.py) - Simple read-along EPUB generator

---

## 8. Appendix: TTS Engine API Details

### 8.1 edge-tts

```python
import edge_tts

# Basic synthesis
voice = edge_tts.Voice("it-IT-GiuseppeMultilingualNeural")
text = "Ciao mondo"
audio = await voice.synthesize(text)

# With word boundaries
class WordBoundaryCollector:
    def __init__(self):
        self.word_boundaries = []
    
    def on_word_boundary(self, word, start, end):
        self.word_boundaries.append({"word": word, "start": start, "end": end})

collector = WordBoundaryCollector()
voice = edge_tts.Voice("it-IT-GiuseppeMultilingualNeural", on_word_boundary=collector.on_word_boundary)
audio = await voice.synthesize(text)
```

### 8.2 Gemini TTS

```bash
# API endpoint (2026-09-19)
curl -X POST "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateSpeech" \
  -H "Authorization: Bearer $GEMINI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Ciao mondo",
    "voice": {
      "languageCode": "it-IT",
      "name": "it-IT-Neural2-A"
    },
    "audioConfig": {
      "sampleRate": 24000,
      "format": "LINEAR16"
    }
  }'
```

### 8.3 Google Cloud TTS

```bash
# API endpoint
curl -X POST "https://texttospeech.googleapis.com/v1/text:synthesize" \
  -H "Authorization: Bearer $GOOGLE_TTS_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {"text": "Ciao mondo"},
    "voice": {
      "languageCode": "it-IT",
      "name": "it-IT-Wavenet-A"
    },
    "audioConfig": {
      "audioEncoding": "MP3"
    }
  }'
```

---

*Document status: Draft - Awaiting review and approval before architecture phase begins.*

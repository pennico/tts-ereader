# Architecture v1: Full Ebook Reader App

**Status:** Role B (Architecture) deliverable  
**Date:** 2026-09-19  
**Author:** Agent Role B  
**Consumes:** docs/SPEC_v1.md, PLAN_v1_reader.md, AGENTS.md  
**Next:** Implementation PRs per milestone (Role C)  

---

## Executive Summary

This document defines the technical architecture for tts-ereader v1: a local-first web application delivering commercial-grade ebook reading with voice-by-progression read-along. The architecture is designed around a modern web stack with TypeScript frontend (Svelte) and Python backend (FastAPI), a pluggable TTS engine interface, reactive UI with precise audio-text synchronization, and local-first Docker deployment through incremental milestones M1-M4.

---

## 1. Technology Stack

### 1.1 Stack Choices

| Layer | Technology | Rationale |
|---|---|---|
| **Frontend Framework** | Svelte (TypeScript) | Lightweight (~4KB gzipped), reactive by design (perfect for audio sync), no virtual DOM overhead, excellent for media-heavy apps |
| **Frontend Styling** | Tailwind CSS | Utility-first, no runtime overhead, rapid development, consistent theming |
| **Frontend State** | Svelte stores + localStorage | Built-in reactivity, persistence for progress/preferences, no external dependency |
| **Audio Playback** | Web Audio API (native) | Zero dependencies, precise timing control for sync, full browser support |
| **EPUB Parsing** | Custom (zipfile + lxml) | Reuse proven logic from edge_reader.py, no heavy dependencies, full control |
| **Backend Framework** | FastAPI (Python 3.11+) | Async-native, modern, excellent for TTS service calls, automatic OpenAPI docs |
| **Backend TTS** | Pluggable interface + adapters | Future-proof, supports multiple engines, easy to extend |
| **File Storage** | Local filesystem | Local-first deployment, EPUBs and audio cached on homelab storage |
| **Progress Storage** | SQLite | Lightweight, file-based, no server required, ACID for progress tracking |
| **Containerization** | Docker + docker-compose | Single-container app for homelab, reproducible deployment |
| **Build Tool** | Vite | Fast dev server, optimized production builds, Svelte integration |
| **Package Manager** | pnpm | Fast, disk-efficient, works well with Vite |

### 1.2 Stack Rationale

**Why Svelte over React/Vue?** Svelte's compile-time reactivity eliminates the virtual DOM, providing more predictable performance for audio synchronization (critical for AC-206: <100ms highlight delay). Bundle size is 30-50% smaller than equivalent React apps, important for mobile responsiveness (AC-117). Simpler mental model; no need for Redux/Context API complexity.

**Why FastAPI over Flask/Django?** Async-native (TTS synthesis is I/O-bound), type hints, automatic OpenAPI documentation, ASGI-based handles concurrent TTS requests efficiently (AC-606, AC-607).

**Why SQLite over IndexedDB/Server DB?** Local-first (no external dependencies, works offline AC-701), simple deployment (single file), sufficient scale (100+ books trivial), ACID ensures progress persistence reliability (AC-003).

**Why Web Audio API over Howler.js?** Zero dependencies (aligns with AGENTS.md preference), precise timing via AudioContext.currentTime, full control for gapless playback and crossfading.

### 1.3 Architecture Diagram

See Section 2.3 for module breakdown and Section 6.1 for deployment structure.

---

## 2. Module Breakdown

### 2.1 Backend Modules (`backend/app/`)

- **`main.py`**: FastAPI entry point with CORS, static files, route aggregation
- **`api/library.py`**: Library endpoints (import, list, delete, progress)
- **`api/reader.py`**: Reader endpoints (chapters, text, preparation)
- **`api/tts.py`**: TTS endpoints (engines, voices, synthesize, batch)
- **`api/epub.py`**: EPUB endpoints (parse, metadata)
- **`core/config.py`**: App configuration (Pydantic Settings)
- **`core/database.py`**: SQLite database setup
- **`models/book.py`**: Book, Chapter, Progress SQLModel models
- **`models/tts.py`**: TTSEngine, Voice, SynthesisTask models
- **`engines/base.py`**: TTSEngine abstract base class
- **`engines/edge_tts.py`**: edge-tts adapter
- **`engines/gemini.py`**: Gemini TTS adapter
- **`engines/google.py`**: Google Cloud TTS adapter (optional)
- **`engines/factory.py`**: Engine factory and registry
- **`services/library_service.py`**: Library business logic
- **`services/reader_service.py`**: Reader business logic
- **`services/tts_service.py`**: TTS business logic, synthesis queue
- **`services/epub_parser.py`**: EPUB parsing (reused from edge_reader.py)
- **`services/llm_service.py`**: LLM text preparation
- **`services/cache_service.py`**: Audio caching
- **`utils/audio.py`**: Audio manipulation (pydub wrapper)
- **`utils/epub.py`**: EPUB utilities
- **`utils/text.py`**: Text processing utilities
- **`utils/cache.py`**: Cache utilities

### 2.2 Frontend Modules (`frontend/src/`)

- **`main.ts`**: App entry point
- **`App.svelte`**: Root component with route handling
- **`routes/+layout.svelte`**: Shared layout
- **`routes/+page.svelte`**: Library page
- **`routes/library/+page.svelte`**: Library route
- **`routes/reader/+page.svelte`**: Reader route
- **`routes/settings/+page.svelte`**: Settings route
- **`lib/components/BookCard.svelte`**: Book card for library
- **`lib/components/ChapterNav.svelte`**: Chapter navigation
- **`lib/components/AudioPlayer.svelte`**: Audio playback controls
- **`lib/components/ProgressBar.svelte`**: Reading progress
- **`lib/components/ThemeToggle.svelte`**: Theme switching
- **`lib/components/FontControls.svelte`**: Font customization
- **`lib/components/VoiceControls.svelte`**: Voice tuning
- **`lib/stores/library.ts`**: Library state
- **`lib/stores/reader.ts`**: Reader state
- **`lib/stores/audio.ts`**: Audio state
- **`lib/stores/settings.ts`**: App settings
- **`lib/stores/tts.ts`**: TTS state
- **`lib/services/api.ts`**: API client (fetch wrapper)
- **`lib/services/audioEngine.ts`**: Web Audio API wrapper
- **`lib/services/sync.ts`**: Audio-text synchronization
- **`lib/types/index.ts`**: TypeScript type definitions

### 2.3 Shared Modules (`shared/`)

- **`text_preparation.py`**: LLM text preparation (from edge_reader.py)
- **`voice_cast.py`**: Voice cast logic (from edge_reader.py)
- **`epub_utils.py`**: EPUB parsing utilities

These modules are shared between v0 CLI scripts and v1 app to ensure backward compatibility (AC-801, AC-802, AC-803).

---

## 3. Data Flow

### 3.1 EPUB Import Flow
User uploads EPUB -> Backend parses EPUB -> Extracts metadata and cover -> Indexes chapters -> Stores in SQLite -> Returns book ID to frontend.

### 3.2 Reading Flow (Voice-by-Progression)
User selects book -> Frontend loads chapter -> Backend returns prepared text -> User taps text -> AudioEngine seeks to position and plays -> SyncEngine highlights spoken sentence via requestAnimationFrame loop -> View auto-scrolls to keep highlight visible.

### 3.3 TTS Synthesis Flow
Raw text -> LLM preparation (clean, repunctuate, speaker tagging) -> Voice cast mapping -> Chunk for synthesis -> Select engine -> Async synthesize -> Return audio + word timestamps -> Cache audio -> Stream to frontend.

---

## 4. Milestones

### 4.1 Milestone M1: Library + Reader View
**Duration:** 2-3 weeks
**Goal:** Functional library management and reading view with all display features, no audio yet.

**Deliverables:** Library endpoints, EPUB parser, chapter navigation, Library UI, Reader UI, Theme system (light/dark/sepia/custom), Font controls, Scroll modes (continuous + paginated, toggleable), Auto-advance/auto-scroll, Progress persistence, Docker container.

**Acceptance Criteria:** AC-001 to AC-005 (Library), AC-101 to AC-108 (Themes/Fonts), AC-109 to AC-113 (Scroll modes), AC-114 to AC-117 (European typography), AC-701, AC-702 (Local-first, Docker).

**Test Strategy:** Unit tests (EPUB parser, progress storage), Integration tests (Library endpoints, chapter navigation), E2E tests (Import EPUB, navigate library, read chapter), Manual tests (Theme switching, font adjustments, scroll modes).

### 4.2 Milestone M2: TTS Engine + Voice-by-Progression
**Duration:** 3-4 weeks
**Goal:** Add TTS synthesis and the core voice-by-progression feature.

**Deliverables:** TTSEngine interface + adapters (edge-tts, Gemini, Google), LLM text preparation service, Voice cast logic, TTS synthesis endpoints, Audio caching, AudioEngine (Web Audio API), SyncEngine, Tap-to-read, Voice-driven auto-advance, Playback controls.

**Acceptance Criteria:** AC-201 to AC-207 (Voice-by-progression), AC-501 to AC-508 (TTS interface), AC-301 to AC-303 (Voice tuning basics), AC-601 to AC-605 (Performance).

**Test Strategy:** Unit tests (TTS adapters with mocks, AudioEngine, SyncEngine), Integration tests (TTS endpoints, audio caching), E2E tests (Tap-to-read, auto-advance, highlight sync), Manual tests (Audio quality, sync accuracy).

### 4.3 Milestone M3: Voice Tuning + LLM Integration
**Duration:** 2-3 weeks
**Goal:** Add voice tuning UI and full LLM text preparation integration.

**Deliverables:** Voice selection UI, Rate/pitch controls, "Test this voice" button, Per-book voice cast configuration, Voice cast persistence, Full LLM preparation pipeline, Italian optimization, Danish optimization, Refactored shared code for v0 CLI reuse.

**Acceptance Criteria:** AC-304 to AC-307 (Voice tuning), AC-401 to AC-407 (Language-specific), AC-801 to AC-803 (Backward compatibility).

**Test Strategy:** Unit tests (Voice cast logic, LLM preparation), Integration tests (Voice tuning endpoints), E2E tests (Voice selection, test voice, per-book cast), Manual tests (Italian/Danish text quality, Saramago dialogue).

### 4.4 Milestone M4: Docker Deployment + Benchmark + Docs
**Duration:** 1-2 weeks
**Goal:** Production-ready deployment with benchmarking and documentation.

**Deliverables:** Optimized production Docker container, docker-compose with volumes, Benchmark harness (synthesis comparison), Health check endpoints, Logging and monitoring, Loading states and error handling, Offline indicator, User guide, Developer guide, API documentation, Synthetic EPUB fixtures, Test coverage >80%.

**Acceptance Criteria:** AC-703 to AC-705 (Platform), AC-901 to AC-905 (Test & Quality), All performance criteria (AC-601 to AC-607).

**Test Strategy:** Integration tests (Docker deployment), Benchmark tests (Engine comparison), Coverage >80%, Documentation completeness.

---

## 5. Test Strategy

### 5.1 Testing Pyramid
E2E Tests (~10, Playwright, full user journeys) -> Integration Tests (~50, API endpoints, module interactions) -> Unit Tests (~200+, pytest, individual functions).

### 5.2 Test Categories

**Unit Tests (Backend):** pytest + pytest-asyncio. Scope: EPUB parsing, text preparation, voice cast, TTS engine adapters (with mocks), audio utilities, database models.

**Unit Tests (Frontend):** Vitest. Scope: AudioEngine calculations, SyncEngine logic, utility functions, store logic.

**Integration Tests:** pytest + TestClient (FastAPI). Scope: API endpoint contracts, module interactions, database operations, file I/O.

**E2E Tests:** Playwright. Scope: Full user journeys, cross-page navigation, audio playback (with mocked audio), responsive behavior.

### 5.3 Test Fixtures

Create `tests/fixtures/make_fixture_epub.py` to generate synthetic EPUBs programmatically:
- Plain narration (Italian, Danish)
- Dialogue heavy (Italian Saramago-style, Danish Adler-Olsen-style)
- Mixed content (narration + dialogue + footnotes)
- Edge cases (empty paragraphs, special characters, mixed languages)

### 5.4 Mocking Strategy

**TTS Engine Mocks:** MockTTSEngine class implementing TTSEngine interface, returns mock audio (silence) with generated word boundaries.

**LLM Mocks:** mock_llm_prepare function that does simple text transformations for testing.

### 5.5 Test Execution

**Local:** `pytest tests/unit/ -v`, `pytest tests/integration/ -v`, `pnpm test`, `pnpm test:e2e`, `pnpm test:all`

**CI:** GitHub Actions with separate jobs for backend tests, frontend tests, E2E tests.

**Coverage:** Target >80% for core functionality (AC-902). Use `pytest --cov=app --cov-report=html --cov-fail-under=80`.

### 5.6 Performance Testing

**Synthesis Benchmark:** Measure synthesis speed vs realtime for each engine. Assert <2x realtime for edge-tts (AC-603), <1.5x for Gemini (AC-604).

**Sync Accuracy Test:** Measure highlight delay, assert <100ms (AC-206).

---

## 6. Deployment

### 6.1 Docker Setup

**Dockerfile:** Multi-stage build (frontend-builder + runtime). Runtime: python:3.11-slim with ffmpeg. Copy built frontend, install Python deps, create data directories, set environment, expose port 8000, health check.

**docker-compose.yml:** Service with build context, ports 8000:8000, volumes for data/epubs, data/audio_cache, data/covers, data/tts_ereader.db, environment from .env, restart unless-stopped, health check.

**.dockerignore:** node_modules/, pnpm-lock.yaml, __pycache__/, *.pyc, .env, .env.*, data/, .git/, .gitignore, *.pytest_cache/, .coverage, htmlcov/, docs/.

### 6.2 Environment Configuration

**.env.example:** TTS API keys, app settings (DEBUG, DEFAULT_ENGINE), directories, LLM settings, audio settings.

### 6.3 Development Workflow

**Local Development:** Clone, copy .env, create venv, pip install deps, cd frontend, pnpm install, run backend (uvicorn --reload), run frontend (pnpm dev), open http://localhost:5173.

**Docker Development:** docker-compose build, docker-compose up, open http://localhost:8000.

### 6.4 Production Deployment (Homelab)
On homelab server: mkdir data directories, copy docker-compose.yml and .env, docker-compose pull, docker-compose up -d, check logs/ps, update with git pull + docker-compose build + docker-compose up -d --no-deps.

---

## 7. File Structure

```
tts-ereader/
├── .env.example
├── .gitignore
├── .dockerignore
├── docker-compose.yml
├── Dockerfile
├── AGENTS.md
├── PLAN_v1_reader.md
├── README.md
├── requirements.txt
├── requirements-dev.txt
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   └── database.py
│   │   ├── api/
│   │   │   ├── library.py
│   │   │   ├── reader.py
│   │   │   ├── tts.py
│   │   │   └── epub.py
│   │   ├── models/
│   │   │   ├── book.py
│   │   │   └── tts.py
│   │   ├── engines/
│   │   │   ├── base.py
│   │   │   ├── edge_tts.py
│   │   │   ├── gemini.py
│   │   │   ├── google.py
│   │   │   └── factory.py
│   │   ├── services/
│   │   │   ├── library_service.py
│   │   │   ├── reader_service.py
│   │   │   ├── tts_service.py
│   │   │   ├── epub_parser.py
│   │   │   ├── llm_service.py
│   │   │   └── cache_service.py
│   │   └── utils/
│   │       ├── audio.py
│   │       ├── epub.py
│   │       ├── text.py
│   │       └── cache.py
│   └── tests/
│       ├── conftest.py
│       ├── unit/
│       ├── integration/
│       ├── benchmark/
│       └── fixtures/
│           ├── make_fixture_epub.py
│           └── epubs/
├── frontend/
│   ├── src/
│   │   ├── main.ts
│   │   ├── App.svelte
│   │   ├── routes/
│   │   │   ├── +layout.svelte
│   │   │   ├── +page.svelte
│   │   │   ├── library/
│   │   │   │   └── +page.svelte
│   │   │   ├── reader/
│   │   │   │   └── +page.svelte
│   │   │   └── settings/
│   │   │       └── +page.svelte
│   │   └── lib/
│   │       ├── components/
│   │       ├── stores/
│   │       ├── services/
│   │       ├── utils/
│   │       └── types/
│   ├── public/
│   │   └── favicon.ico
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
├── shared/
│   ├── text_preparation.py
│   ├── voice_cast.py
│   └── epub_utils.py
├── docs/
│   ├── SPEC_v1.md
│   └── ARCHITECTURE_v1.md
├── samples/
│   ├── english_fiction.txt
│   ├── italian_fiction.txt
│   ├── danish_fiction.txt
│   └── danish_technical.txt
└── tests/
    └── fixtures/
        └── make_fixture_epub.py
```

---

## 8. Backward Compatibility

**Strategy:** Extract shared logic (text preparation, voice cast, EPUB parsing) from v0 scripts into `shared/` module. Update v0 scripts to import from `shared/`. Add tests to verify CLI functionality after refactoring. This ensures AC-801, AC-802, AC-803.

---

## 9. Risk Assessment

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Web Audio API timing inaccuracies | Medium | High | Use AudioContext.currentTime, test on multiple browsers |
| TTS engine API changes | Low | High | Abstract behind interface, version pinning |
| Performance issues with large books | Medium | Medium | Chunked processing, lazy loading |
| SQLite lock contention | Low | Medium | Single writer principle, async with retries |
| Browser compatibility issues | Medium | Medium | Test on target browsers, polyfills |
| Docker size too large | Low | Low | Multi-stage build, alpine base |
| Memory issues with many concurrent TTS requests | Medium | Medium | Limit concurrent requests, streaming |
| LLM preparation quality for Danish | Medium | High | Fine-tune prompts, test with Adler-Olsen excerpts |

---

## 10. References

1. [SPEC_v1.md](./SPEC_v1.md) - Feature specification and acceptance criteria
2. [PLAN_v1_reader.md](../PLAN_v1_reader.md) - Project plan and workflow
3. [AGENTS.md](../AGENTS.md) - Agent instructions and constraints
4. [edge_reader.py](../edge_reader.py) - Current LLM preparation + edge-tts pipeline
5. [epub_mo.py](../epub_mo.py) - EPUB3 Media Overlays generator
6. [epub_readaloud.py](../epub_readaloud.py) - Simple read-along EPUB generator
7. [poc_player.html](../poc_player.html) - Current web player

---

## 11. Appendix

### 11.1 TTSEngine Interface

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator
from dataclasses import dataclass

@dataclass
class WordBoundary:
    word: str
    start_ms: float
    end_ms: float

@dataclass
class SynthesisResult:
    audio: bytes
    sample_rate: int
    word_boundaries: list[WordBoundary] | None
    duration_ms: float

class TTSEngine(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...
    
    @property
    @abstractmethod
    def display_name(self) -> str: ...
    
    @abstractmethod
    async def list_voices(self) -> list[str]: ...
    
    @abstractmethod
    async def synthesize(self, text: str, voice: str, rate: float = 1.0, pitch: float = 0.0) -> SynthesisResult: ...
    
    @abstractmethod
    async def synthesize_stream(self, text: str, voice: str, rate: float = 1.0, pitch: float = 0.0) -> AsyncIterator[bytes]: ...
```

### 11.2 AudioEngine (TypeScript)

```typescript
interface WordBoundary {
  word: string;
  startMs: number;
  endMs: number;
}

class AudioEngine {
  private context: AudioContext;
  private source: AudioBufferSourceNode | null = null;
  private gainNode: GainNode;
  private segments: AudioSegment[] = [];
  private currentSegmentIndex: number = 0;
  private isPlaying: boolean = false;
  private startTime: number = 0;
  private pauseTime: number = 0;

  play(fromPosition?: number): void { /* play from position */ }
  pause(): void { /* pause playback */ }
  seek(position: number): void { /* seek to position */ }
  getCurrentPosition(): number { /* get current playback position in ms */ }
  getWordAtPosition(position: number): WordBoundary | null { /* find word at position */ }
  setRate(rate: number): void { /* set playback rate */ }
  setVolume(volume: number): void { /* set volume (0-1) */ }
}
```

### 11.3 SyncEngine (TypeScript)

```typescript
class SyncEngine {
  private audioEngine: AudioEngine;
  private textContainer: HTMLElement;
  private rafId: number | null = null;

  start(): void { /* start synchronization loop */ }
  stop(): void { /* stop synchronization loop */ }
  tapToRead(element: HTMLElement): void { /* seek audio to element position and play */ }
}
```

*Document status: Ready for review and implementation (Role C).*

<script lang="ts">
  import { onDestroy, onMount, tick } from "svelte";
  import { api } from "../services/api";
  import { settings } from "../stores/settings";
  import { browserStorage, createTtsStore } from "../stores/tts";
  import { AudioEngine, type AudioBufferLike } from "../services/audioEngine";
  import { nextWindow } from "../services/sync";
  import { splitChapter, sentencePosition, type ChapterSentence } from "../utils/sentences";
  import {
    COLUMN_GAP,
    clampPage,
    nextPage,
    pageAtOffset,
    pageCount,
    pageOffset,
    pageToPosition,
    positionToPage,
    positionToScrollTop,
    scrollTopToPosition,
  } from "../utils/pagination";
  import { FONT_STACKS } from "../utils/themes";
  import ChapterNav from "../components/ChapterNav.svelte";
  import SettingsPanel from "../components/SettingsPanel.svelte";
  import SentenceContent from "../components/SentenceContent.svelte";
  import VoicePanel from "../components/VoicePanel.svelte";
  import type { Book, ChapterMeta, PreparedSegment, TtsSettings } from "../types";

  export let bookId: number;

  let book: Book | null = null;
  let chapters: ChapterMeta[] = [];
  let chapterIndex = 0;
  let paragraphs: string[] = [];
  let loading = true;
  let loadError: string | null = null;

  // Layout (paginated mode measures CSS columns; scroll mode uses scrollTop).
  let viewportEl: HTMLElement;
  let contentEl: HTMLElement;
  let colWidth = 0; // width available to one column/page (excludes padding)
  let pages = 1;
  let page = 0;
  let position = 0; // 0..1 within the chapter — source of truth for progress
  let showSettings = false;
  let showVoice = false;

  let autoTimer: ReturnType<typeof setInterval> | null = null;
  let rafId: number | null = null;
  let lastFrame = 0;
  let saveTimer: ReturnType<typeof setTimeout> | null = null;

  // ── Voice-by-progression state (M2) ──────────────────────────────────────
  // Playback unit is the sentence: the chapter is split into sentences, a
  // window of them is synthesized per batch request, and the spoken sentence
  // is highlighted while the view follows the voice.

  const WINDOW_SENTENCES = 12;
  const WINDOW_CHARS = 3000;

  interface QueueItem {
    sentence: number; // global sentence index
    buffer: AudioBufferLike;
    durationMs: number;
  }

  let sentences: ChapterSentence[] = [];
  let sentencesByPara: Map<number, ChapterSentence[]> = new Map();
  // Voice-cast mode (M3, AC-305): prepared segments replace the chapter's
  // own sentences as the playback + display unit.
  let castSegments: PreparedSegment[] | null = null;
  let castBusy = false;
  let castError: string | null = null;
  let labels: (string | null)[] = [];
  let audio: AudioEngine | null = null;
  let playing = false;
  let ttsBusy = false;
  let ttsError: string | null = null;
  let activeSentence = -1; // global index of the spoken sentence
  let queue: QueueItem[] = [];
  let queueStart = 0; // global sentence index of queue[0]
  let queuePos = -1;
  let playToken = 0; // invalidates async continuations on stop/seek
  let loadToken = 0; // invalidates superseded chapter loads
  let prefetching = false;
  let voiceDirty = false; // user navigated; voice must reposition
  let suppressScroll = false; // follow-voice scrolling is not user scrolling
  let repositionTimer: ReturnType<typeof setTimeout> | null = null;

  // prevTts must be declared before the store is created: createTtsStore
  // subscribes synchronously, so onTtsChange runs inside this very
  // initializer and would hit the temporal dead zone otherwise (issue #39).
  let prevTts: TtsSettings | null = null;
  const tts = createTtsStore(bookId, browserStorage(), onTtsChange);

  function onTtsChange(next: TtsSettings): void {
    if (prevTts === null) {
      prevTts = { ...next };
      return;
    }
    const engineOrVoiceChanged =
      next.engine !== prevTts.engine || next.voice !== prevTts.voice;
    const pitchChanged = next.pitch !== prevTts.pitch;
    const castToggled = next.castEnabled !== prevTts.castEnabled;
    const castChanged =
      !castToggled &&
      next.castEnabled &&
      JSON.stringify(next.cast) !== JSON.stringify(prevTts.cast);
    const rateChanged = next.rate !== prevTts.rate;
    const wasPlaying = playing || queuePos >= 0;
    prevTts = { ...next };
    // Cast mode changes the content itself (prepared lines vs. original
    // sentences), so the chapter must be rebuilt; engine/cast changes also
    // re-resolve the prepared voices.
    if (castToggled || (next.castEnabled && (engineOrVoiceChanged || castChanged))) {
      void reloadForCast(wasPlaying);
      return;
    }
    if (engineOrVoiceChanged || pitchChanged || castChanged) {
      // Restart from the spoken sentence with the new engine/voice/pitch.
      if (wasPlaying) {
        const from = activeSentence >= 0 ? activeSentence : sentenceAtOrAfter(position);
        void playFrom(from);
      }
      return;
    }
    if (rateChanged && playing) void audio?.setRate(next.rate);
  }

  /** Rebuild the chapter content after a cast/engine change (AC-305). */
  async function reloadForCast(resume: boolean): Promise<void> {
    const pos = position;
    await loadChapter(chapterIndex, pos);
    if (resume) void playFrom(sentenceAtOrAfter(pos));
  }

  $: isPaged = $settings.scrollMode === "paged";
  $: contentStyle = `font-family: ${FONT_STACKS[$settings.fontFamily]}; font-size: ${$settings.fontSize}pt; font-weight: ${$settings.fontWeight}; line-height: ${$settings.lineHeight};`;
  $: chapterPct = Math.round(position * 100);
  $: bookPct =
    chapters.length > 0
      ? Math.round(((chapterIndex + position) / chapters.length) * 100)
      : 0;

  // ── Loading ──────────────────────────────────────────────────────────────

  async function open(): Promise<void> {
    loading = true;
    loadError = null;
    try {
      book = await api.getBook(bookId);
      chapters = await api.listChapters(bookId);
      const progress = await api.getProgress(bookId);
      const target = Math.min(progress.chapter_index, Math.max(0, chapters.length - 1));
      await loadChapter(target, progress.position);
    } catch (e) {
      loadError = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  async function loadChapter(index: number, restorePosition: number | null = null): Promise<void> {
    const token = ++loadToken;
    stopPlayback();
    const chapter = await api.getChapter(bookId, index);
    if (token !== loadToken) return; // superseded by a newer load
    chapterIndex = index;
    castSegments = null;
    castError = null;
    if ($tts.castEnabled) await loadPrepared(chapter.index);
    if (token !== loadToken) return;
    buildContent(chapter.text, restorePosition);
    await tick();
    measure();
    if (restorePosition !== null) applyPosition(restorePosition);
  }

  /** Fetch (cached) LLM-prepared segments for the chapter (AC-305, AC-401). */
  async function loadPrepared(chapterIndexToLoad: number): Promise<void> {
    castBusy = true;
    try {
      const prepared = await api.prepareChapter(bookId, chapterIndexToLoad, {
        engine: $tts.engine,
        cast: $tts.cast,
      });
      castSegments = prepared.segments.length > 0 ? prepared.segments : null;
    } catch (e) {
      // e.g. MISTRAL_API_KEY missing: fall back to plain narration below.
      castError = msg(e);
      castSegments = null;
    } finally {
      castBusy = false;
    }
  }

  /** Build paragraphs/sentences from the original text or the prepared lines. */
  function buildContent(chapterText: string, restorePosition: number | null): void {
    if (castSegments) {
      paragraphs = castSegments.map((s) => s.text);
      labels = castSegments.map((s) => s.speaker);
      sentences = castSegments.map((s, i) => ({
        index: i,
        para: i,
        text: s.text,
        start: 0,
      }));
    } else {
      paragraphs = chapterText
        .split(/\n{2,}/)
        .map((p) => p.trim())
        .filter((p) => p.length > 0);
      labels = [];
      sentences = splitChapter(paragraphs);
    }
    const byPara = new Map<number, ChapterSentence[]>();
    for (const s of sentences) {
      const list = byPara.get(s.para) ?? [];
      list.push(s);
      byPara.set(s.para, list);
    }
    sentencesByPara = byPara;
    page = 0;
    position = restorePosition ?? 0;
  }

  function measure(): void {
    if (!viewportEl || !contentEl) return;
    if (isPaged) {
      colWidth = contentEl.clientWidth;
      const total = pageCount(contentEl.scrollWidth, colWidth);
      if (total !== pages) pages = total;
    }
    page = clampPage(page, pages);
  }

  function applyPosition(pos: number): void {
    if (isPaged) {
      page = positionToPage(pos, pages);
    } else if (viewportEl) {
      viewportEl.scrollTop = positionToScrollTop(
        pos,
        viewportEl.scrollHeight,
        viewportEl.clientHeight
      );
    }
  }

  // Re-measure whenever anything that affects layout changes.
  $: layoutKey = `${paragraphs.length}|${chapterIndex}|${$settings.fontSize}|${$settings.lineHeight}|${$settings.fontFamily}|${$settings.fontWeight}|${$settings.scrollMode}|${colWidth}`;
  $: if (layoutKey && !loading) void tick().then(() => measure());

  // Preserve the reading position when the user switches modes (AC-111).
  let lastMode = $settings.scrollMode;
  $: if ($settings.scrollMode !== lastMode) {
    lastMode = $settings.scrollMode;
    void tick().then(() => {
      measure();
      applyPosition(position);
    });
  }

  // ── Progress persistence (AC-003) ────────────────────────────────────────

  function scheduleSave(): void {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(saveNow, 800);
  }

  async function saveNow(): Promise<void> {
    if (saveTimer) {
      clearTimeout(saveTimer);
      saveTimer = null;
    }
    try {
      await api.setProgress(bookId, { chapter_index: chapterIndex, position });
    } catch {
      /* progress save is best-effort; retried on the next change */
    }
  }

  // ── Navigation ───────────────────────────────────────────────────────────

  function onScroll(): void {
    if (!viewportEl || isPaged) return;
    position = scrollTopToPosition(
      viewportEl.scrollTop,
      viewportEl.scrollHeight,
      viewportEl.clientHeight
    );
    scheduleSave();
    if (suppressScroll) return;
    markVoiceDirty(); // AC-204: manual scroll repositions the voice
  }

  function goToPage(target: number, fromVoice = false): void {
    page = clampPage(target, pages);
    position = pageToPosition(page, pages);
    scheduleSave();
    if (!fromVoice) markVoiceDirty();
  }

  function turnPage(dir: 1 | -1): void {
    if (!isPaged) return;
    if (dir > 0) {
      const next = nextPage(page, pages);
      if (next !== null) goToPage(next);
      else if (chapterIndex < chapters.length - 1) void loadChapter(chapterIndex + 1, 0);
    } else {
      if (page > 0) goToPage(page - 1);
      else if (chapterIndex > 0) void loadChapter(chapterIndex - 1, 1);
    }
  }

  function prevChapter(): void {
    if (chapterIndex > 0) void loadChapter(chapterIndex - 1, 0);
  }

  function nextChapter(): void {
    if (chapterIndex < chapters.length - 1) void loadChapter(chapterIndex + 1, 0);
  }

  function selectChapter(index: number): void {
    if (index !== chapterIndex) void loadChapter(index, 0);
  }

  function onKeydown(event: KeyboardEvent): void {
    if (!isPaged) return;
    if (event.key === "ArrowRight" || event.key === " ") {
      event.preventDefault();
      turnPage(1);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      turnPage(-1);
    }
  }

  function onResize(): void {
    void tick().then(() => {
      measure();
      applyPosition(position);
    });
  }

  // ── Auto progression (AC-112, AC-113) ─────────────────────────────────────
  // Suspended while the voice plays: the voice drives progression instead.

  $: autoKey = `${$settings.autoEnabled}|${$settings.scrollMode}|${$settings.autoPageSeconds}|${$settings.autoScrollPxPerSec}|${chapterIndex}|${pages}|${playing}`;
  $: if (autoKey && !loading && !loadError) restartAuto();

  function restartAuto(): void {
    stopAuto();
    if (!$settings.autoEnabled || playing) return;
    if (isPaged) {
      autoTimer = setInterval(() => autoAdvancePage(), $settings.autoPageSeconds * 1000);
    } else {
      lastFrame = performance.now();
      rafId = requestAnimationFrame(autoScrollFrame);
    }
  }

  function stopAuto(): void {
    if (autoTimer) {
      clearInterval(autoTimer);
      autoTimer = null;
    }
    if (rafId !== null) {
      cancelAnimationFrame(rafId);
      rafId = null;
    }
  }

  function autoAdvancePage(): void {
    const next = nextPage(page, pages);
    if (next !== null) {
      goToPage(next);
    } else if (chapterIndex < chapters.length - 1) {
      void loadChapter(chapterIndex + 1, 0);
    } else {
      settings.update((s) => ({ ...s, autoEnabled: false }));
    }
  }

  function autoScrollFrame(ts: number): void {
    if (!viewportEl) return;
    const dt = Math.min(0.1, (ts - lastFrame) / 1000);
    lastFrame = ts;
    const before = viewportEl.scrollTop;
    viewportEl.scrollTop = before + $settings.autoScrollPxPerSec * dt;
    const atBottom =
      viewportEl.scrollTop + viewportEl.clientHeight >= viewportEl.scrollHeight - 1;
    if (atBottom) {
      if (chapterIndex < chapters.length - 1) {
        void loadChapter(chapterIndex + 1, 0);
      } else {
        settings.update((s) => ({ ...s, autoEnabled: false }));
        return;
      }
    }
    position = scrollTopToPosition(
      viewportEl.scrollTop,
      viewportEl.scrollHeight,
      viewportEl.clientHeight
    );
    scheduleSave();
    rafId = requestAnimationFrame(autoScrollFrame);
  }

  // ── Voice-by-progression (M2: AC-201..AC-207) ─────────────────────────────

  function msg(e: unknown): string {
    return e instanceof Error ? e.message : String(e);
  }

  /** Global sentence index at or after a fractional reading position. */
  function sentenceAtOrAfter(pos: number): number {
    for (const s of sentences) {
      if (sentencePosition(paragraphs, s) >= pos - 0.001) return s.index;
    }
    return sentences.length > 0 ? sentences[sentences.length - 1].index : 0;
  }

  /** First sentence visible in the viewport (tap-to-read anchor, AC-204). */
  function firstVisibleSentence(): number {
    if (!contentEl || !viewportEl || sentences.length === 0) return 0;
    let fallback = sentences[0].index;
    for (const s of sentences) {
      const el = contentEl.querySelector(`[data-sid="${s.index}"]`) as HTMLElement | null;
      if (!el) continue;
      if (isPaged) {
        if (pageAtOffset(el.offsetLeft - contentEl.offsetLeft, colWidth) === page) return s.index;
      } else {
        const elTop = el.offsetTop - contentEl.offsetTop;
        if (elTop + el.offsetHeight >= viewportEl.scrollTop + 40) return s.index;
      }
      fallback = s.index;
    }
    return fallback;
  }

  /** Synthesize + decode the window of sentences starting at `from`. */
  async function fetchWindow(from: number): Promise<QueueItem[]> {
    const lengths = sentences.map((s) => s.text.length);
    const idxs = nextWindow(from, sentences.length, WINDOW_SENTENCES, WINDOW_CHARS, lengths);
    if (idxs.length === 0 || !audio) return [];
    const texts = idxs.map((i) => sentences[i].text);
    const { segments } = await api.synthesizeBatch({
      texts,
      engine: $tts.engine,
      voice: $tts.voice,
      rate: 1.0, // playback rate is applied client-side (AC-303)
      pitch: $tts.pitch, // baked into synthesis (AC-304)
      // Voice cast: each prepared segment reads with its own voice (AC-305).
      ...(castSegments
        ? { voices: idxs.map((i) => castSegments?.[i]?.voice || $tts.voice) }
        : {}),
    });
    const items: QueueItem[] = [];
    for (let i = 0; i < segments.length; i++) {
      const buffer = await audio.decode(segments[i].audio_b64);
      items.push({
        sentence: idxs[i],
        buffer,
        durationMs: buffer.duration * 1000,
      });
    }
    return items;
  }

  /** Tap-to-read (AC-201/AC-204): play from the tapped sentence. */
  function tapSentence(index: number): void {
    voiceDirty = false;
    void playFrom(index);
  }

  async function playFrom(index: number): Promise<void> {
    if (!audio || sentences.length === 0 || !$tts.voice) return;
    if (index < 0 || index >= sentences.length) index = 0;
    const token = ++playToken;
    pauseSource();
    queue = [];
    queuePos = -1;
    queueStart = index;
    prefetching = false;
    ttsBusy = true;
    ttsError = null;
    try {
      const items = await fetchWindow(index);
      if (token !== playToken) return;
      queue = items;
      await playQueueItem(0, token);
    } catch (e) {
      if (token === playToken) {
        ttsError = msg(e);
        playing = false;
      }
    } finally {
      if (token === playToken) ttsBusy = false;
    }
  }

  async function playQueueItem(pos: number, token: number): Promise<void> {
    if (token !== playToken || !audio) return;
    const item = queue[pos];
    if (!item) {
      await onQueueExhausted(token);
      return;
    }
    queuePos = pos;
    setActiveSentence(item.sentence);
    prefetchIfNeeded(token);
    audio.onEnded = () => void playQueueItem(pos + 1, token);
    try {
      await audio.play(item.buffer, 0, $tts.rate);
    } catch (e) {
      if (token === playToken) {
        ttsError = msg(e);
        stopPlayback();
      }
    }
  }

  async function onQueueExhausted(token: number): Promise<void> {
    const nextStart = queueStart + queue.length;
    if (nextStart < sentences.length) {
      ttsBusy = true;
      try {
        const items = await fetchWindow(nextStart);
        if (token !== playToken) return;
        queue.push(...items);
        await playQueueItem(queue.length - items.length, token);
      } catch (e) {
        if (token === playToken) {
          ttsError = msg(e);
          playing = false;
        }
      } finally {
        if (token === playToken) ttsBusy = false;
      }
      return;
    }
    // Chapter finished: voice-driven auto-advance (AC-205).
    playing = false;
    activeSentence = -1;
    if ($tts.autoAdvance && chapterIndex < chapters.length - 1) {
      await loadChapter(chapterIndex + 1, 0);
      void playFrom(0);
    }
  }

  /** Keep a window of audio ahead of the voice so playback stays gapless. */
  function prefetchIfNeeded(token: number): void {
    if (prefetching || token !== playToken) return;
    const nextStart = queueStart + queue.length;
    if (queuePos < queue.length - 3 || nextStart >= sentences.length) return;
    prefetching = true;
    void fetchWindow(nextStart)
      .then((items) => {
        if (token === playToken) queue.push(...items);
      })
      .catch(() => {
        /* prefetch failure is non-fatal; retried at queue exhaustion */
      })
      .finally(() => {
        prefetching = false;
      });
  }

  function setActiveSentence(index: number): void {
    activeSentence = index;
    playing = true;
    // The reading position follows the voice (progress + AC-207).
    position = sentencePosition(paragraphs, sentences[index]);
    scheduleSave();
    followVoice(index);
  }

  /** View follows the voice (AC-203): scroll to / turn to the spoken sentence. */
  function followVoice(index: number): void {
    const el = contentEl?.querySelector(`[data-sid="${index}"]`) as HTMLElement | null;
    if (!el || !viewportEl || !contentEl) return;
    if (isPaged) {
      const target = pageAtOffset(el.offsetLeft - contentEl.offsetLeft, colWidth);
      if (target !== page) goToPage(target, true);
    } else {
      suppressScroll = true;
      const elTop = el.offsetTop - contentEl.offsetTop;
      viewportEl.scrollTop = Math.max(0, elTop - viewportEl.clientHeight / 2);
      setTimeout(() => {
        suppressScroll = false;
      }, 200);
    }
  }

  /** User navigated manually: the voice must reposition (AC-204). */
  function markVoiceDirty(): void {
    voiceDirty = true;
    if (repositionTimer) clearTimeout(repositionTimer);
    if (!playing) return;
    repositionTimer = setTimeout(() => {
      const idx = firstVisibleSentence();
      if (idx >= 0 && idx !== activeSentence) void playFrom(idx);
    }, 500);
  }

  function togglePlay(): void {
    if (!audio || sentences.length === 0) return;
    if (playing) {
      pauseSource();
      return;
    }
    if (queuePos >= 0 && queue[queuePos] && !voiceDirty) {
      playing = true;
      const token = playToken;
      const resumePos = queuePos;
      // Restore the segment chain that pauseSource() detached.
      audio.onEnded = () => void playQueueItem(resumePos + 1, token);
      void audio.resume().catch((e) => {
        ttsError = msg(e);
        playing = false;
      });
      return;
    }
    const from =
      voiceDirty || activeSentence < 0 ? firstVisibleSentence() : activeSentence;
    voiceDirty = false;
    void playFrom(from);
  }

  function pauseSource(): void {
    if (!audio) return;
    audio.onEnded = null;
    audio.pause();
    playing = false;
  }

  function stopPlayback(): void {
    playToken++;
    pauseSource();
    queue = [];
    queuePos = -1;
    queueStart = 0;
    prefetching = false;
    voiceDirty = false;
    activeSentence = -1;
    ttsBusy = false;
    if (repositionTimer) {
      clearTimeout(repositionTimer);
      repositionTimer = null;
    }
  }

  onMount(() => {
    audio = new AudioEngine();
    void open();
    window.addEventListener("resize", onResize);
    window.addEventListener("keydown", onKeydown);
  });

  onDestroy(() => {
    stopPlayback();
    stopAuto();
    window.removeEventListener("resize", onResize);
    window.removeEventListener("keydown", onKeydown);
    if (saveTimer) {
      clearTimeout(saveTimer);
      void saveNow();
    }
  });
</script>

<div class="reader">
  <header class="reader-header">
    <a href="#/" class="back" title="Back to library">←</a>
    <div class="title-block">
      <span class="book-title">{book?.title ?? "…"}</span>
      <span class="muted chapter-pos">
        Chapter {chapterIndex + 1}/{chapters.length} · {chapterPct}%
      </span>
    </div>
    <ChapterNav
      chapters={chapters}
      currentIndex={chapterIndex}
      onPrev={prevChapter}
      onNext={nextChapter}
      onSelect={selectChapter}
    />
    <div class="header-actions">
      <button
        class="listen-toggle"
        class:active={playing}
        on:click={togglePlay}
        disabled={loading || paragraphs.length === 0}
        title="Read aloud from the current position"
      >
        {castBusy ? "Preparing…" : ttsBusy ? "Loading…" : playing ? "Pause" : "Listen"}
      </button>
      <button
        class="auto-toggle"
        class:active={$settings.autoEnabled}
        on:click={() => settings.update((s) => ({ ...s, autoEnabled: !s.autoEnabled }))}
        title="Toggle auto progression"
      >
        Auto
      </button>
      <div class="settings-wrap">
        <button on:click={() => (showSettings = !showSettings)} title="Display settings">
          Aa
        </button>
        {#if showSettings}
          <SettingsPanel />
        {/if}
      </div>
      <div class="settings-wrap">
        <button
          on:click={() => (showVoice = !showVoice)}
          title="Voice settings"
          class:active={showVoice}
        >
          Voice
        </button>
        {#if showVoice}
          <VoicePanel store={tts} language={book?.language || ""} />
        {/if}
      </div>
    </div>
  </header>

  {#if loading}
    <main class="reader-body centered"><p class="muted">Loading…</p></main>
  {:else if loadError}
    <main class="reader-body centered">
      <p class="error">{loadError}</p>
      <a href="#/">Back to library</a>
    </main>
  {:else if paragraphs.length === 0}
    <main class="reader-body centered"><p class="muted">This chapter is empty.</p></main>
  {:else}
    <main class="reader-body">
      {#if isPaged}
        <div class="paged-viewport" bind:this={viewportEl}>
          <button
            class="zone left"
            aria-label="Previous page"
            on:click={() => turnPage(-1)}
          ></button>
          <button
            class="zone right"
            aria-label="Next page"
            on:click={() => turnPage(1)}
          ></button>
          <div
            class="reader-content paged-content"
            bind:this={contentEl}
            lang={book?.language || "en"}
            style={contentStyle +
              (colWidth > 0
                ? ` column-width: ${colWidth}px; column-gap: ${COLUMN_GAP}px; transform: translateX(-${pageOffset(
                    page,
                    colWidth
                  )}px);`
                : "")}
          >
            <h2 class="chapter-title">{chapters[chapterIndex]?.title}</h2>
            <SentenceContent
              {paragraphs}
              {sentencesByPara}
              {labels}
              activeSentence={activeSentence}
              on:tap={(e) => tapSentence(e.detail)}
            />
          </div>
        </div>
        <div class="page-indicator muted">Page {page + 1}/{pages}</div>
      {:else}
        <div class="scroll-viewport" bind:this={viewportEl} on:scroll={onScroll}>
          <div
            class="reader-content"
            bind:this={contentEl}
            lang={book?.language || "en"}
            style={contentStyle}
          >
            <h2 class="chapter-title">{chapters[chapterIndex]?.title}</h2>
            <SentenceContent
              {paragraphs}
              {sentencesByPara}
              {labels}
              activeSentence={activeSentence}
              on:tap={(e) => tapSentence(e.detail)}
            />
          </div>
        </div>
      {/if}
    </main>
  {/if}

  <footer class="reader-footer">
    <div class="progress-track">
      <div class="progress-fill" style="width: {bookPct}%"></div>
    </div>
    {#if ttsError}
      <span class="error" title={ttsError}>{ttsError}</span>
    {:else if castError}
      <span class="error" title={castError}>
        Voice cast unavailable: {castError}
      </span>
    {:else}
      <span class="muted">{bookPct}% of book</span>
    {/if}
  </footer>
</div>

<style>
  .reader {
    display: flex;
    flex-direction: column;
    height: 100%;
  }

  .reader-header {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
    background: var(--panel);
    flex-wrap: wrap;
  }

  .back {
    text-decoration: none;
    font-size: 18px;
    color: var(--fg);
  }

  .title-block {
    display: flex;
    flex-direction: column;
    min-width: 0;
    flex: 1;
  }

  .book-title {
    font-size: 15px;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .chapter-pos {
    font-size: 12px;
  }

  .header-actions {
    display: flex;
    gap: 8px;
    position: relative;
  }

  .listen-toggle.active,
  .auto-toggle.active {
    background: var(--accent);
    color: var(--bg);
    border-color: var(--accent);
  }

  .settings-wrap {
    position: relative;
  }

  .reader-body {
    flex: 1;
    min-height: 0;
    position: relative;
  }

  .scroll-viewport {
    height: 100%;
    overflow-y: auto;
    padding: 0 16px;
  }

  .reader-content {
    max-width: 42em;
    margin: 0 auto;
    /* European typography (AC-114..AC-116): justified with lang-aware
       hyphenation; quotes and dialogue dashes come through as authored. */
    text-align: justify;
    hyphens: auto;
    -webkit-hyphens: auto;
    overflow-wrap: break-word;
  }

  .paged-viewport {
    height: 100%;
    overflow: hidden;
    padding: 0 16px;
    position: relative;
  }

  /* Transparent tap zones: left third = previous page, right third = next
     page (reader convention). Keyboard: arrows / space. */
  .zone {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 30%;
    background: transparent;
    border: none;
    z-index: 5;
    cursor: pointer;
  }

  .zone:hover {
    background: transparent;
    border: none;
  }

  .zone.left {
    left: 0;
  }

  .zone.right {
    right: 0;
  }

  .paged-content {
    height: 100%;
    column-fill: auto;
    transition: transform 0.18s ease;
  }

  .chapter-title {
    font-size: 1.3em;
    margin: 1em 0 0.8em;
    text-align: left;
  }

  .reader-content :global(p) {
    margin: 0 0 0.9em;
    text-indent: 1.2em;
  }

  .page-indicator {
    text-align: center;
    font-size: 12px;
    padding: 6px 0;
  }

  .reader-footer {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 16px;
    border-top: 1px solid var(--border);
    background: var(--panel);
    font-size: 12px;
  }

  .progress-track {
    flex: 1;
    height: 4px;
    border-radius: 2px;
    background: var(--border);
    overflow: hidden;
  }

  .progress-fill {
    height: 100%;
    background: var(--accent);
    transition: width 0.2s ease;
  }

  @media (max-width: 600px) {
    .reader-header {
      gap: 8px;
      padding: 8px 10px;
    }

    .title-block {
      order: 5;
      flex-basis: 100%;
    }
  }
</style>

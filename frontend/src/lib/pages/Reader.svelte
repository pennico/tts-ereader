<script lang="ts">
  import { onDestroy, onMount, tick } from "svelte";
  import { api } from "../services/api";
  import { settings } from "../stores/settings";
  import {
    COLUMN_GAP,
    clampPage,
    nextPage,
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
  import type { Book, ChapterMeta } from "../types";

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

  let autoTimer: ReturnType<typeof setInterval> | null = null;
  let rafId: number | null = null;
  let lastFrame = 0;
  let saveTimer: ReturnType<typeof setTimeout> | null = null;

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
    const chapter = await api.getChapter(bookId, index);
    chapterIndex = index;
    paragraphs = chapter.text
      .split(/\n{2,}/)
      .map((p) => p.trim())
      .filter((p) => p.length > 0);
    page = 0;
    position = restorePosition ?? 0;
    await tick();
    measure();
    if (restorePosition !== null) applyPosition(restorePosition);
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
  }

  function goToPage(target: number): void {
    page = clampPage(target, pages);
    position = pageToPosition(page, pages);
    scheduleSave();
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

  $: autoKey = `${$settings.autoEnabled}|${$settings.scrollMode}|${$settings.autoPageSeconds}|${$settings.autoScrollPxPerSec}|${chapterIndex}|${pages}`;
  $: if (autoKey && !loading && !loadError) restartAuto();

  function restartAuto(): void {
    stopAuto();
    if (!$settings.autoEnabled) return;
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

  onMount(() => {
    void open();
    window.addEventListener("resize", onResize);
    window.addEventListener("keydown", onKeydown);
  });

  onDestroy(() => {
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
            {#each paragraphs as para, i (i)}
              <p>{para}</p>
            {/each}
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
            {#each paragraphs as para, i (i)}
              <p>{para}</p>
            {/each}
          </div>
        </div>
      {/if}
    </main>
  {/if}

  <footer class="reader-footer">
    <div class="progress-track">
      <div class="progress-fill" style="width: {bookPct}%"></div>
    </div>
    <span class="muted">{bookPct}% of book</span>
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

  .reader-content p {
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

<script lang="ts">
  import type { ChapterMeta } from "../types";

  export let chapters: ChapterMeta[];
  export let currentIndex: number;
  export let onPrev: () => void;
  export let onNext: () => void;
  export let onSelect: (index: number) => void;

  function change(event: Event & { currentTarget: HTMLSelectElement }): void {
    onSelect(Number(event.currentTarget.value));
  }
</script>

<nav class="chapter-nav" aria-label="Chapter navigation">
  <button on:click={onPrev} disabled={currentIndex <= 0} title="Previous chapter">
    ‹‹
  </button>
  <select value={currentIndex} on:change={change} aria-label="Chapter">
    {#each chapters as chapter (chapter.index)}
      <option value={chapter.index}>{chapter.index + 1}. {chapter.title}</option>
    {/each}
  </select>
  <button
    on:click={onNext}
    disabled={currentIndex >= chapters.length - 1}
    title="Next chapter"
  >
    ››
  </button>
</nav>

<style>
  .chapter-nav {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  select {
    max-width: 220px;
  }

  @media (max-width: 600px) {
    select {
      max-width: 130px;
    }
  }
</style>

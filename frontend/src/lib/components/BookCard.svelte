<script lang="ts">
  import type { Book } from "../types";
  import { api } from "../services/api";

  export let book: Book;
  export let onOpen: (book: Book) => void;
  export let onDelete: (book: Book) => void;

  let coverFailed = false;
  $: if (book.id) coverFailed = false;

  // Rough overall progress: (chapters done + fraction of current) / total.
  $: overall =
    book.chapter_count > 0
      ? Math.min(1, (book.progress_chapter + book.progress_position) / book.chapter_count)
      : 0;
  $: pct = Math.round(overall * 100);
</script>

<article class="book-card">
  <button class="cover-button" on:click={() => onOpen(book)} title="Open book">
    {#if book.cover_path && !coverFailed}
      <img
        src={api.coverUrl(book.id)}
        alt={`Cover of ${book.title}`}
        on:error={() => (coverFailed = true)}
      />
    {:else}
      <div class="cover-placeholder">
        <span class="cover-title">{book.title}</span>
        <span class="cover-author">{book.author}</span>
      </div>
    {/if}
  </button>
  <div class="book-meta">
    <button class="title" on:click={() => onOpen(book)} title="Open book">
      {book.title}
    </button>
    <p class="muted">{book.author}</p>
    <div class="progress-row">
      <div class="progress-track">
        <div class="progress-fill" style="width: {pct}%"></div>
      </div>
      <span class="muted progress-pct">{pct}%</span>
    </div>
  </div>
  <button class="delete" on:click={() => onDelete(book)} title="Remove from library">
    Remove
  </button>
</article>

<style>
  .book-card {
    display: flex;
    flex-direction: column;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px;
    gap: 8px;
  }

  .cover-button {
    padding: 0;
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
    background: var(--bg);
    aspect-ratio: 2 / 3;
    cursor: pointer;
    display: flex;
  }

  .cover-button img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .cover-placeholder {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 12px;
    text-align: center;
    gap: 6px;
  }

  .cover-title {
    font-family: Georgia, serif;
    font-size: 17px;
  }

  .cover-author {
    font-size: 12px;
    color: var(--muted);
  }

  .book-meta .title {
    text-align: left;
    background: none;
    border: none;
    padding: 0;
    margin: 0;
    font-size: 15px;
    font-weight: 600;
    color: var(--fg);
    cursor: pointer;
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
  }

  .book-meta p {
    margin: 2px 0 6px;
    font-size: 13px;
  }

  .progress-row {
    display: flex;
    align-items: center;
    gap: 8px;
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
  }

  .progress-pct {
    font-size: 12px;
    min-width: 34px;
    text-align: right;
  }

  .delete {
    align-self: flex-start;
    font-size: 12px;
    padding: 3px 8px;
  }
</style>

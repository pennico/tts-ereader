<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../services/api";
  import BookCard from "../components/BookCard.svelte";
  import type { Book } from "../types";

  let books: Book[] = [];
  let error: string | null = null;
  let importing = false;
  let dragOver = false;
  let fileInput: HTMLInputElement;

  async function refresh(): Promise<void> {
    try {
      books = await api.listBooks();
      error = null;
    } catch (e) {
      error = `Could not load library: ${e instanceof Error ? e.message : String(e)}`;
    }
  }

  async function importFiles(files: Iterable<File>): Promise<void> {
    importing = true;
    error = null;
    try {
      for (const file of files) {
        if (!file.name.toLowerCase().endsWith(".epub")) {
          error = `Skipped "${file.name}": not an EPUB`;
          continue;
        }
        try {
          await api.importBook(file);
        } catch (e) {
          error = `Import of "${file.name}" failed: ${
            e instanceof Error ? e.message : String(e)
          }`;
        }
      }
      await refresh();
    } finally {
      importing = false;
    }
  }

  function onDrop(event: DragEvent): void {
    event.preventDefault();
    dragOver = false;
    if (event.dataTransfer?.files?.length) {
      void importFiles(Array.from(event.dataTransfer.files));
    }
  }

  function onDragOver(event: DragEvent): void {
    event.preventDefault();
    dragOver = true;
  }

  function onDragLeave(): void {
    dragOver = false;
  }

  function openBook(book: Book): void {
    window.location.hash = `#/book/${book.id}`;
  }

  async function removeBook(book: Book): Promise<void> {
    if (!window.confirm(`Remove "${book.title}" from the library?`)) return;
    await api.deleteBook(book.id);
    await refresh();
  }

  onMount(refresh);
</script>

<svelte:window on:dragover={onDragOver} />

<main
  class="library"
  class:dragover={dragOver}
  on:drop={onDrop}
  on:dragover={onDragOver}
  on:dragleave={onDragLeave}
>
  <header class="library-header">
    <h1>Library</h1>
    <div class="actions">
      <input
        type="file"
        accept=".epub,application/epub+zip"
        multiple
        bind:this={fileInput}
        on:change={() => fileInput.files && importFiles(Array.from(fileInput.files))}
        hidden
      />
      <button class="primary" disabled={importing} on:click={() => fileInput.click()}>
        {importing ? "Importing…" : "Import EPUBs"}
      </button>
    </div>
  </header>

  {#if error}
    <p class="error">{error}</p>
  {/if}

  {#if books.length === 0 && !error}
    <p class="muted empty-hint">
      No books yet. Import EPUB files with the button above, or drag &amp; drop
      them anywhere on this page.
    </p>
  {:else}
    <div class="book-grid">
      {#each books as book (book.id)}
        <BookCard book={book} onOpen={openBook} onDelete={removeBook} />
      {/each}
    </div>
  {/if}
</main>

<style>
  .library {
    max-width: 1100px;
    margin: 0 auto;
    padding: 24px;
    min-height: 100%;
  }

  .library.dragover {
    outline: 2px dashed var(--accent);
    outline-offset: -12px;
    border-radius: 12px;
  }

  .library-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
  }

  h1 {
    margin: 0;
    font-size: 24px;
  }

  .empty-hint {
    margin-top: 48px;
    text-align: center;
  }

  .book-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
    gap: 16px;
    margin-top: 20px;
  }

  @media (max-width: 600px) {
    .library {
      padding: 14px;
    }

    .book-grid {
      grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
      gap: 10px;
    }
  }
</style>

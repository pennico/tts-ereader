<script lang="ts">
  import { onDestroy } from "svelte";
  import Library from "./lib/pages/Library.svelte";
  import Reader from "./lib/pages/Reader.svelte";
  import { settings } from "./lib/stores/settings";
  import { applyTheme } from "./lib/utils/themes";

  type Route =
    | { name: "library" }
    | { name: "reader"; bookId: number }
    | { name: "notfound" };

  let hash = typeof window !== "undefined" ? window.location.hash : "#/";
  // Offline indicator (M4): the app is local-first, but imports, synthesis,
  // and LLM preparation need the server — surface lost connectivity instead
  // of failing silently.
  let online = typeof navigator !== "undefined" ? navigator.onLine : true;

  function handleHashChange(): void {
    hash = window.location.hash || "#/";
  }
  function updateOnline(): void {
    online = navigator.onLine;
  }
  window.addEventListener("hashchange", handleHashChange);
  window.addEventListener("online", updateOnline);
  window.addEventListener("offline", updateOnline);
  onDestroy(() => {
    window.removeEventListener("hashchange", handleHashChange);
    window.removeEventListener("online", updateOnline);
    window.removeEventListener("offline", updateOnline);
  });

  function parseRoute(h: string): Route {
    const match = h.match(/^#\/book\/(\d+)/);
    if (match) return { name: "reader", bookId: Number(match[1]) };
    if (h === "#/" || h === "" || h === "#") return { name: "library" };
    return { name: "notfound" };
  }

  $: route = parseRoute(hash);
  // Theme is app-wide so the library and reader share it (AC-105..AC-108).
  $: applyTheme(document.documentElement, $settings);
</script>

{#if !online}
  <div class="offline-banner" role="status">
    Offline — the server is unreachable. Reading and cached audio still work;
    imports and synthesis will fail until the connection returns.
  </div>
{/if}
{#if route.name === "library"}
  <Library />
{:else if route.name === "reader"}
  <Reader bookId={route.bookId} />
{:else}
  <main class="centered">
    <p>Page not found.</p>
    <a href="#/">Back to library</a>
  </main>
{/if}

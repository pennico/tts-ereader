<script lang="ts">
  import Library from "./lib/pages/Library.svelte";
  import Reader from "./lib/pages/Reader.svelte";
  import { settings } from "./lib/stores/settings";
  import { applyTheme } from "./lib/utils/themes";

  type Route =
    | { name: "library" }
    | { name: "reader"; bookId: number }
    | { name: "notfound" };

  let hash = typeof window !== "undefined" ? window.location.hash : "#/";

  function handleHashChange(): void {
    hash = window.location.hash || "#/";
  }
  window.addEventListener("hashchange", handleHashChange);

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

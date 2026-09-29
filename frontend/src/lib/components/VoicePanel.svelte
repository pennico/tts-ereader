<script lang="ts">
  /**
   * Voice panel: engine + voice selection and rate (AC-301..AC-303), plus the
   * voice-driven auto-advance toggle (AC-205). Per-book settings via the tts
   * store passed in from the reader.
   */
  import { onMount } from "svelte";
  import type { Writable } from "svelte/store";
  import { api } from "../services/api";
  import type { TtsEngineInfo, TtsSettings, TtsVoiceInfo } from "../types";

  export let store: Writable<TtsSettings>;
  export let language = "";

  let engines: TtsEngineInfo[] = [];
  let voices: TtsVoiceInfo[] = [];
  let loading = true;
  let error: string | null = null;

  $: selectedEngine = $store.engine;
  $: selectedVoice = $store.voice;
  $: unavailableEngine = engines.find(
    (e) => e.name === selectedEngine && !e.available
  );

  onMount(async () => {
    try {
      engines = await api.listEngines();
      await refreshVoices();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  });

  async function refreshVoices(): Promise<void> {
    try {
      voices = await api.listVoices(selectedEngine, language || undefined);
      if (voices.length > 0 && !voices.some((v) => v.name === $store.voice)) {
        // Pick a voice matching the book's language, else the first.
        const lang = (language || "").split("-")[0].toLowerCase();
        const preferred =
          voices.find((v) => v.locale.toLowerCase().startsWith(lang)) ?? voices[0];
        setVoice(preferred.name);
      }
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  }

  function setVoice(name: string): void {
    store.update((s) => ({ ...s, voice: name }));
  }

  function onEngine(event: Event & { currentTarget: HTMLSelectElement }): void {
    const name = event.currentTarget.value;
    store.update((s) => ({ ...s, voice: "" })); // force re-pick for the engine
    store.update((s) => ({ ...s, engine: name }));
    void refreshVoices();
  }

  function onVoice(event: Event & { currentTarget: HTMLSelectElement }): void {
    setVoice(event.currentTarget.value);
  }

  function onRate(event: Event & { currentTarget: HTMLInputElement }): void {
    store.update((s) => ({ ...s, rate: Number(event.currentTarget.value) }));
  }

  function onAutoAdvance(event: Event & { currentTarget: HTMLInputElement }): void {
    store.update((s) => ({ ...s, autoAdvance: event.currentTarget.checked }));
  }
</script>

<div class="voice-panel" role="dialog" aria-label="Voice settings">
  {#if loading}
    <p class="muted">Loading engines…</p>
  {:else if error}
    <p class="error">{error}</p>
  {:else}
    <section>
      <h4>Engine</h4>
      <select value={selectedEngine} on:change={onEngine}>
        {#each engines as engine (engine.name)}
          <option value={engine.name} disabled={!engine.available}>
            {engine.display_name}{engine.is_default ? " (default)" : ""}
            {engine.available ? "" : " — unavailable"}
          </option>
        {/each}
      </select>
      {#if unavailableEngine}
        <p class="hint">
          {unavailableEngine.display_name} is unavailable here (missing API key);
          synthesis falls back automatically.
        </p>
      {/if}
    </section>

    <section>
      <h4>Voice</h4>
      <select value={selectedVoice} on:change={onVoice}>
        {#each voices as voice (voice.name)}
          <option value={voice.name}>
            {voice.display_name}{voice.locale ? ` (${voice.locale})` : ""}
          </option>
        {/each}
      </select>
    </section>

    <section>
      <h4>Rate</h4>
      <label class="inline">
        <input
          type="range"
          min="0.5"
          max="2"
          step="0.05"
          value={$store.rate}
          on:input={onRate}
        />
        <span class="muted">{$store.rate.toFixed(2)}x</span>
      </label>
    </section>

    <section>
      <label class="inline">
        <input
          type="checkbox"
          checked={$store.autoAdvance}
          on:change={onAutoAdvance}
        />
        Auto-advance chapters when the voice finishes
      </label>
    </section>
  {/if}
</div>

<style>
  .voice-panel {
    position: absolute;
    right: 0;
    top: calc(100% + 6px);
    z-index: 30;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px 14px;
    width: 280px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.18);
  }

  h4 {
    margin: 0 0 6px;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted, inherit);
  }

  select,
  input[type="range"] {
    width: 100%;
  }

  .inline {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .hint {
    font-size: 12px;
    margin: 6px 0 0;
    color: var(--muted, inherit);
  }

  .error {
    color: #b33;
    font-size: 13px;
    margin: 0;
  }
</style>

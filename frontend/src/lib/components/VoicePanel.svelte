<script lang="ts">
  /**
   * Voice panel: engine + voice selection, rate and pitch (AC-301..AC-304),
   * "Test this voice" (AC-306), and the per-book voice cast (AC-305, AC-307).
   * Cast preparation itself is driven by the reader when castEnabled turns
   * on; this panel only edits and persists the settings.
   */
  import { onDestroy, onMount } from "svelte";
  import type { Writable } from "svelte/store";
  import { api } from "../services/api";
  import { AudioEngine } from "../services/audioEngine";
  import {
    CAST_ROLES,
    CAST_ROLE_LABELS,
    type CastRole,
    type TtsEngineInfo,
    type TtsSettings,
    type TtsVoiceInfo,
  } from "../types";

  export let store: Writable<TtsSettings>;
  export let language = "";

  let engines: TtsEngineInfo[] = [];
  let voices: TtsVoiceInfo[] = [];
  let loading = true;
  let error: string | null = null;

  // "Test this voice" (AC-306)
  let testing = false;
  let testEngine: AudioEngine | null = null;

  const SAMPLE_TEXTS: Record<string, string> = {
    it: "Così va il mondo: una voce legge, e il resto ascolta.",
    da: "Sådan går verden: en stemme læser, og resten lytter.",
    en: "So goes the world: one voice reads, and the rest listens.",
  };

  function sampleText(): string {
    const lang = (language || "en").split("-")[0].toLowerCase();
    return SAMPLE_TEXTS[lang] ?? SAMPLE_TEXTS.en;
  }

  $: selectedEngine = $store.engine;
  $: selectedVoice = $store.voice;
  $: unavailableEngine = engines.find(
    (e) => e.name === selectedEngine && !e.available
  );

  onMount(async () => {
    try {
      engines = await api.listEngines();
      await refreshVoices();
      await refreshCastDefaults();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  });

  onDestroy(() => {
    testEngine?.pause();
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

  /** Default cast voices for the engine + language (AC-305). */
  async function refreshCastDefaults(): Promise<void> {
    try {
      const defaults = await api.castDefaults(selectedEngine, language || undefined);
      const byRole = new Map(defaults.roles.map((r) => [r.role, r.voice]));
      store.update((s) => {
        const cast: Record<string, string> = {};
        for (const role of CAST_ROLES) {
          cast[role] = s.cast[role] || byRole.get(role) || "";
        }
        return { ...s, cast };
      });
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  }

  function setVoice(name: string): void {
    store.update((s) => ({ ...s, voice: name }));
  }

  function onEngine(event: Event & { currentTarget: HTMLSelectElement }): void {
    const name = event.currentTarget.value;
    store.update((s) => ({
      ...s,
      voice: "", // force re-pick for the engine
      cast: {}, // cast voices are engine-specific; refill from defaults
      engine: name,
    }));
    void refreshVoices();
    void refreshCastDefaults();
  }

  function onVoice(event: Event & { currentTarget: HTMLSelectElement }): void {
    setVoice(event.currentTarget.value);
  }

  function onRate(event: Event & { currentTarget: HTMLInputElement }): void {
    store.update((s) => ({ ...s, rate: Number(event.currentTarget.value) }));
  }

  function onPitch(event: Event & { currentTarget: HTMLInputElement }): void {
    store.update((s) => ({ ...s, pitch: Number(event.currentTarget.value) }));
  }

  function onAutoAdvance(event: Event & { currentTarget: HTMLInputElement }): void {
    store.update((s) => ({ ...s, autoAdvance: event.currentTarget.checked }));
  }

  function onCastToggle(event: Event & { currentTarget: HTMLInputElement }): void {
    store.update((s) => ({ ...s, castEnabled: event.currentTarget.checked }));
  }

  function onCastRoleSelect(
    role: CastRole
  ): (event: Event & { currentTarget: HTMLSelectElement }) => void {
    return (event) => {
      store.update((s) => ({
        ...s,
        cast: { ...s.cast, [role]: event.currentTarget.value },
      }));
    };
  }

  /** AC-306: synthesize a short sample with the current settings and play it. */
  async function testVoice(): Promise<void> {
    if (testing || !$store.voice) return;
    testing = true;
    error = null;
    try {
      if (!testEngine) testEngine = new AudioEngine();
      testEngine.pause();
      const segment = await api.synthesize({
        text: sampleText(),
        engine: $store.engine,
        voice: $store.voice,
        rate: 1.0, // playback rate is applied client-side (AC-303)
        pitch: $store.pitch,
      });
      const buffer = await testEngine.decode(segment.audio_b64);
      await testEngine.play(buffer, 0, $store.rate);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      testing = false;
    }
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
      <button class="test" on:click={testVoice} disabled={testing || !$store.voice}>
        {testing ? "Synthesizing…" : "Test this voice"}
      </button>
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
      <h4>Pitch</h4>
      <label class="inline">
        <input
          type="range"
          min="-20"
          max="20"
          step="1"
          value={$store.pitch}
          on:input={onPitch}
        />
        <span class="muted">
          {$store.pitch > 0 ? "+" : ""}{$store.pitch}
        </span>
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

    <section>
      <label class="inline">
        <input
          type="checkbox"
          checked={$store.castEnabled}
          on:change={onCastToggle}
        />
        Voice cast (LLM speaker tagging)
      </label>
      {#if $store.castEnabled}
        <div class="cast">
          {#each CAST_ROLES as role (role)}
            <label class="cast-role">
              <span>{CAST_ROLE_LABELS[role]}</span>
              <select value={$store.cast[role] ?? ""} on:change={onCastRoleSelect(role)}>
                {#each voices as voice (voice.name)}
                  <option value={voice.name}>
                    {voice.display_name}{voice.locale ? ` (${voice.locale})` : ""}
                  </option>
                {/each}
              </select>
            </label>
          {/each}
          <p class="hint">
            The chapter is prepared with the LLM (needs MISTRAL_API_KEY) and each
            character reads with their own voice. The prepared text replaces the
            chapter view while the cast is on.
          </p>
        </div>
      {/if}
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
    max-height: 70vh;
    overflow-y: auto;
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

  .test {
    margin-top: 6px;
    width: 100%;
  }

  .cast {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-top: 8px;
  }

  .cast-role {
    display: flex;
    flex-direction: column;
    gap: 2px;
    font-size: 12px;
    color: var(--muted, inherit);
  }
</style>

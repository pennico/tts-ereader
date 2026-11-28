<script lang="ts">
  import { settings } from "../stores/settings";
  import { THEMES } from "../utils/themes";
  import type { FontFamily, ReaderSettings, ThemeName } from "../types";

  function patch(part: Partial<ReaderSettings>): void {
    settings.update((s) => ({ ...s, ...part }));
  }

  function onTheme(event: Event & { currentTarget: HTMLSelectElement }): void {
    patch({ theme: event.currentTarget.value as ThemeName });
  }

  function onFontFamily(event: Event & { currentTarget: HTMLSelectElement }): void {
    patch({ fontFamily: event.currentTarget.value as FontFamily });
  }

  function onFontSize(event: Event & { currentTarget: HTMLInputElement }): void {
    patch({ fontSize: Number(event.currentTarget.value) });
  }

  function onWeight(event: Event & { currentTarget: HTMLSelectElement }): void {
    patch({ fontWeight: event.currentTarget.value as "normal" | "bold" });
  }

  function onLineHeight(event: Event & { currentTarget: HTMLInputElement }): void {
    patch({ lineHeight: Number(event.currentTarget.value) });
  }

  function onMode(event: Event & { currentTarget: HTMLInputElement }): void {
    patch({ scrollMode: event.currentTarget.value as "scroll" | "paged" });
  }

  function onAuto(event: Event & { currentTarget: HTMLInputElement }): void {
    patch({ autoEnabled: event.currentTarget.checked });
  }

  function onPageSeconds(event: Event & { currentTarget: HTMLInputElement }): void {
    patch({ autoPageSeconds: Number(event.currentTarget.value) });
  }

  function onScrollSpeed(event: Event & { currentTarget: HTMLInputElement }): void {
    patch({ autoScrollPxPerSec: Number(event.currentTarget.value) });
  }
</script>

<div class="settings-panel" role="dialog" aria-label="Reader settings">
  <section>
    <h4>Theme</h4>
    <select value={$settings.theme} on:change={onTheme}>
      <option value="light">Light</option>
      <option value="dark">Dark</option>
      <option value="sepia">Sepia</option>
      <option value="custom">Custom</option>
    </select>
    {#if $settings.theme === "custom"}
      <label class="inline">
        Text
        <input
          type="color"
          value={$settings.customFg}
          on:input={(e) => patch({ customFg: e.currentTarget.value })}
        />
      </label>
      <label class="inline">
        Background
        <input
          type="color"
          value={$settings.customBg}
          on:input={(e) => patch({ customBg: e.currentTarget.value })}
        />
      </label>
    {/if}
  </section>

  <section>
    <h4>Font</h4>
    <label class="block">
      Family
      <select value={$settings.fontFamily} on:change={onFontFamily}>
        <option value="serif">Serif</option>
        <option value="sans-serif">Sans-serif</option>
        <option value="monospace">Monospace</option>
      </select>
    </label>
    <label class="block">
      Size ({$settings.fontSize}pt)
      <input
        type="range"
        min="8"
        max="32"
        step="1"
        value={$settings.fontSize}
        on:input={onFontSize}
      />
    </label>
    <label class="block">
      Weight
      <select value={$settings.fontWeight} on:change={onWeight}>
        <option value="normal">Normal</option>
        <option value="bold">Bold</option>
      </select>
    </label>
    <label class="block">
      Line height ({$settings.lineHeight.toFixed(2)})
      <input
        type="range"
        min="1.0"
        max="2.5"
        step="0.05"
        value={$settings.lineHeight}
        on:input={onLineHeight}
      />
    </label>
  </section>

  <section>
    <h4>Scrolling</h4>
    <label class="inline">
      <input
        type="radio"
        name="scroll-mode"
        value="scroll"
        checked={$settings.scrollMode === "scroll"}
        on:change={onMode}
      />
      Continuous
    </label>
    <label class="inline">
      <input
        type="radio"
        name="scroll-mode"
        value="paged"
        checked={$settings.scrollMode === "paged"}
        on:change={onMode}
      />
      Paginated
    </label>
  </section>

  <section>
    <h4>Auto progression</h4>
    <label class="inline">
      <input type="checkbox" checked={$settings.autoEnabled} on:change={onAuto} />
      Enabled
    </label>
    {#if $settings.scrollMode === "paged"}
      <label class="block">
        Seconds per page
        <input
          type="range"
          min="2"
          max="60"
          step="1"
          value={$settings.autoPageSeconds}
          on:input={onPageSeconds}
        />
        <span class="muted">{$settings.autoPageSeconds}s</span>
      </label>
    {:else}
      <label class="block">
        Scroll speed
        <input
          type="range"
          min="10"
          max="200"
          step="5"
          value={$settings.autoScrollPxPerSec}
          on:input={onScrollSpeed}
        />
        <span class="muted">{$settings.autoScrollPxPerSec}px/s</span>
      </label>
    {/if}
  </section>
</div>

<style>
  .settings-panel {
    position: absolute;
    top: 100%;
    right: 0;
    z-index: 20;
    width: 280px;
    max-height: 70vh;
    overflow-y: auto;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px 16px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18);
  }

  section {
    margin-bottom: 14px;
  }

  section:last-child {
    margin-bottom: 4px;
  }

  h4 {
    margin: 0 0 6px;
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted);
  }

  label {
    display: block;
    font-size: 14px;
    margin: 6px 0;
  }

  label.inline {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-right: 12px;
  }

  label.block {
    display: block;
  }

  input[type="range"] {
    width: 100%;
  }
</style>

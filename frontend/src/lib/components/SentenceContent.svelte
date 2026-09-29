<script lang="ts">
  /**
   * Chapter body rendered as tappable sentence spans (M2, AC-201/AC-202).
   * Each span carries its global sentence index (data-sid) so the reader can
   * highlight the spoken sentence and map taps to playback positions.
   * In voice-cast mode (M3) each paragraph is one prepared line and may carry
   * a speaker label, shown as a non-spoken prefix.
   */
  import { createEventDispatcher } from "svelte";
  import type { ChapterSentence } from "../utils/sentences";

  export let paragraphs: string[] = [];
  export let sentencesByPara: Map<number, ChapterSentence[]> = new Map();
  export let activeSentence = -1;
  export let labels: (string | null)[] = [];

  const dispatch = createEventDispatcher<{ tap: number }>();

  function sentencesOf(para: number): ChapterSentence[] {
    return sentencesByPara.get(para) ?? [];
  }
</script>

{#each paragraphs as para, i (i)}
  <p>
    {#if labels[i]}<span class="speaker">{labels[i]}</span>{" "}{/if}
    {#each sentencesOf(i) as s, k (s.index)}
      {#if k > 0}{" "}{/if}
      <span
        class="sent"
        class:active={s.index === activeSentence}
        data-sid={s.index}
        on:click={() => dispatch("tap", s.index)}
        on:keydown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            dispatch("tap", s.index);
          }
        }}
        role="button"
        tabindex="-1"
      >{s.text}</span>
    {/each}
  </p>
{/each}

<style>
  .sent {
    cursor: pointer;
    border-radius: 2px;
    transition: background 0.12s ease;
  }

  .sent:hover {
    background: var(--border);
  }

  /* Spoken-sentence highlight (AC-202). */
  .sent.active {
    background: var(--accent);
    color: var(--bg);
  }

  /* Speaker label in voice-cast mode (M3, AC-305) — never spoken. */
  .speaker {
    font-weight: 600;
    font-size: 0.85em;
    letter-spacing: 0.04em;
    color: var(--muted, inherit);
  }
</style>

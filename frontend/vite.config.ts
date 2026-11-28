/// <reference types="vitest" />
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { sveltePreprocess } from "svelte-preprocess";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [svelte({ preprocess: sveltePreprocess() })],
  server: {
    proxy: {
      // Dev only: the FastAPI backend runs on :8000.
      "/api": "http://localhost:8000",
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});

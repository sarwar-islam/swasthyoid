/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // live mode (VITE_API_MODE=live) talks to the FastAPI app through the dev server, so the browser sees one origin. The
  // normal API is :8000; SWASTHYOID_API_TARGET points the isolated M10 test build at its own API (scripts/dev_api.ps1).
  server: { port: 5173, proxy: { "/api": process.env.SWASTHYOID_API_TARGET ?? "http://127.0.0.1:8000" } },
  test: { environment: "jsdom" },
});

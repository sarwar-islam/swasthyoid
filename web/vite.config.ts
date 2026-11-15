/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // live mode (VITE_API_MODE=live) talks to the FastAPI app on :8000 through the dev server, so the browser sees one origin
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
  test: { environment: "jsdom" },
});

import { fetchTransport, type Transport } from "./client";
import { mockTransport } from "./mock";

// VITE_API_MODE=live talks to the FastAPI app (through the dev-server proxy); anything else uses the synthetic mock.
export const apiMode: "live" | "mock" = import.meta.env.VITE_API_MODE === "live" ? "live" : "mock";

export function defaultTransport(): Transport {
  return apiMode === "live" ? fetchTransport() : mockTransport();
}

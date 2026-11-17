import { fetchTransport, type Transport } from "./client";

// VITE_API_MODE=live talks to the FastAPI app (through the dev-server proxy); anything else uses the synthetic mock.
export const apiMode: "live" | "mock" = import.meta.env.VITE_API_MODE === "live" ? "live" : "mock";

export function defaultTransport(): Transport {
  if (apiMode === "live") return fetchTransport();
  // the synthetic mock is a separate file, fetched on the first request: a live build never downloads it
  let mock: Promise<Transport> | null = null;
  return (request) => (mock ??= import("./mock").then((m) => m.mockTransport()))
    .then((transport) => transport(request));
}

import type { ApiErrorBody } from "./types";

export type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface ApiRequest {
  method: Method;
  path: string; // under /api/v1, e.g. "/auth/otp/request"
  headers: Record<string, string>;
  body?: unknown; // JSON-serialisable, or FormData for uploads
  binary?: boolean; // the caller wants the body as a Blob (images)
}

export interface ApiResponse {
  status: number;
  body: unknown;
}

/** How a request reaches a server: fetch for the real API, or the in-memory mock (api/mock.ts). */
export type Transport = (request: ApiRequest) => Promise<ApiResponse>;

export class ApiError extends Error {
  constructor(readonly status: number, readonly code: string, message: string, readonly details: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
  }
}

function asError(status: number, body: unknown): ApiError {
  const b = body as Partial<ApiErrorBody> | null;
  if (b && typeof b.code === "string" && typeof b.message === "string") {
    return new ApiError(status, b.code, b.message, b.details ?? {});
  }
  // FastAPI answers a route it does not have with a bare 404/405: say the screen is not on the server yet (docs/ROUTES.md)
  if (status === 404 || status === 405) return new ApiError(status, "not_built", `HTTP ${status}`);
  // a proxy in front of a stopped or unreachable API answers 502/503/504 with no API body: the server can't be reached
  if (status === 502 || status === 503 || status === 504) return new ApiError(status, "network_unavailable", `HTTP ${status}`);
  return new ApiError(status, "unexpected_response", `HTTP ${status}`); // never echo an unknown body
}

export function fetchTransport(base = "/api/v1"): Transport {
  return async ({ method, path, headers, body, binary }) => {
    const form = body instanceof FormData; // the browser sets the multipart boundary itself
    let response: Response;
    try {
      response = await fetch(base + path, {
        method,
        headers: body === undefined || form ? headers : { "Content-Type": "application/json", ...headers },
        body: body === undefined ? undefined : form ? body : JSON.stringify(body),
      });
    } catch {
      return { status: 0, body: { code: "network_unavailable", message: "The server could not be reached.", details: {} } };
    }
    if (binary && response.ok) return { status: response.status, body: await response.blob() };
    const text = await response.text();
    let parsed: unknown = null;
    try {
      parsed = text ? JSON.parse(text) : null;
    } catch {
      parsed = null;
    }
    return { status: response.status, body: parsed };
  };
}

export interface RequestOptions {
  body?: unknown;
  idempotencyKey?: string;
  binary?: boolean;
}

/** A typed client. Writes always carry an Idempotency-Key (FRD section 7); the token stays in memory, never in storage. */
export function createClient(transport: Transport, getToken: () => string | null = () => null) {
  async function request<T>(method: Method, path: string, options: RequestOptions = {}): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    if (method !== "GET") headers["Idempotency-Key"] = options.idempotencyKey ?? crypto.randomUUID();
    const response = await transport({ method, path, headers, body: options.body, binary: options.binary });
    if (response.status >= 200 && response.status < 300) return response.body as T;
    throw asError(response.status, response.body);
  }
  return { request };
}

export type Client = ReturnType<typeof createClient>;

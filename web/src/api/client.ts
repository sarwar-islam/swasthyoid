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

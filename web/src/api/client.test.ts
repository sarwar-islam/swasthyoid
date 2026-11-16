import { describe, expect, it } from "vitest";
import { ApiError, createClient, type ApiRequest, type Transport } from "./client";
import { MOCK_CODE, mockTransport } from "./mock";
import type { TokenPair } from "./types";

const failed = (p: Promise<unknown>) => p.then(() => { throw new Error("expected a failure"); }, (e: ApiError) => e);

function recording(status: number, body: unknown) {
  const seen: ApiRequest[] = [];
  const transport: Transport = async (request) => {
    seen.push(request);
    return { status, body };
  };
  return { seen, transport };
}

describe("client", () => {
  it("sends the bearer token, and an Idempotency-Key on writes only", async () => {
    const { seen, transport } = recording(200, { ok: true });
    const client = createClient(transport, () => "tok");
    await client.request("GET", "/consents");
    await client.request("POST", "/consents/requests", { body: { health_id: "SID-0" } });
    await client.request("POST", "/x", { idempotencyKey: "fixed" });
    expect(seen[0].headers.Authorization).toBe("Bearer tok");
    expect(seen[0].headers["Idempotency-Key"]).toBeUndefined();
    expect(seen[1].headers["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(seen[2].headers["Idempotency-Key"]).toBe("fixed");
  });

  it("turns the API error format into an ApiError", async () => {
    const { transport } = recording(403, { code: "consent_required", message: "No consent.", details: { purpose: "TIMELINE" } });
    const failure = await failed(createClient(transport).request("GET", "/patients/1/timeline"));
    expect(failure).toBeInstanceOf(ApiError);
    expect([failure.status, failure.code, failure.details]).toEqual([403, "consent_required", { purpose: "TIMELINE" }]);
  });

  it("never echoes an unexpected error body", async () => {
    const { transport } = recording(500, "<html>stack trace with SYNTH-SECRET</html>");
    const failure = await failed(createClient(transport).request("GET", "/x"));
    expect([failure.code, failure.message]).toEqual(["unexpected_response", "HTTP 500"]);
  });
});

describe("mock transport", () => {
  const client = createClient(mockTransport());

  it("answers the built OTP routes with the backend's shapes", async () => {
    await expect(client.request("POST", "/auth/otp/request", { body: { phone: "+8801700000001" } })).resolves.toBeNull();
    const tokens = await client.request<TokenPair>("POST", "/auth/otp/verify",
      { body: { phone: "+8801700000001", code: MOCK_CODE, device_id: "web" } });
    expect(Object.keys(tokens).sort()).toEqual(["access_token", "refresh_token"]);
    const wrong = await failed(client.request("POST", "/auth/otp/verify", { body: { code: "000000" } }));
    expect([wrong.status, wrong.code]).toEqual([401, "invalid_code"]);
  });

  it("answers 501 for any route it does not know, never a made-up success", async () => {
    const failure = await failed(client.request("GET", "/patients/1/referrals")); // M9 is out of scope: never mocked
    expect([failure.status, failure.code]).toEqual([501, "not_built_in_mock"]);
  });
});

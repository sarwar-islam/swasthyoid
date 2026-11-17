import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApiRequest, Transport } from "../api/client";
import { MOCK_CODE, MOCK_PHONE, mockTransport } from "../api/mock";
import { IDLE_MS } from "../session";
import { axeViolations, DOCTOR_TOKEN, PATIENT_TOKEN, renderApp } from "../test-utils";

// W2 (owner decisions a and S8, 2026-11-17): the refresh token is an HttpOnly cookie the page never sees; a refused request
// renews the access token once, a reload renews it from the cookie, and an idle screen signs out (30 min patient, 15 staff).
afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const ENDED = { bn: "আপনার সেশন শেষ হয়ে গেছে। আবার লগইন করুন।", en: "Your session has ended. Please sign in again." };

/** The mock, recording every request; `refuse(r)` turns a request into a 401 as the server would. */
function spy(refuse: (r: ApiRequest) => boolean = () => false) {
  const inner = mockTransport();
  const seen: ApiRequest[] = [];
  const transport: Transport = (r) => {
    seen.push(r);
    return refuse(r) ? Promise.resolve({ status: 401, body: { code: "unauthenticated", message: "x", details: {} } }) : inner(r);
  };
  return { seen, transport, refreshes: () => seen.filter((r) => r.path === "/auth/refresh") };
}

/** A server whose refresh cookie holds `token` for `account` (as after a reload). */
function cookieFor(account: "patient" | "staff", token: string) {
  const inner = mockTransport();
  const seen: ApiRequest[] = [];
  const transport: Transport = (r) => {
    seen.push(r);
    if (r.path !== "/auth/refresh") return inner(r);
    const body = r.body as { account?: string };
    return Promise.resolve(body.account === account && r.headers["X-SwasthyoID-CSRF"] === "1"
      ? { status: 200, body: { access_token: token } }
      : { status: 401, body: { code: "invalid_session", message: "Log in again.", details: {} } });
  };
  return { seen, transport };
}

async function signInAsPatient() {
  fireEvent.change(screen.getByLabelText("Mobile number"), { target: { value: MOCK_PHONE } });
  fireEvent.click(screen.getByRole("button", { name: "Send code" }));
  fireEvent.change(await screen.findByLabelText("One-time code"), { target: { value: MOCK_CODE } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  await screen.findByText("SID-4827190356");
}

describe("W2 session renewal", () => {
  it("a request refused for an old access token is renewed from the cookie and sent again, unseen", async () => {
    let refuseNext = false;
    const { seen, transport, refreshes } = spy((r) => !!r.headers.Authorization && refuseNext && !(refuseNext = false));
    renderApp("/patient/login", { lang: "en", transport });
    await signInAsPatient();
    expect(seen.find((r) => r.path === "/auth/otp/verify")!.headers["X-SwasthyoID-CSRF"]).toBe("1");
    refuseNext = true;
    fireEvent.click(screen.getAllByRole("link", { name: "Timeline" })[0]);
    expect(await screen.findByRole("heading", { level: 1, name: "Timeline" })).toBeTruthy();
    expect(refreshes()).toHaveLength(1);
    expect(refreshes()[0].body).toMatchObject({ account: "patient" });
    expect(screen.queryByText(ENDED.en)).toBeNull();
  });

  for (const lang of ["bn", "en"] as const) {
    it(`after a reload the patient stays signed in through the refresh cookie (${lang})`, async () => {
      const { seen, transport } = cookieFor("patient", PATIENT_TOKEN);
      const { container } = renderApp("/patient", { lang, transport });
      expect(await screen.findByText("SID-4827190356")).toBeTruthy();
      const refresh = seen.find((r) => r.path === "/auth/refresh")!;
      expect(refresh.body).toMatchObject({ account: "patient" });
      expect((refresh.body as { device_id: string }).device_id).toBe(localStorage.getItem("swasthyoid.device"));
      expect(await axeViolations(container)).toEqual([]);
    });
  }

  it("a doctor's page is restored from the staff cookie, never the patient's", async () => {
    renderApp("/doctor", { lang: "en", transport: cookieFor("staff", DOCTOR_TOKEN).transport });
    expect(await screen.findByRole("button", { name: "Sign out" })).toBeTruthy(); // the doctor's shell, signed in
    cleanup();
    renderApp("/doctor", { lang: "en", transport: cookieFor("patient", PATIENT_TOKEN).transport });
    expect((await screen.findByRole("heading", { level: 1 })).textContent).toBe("Sign in");
  });

  it("several refused requests at once share one renewal, held under a cross-tab lock", async () => {
    const names: string[] = [];
    vi.stubGlobal("navigator", { ...navigator, locks: { request: (name: string, run: () => Promise<boolean>) => (names.push(name), run()) } });
    let old: string | undefined; // every request still carrying the token from before the renewal is refused
    const { seen, transport, refreshes } = spy((r) => old !== undefined && r.headers.Authorization === old);
    renderApp("/patient/login", { lang: "en", transport });
    await signInAsPatient();
    old = [...seen].reverse().find((r) => r.headers.Authorization)!.headers.Authorization;
    fireEvent.click(screen.getAllByRole("link", { name: "Timeline" })[0]);
    await screen.findByRole("heading", { level: 1, name: "Timeline" });
    expect(seen.filter((r) => r.headers.Authorization === old).length).toBeGreaterThan(1); // several were refused...
    expect(refreshes()).toHaveLength(1); // ...and renewed once
    expect(names).toEqual(["swasthyoid-refresh-patient"]);
    expect(screen.queryByText(ENDED.en)).toBeNull();
  });

  it("after sign-out a reload does not bring the session back, even if the server could not clear the cookie", async () => {
    const { seen, transport } = cookieFor("patient", PATIENT_TOKEN);
    renderApp("/patient/more", { lang: "en", transport });
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    fireEvent.click(await screen.findByRole("button", { name: "Yes, sign out" }));
    await screen.findByRole("button", { name: /Send code/ });
    cleanup();
    seen.length = 0;
    renderApp("/patient", { lang: "en", transport });
    await screen.findByRole("button", { name: /Send code/ });
    expect(seen.some((r) => r.path === "/auth/refresh")).toBe(false);
  });
});

describe("W2 idle timeout on screen", () => {
  for (const [lang, token, ms] of [["bn", PATIENT_TOKEN, IDLE_MS.patient], ["en", DOCTOR_TOKEN, IDLE_MS.staff]] as const) {
    it(`${token === PATIENT_TOKEN ? "a patient" : "a doctor"} is signed out after ${ms / 60_000} idle minutes, not before (${lang})`,
      async () => {
        vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
        renderApp(token === PATIENT_TOKEN ? "/patient" : "/doctor", { lang, token, transport: cookieFor("none" as "patient", "").transport });
        await act(() => vi.advanceTimersByTimeAsync(ms - 60_000));
        fireEvent.keyDown(window, { key: "Tab" }); // input restarts the clock
        await act(() => vi.advanceTimersByTimeAsync(ms - 60_000));
        expect(screen.queryByText(ENDED[lang])).toBeNull();
        await act(() => vi.advanceTimersByTimeAsync(60_000));
        vi.useRealTimers();
        expect(await screen.findByText(ENDED[lang])).toBeTruthy();
      });
  }
});

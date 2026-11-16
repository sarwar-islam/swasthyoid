import { render } from "@testing-library/react";
import axe from "axe-core";
import { MemoryRouter } from "react-router";
import { AppRoutes } from "./App";
import type { Transport } from "./api/client";
import { MOCK_CAREGIVER_ID, MOCK_DOCTOR_ID, MOCK_PATIENT_ID, MOCK_VERIFIER_ID, mockTransport } from "./api/mock";
import { I18nProvider, type Lang } from "./i18n/i18n";
import { SessionProvider } from "./session";
import { ThemeProvider } from "./theme";

const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/=+$/, "");
export const PATIENT_TOKEN = `${b64({ alg: "none" })}.${b64({ sub: MOCK_PATIENT_ID, role: "patient" })}.test`;
export const DOCTOR_TOKEN = `${b64({ alg: "none" })}.${b64({ sub: MOCK_DOCTOR_ID, role: "doctor" })}.test`;
export const PENDING_DOCTOR_TOKEN = `${b64({ alg: "none" })}.${b64({ sub: "55555555-5555-4555-8555-555555555555", role: "doctor" })}.test`;
export const VERIFIER_TOKEN = `${b64({ alg: "none" })}.${b64({ sub: MOCK_VERIFIER_ID, role: "verifier" })}.test`;
// another person account (role patient) that has asked to care for the mock patient
export const CAREGIVER_TOKEN = `${b64({ alg: "none" })}.${b64({ sub: MOCK_CAREGIVER_ID, role: "patient" })}.test`;

/** The whole app at `path`, on a fresh synthetic mock (or the transport given), optionally signed in as the mock patient. */
export function renderApp(path: string, { lang = "bn", signedIn = false, token, transport }:
  { lang?: Lang; signedIn?: boolean; token?: string; transport?: Transport } = {}) {
  return render(
    <ThemeProvider>
      <I18nProvider initial={lang}>
        <SessionProvider transport={transport ?? mockTransport()} initialToken={token ?? (signedIn ? PATIENT_TOKEN : null)}>
          <MemoryRouter initialEntries={[path]}><AppRoutes /></MemoryRouter>
        </SessionProvider>
      </I18nProvider>
    </ThemeProvider>,
  );
}

/** axe violations, minus colour contrast (jsdom cannot compute colour; the palette was checked by calculation). */
export async function axeViolations(container: Element) {
  const result = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  return result.violations.map((v) => `${v.id}: ${v.nodes[0]?.target}`);
}

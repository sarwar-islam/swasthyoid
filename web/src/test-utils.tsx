import { render } from "@testing-library/react";
import axe from "axe-core";
import { MemoryRouter } from "react-router";
import { AppRoutes } from "./App";
import type { Transport } from "./api/client";
import { MOCK_PATIENT_ID, mockTransport } from "./api/mock";
import { I18nProvider, type Lang } from "./i18n/i18n";
import { SessionProvider } from "./session";
import { ThemeProvider } from "./theme";

const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/=+$/, "");
export const PATIENT_TOKEN = `${b64({ alg: "none" })}.${b64({ sub: MOCK_PATIENT_ID, role: "patient" })}.test`;

/** The whole app at `path`, on a fresh synthetic mock (or the transport given), optionally signed in as the mock patient. */
export function renderApp(path: string, { lang = "bn", signedIn = false, transport }:
  { lang?: Lang; signedIn?: boolean; transport?: Transport } = {}) {
  return render(
    <ThemeProvider>
      <I18nProvider initial={lang}>
        <SessionProvider transport={transport ?? mockTransport()} initialToken={signedIn ? PATIENT_TOKEN : null}>
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

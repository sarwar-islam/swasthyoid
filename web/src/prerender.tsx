// UX-3b: the build renders the landing page to HTML (Bangla, light theme) so `/` paints before the JS arrives. The client
// still renders from scratch with createRoot; this is only the first paint. No session, no patient data, only `/`.
import { renderToString } from "react-dom/server";
import { MemoryRouter } from "react-router";
import type { Transport } from "./api/client";
import { I18nProvider } from "./i18n/i18n";
import { Landing } from "./pages/Landing";
import { SessionProvider } from "./session";
import { ThemeProvider } from "./theme";

const offline: Transport = () => Promise.reject(new Error("no network while pre-rendering"));

export function render(): string {
  return renderToString(
    <ThemeProvider><I18nProvider initial="bn"><SessionProvider transport={offline}>
      <MemoryRouter initialEntries={["/"]}><Landing /></MemoryRouter>
    </SessionProvider></I18nProvider></ThemeProvider>);
}

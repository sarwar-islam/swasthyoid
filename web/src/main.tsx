// Bangla: Hind Siliguri, Bengali subset only (Latin comes from Atkinson Hyperlegible); all self-hosted from node_modules
import "@fontsource/hind-siliguri/bengali-400.css";
import "@fontsource/hind-siliguri/bengali-500.css";
import "@fontsource/hind-siliguri/bengali-600.css";
import "@fontsource/hind-siliguri/bengali-700.css";
import "@fontsource/atkinson-hyperlegible/400.css";
import "@fontsource/atkinson-hyperlegible/700.css";
import "@fontsource/jetbrains-mono/400.css";
import "./styles/tokens.css";
import "./styles/base.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { AppRoutes } from "./App";
import { defaultTransport } from "./api";
import { SessionProvider } from "./session";
import { I18nProvider } from "./i18n/i18n";
import { ThemeProvider } from "./theme";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <I18nProvider>
        <SessionProvider transport={defaultTransport()}>
          <BrowserRouter><AppRoutes /></BrowserRouter>
        </SessionProvider>
      </I18nProvider>
    </ThemeProvider>
  </StrictMode>,
);

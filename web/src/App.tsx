import { HeartPulse } from "lucide-react";
import type React from "react";
import { Link, Route, Routes } from "react-router";
import { LanguageToggle, ThemeSelect } from "./components/Controls";
import { localDigits, useI18n } from "./i18n/i18n";
import type { Key } from "./i18n/strings";
import { ConsentCenter } from "./pages/patient/Consent";
import { Capture } from "./pages/patient/Capture";
import { DocumentPage } from "./pages/patient/Document";
import { Home } from "./pages/patient/Home";
import { Login } from "./pages/patient/Login";
import { Timeline } from "./pages/patient/Timeline";
import { RequireRole } from "./session";
import { PATIENT_NAV, PatientShell, STAFF_NAV, StaffShell, type NavItem } from "./shells/Shells";

function Placeholder({ item }: { item: NavItem }) {
  const { t, lang } = useI18n();
  return (
    <section aria-labelledby="page-title">
      <h1 id="page-title">{t(item.label)}</h1>
      <p className="notice">{t("page.comingIn", { phase: localDigits(item.phase, lang) })}</p>
    </section>
  );
}

const PORTALS: Array<{ to: string; title: Key; desc: Key }> = [
  { to: "/patient", title: "portal.patient", desc: "portal.patient.desc" },
  { to: "/doctor", title: "portal.doctor", desc: "portal.doctor.desc" },
  { to: "/verifier", title: "portal.verifier", desc: "portal.verifier.desc" },
  { to: "/console", title: "portal.console", desc: "portal.console.desc" },
];

/** Development landing page until sign-in exists (F1): one card per portal. */
function PortalChooser() {
  const { t } = useI18n();
  return (
    <div className="shell" data-portal="patient">
      <header className="topbar">
        <span className="brand"><HeartPulse size={22} aria-hidden="true" />{t("app.name")}</span>
        <div className="controls"><LanguageToggle /><ThemeSelect /></div>
      </header>
      <main id="main" className="content">
        <h1>{t("portal.choose")}</h1>
        <p>{t("portal.devNote")} {t("app.synthetic")}</p>
        <ul className="portal-grid" style={{ listStyle: "none", padding: 0 }}>
          {PORTALS.map((p) => (
            <li key={p.to}><Link to={p.to} className="card"><strong>{t(p.title)}</strong><span>{t(p.desc)}</span></Link></li>
          ))}
        </ul>
      </main>
    </div>
  );
}

// built pages by route; any other menu item shows which phase builds it
const BUILT: Record<string, React.ReactNode> = {
  "/patient": <Home />, "/patient/timeline": <Timeline />, "/patient/capture": <Capture />, "/patient/consent": <ConsentCenter />,
};

const pages = (items: NavItem[], base: string) =>
  items.map((item) => item.to === base
    ? <Route key={item.to} index element={BUILT[item.to] ?? <Placeholder item={item} />} />
    : <Route key={item.to} path={item.to.slice(base.length + 1)} element={BUILT[item.to] ?? <Placeholder item={item} />} />);

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<PortalChooser />} />
      <Route path="/patient/login" element={<Login />} />
      <Route element={<RequireRole role="patient" login="/patient/login" />}>
        <Route path="/patient" element={<PatientShell />}>
          {pages(PATIENT_NAV, "/patient")}
          <Route path="documents/:id" element={<DocumentPage />} />
        </Route>
      </Route>
      {(["doctor", "verifier", "console"] as const).map((portal) => (
        <Route key={portal} path={`/${portal}`} element={<StaffShell portal={portal} />}>
          {pages(STAFF_NAV[portal].items, `/${portal}`)}
        </Route>
      ))}
    </Routes>
  );
}

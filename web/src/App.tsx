import { HeartPulse } from "lucide-react";
import type React from "react";
import { Link, Navigate, Route, Routes } from "react-router";
import { LanguageToggle, ThemeSelect } from "./components/Controls";
import { flags } from "./flags";
import { localDigits, useI18n } from "./i18n/i18n";
import type { Key } from "./i18n/strings";
import { DoctorFrame } from "./pages/doctor/doctor";
import { AllAlerts, BreakGlass, Credentials } from "./pages/doctor/Other";
import { Patients } from "./pages/doctor/Patients";
import { AlertsPage, DoctorDocument, DoctorTimeline, SearchPage, SummaryPage, Workspace } from "./pages/doctor/Workspace";
import { CareDocument, CaregiverFrame, CareIndex, CareRoute, CARE_TABS, Caregiving } from "./pages/patient/Caregiver";
import { ConsentCenter } from "./pages/patient/Consent";
import { Capture } from "./pages/patient/Capture";
import { DocumentPage } from "./pages/patient/Document";
import { Home } from "./pages/patient/Home";
import { EmergencyProfile } from "./pages/patient/EmergencyProfile";
import { Login } from "./pages/patient/Login";
import { More } from "./pages/patient/More";
import { Reminders } from "./pages/patient/Reminders";
import { Timeline } from "./pages/patient/Timeline";
import { EmergencyPage, FirstAid, Triage } from "./pages/patient/Triage";
import { Vitals } from "./pages/patient/Vitals";
import { AssistDocument, AssistQueue, AssistStart, VerifierFrame } from "./pages/verifier/Verifier";
import { RequireRole } from "./session";
import { PATIENT_NAV, PatientShell, STAFF_NAV, StaffShell, visible, type NavItem } from "./shells/Shells";

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
  "/patient/more": <More />,
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
          <Route path="vitals" element={<Vitals />} />
          <Route path="reminders" element={<Reminders />} />
          <Route path="help" element={<Triage />} />
          <Route path="first-aid" element={<FirstAid />} />
          <Route path="emergency" element={<EmergencyPage />} />
          {flags.emergencyAccess && <Route path="emergency-profile" element={<EmergencyProfile />} />}
          <Route path="caregiving" element={<Caregiving />} />
          <Route path="for/:pid" element={<CaregiverFrame />}>
            <Route index element={<CareIndex />} />
            {CARE_TABS.map((tab) => <Route key={tab.path} path={tab.path} element={<CareRoute scope={tab.scope} />} />)}
            <Route path="documents/:docId" element={<CareDocument />} />
          </Route>
          <Route path="*" element={<Navigate to="/patient" replace />} />
        </Route>
      </Route>
      <Route path="/doctor/login" element={<Login portal="doctor" />} />
      <Route element={<RequireRole role="doctor" login="/doctor/login" />}>
        <Route path="/doctor" element={<StaffShell portal="doctor" />}>
          <Route element={<DoctorFrame />}>
            <Route index element={<Patients />} />
            <Route path="alerts" element={<AllAlerts />} />
            <Route path="credentials" element={<Credentials />} />
            {flags.emergencyAccess && <Route path="emergency" element={<BreakGlass />} />}
            <Route path="patients/:pid" element={<Workspace />}>
              <Route index element={<SummaryPage />} />
              <Route path="timeline" element={<DoctorTimeline />} />
              <Route path="search" element={<SearchPage />} />
              <Route path="alerts" element={<AlertsPage />} />
              <Route path="documents/:docId" element={<DoctorDocument />} />
            </Route>
            <Route path="*" element={<Navigate to="/doctor" replace />} />
          </Route>
        </Route>
      </Route>
      <Route path="/verifier/login" element={<Login portal="verifier" />} />
      <Route element={<RequireRole role="verifier" login="/verifier/login" />}>
        <Route path="/verifier" element={<StaffShell portal="verifier" />}>
          <Route element={<VerifierFrame />}>
            <Route index element={<AssistStart />} />
            <Route path="queue" element={<AssistQueue />} />
            <Route path="documents/:id" element={<AssistDocument />} />
            <Route path="*" element={<Navigate to="/verifier" replace />} />
          </Route>
        </Route>
      </Route>
      <Route path="/console" element={<StaffShell portal="console" />}>
        {pages(visible(STAFF_NAV.console.items), "/console")}
      </Route>
    </Routes>
  );
}

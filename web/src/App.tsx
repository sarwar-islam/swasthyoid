import { HeartPulse } from "lucide-react";
import { lazy, Suspense, type ComponentType } from "react";
import type React from "react";
import { Link, Navigate, Route, Routes } from "react-router";
import { LanguageToggle, ThemeSelect } from "./components/Controls";
import { flags } from "./flags";
import { useI18n } from "./i18n/i18n";
import type { Key } from "./i18n/strings";
import { Loading } from "./components/ui";
import { Landing } from "./pages/Landing";
import { CareDocument, CaregiverFrame, CareIndex, CareRoute, CARE_TABS, Caregiving } from "./pages/patient/Caregiver";
import { ConsentCenter, QrConsentPage } from "./pages/patient/Consent";
import { Inbox } from "./pages/patient/Inbox";
import { Capture } from "./pages/patient/Capture";
import { DocumentPage } from "./pages/patient/Document";
import { Home } from "./pages/patient/Home";
import { EmergencyProfile } from "./pages/patient/EmergencyProfile";
import { Login } from "./pages/patient/Login";
import { More } from "./pages/patient/More";
import { Profile, Records } from "./pages/patient/Profile";
import { HealthSummary } from "./pages/patient/HealthSummary";
import { Reminders } from "./pages/patient/Reminders";
import { Timeline } from "./pages/patient/Timeline";
import { EmergencyPage, FirstAid, Triage } from "./pages/patient/Triage";
import { Vitals } from "./pages/patient/Vitals";
import { RequireRole } from "./session";
import { PATIENT_NAV, PatientShell, StaffShell, type NavItem } from "./shells/Shells";

// UX-3a: the doctor, verifier and console pages load only when someone opens that portal; the landing page, sign-in and the
// patient app stay in the first file (most visitors are patients). `part(load, "Name")` is one named export of a module.
function part<M extends Record<string, unknown>>(load: () => Promise<M>, name: keyof M & string) {
  return lazy(() => load().then((m) => ({ default: m[name] as ComponentType<Record<string, unknown>> })));
}
const doctorMod = () => import("./pages/doctor/doctor");
const doctorOther = () => import("./pages/doctor/Other");
const doctorPatients = () => import("./pages/doctor/Patients");
const doctorWs = () => import("./pages/doctor/Workspace");
const verifierMod = () => import("./pages/verifier/Verifier");
const consoleMod = () => import("./pages/console/console");
const consoleAdmin = () => import("./pages/console/Admin");
const consoleReviewer = () => import("./pages/console/Reviewer");
const DoctorFrame = part(doctorMod, "DoctorFrame");
const AllAlerts = part(doctorOther, "AllAlerts");
const BreakGlass = part(doctorOther, "BreakGlass");
const Credentials = part(doctorOther, "Credentials");
const Patients = part(doctorPatients, "Patients");
const Workspace = part(doctorWs, "Workspace");
const SummaryPage = part(doctorWs, "SummaryPage");
const DoctorTimeline = part(doctorWs, "DoctorTimeline");
const SearchPage = part(doctorWs, "SearchPage");
const AlertsPage = part(doctorWs, "AlertsPage");
const ThresholdsPage = part(doctorWs, "ThresholdsPage");
const DoctorDocument = part(doctorWs, "DoctorDocument");
const VerifierFrame = part(verifierMod, "VerifierFrame");
const AssistStart = part(verifierMod, "AssistStart");
const AssistQueue = part(verifierMod, "AssistQueue");
const AssistDocument = part(verifierMod, "AssistDocument");
const ConsoleIndex = part(consoleMod, "ConsoleIndex");
const OnlyRole = lazy(() => consoleMod().then((m) => ({ default: m.OnlyRole })));
const RulesPage = part(consoleReviewer, "RulesPage");
const ReviewsPage = part(consoleReviewer, "ReviewsPage");
const CredentialsPage = part(consoleAdmin, "CredentialsPage");
const StaffPage = part(consoleAdmin, "StaffPage");
const CatalogPage = part(consoleAdmin, "CatalogPage");
const AuditPage = part(consoleAdmin, "AuditPage");
const MetricsPage = part(consoleAdmin, "MetricsPage");

const PORTALS: Array<{ to: string; title: Key; desc: Key }> = [
  { to: "/patient", title: "portal.patient", desc: "portal.patient.desc" },
  { to: "/doctor", title: "portal.doctor", desc: "portal.doctor.desc" },
  { to: "/verifier", title: "portal.verifier", desc: "portal.verifier.desc" },
  { to: "/console", title: "portal.console", desc: "portal.console.desc" },
];

/** Development page at /portals: one card per portal (the landing page at / is for visitors, W1). */
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

// the patient app's bottom-bar pages by route
const BUILT: Record<string, React.ReactNode> = {
  "/patient": <Home />, "/patient/timeline": <Timeline />, "/patient/capture": <Capture />, "/patient/consent": <ConsentCenter />,
  "/patient/more": <More />,
};

const pages = (items: NavItem[], base: string) =>
  items.map((item) => item.to === base
    ? <Route key={item.to} index element={BUILT[item.to]} />
    : <Route key={item.to} path={item.to.slice(base.length + 1)} element={BUILT[item.to]} />);
const reviewer = (page: React.ReactNode) => <OnlyRole role="clinical_reviewer">{page}</OnlyRole>;
const admin = (page: React.ReactNode) => <OnlyRole role="admin">{page}</OnlyRole>;

export function AppRoutes() {
  return (
    <Suspense fallback={<Loading lines={3} />}>
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/portals" element={<PortalChooser />} />
      <Route path="/patient/login" element={<Login />} />
      <Route element={<RequireRole role="patient" login="/patient/login" />}>
        <Route path="/patient" element={<PatientShell />}>
          {pages(PATIENT_NAV, "/patient")}
          <Route path="documents/:id" element={<DocumentPage />} />
          <Route path="inbox" element={<Inbox />} />
          <Route path="profile" element={<Profile />} />
          <Route path="records" element={<Records />} />
          <Route path="summary" element={<HealthSummary />} />
          <Route path="consent/qr/:ref" element={<QrConsentPage />} />
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
              <Route path="thresholds" element={<ThresholdsPage />} />
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
      <Route path="/console/login" element={<Login portal="console" />} />
      <Route element={<RequireRole role={["clinical_reviewer", "admin"]} login="/console/login" />}>
        <Route path="/console" element={<StaffShell portal="console" />}>
          <Route index element={<ConsoleIndex />} />
          <Route path="rules" element={reviewer(<RulesPage />)} />
          {flags.emergencyAccess && <Route path="reviews" element={reviewer(<ReviewsPage />)} />}
          <Route path="credentials" element={admin(<CredentialsPage />)} />
          <Route path="staff" element={admin(<StaffPage />)} />
          <Route path="catalog" element={admin(<CatalogPage />)} />
          <Route path="audit" element={admin(<AuditPage />)} />
          <Route path="metrics" element={admin(<MetricsPage />)} />
          <Route path="*" element={<Navigate to="/console" replace />} />
        </Route>
      </Route>
    </Routes>
    </Suspense>
  );
}

import type { LucideIcon } from "lucide-react";
import { Activity, BadgeCheck, Camera, Database, FileSearch, Gavel, HeartPulse, Home, Inbox, KeyRound, LayoutGrid,
  ListChecks, ScrollText, ShieldAlert, ShieldCheck, Siren, UserPlus, Users } from "lucide-react";
import { Link, NavLink, Outlet } from "react-router";
import { LanguageToggle, ThemeSelect } from "../components/Controls";
import { flags } from "../flags";
import { useI18n } from "../i18n/i18n";
import { useSession } from "../session";
import type { Key } from "../i18n/strings";

export interface NavItem {
  to: string;
  label: Key;
  icon: LucideIcon;
  phase: string; // the build phase that fills the page
  flag?: keyof typeof flags;
  roles?: string[]; // only these staff roles (the console holds two)
}

/** The items whose feature flag is on (checked at render time) and, when `role` is given, that this role may use. */
export const visible = (items: NavItem[], role?: string) =>
  items.filter((item) => (!item.flag || flags[item.flag]) && (!item.roles || (role !== undefined && item.roles.includes(role))));

const REVIEWER = ["clinical_reviewer"];
const ADMIN = ["admin"];

export const PATIENT_NAV: NavItem[] = [
  { to: "/patient", label: "nav.home", icon: Home, phase: "F1" },
  { to: "/patient/timeline", label: "nav.timeline", icon: Activity, phase: "F1" },
  { to: "/patient/capture", label: "nav.capture", icon: Camera, phase: "F1" },
  { to: "/patient/consent", label: "nav.consent", icon: ShieldCheck, phase: "F1" },
  { to: "/patient/more", label: "nav.more", icon: LayoutGrid, phase: "F2" },
];

export const STAFF_NAV: Record<"doctor" | "verifier" | "console", { title: Key; items: NavItem[] }> = {
  doctor: { title: "portal.doctor", items: [
    { to: "/doctor", label: "nav.patients", icon: Users, phase: "F3" },
    { to: "/doctor/alerts", label: "nav.alerts", icon: ShieldAlert, phase: "F3" },
    { to: "/doctor/emergency", label: "nav.breakglass", icon: Siren, phase: "F3", flag: "emergencyAccess" },
    { to: "/doctor/credentials", label: "nav.credentials", icon: BadgeCheck, phase: "F3" },
  ] },
  verifier: { title: "portal.verifier", items: [
    { to: "/verifier", label: "nav.capture", icon: Camera, phase: "F4" },
    { to: "/verifier/queue", label: "nav.queue", icon: ListChecks, phase: "F4" },
  ] },
  console: { title: "portal.console", items: [
    { to: "/console/rules", label: "nav.rules", icon: Gavel, phase: "F5", roles: REVIEWER },
    { to: "/console/reviews", label: "nav.reviews", icon: FileSearch, phase: "F5", flag: "emergencyAccess", roles: REVIEWER },
    { to: "/console/credentials", label: "nav.approvals", icon: KeyRound, phase: "F5", roles: ADMIN },
    { to: "/console/staff", label: "nav.staff", icon: UserPlus, phase: "F5", roles: ADMIN },
    { to: "/console/catalog", label: "nav.catalog", icon: Database, phase: "F5", roles: ADMIN },
    { to: "/console/audit", label: "nav.audit", icon: ScrollText, phase: "F5", roles: ADMIN },
    { to: "/console/metrics", label: "nav.metrics", icon: Inbox, phase: "F5", roles: ADMIN },
  ] },
};

function TopBar({ subtitle }: { subtitle: Key }) {
  const { t } = useI18n();
  const { claims, signOut } = useSession();
  return (
    <header className="topbar">
      <Link to="/" className="brand"><HeartPulse size={22} aria-hidden="true" />{t("app.name")} <small>{t(subtitle)}</small></Link>
      <div className="controls"><LanguageToggle /><ThemeSelect />{claims && <button type="button" onClick={signOut}>{t("common.signOut")}</button>}</div>
    </header>
  );
}

function SkipLink() {
  const { t } = useI18n();
  return <a className="skip-link" href="#main">{t("a11y.skip")}</a>;
}

/** Patient app: mobile-first, the emergency bar on every screen, a bottom bar of five. */
export function PatientShell() {
  const { t } = useI18n();
  return (
    <div className="shell" data-portal="patient">
      <SkipLink />
      <TopBar subtitle="portal.patient" />
      {/* tel: works with no server at all: the emergency route never depends on the backend */}
      <a className="emergency-bar" href="tel:999"><Siren size={20} aria-hidden="true" />{t("emergency.bar")}</a>
      <main id="main" className="content" tabIndex={-1}><Outlet /></main>
      <nav className="bottom-nav" aria-label={t("a11y.mainNav")}>
        <ul>
          {PATIENT_NAV.map(({ to, label, icon: Icon }) => (
            <li key={to}><NavLink to={to} end><Icon size={22} aria-hidden="true" />{t(label)}</NavLink></li>
          ))}
        </ul>
      </nav>
    </div>
  );
}

/** Doctor, verifier and console: a side menu on wide screens, a scrolling row on narrow ones. */
export function StaffShell({ portal }: { portal: keyof typeof STAFF_NAV }) {
  const { t } = useI18n();
  const { claims } = useSession();
  const { title } = STAFF_NAV[portal];
  const items = visible(STAFF_NAV[portal].items, claims?.role);
  return (
    <div className="shell" data-portal="staff">
      <SkipLink />
      <TopBar subtitle={title} />
      <div className="staff-body">
        <nav className="side-nav" aria-label={t("a11y.mainNav")}>
          <ul>
            {items.map(({ to, label, icon: Icon }) => (
              <li key={to}><NavLink to={to} end><Icon size={20} aria-hidden="true" />{t(label)}</NavLink></li>
            ))}
          </ul>
        </nav>
        <main id="main" className="content" tabIndex={-1}><Outlet /></main>
      </div>
    </div>
  );
}

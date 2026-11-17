import { Camera, FileCheck2, HeartHandshake, HeartPulse, History, ShieldCheck, Siren, Stethoscope, UserCheck } from "lucide-react";
import { Link } from "react-router";
import { LanguageToggle, ThemeSelect } from "../components/Controls";
import { flags } from "../flags";
import { useI18n } from "../i18n/i18n";
import type { Key } from "../i18n/strings";

const STEPS: Array<{ text: Key; icon: typeof Camera }> = [
  { text: "land.step1", icon: Camera }, { text: "land.step2", icon: UserCheck }, { text: "land.step3", icon: ShieldCheck },
];
// only what the server serves today (no reminders or triage until P8)
const CAN: Array<{ text: Key; icon: typeof Camera }> = [
  { text: "land.can.timeline", icon: History }, { text: "land.can.consent", icon: ShieldCheck },
  { text: "land.can.vitals", icon: HeartPulse }, { text: "land.can.care", icon: HeartHandshake },
];

/** W1: what a first-time visitor sees at `/`. Patients first; doctors get a short section; staff sign-in is in the footer.
 * Every claim here is something the code does today; no numbers, badges or medical claims (owner plan, 2026-11-17). */
export function Landing() {
  const { t } = useI18n();
  return (
    <div className="shell landing" data-portal="patient">
      <header className="topbar">
        <span className="brand"><HeartPulse size={22} aria-hidden="true" />{t("app.name")}</span>
        <nav aria-label={t("land.nav")} className="land-nav">
          <a href="#how">{t("land.how")}</a> <a href="#can">{t("land.forPatients")}</a>{" "}
          <a href="#doctors">{t("land.doctors")}</a> <a href="#yours">{t("land.privacy")}</a>
        </nav>
        <div className="controls">
          <LanguageToggle /><ThemeSelect />
          <Link className="btn" to="/patient/login">{t("land.login")}</Link>
        </div>
      </header>
      <div role="region" aria-label={t("emergency.title")}>
        <a className="emergency-bar" href="tel:999"><Siren size={20} aria-hidden="true" />{t("emergency.bar")}</a>
      </div>
      <main id="main" className="content">
        <section className="stack" aria-labelledby="hero">
          <h1 id="hero">{t("land.hero")}</h1>
          <p>{t("land.lead")}</p>
          <div className="actions">
            <Link className="btn btn-primary" to="/patient/login">{t("land.create")}</Link>
            <a href="#doctors">{t("land.areDoctor")}</a>
          </div>
          <p className="notice">{t("land.prototype")}</p>
        </section>

        <section className="section" aria-labelledby="how">
          <h2 id="how">{t("land.how")}</h2>
          <ol className="list">
            {STEPS.map(({ text, icon: Icon }) => <li key={text} className="card icon-line"><Icon size={24} aria-hidden="true" /><span>{t(text)}</span></li>)}
          </ol>
        </section>

        <section id="can" className="section" aria-labelledby="can-title">
          <h2 id="can-title">{t("land.can")}</h2>
          <ul className="list">
            {CAN.map(({ text, icon: Icon }) => <li key={text} className="card icon-line"><Icon size={24} aria-hidden="true" /><span>{t(text)}</span></li>)}
          </ul>
        </section>

        <section id="yours" className="section card" aria-labelledby="yours-title">
          <h2 id="yours-title"><FileCheck2 size={22} aria-hidden="true" /> {t("land.yours")}</h2>
          <ul>
            {/* M10 shares the minimal card without a code, so the promise changes when its flag is on */}
            <li>{t(flags.emergencyAccess ? "land.yours.consentEmergency" : "land.yours.consent")}</li>
            <li>{t("land.yours.revoke")}</li>
            <li>{t("land.yours.history")}</li>
            <li>{t("land.yours.reported")}</li>
          </ul>
        </section>

        <section id="doctors" className="section card" aria-labelledby="doctors-title">
          <h2 id="doctors-title"><Stethoscope size={22} aria-hidden="true" /> {t("land.doctors")}</h2>
          <p>{t("land.doctors.text")}</p>
          <div className="actions">
            {/* a new doctor signs in with the phone, then submits the BMDC number for an admin to approve */}
            <Link className="btn btn-primary" to="/doctor/login">{t("land.doctors.apply")}</Link>
            <Link to="/doctor/login">{t("land.doctors.go")}</Link>
          </div>
        </section>
      </main>
      <footer className="content muted">
        <nav aria-label={t("land.staff")}>
          <strong>{t("land.staff")}:</strong>{" "}
          <Link to="/verifier/login">{t("land.staff.verifier")}</Link> · <Link to="/console/login">{t("land.staff.console")}</Link>
          {" · "}<Link to="/portals">{t("land.dev")}</Link>
        </nav>
        <p>{t("land.policy")}</p>
        <p>{t("app.synthetic")}</p>
      </footer>
    </div>
  );
}

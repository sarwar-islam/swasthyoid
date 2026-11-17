import { Activity, ArrowRight, ArrowUp, Camera, Check, ClipboardList, Eye, FileCheck2, FileText, HeartPulse, History, Info, Menu,
  ScrollText, ShieldCheck, Siren, Stethoscope, UserCheck, UserRound } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { LanguageToggle, ThemeSelect } from "../components/Controls";
import { ProvenanceBadge, StatusChip } from "../components/ui";
import { flags } from "../flags";
import { SkipLink } from "../shells/Shells";
import { useI18n } from "../i18n/i18n";
import type { Key } from "../i18n/strings";

type Icon = typeof Camera;
const STEPS: Array<{ title: Key; text: Key; icon: Icon }> = [
  { title: "land.step1.t", text: "land.step1", icon: Camera },
  { title: "land.step2.t", text: "land.step2", icon: UserCheck },
  { title: "land.step3.t", text: "land.step3", icon: ShieldCheck },
];
// only what the server serves today (no reminders or triage until P8)
const FEATURES: Array<{ title: Key; text: Key; icon: Icon }> = [
  { title: "cap.timeline.t", text: "land.can.timeline", icon: Activity },
  { title: "cap.records.t", text: "cap.records", icon: FileText },
  { title: "cap.summary.t", text: "cap.summary", icon: ClipboardList },
  { title: "cap.consent.t", text: "land.can.consent", icon: ShieldCheck },
  { title: "cap.vitals.t", text: "land.can.vitals", icon: HeartPulse },
  { title: "cap.history.t", text: "land.yours.history", icon: History },
];
const SECTIONS: Array<{ href: string; label: Key }> = [
  { href: "#how", label: "land.how" }, { href: "#patients", label: "land.forPatients" },
  { href: "#doctors", label: "land.doctors" }, { href: "#yours", label: "land.privacy" },
];

/** A picture of the app made from the app's own badges, with made-up content, labelled as a demo. Not a live record. */
function Preview() {
  const { t } = useI18n();
  return (
    <figure className="preview card" aria-labelledby="preview-cap">
      <figcaption id="preview-cap" className="preview-cap"><Info size={16} aria-hidden="true" />{t("land.preview")}</figcaption>
      <p className="preview-title">{t("tl.title")}</p>
      <ol className="preview-rail">
        <li>
          <span className="tl-category">{t("tl.medication")}</span>
          <strong lang="en">SYNTH-DRUG-003</strong>
          <ProvenanceBadge value="document_verified" />
        </li>
        <li>
          <span className="tl-category">{t("tl.lab_result")}</span>
          <strong lang="en">SYNTH-TEST-A</strong>
          <ProvenanceBadge value="document_verified" />
        </li>
        <li className="reported">
          <span className="tl-category">{t("tl.vital_reading")}</span>
          <strong lang="en">SYNTH-READING-1</strong>
          <ProvenanceBadge value="patient_reported" />
        </li>
      </ol>
      <div className="preview-row">
        <span><FileText size={18} aria-hidden="true" /> {t("doc.prescription")}</span>
        <StatusChip status="needs_review" />
      </div>
      <div className="preview-row">
        <span><Stethoscope size={18} aria-hidden="true" /> {t("land.preview.doctor")}</span>
        <span className="chip chip-verified"><Eye size={14} aria-hidden="true" />{t("land.preview.allowed")}</span>
      </div>
    </figure>
  );
}

/** W1, refined: what a first-time visitor sees at `/`. One page in the app's own design system: header, a calm emergency
 * strip, the hero with a demo preview, how it works, what it does, privacy, the two audiences, footer. Every claim is
 * something the code does today; no numbers, badges, certifications or medical claims (owner plan, 2026-11-17). */
export function Landing() {
  const { t } = useI18n();
  const [menu, setMenu] = useState(false);
  const [scrolled, setScrolled] = useState(0);
  // reading progress and the back-to-top button; one passive listener, no layout reads beyond the scroll position
  useEffect(() => {
    const onScroll = () => {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      setScrolled(max > 0 ? Math.min(1, window.scrollY / max) : 0);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return (
    <div className="shell landing" data-portal="patient">
      <SkipLink />
      <div className="scroll-progress" aria-hidden="true" style={{ "--progress": scrolled } as React.CSSProperties} />
      <header className="topbar land-top">
        <Link to="/" className="brand"><HeartPulse size={22} aria-hidden="true" />{t("app.name")}</Link>
        <nav id="land-nav" aria-label={t("land.nav")} className={`land-nav${menu ? " open" : ""}`} onClick={() => setMenu(false)}>
          {SECTIONS.map(({ href, label }) => <a key={href} href={href}>{t(label)}</a>)}
        </nav>
        <div className="controls">
          <LanguageToggle /><ThemeSelect />
          <Link className="btn" to="/patient/login">{t("land.login")}</Link>
          <button type="button" className="menu-toggle icon-btn" aria-expanded={menu} aria-controls="land-nav"
                  onClick={() => setMenu((m) => !m)}><Menu size={20} aria-hidden="true" /><span className="menu-label">{t("land.menu")}</span></button>
        </div>
      </header>
      <div role="region" aria-label={t("emergency.title")} className="emergency-strip">
        <a href="tel:999"><Siren size={16} aria-hidden="true" />{t("emergency.bar")}</a>
      </div>

      <main id="main" className="land-main" tabIndex={-1}>
        <section className="hero land-wrap" aria-labelledby="hero">
          <div className="hero-copy">
            <h1 id="hero">{t("land.hero")}</h1>
            <p className="lead">{t("land.lead")}</p>
            <div className="actions">
              <Link className="btn btn-primary btn-lg" to="/patient/login">{t("land.create")}<ArrowRight size={18} aria-hidden="true" /></Link>
              <a className="btn btn-lg" href="#doctors">{t("land.areDoctor")}</a>
            </div>
            <p className="disclaimer"><Info size={16} aria-hidden="true" /><span>{t("land.prototype")}</span></p>
          </div>
          <Preview />
        </section>

        <section id="how" className="land-band" aria-labelledby="how-title">
          <div className="land-wrap">
            <h2 id="how-title" className="land-h2">{t("land.how")}</h2>
            <ol className="steps">
              {STEPS.map(({ title, text, icon: StepIcon }, i) => (
                <li key={text} className="step">
                  <span className="step-n" aria-hidden="true">{i + 1}</span>
                  <StepIcon size={24} aria-hidden="true" className="step-icon" />
                  <h3>{t(title)}</h3>
                  <p>{t(text)}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section id="features" className="land-wrap land-section" aria-labelledby="features-title">
          <h2 id="features-title" className="land-h2">{t("land.can")}</h2>
          <ul className="features">
            {FEATURES.map(({ title, text, icon: FeatureIcon }) => (
              <li key={title}>
                <span className="feature-icon"><FeatureIcon size={20} aria-hidden="true" /></span>
                <div><h3>{t(title)}</h3><p>{t(text)}</p></div>
              </li>
            ))}
          </ul>
        </section>

        <section id="yours" className="land-band" aria-labelledby="yours-title">
          <div className="land-wrap trust">
            <div>
              <h2 id="yours-title" className="land-h2"><FileCheck2 size={24} aria-hidden="true" /> {t("land.yours")}</h2>
              <p className="muted">{t("land.trust.lead")}</p>
            </div>
            <ul className="checks">
              {/* M10 shares the minimal card without a code, so the promise changes when its flag is on */}
              <li><Check size={18} aria-hidden="true" /><span>{t(flags.emergencyAccess ? "land.yours.consentEmergency" : "land.yours.consent")}</span></li>
              <li><Check size={18} aria-hidden="true" /><span>{t("land.trust.verify")}</span></li>
              <li><Check size={18} aria-hidden="true" /><span>{t("land.trust.audit")}</span></li>
              <li><Check size={18} aria-hidden="true" /><span>{t("land.yours.revoke")}</span></li>
              <li><Check size={18} aria-hidden="true" /><span>{t("land.yours.reported")}</span></li>
            </ul>
          </div>
        </section>

        <div className="land-wrap land-section audiences">
          <section id="patients" className="card audience" aria-labelledby="patients-title">
            <h2 id="patients-title"><UserRound size={22} aria-hidden="true" /> {t("land.forPatients")}</h2>
            <ul className="checks">
              {(["aud.p1", "aud.p2", "aud.p3"] as const).map((k) => <li key={k}><Check size={18} aria-hidden="true" /><span>{t(k)}</span></li>)}
            </ul>
            <div className="actions"><Link className="btn btn-primary" to="/patient/login">{t("land.create")}</Link></div>
          </section>
          <section id="doctors" className="card audience" aria-labelledby="doctors-title">
            <h2 id="doctors-title"><Stethoscope size={22} aria-hidden="true" /> {t("land.doctors")}</h2>
            <p className="muted">{t("land.doctors.text")}</p>
            <ul className="checks">
              {(["aud.d1", "aud.d2", "aud.d3"] as const).map((k) => <li key={k}><Check size={18} aria-hidden="true" /><span>{t(k)}</span></li>)}
            </ul>
            <div className="actions">
              {/* a new doctor signs in with the phone, then submits the BMDC number for an admin to approve */}
              <Link className="btn btn-primary" to="/doctor/login">{t("land.doctors.apply")}</Link>
              <Link className="btn" to="/doctor/login">{t("land.doctors.go")}</Link>
            </div>
          </section>
        </div>
      </main>

      {scrolled > 0.25 && (
        <button type="button" className="to-top icon-btn" aria-label={t("land.toTop")}
                onClick={() => { window.scrollTo({ top: 0 }); document.getElementById("main")?.focus({ preventScroll: true }); }}>
          <ArrowUp size={20} aria-hidden="true" /></button>
      )}
      <footer className="land-footer">
        <div className="land-wrap footer-grid">
          <div>
            <span className="brand"><HeartPulse size={20} aria-hidden="true" />{t("app.name")}</span>
            <p className="muted">{t("app.synthetic")}</p>
          </div>
          <nav aria-label={t("land.footerNav")} className="footer-links">
            {SECTIONS.map(({ href, label }) => <a key={href} href={href}>{t(label)}</a>)}
            <Link to="/patient/login">{t("land.login")}</Link>
          </nav>
          <nav aria-label={t("land.staff")} className="footer-links">
            <span className="muted"><ScrollText size={16} aria-hidden="true" /> {t("land.staff")}</span>
            <Link to="/verifier/login">{t("land.staff.verifier")}</Link>
            <Link to="/console/login">{t("land.staff.console")}</Link>
            <Link to="/portals">{t("land.dev")}</Link>
          </nav>
        </div>
        <p className="land-wrap muted footer-note">{t("land.policy")}</p>
      </footer>
    </div>
  );
}

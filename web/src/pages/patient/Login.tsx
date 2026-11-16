import { HeartPulse } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { ApiError } from "../../api/client";
import { apiMode } from "../../api";
import { MOCK_ADMIN_PHONE, MOCK_CODE, MOCK_DOCTOR_PHONE, MOCK_PHONE, MOCK_REVIEWER_PHONE, MOCK_VERIFIER_PHONE } from "../../api/mock";
import type { PatientProfile, TokenPair } from "../../api/types";
import { LanguageToggle, ThemeSelect } from "../../components/Controls";
import { ErrorNote } from "../../components/ui";
import { localDigits, toAsciiDigits, useI18n } from "../../i18n/i18n";
import { useSession } from "../../session";

type Step = "phone" | "code" | "profile";

/** M1: phone OTP sign-in for the patient app, or for staff (`account: "staff"`): the doctor portal, the verifier/CHW app and the
 * reviewer/admin console. A new user's first verify answers 409 registration_required; the code is spent, so the profile is
 * collected and a NEW code is sent with it (the backend's contract). New doctors and verifiers give only a name: registration
 * starts unverified (a doctor then submits the BMDC credential; an admin approves). Console accounts are never self-registered. */
export function Login({ portal = "patient" }: { portal?: "patient" | "doctor" | "verifier" | "console" }) {
  const staff = portal !== "patient";
  const { t, lang } = useI18n();
  const { api, deviceId, signIn } = useSession();
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [profile, setProfile] = useState<PatientProfile | null>(null);
  const [draft, setDraft] = useState<PatientProfile>({ name: "", dob: "", sex: "F", language: lang });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  const sendCode = () => api.request("POST", "/auth/otp/request", { body: { phone: toAsciiDigits(phone.trim()) } });

  const onPhone = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      await sendCode();
      setStep("code");
    });
  };

  const onCode = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      try {
        const tokens = await api.request<TokenPair>("POST", "/auth/otp/verify", { body: {
          phone: toAsciiDigits(phone.trim()), code: toAsciiDigits(code.trim()), device_id: deviceId,
          ...(staff ? { account: "staff", ...(profile ? { staff: { role: portal, name: profile.name } } : {}) }
            : { account: "patient", ...(profile ? { profile } : {}) }) } });
        signIn(tokens);
        navigate(`/${portal}`, { replace: true });
      } catch (e) {
        if (e instanceof ApiError && e.code === "registration_required") {
          setCode("");
          if (portal === "console") { // reviewers and admins are created by an admin, never here
            setStep("phone");
            throw new ApiError(403, "console_no_signup", "");
          }
          setStep("profile");
          return;
        }
        throw e;
      }
    });
  };

  const onProfile = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      setProfile({ ...draft, name: draft.name.trim(), language: lang });
      await sendCode();
      setStep("code");
    });
  };

  return (
    <div className="shell" data-portal={staff ? "staff" : "patient"}>
      <header className="topbar">
        <span className="brand"><HeartPulse size={22} aria-hidden="true" />{t("app.name")} <small>{t(`portal.${portal}`)}</small></span>
        <div className="controls"><LanguageToggle /><ThemeSelect /></div>
      </header>
      <main id="main" className="content" style={{ maxWidth: "32rem" }}>
        <h1>{t("login.title")}</h1>
        <p>{t("login.intro")}</p>
        {apiMode === "mock" && <p className="notice">{t("common.mockMode", { code: localDigits(MOCK_CODE, lang) })}<br />
          <span lang="en" className="mono">{{ patient: MOCK_PHONE, doctor: MOCK_DOCTOR_PHONE, verifier: MOCK_VERIFIER_PHONE,
            console: `${MOCK_REVIEWER_PHONE} (reviewer) · ${MOCK_ADMIN_PHONE} (admin)` }[portal]}</span></p>}
        <ErrorNote error={error} />

        {step === "phone" && (
          <form onSubmit={onPhone} noValidate>
            <div className="field">
              <label htmlFor="phone">{t("login.phone")}</label>
              <input id="phone" type="tel" inputMode="tel" autoComplete="tel" required value={phone}
                     aria-describedby="phone-hint" onChange={(e) => setPhone(e.target.value)} />
              <span id="phone-hint" className="hint">{t("login.phoneHint")}</span>
            </div>
            <button type="submit" className="btn-primary" disabled={busy || !phone.trim()}>{t("login.send")}</button>
          </form>
        )}

        {step === "code" && (
          <form onSubmit={onCode} noValidate>
            <div className="field">
              <label htmlFor="code">{t("login.code")}</label>
              {/* paste allowed and autofill from SMS (WCAG 3.3.8, accessible authentication) */}
              <input id="code" inputMode="numeric" autoComplete="one-time-code" required value={code} autoFocus
                     aria-describedby="code-hint" onChange={(e) => setCode(e.target.value)} />
              <span id="code-hint" className="hint">{t("login.codeHint")}</span>
            </div>
            <div className="actions">
              <button type="submit" className="btn-primary" disabled={busy || !code.trim()}>{t("login.verify")}</button>
              <button type="button" onClick={() => { setStep("phone"); setCode(""); setProfile(null); }}>{t("login.changePhone")}</button>
            </div>
          </form>
        )}

        {step === "profile" && (
          <form onSubmit={onProfile} noValidate>
            <p className="notice">{t("login.newHere")}</p>
            <div className="field">
              <label htmlFor="name">{t("login.name")}</label>
              <input id="name" autoComplete="name" required value={draft.name} autoFocus onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </div>
            {!staff && <>
            <div className="field">
              <label htmlFor="dob">{t("login.dob")}</label>
              <input id="dob" type="date" autoComplete="bday" required value={draft.dob} onChange={(e) => setDraft({ ...draft, dob: e.target.value })} />
            </div>
            <div className="field">
              <label htmlFor="sex">{t("login.sex")}</label>
              <select id="sex" value={draft.sex} onChange={(e) => setDraft({ ...draft, sex: e.target.value })}>
                <option value="F">{t("login.sex.F")}</option>
                <option value="M">{t("login.sex.M")}</option>
                <option value="O">{t("login.sex.O")}</option>
              </select>
            </div>
            </>}
            <button type="submit" className="btn-primary" disabled={busy || !draft.name.trim() || (!staff && !draft.dob)}>{t("login.register")}</button>
          </form>
        )}
      </main>
    </div>
  );
}

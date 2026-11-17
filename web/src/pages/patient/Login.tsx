import { HeartPulse } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router";
import { ApiError } from "../../api/client";
import { apiMode } from "../../api";
import { MOCK_ADMIN_PHONE, MOCK_CODE, MOCK_DOCTOR_PHONE, MOCK_PHONE, MOCK_REVIEWER_PHONE, MOCK_VERIFIER_PHONE } from "../../api/mockConstants";
import type { PatientProfile, TokenPair } from "../../api/types";
import { LanguageToggle, ThemeSelect } from "../../components/Controls";
import { SkipLink } from "../../shells/Shells";
import { ErrorNote } from "../../components/ui";
import { localDigits, toAsciiDigits, useI18n } from "../../i18n/i18n";
import { useSession } from "../../session";

type Step = "phone" | "code" | "profile";

// the server's code lifetime (identity/otp.py CODE_TTL); the server alone decides, this only tells the user how long is left
const CODE_TTL_S = 5 * 60;

/** "01700000101" -> "•••••••0101": enough to recognise the number on a shared screen. */
export const maskPhone = (phone: string): string => {
  const digits = toAsciiDigits(phone).replace(/\D/g, "");
  return digits.length > 4 ? "•".repeat(digits.length - 4) + digits.slice(-4) : digits;
};

/** M1: phone OTP sign-in for the patient app, or for staff (`account: "staff"`): the doctor portal, the verifier/CHW app and the
 * reviewer/admin console. A new user's first verify answers 409 registration_required; the code is spent, so the profile is
 * collected and a NEW code is sent with it (the backend's contract). New doctors and verifiers give only a name: registration
 * starts unverified (a doctor then submits the BMDC credential; an admin approves). Console accounts are never self-registered. */
export function Login({ portal = "patient" }: { portal?: "patient" | "doctor" | "verifier" | "console" }) {
  const staff = portal !== "patient";
  const { t, lang } = useI18n();
  const { api, deviceId, signIn, expired } = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [profile, setProfile] = useState<PatientProfile | null>(null);
  const [draft, setDraft] = useState<PatientProfile>({ name: "", dob: "", sex: "F", language: lang });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [sentAt, setSentAt] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [resent, setResent] = useState(false);
  useEffect(() => {
    if (step !== "code") return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [step]);
  const left = Math.max(0, CODE_TTL_S - Math.floor((now - sentAt) / 1000));
  const clock = localDigits(`${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`, lang);

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

  const sendCode = async () => {
    await api.request("POST", "/auth/otp/request", { body: { phone: toAsciiDigits(phone.trim()) } });
    setSentAt(Date.now());
    setNow(Date.now());
  };
  // a new code replaces the old one; the server counts requests (5 in 15 minutes) and says so when there are too many
  const onResend = () => run(async () => {
    setResent(false);
    await sendCode();
    setCode("");
    setResent(true);
  });

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
        const from = (location.state as { from?: unknown } | null)?.from;
        // back to the page asked for, only inside this portal
        navigate(typeof from === "string" && from.startsWith(`/${portal}/`) ? from : `/${portal}`, { replace: true });
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
      <SkipLink />
      <header className="topbar">
        <span className="brand"><HeartPulse size={22} aria-hidden="true" />{t("app.name")} <small>{t(`portal.${portal}`)}</small></span>
        <div className="controls"><LanguageToggle /><ThemeSelect /></div>
      </header>
      <main id="main" className="content" style={{ maxWidth: "32rem" }} tabIndex={-1}>
        <h1>{t("login.title")}</h1>
        {expired && <p className="notice" role="status">{t("login.expired")}</p>}
        <p>{t("login.intro")}</p>
        {apiMode === "mock" && <p className="notice">{t("common.mockMode", { code: localDigits(MOCK_CODE, lang) })}<br />
          <span lang="en" className="mono">{{ patient: MOCK_PHONE, doctor: MOCK_DOCTOR_PHONE, verifier: MOCK_VERIFIER_PHONE,
            console: `${MOCK_REVIEWER_PHONE} (reviewer) · ${MOCK_ADMIN_PHONE} (admin)` }[portal]}</span></p>}
        {step === "profile" && <ErrorNote error={error} />}

        {step === "phone" && (
          <form onSubmit={onPhone} noValidate>
            <div className="field">
              <label htmlFor="phone">{t("login.phone")}</label>
              <input id="phone" type="tel" inputMode="tel" autoComplete="tel" required value={phone}
                     aria-describedby={error ? "phone-error phone-hint" : "phone-hint"} aria-invalid={Boolean(error)}
                     onChange={(e) => setPhone(e.target.value)} />
              <span id="phone-hint" className="hint">{t("login.phoneHint")}</span>
              {Boolean(error) && <div id="phone-error"><ErrorNote error={error} /><p className="hint">{t("login.fixPhone")}</p></div>}
            </div>
            <button type="submit" className="btn-primary" aria-busy={busy} disabled={busy || !phone.trim()}>{t("login.send")}</button>
          </form>
        )}

        {step === "code" && (
          <form onSubmit={onCode} noValidate>
            <p>{t("login.sentTo")} <bdi className="mono" lang="en">{maskPhone(phone)}</bdi></p>
            {resent && <p className="notice" role="status">{t("login.resent")}</p>}
            {left > 0
              ? <p className="muted" aria-live="off">{t("login.expiresIn", { time: clock })}</p>
              : <p className="notice" role="status">{t("login.codeExpired")}</p>}
            <div className="field">
              <label htmlFor="code">{t("login.code")}</label>
              {/* paste allowed and autofill from SMS (WCAG 3.3.8, accessible authentication) */}
              <input id="code" inputMode="numeric" autoComplete="one-time-code" required value={code} autoFocus
                     aria-describedby={error ? "code-error code-hint" : "code-hint"} aria-invalid={Boolean(error)}
                     onChange={(e) => setCode(e.target.value)} />
              <span id="code-hint" className="hint">{t("login.codeHint")}</span>
              {Boolean(error) && <div id="code-error"><ErrorNote error={error} /><p className="hint">{t("login.fixCode")}</p></div>}
            </div>
            <div className="actions">
              <button type="submit" className="btn-primary" aria-busy={busy} disabled={busy || !code.trim() || left === 0}>{t("login.verify")}</button>
              <button type="button" disabled={busy} onClick={onResend}>{t("login.resend")}</button>
              <button type="button" onClick={() => { setStep("phone"); setCode(""); setProfile(null); setResent(false); }}>{t("login.changePhone")}</button>
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

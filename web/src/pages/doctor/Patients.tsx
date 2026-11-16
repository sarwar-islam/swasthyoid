import { KeyRound, Send } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import type { DoctorConsent } from "../../api/types";
import { ErrorNote, Section } from "../../components/ui";
import { toAsciiDigits, useI18n } from "../../i18n/i18n";
import type { Key } from "../../i18n/strings";
import { useSession } from "../../session";
import { clock, useMe, useOpenPatients, useSecondsLeft } from "./doctor";

const CATEGORIES = ["timeline", "documents", "safety"] as const;
const HEALTH_ID = /^SID-\d{10}$/;

function OpenRow({ c }: { c: DoctorConsent }) {
  const { t, lang } = useI18n();
  const left = useSecondsLeft(c.expires_at);
  return (
    <li className="card row">
      <span><strong className="mono">{c.health_id}</strong><br />
        <span className="muted">{left ? t("bar.expires", { time: clock(left, lang) }) : t("bar.expired")}</span></span>
      <Link className="btn" to={`/doctor/patients/${c.patient_id}`}>{t("open.view")}</Link>
    </li>
  );
}

/** M1/C1 from the doctor's side: request TIMELINE consent by Health ID with the categories needed; the patient receives a one-time
 * code and, if they agree, tells it to the doctor, who confirms it. Unverified or suspended doctors cannot request. */
export function Patients() {
  const { t } = useI18n();
  const { api } = useSession();
  const me = useMe();
  const { open, remember } = useOpenPatients();
  const navigate = useNavigate();
  const [healthId, setHealthId] = useState("");
  const [categories, setCategories] = useState<string[]>(["timeline"]);
  const [pending, setPending] = useState<DoctorConsent | null>(null);
  const [code, setCode] = useState("");
  const [badId, setBadId] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const verified = me.data?.status === "verified";

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

  const request = (e: FormEvent) => {
    e.preventDefault();
    const id = toAsciiDigits(healthId.trim().toUpperCase());
    setBadId(!HEALTH_ID.test(id));
    if (!HEALTH_ID.test(id)) return;
    run(async () => setPending(await api.request<DoctorConsent>("POST", "/consents/requests", { body: { health_id: id, categories } })));
  };

  const confirm = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      const active = await api.request<DoctorConsent>("POST", `/consents/requests/${pending!.id}/confirm`, { body: { code: toAsciiDigits(code.trim()) } });
      remember(active);
      navigate(`/doctor/patients/${active.patient_id}`);
    });
  };

  return (
    <>
      <h1>{t("nav.patients")}</h1>
      <Section id="request" title={t("req.title")}>
        {!pending ? (
          <form onSubmit={request} className="card" noValidate>
            <div className="field">
              <label htmlFor="health-id">{t("req.healthId")}</label>
              <input id="health-id" className="mono" autoComplete="off" spellCheck={false} value={healthId} lang="en"
                     aria-describedby="hid-hint" aria-invalid={badId} onChange={(e) => setHealthId(e.target.value)} />
              <span id="hid-hint" className="hint">{t("req.healthIdHint")}</span>
              {badId && <span className="error-note" role="alert">{t("req.badId")}</span>}
            </div>
            <fieldset>
              <legend>{t("req.categories")}</legend>
              {CATEGORIES.map((c) => (
                <label key={c} className="check">
                  <input type="checkbox" checked={categories.includes(c)}
                         onChange={() => setCategories((l) => (l.includes(c) ? l.filter((x) => x !== c) : [...l, c]))} />
                  {t(`cat.${c}` as Key)}
                </label>
              ))}
            </fieldset>
            <ErrorNote error={error} />
            {!verified && me.data && <p className="muted" id="not-verified">{t("req.notVerified")}</p>}
            <button type="submit" className="btn-primary" disabled={busy || !verified || categories.length === 0}
                    aria-describedby={!verified ? "not-verified" : undefined}>
              <Send size={18} aria-hidden="true" />{t("req.send")}
            </button>
            <p className="muted">{t("req.qr")}</p>
          </form>
        ) : (
          <form onSubmit={confirm} className="card" noValidate>
            <h3>{t("req.codeTitle")}</h3>
            <p>{t("req.codeNote")}</p>
            <div className="field">
              <label htmlFor="consent-code">{t("req.code")}</label>
              <input id="consent-code" inputMode="numeric" autoComplete="off" autoFocus value={code} onChange={(e) => setCode(e.target.value)} />
            </div>
            <ErrorNote error={error} />
            <div className="actions">
              <button type="submit" className="btn-primary" disabled={busy || !code.trim()}><KeyRound size={18} aria-hidden="true" />{t("req.confirm")}</button>
              <button type="button" onClick={() => { setPending(null); setCode(""); setError(null); }}>{t("req.cancel")}</button>
            </div>
          </form>
        )}
      </Section>

      <Section id="open" title={t("open.title")}>
        {open.length === 0 ? <p className="muted">{t("open.none")}</p> : <ul className="list">{open.map((c) => <OpenRow key={c.id} c={c} />)}</ul>}
      </Section>
    </>
  );
}

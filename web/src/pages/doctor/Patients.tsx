import { KeyRound, QrCode, Send } from "lucide-react";
import QRCode from "qrcode";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import type { DoctorConsent, DoctorQrConsent } from "../../api/types";
import { ErrorNote, Section } from "../../components/ui";
import { toAsciiDigits, useI18n } from "../../i18n/i18n";
import type { Key } from "../../i18n/strings";
import { useSession } from "../../session";
import { clock, useMe, useOpenPatients, useSecondsLeft } from "./doctor";

const CATEGORIES = ["timeline", "documents", "safety"] as const;
const HEALTH_ID = /^SID-\d{10}$/;
const POLL_MS = 3000;

/** A QR request (GAP, F6): the QR links to the patient app, where the signed-in patient sees exactly what is asked and answers.
 * This screen asks the server for the request's state until the patient answers or the QR expires. */
function QrPending({ request, onActive, onCancel }: { request: DoctorQrConsent; onActive: (c: DoctorConsent) => void; onCancel: () => void }) {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const [src, setSrc] = useState<string | null>(null);
  const [status, setStatus] = useState<DoctorConsent["status"]>("pending");
  const [error, setError] = useState<unknown>(null);
  const left = useSecondsLeft(request.qr.expires_at);
  const open = status === "pending" && left > 0;

  useEffect(() => {
    const url = `${window.location.origin}/patient/consent/qr/${encodeURIComponent(request.qr.token)}`;
    // dark on light whatever the theme: phone cameras need the contrast
    QRCode.toString(url, { type: "svg", margin: 2, errorCorrectionLevel: "M", color: { dark: "#000000", light: "#ffffff" } })
      .then((svg) => setSrc(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`), setError);
  }, [request.qr.token]);

  useEffect(() => {
    if (!open) return;
    const timer = setInterval(() => {
      api.request<DoctorConsent>("GET", `/consents/requests/${request.id}`).then((c) => {
        setError(null);
        if (c.status === "active") onActive(c);
        else setStatus(c.status);
      }, setError);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [open, api, request.id]); // onActive only navigates away

  return (
    <div className="card stack">
      <h3><QrCode size={20} aria-hidden="true" /> {t("qr.title")}</h3>
      {open && (
        <>
          <p>{t("qr.note")}</p>
          <div className="qr-box">{src ? <img src={src} alt={t("qr.alt")} width={240} height={240} /> : null}</div>
          <p>{t("qr.codeNote")}</p>
          <p className="qr-code mono" lang="en">{request.qr.short_code}</p>
          <p className="muted">{t("qr.left", { time: clock(left, lang) })}</p>
        </>
      )}
      <p role="status" className={open ? "muted" : "notice"}>
        {status === "declined" ? t("qr.declined") : !open ? t("qr.expired") : t("qr.waiting")}
      </p>
      <ErrorNote error={error} />
      <div className="actions"><button type="button" onClick={onCancel}>{t("req.cancel")}</button></div>
    </div>
  );
}

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
  const [method, setMethod] = useState<"otp" | "qr">("otp");
  const [pending, setPending] = useState<DoctorConsent | DoctorQrConsent | null>(null);
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
    // the BUILT body for a code; `method: "qr"` is the GAP addition (F6)
    const body = method === "qr" ? { health_id: id, categories, method } : { health_id: id, categories };
    run(async () => setPending(await api.request<DoctorConsent>("POST", "/consents/requests", { body })));
  };
  const cancel = () => { setPending(null); setCode(""); setError(null); };
  const opened = (c: DoctorConsent) => {
    remember(c);
    navigate(`/doctor/patients/${c.patient_id}`);
  };

  const confirm = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      opened(await api.request<DoctorConsent>("POST", `/consents/requests/${pending!.id}/confirm`, { body: { code: toAsciiDigits(code.trim()) } }));
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
            <fieldset>
              <legend>{t("req.method")}</legend>
              {(["otp", "qr"] as const).map((m) => (
                <label key={m} className="check">
                  <input type="radio" name="consent-method" value={m} checked={method === m} onChange={() => setMethod(m)} />
                  {t(`req.method.${m}`)}
                </label>
              ))}
            </fieldset>
            <ErrorNote error={error} />
            {!verified && me.data && <p className="muted" id="not-verified">{t("req.notVerified")}</p>}
            <button type="submit" className="btn-primary" disabled={busy || !verified || categories.length === 0}
                    aria-describedby={!verified ? "not-verified" : undefined}>
              <Send size={18} aria-hidden="true" />{t("req.send")}
            </button>
          </form>
        ) : "qr" in pending ? (
          <QrPending request={pending} onActive={opened} onCancel={cancel} />
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
              <button type="button" onClick={cancel}>{t("req.cancel")}</button>
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

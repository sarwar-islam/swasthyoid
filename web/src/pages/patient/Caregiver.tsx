import { ArrowLeft, CalendarClock, ShieldCheck, UserRound } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, NavLink, Outlet, useOutletContext, useParams } from "react-router";
import { apiMode } from "../../api";
import { MOCK_CODE } from "../../api/mock";
import type { CaregiverAuthorization, CaregiverScope } from "../../api/types";
import { ErrorNote, Loading, Section } from "../../components/ui";
import { formatDate, localDigits, toAsciiDigits, useI18n } from "../../i18n/i18n";
import type { Key } from "../../i18n/strings";
import { useLoad, useSession } from "../../session";
import { DoctorDocument } from "../doctor/Workspace";
import { Capture, DocList } from "./Capture";
import { TimelineView } from "./Timeline";

const SCOPES: CaregiverScope[] = ["view_timeline", "view_documents", "upload_documents"];
/** The caregiver's pages, one per scope. Nothing else of the patient's is reachable here: no consent, access history or check. */
export const CARE_TABS: Array<{ path: string; scope: CaregiverScope; label: Key }> = [
  { path: "timeline", scope: "view_timeline", label: "tl.title" },
  { path: "documents", scope: "view_documents", label: "care.documents" },
  { path: "upload", scope: "upload_documents", label: "care.upload" }, // not "Capture": that is the caregiver's own page
];

const scopeList = (a: { scopes: CaregiverScope[] }, t: (k: Key) => string) => a.scopes.map((s) => t(`cat.${s}`)).join(", ");

/** M1 caregiver side: the people I may act for now, and asking for access (approved by the patient in their app, or by the code
 * sent to the patient's own phone, which the patient reads out). Pending requests are never listed (the backend's rule). */
export function Caregiving() {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const people = useLoad(() => api.request<CaregiverAuthorization[]>("GET", "/caregiver-authorizations"), []);
  const [healthId, setHealthId] = useState("");
  const [scopes, setScopes] = useState<CaregiverScope[]>(["view_timeline"]);
  const [days, setDays] = useState("30");
  const [asked, setAsked] = useState<string | null>(null); // the Health ID asked for, once sent
  const [code, setCode] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);
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

  const ask = (e: FormEvent) => {
    e.preventDefault();
    const hid = toAsciiDigits(healthId.trim()).toUpperCase();
    run(async () => {
      await api.request("POST", "/caregiver-authorizations", { body: { patient_health_id: hid, scopes, duration_days: Number(toAsciiDigits(days)) } });
      setAsked(hid);
      setDone(false);
    });
  };
  const confirm = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      await api.request("POST", "/caregiver-authorizations/confirm", { body: { patient_health_id: asked, code: toAsciiDigits(code.trim()) } });
      setAsked(null);
      setCode("");
      setHealthId("");
      setDone(true);
      people.reload();
    });
  };
  const daysNumber = Number(toAsciiDigits(days));

  return (
    <>
      <h1>{t("care.title")}</h1>
      <p>{t("care.intro")}</p>
      {done && <p className="ok-note" role="status">{t("care.approved")}</p>}
      {people.loading ? <Loading /> : <ErrorNote error={people.error} />}
      {people.data?.length === 0 && <p className="muted">{t("care.none")}</p>}
      <ul className="list">
        {people.data?.map((a) => (
          <li key={a.id} className="card">
            <p><strong>{a.patient_name}</strong></p>
            <p className="muted">{t("bar.allowed", { what: scopeList(a, t) })} · {t("care.until", { date: formatDate(a.expires_at ?? "", lang) })}</p>
            <Link to={`/patient/for/${a.patient_id}`} className="btn btn-primary">{t("care.open", { name: a.patient_name })}</Link>
          </li>
        ))}
      </ul>

      <Section id="care-ask" title={t("care.askTitle")}>
        {!asked ? (
          <form onSubmit={ask} className="card" noValidate>
            <div className="field">
              <label htmlFor="care-hid">{t("care.healthId")}</label>
              <input id="care-hid" autoComplete="off" spellCheck={false} value={healthId} onChange={(e) => setHealthId(e.target.value)} />
            </div>
            <fieldset>
              <legend>{t("care.scopes")}</legend>
              {SCOPES.map((s) => (
                <label key={s} className="check">
                  <input type="checkbox" checked={scopes.includes(s)}
                         onChange={(e) => setScopes((list) => (e.target.checked ? [...list, s] : list.filter((x) => x !== s)))} />
                  {t(`cat.${s}`)}
                </label>
              ))}
            </fieldset>
            <div className="field">
              <label htmlFor="care-days">{t("care.days")}</label>
              <input id="care-days" inputMode="numeric" value={days} aria-describedby="care-days-hint" onChange={(e) => setDays(e.target.value)} />
              <span id="care-days-hint" className="hint">{t("care.daysHint")}</span>
            </div>
            <p className="muted">{t("care.never")}</p>
            <ErrorNote error={error} />
            <button type="submit" className="btn-primary"
                    disabled={busy || !healthId.trim() || !scopes.length || !Number.isInteger(daysNumber) || daysNumber < 1 || daysNumber > 90}>
              {t("care.send")}
            </button>
          </form>
        ) : (
          <form onSubmit={confirm} className="card" noValidate>
            <p className="notice" role="status">{t("care.sent", { id: asked })}</p>{/* an ID keeps its own digits (owner decision 2026-11-17) */}
            {apiMode === "mock" && <p className="notice">{t("common.mockMode", { code: localDigits(MOCK_CODE, lang) })}</p>}
            <div className="field">
              <label htmlFor="care-code">{t("req.code")}</label>
              <input id="care-code" inputMode="numeric" autoComplete="off" value={code} autoFocus onChange={(e) => setCode(e.target.value)} />
            </div>
            <ErrorNote error={error} />
            <div className="actions">
              <button type="submit" className="btn-primary" disabled={busy || !code.trim()}>{t("care.confirm")}</button>
              <button type="button" onClick={() => { setAsked(null); setCode(""); setError(null); }}>{t("req.cancel")}</button>
            </div>
          </form>
        )}
      </Section>
    </>
  );
}

const useAuth = () => useOutletContext<CaregiverAuthorization>();

/** Acting for another patient: only under an active authorization the server lists for me, only its scopes. The bar says whose
 * record this is on every page. The server checks every request again (C1, then the C2 audit the patient can see). */
export function CaregiverFrame() {
  const { pid = "" } = useParams();
  const { t, lang } = useI18n();
  const { api } = useSession();
  const list = useLoad(() => api.request<CaregiverAuthorization[]>("GET", "/caregiver-authorizations"), []);
  if (list.loading && !list.data) return <Loading />;
  const auth = list.data?.find((a) => a.patient_id === pid);
  if (!auth) {
    return (
      <>
        <h1>{t("care.title")}</h1>
        {list.error ? <ErrorNote error={list.error} /> : <p className="notice">{t("care.noAccess")}</p>}
        <Link to="/patient/caregiving">{t("care.back")}</Link>
      </>
    );
  }
  const base = `/patient/for/${pid}`;
  return (
    <>
      <div className="context-bar" role="region" aria-label={t("care.actingFor", { name: auth.patient_name })}>
        <span><UserRound size={18} aria-hidden="true" /> {t("care.actingFor", { name: auth.patient_name })}</span>
        <span><ShieldCheck size={18} aria-hidden="true" /> {t("bar.allowed", { what: scopeList(auth, t) })}</span>
        <span><CalendarClock size={18} aria-hidden="true" /> {t("care.until", { date: formatDate(auth.expires_at ?? "", lang) })}</span>
        <Link to="/patient/caregiving"><ArrowLeft size={18} aria-hidden="true" /> {t("care.back")}</Link>
      </div>
      <nav aria-label={t("ws.sections")} className="tabs-nav">
        {CARE_TABS.filter((tab) => auth.scopes.includes(tab.scope)).map((tab) => <NavLink key={tab.path} to={`${base}/${tab.path}`}>{t(tab.label)}</NavLink>)}
      </nav>
      <Outlet context={auth} />
    </>
  );
}

/** The first page this authorization allows. */
export function CareIndex() {
  const auth = useAuth();
  const first = CARE_TABS.find((tab) => auth.scopes.includes(tab.scope));
  return first ? <Navigate to={first.path} replace /> : null;
}

/** A caregiver page, shown only when the authorization holds `scope` (the server refuses it otherwise anyway). */
export function CareRoute({ scope }: { scope: CaregiverScope }) {
  const { t } = useI18n();
  const auth = useAuth();
  const base = `/patient/for/${auth.patient_id}`;
  const docs = auth.scopes.includes("view_documents") ? `${base}/documents` : null;
  if (!auth.scopes.includes(scope)) return <><h1>{t("care.title")}</h1><p className="notice">{t("care.noScope")}</p></>;
  const pages: Record<CaregiverScope, ReactNode> = {
    view_timeline: <TimelineView patientId={auth.patient_id} docBase={docs} title />,
    view_documents: <><h1>{t("care.documents")}</h1><DocList patientId={auth.patient_id} base={`${base}/documents`} title="care.allDocs" /></>,
    upload_documents: <Capture patientId={auth.patient_id} docBase={docs} listTitle="care.allDocs" />,
  };
  return pages[scope];
}

/** One document of theirs, view only: the photos, never the unverified extraction (caregivers never verify). */
export function CareDocument() {
  const { t } = useI18n();
  const auth = useAuth();
  if (!auth.scopes.includes("view_documents")) return <><h1>{t("care.title")}</h1><p className="notice">{t("care.noScope")}</p></>;
  return <><h1>{t("care.documents")}</h1><DoctorDocument /></>;
}

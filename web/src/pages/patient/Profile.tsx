import { useState } from "react";
import { Link } from "react-router";
import type { DocType, DocumentView, Me } from "../../api/types";
import { CopyButton, ErrorNote, Loading, StatusChip } from "../../components/ui";
import { formatDate, useI18n } from "../../i18n/i18n";
import type { Key } from "../../i18n/strings";
import { useLoad, useSession } from "../../session";

/** UX-1: the patient's own details, read only. The phone shows only its last four digits; nothing here can be edited yet. */
export function Profile() {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const me = useLoad(() => api.request<Me>("GET", "/me"), []);
  const p = me.data;
  const sex = p && (["F", "M", "O"].includes(p.sex) ? t(`login.sex.${p.sex}` as Key) : p.sex);
  return (
    <>
      <h1>{t("me.title")}</h1>
      {me.loading ? <Loading lines={2} /> : <ErrorNote error={me.error} onRetry={me.reload} />}
      {p && (
        <dl className="card profile">
          <dt>{t("me.healthId")}</dt><dd><bdi className="mono" lang="en">{p.health_id}</bdi> <CopyButton value={p.health_id} label="home.copy" /></dd>
          <dt>{t("login.name")}</dt><dd><bdi>{p.name}</bdi></dd>
          <dt>{t("login.dob")}</dt><dd>{formatDate(p.dob, lang)}</dd>
          <dt>{t("login.sex")}</dt><dd>{sex}</dd>
          <dt>{t("me.language")}</dt><dd>{p.language === "bn" ? "বাংলা" : "English"}</dd>
          <dt>{t("login.phone")}</dt><dd><bdi className="mono" lang="en">{"•".repeat(7) + p.phone_tail}</bdi></dd>
          <dt>{t("me.since")}</dt><dd>{formatDate(p.created_at, lang)}</dd>
        </dl>
      )}
      <p className="muted">{t("me.readOnly")}</p>
    </>
  );
}

const DOC_TYPES: DocType[] = ["prescription", "lab_report", "discharge_summary", "other"];

/** UX-1: every document the patient uploaded, filterable by type. Only verified ones reach the timeline; the status says why
 * a document is not there yet. */
export function Records() {
  const { t, lang } = useI18n();
  const { api, claims } = useSession();
  const docs = useLoad(() => api.request<DocumentView[]>("GET", `/patients/${claims?.sub}/documents`), [claims?.sub]);
  const [type, setType] = useState<"all" | DocType>("all");
  const all = docs.data ?? [];
  const shown = all.filter((d) => type === "all" || d.doc_type === type).sort((a, b) => b.created_at.localeCompare(a.created_at));
  return (
    <>
      <h1>{t("records.title")}</h1>
      <p className="muted">{t("records.explain")}</p>
      <fieldset className="segmented chips">
        <legend className="sr-only">{t("tl.type")}</legend>
        {(["all", ...DOC_TYPES] as const).map((f) => (
          <label key={f}>
            <input type="radio" name="doc-type" value={f} checked={type === f} onChange={() => setType(f)} />
            {t(f === "all" ? "tl.all" : `doc.${f}` as Key)}
          </label>
        ))}
      </fieldset>
      {docs.loading ? <Loading lines={3} /> : <ErrorNote error={docs.error} onRetry={docs.reload} />}
      {!docs.loading && !docs.error && all.length === 0 && (
        <p className="muted">{t("capture.noDocs")} <Link to="/patient/capture">{t("nav.capture")}</Link></p>
      )}
      {all.length > 0 && shown.length === 0 && <p className="muted">{t("tl.noMatch")}</p>}
      <ul className="list">
        {shown.map((d) => (
          <li key={d.id}>
            <Link to={`/patient/documents/${d.id}`} className="card row">
              <span><strong>{t(`doc.${d.doc_type}`)}</strong><br /><span className="muted">{formatDate(d.created_at, lang)}</span></span>
              <StatusChip status={d.status} />
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}

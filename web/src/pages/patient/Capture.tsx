import { AlertTriangle, Upload } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { ApiError } from "../../api/client";
import type { DocType, DocumentView, QualityWarningDetails } from "../../api/types";
import { ErrorNote, Loading, Section, StatusChip } from "../../components/ui";
import { formatDate, formatNumber, useI18n } from "../../i18n/i18n";
import type { Key } from "../../i18n/strings";
import { useLoad, useSession } from "../../session";

const DOC_TYPES: DocType[] = ["prescription", "lab_report", "discharge_summary", "other"];

/** M2 capture: upload, then the Phase 5 quality warning with the approved Bangla guidance, a retake, or "upload anyway". Hard
 * errors (wrong file type, damaged, too large) are never bypassed, by the server or here. With `patientId` it uploads for that
 * patient (a caregiver or a verifier; the server decides). `docBase` null: the uploader may not view documents, so no list. */
export function Capture({ patientId, docBase = "/patient/documents", listTitle }: { patientId?: string; docBase?: string | null; listTitle?: Key }) {
  const { t, lang } = useI18n();
  const { claims, api } = useSession();
  const navigate = useNavigate();
  const [sent, setSent] = useState(false);
  const [docType, setDocType] = useState<DocType>("prescription");
  const [files, setFiles] = useState<File[]>([]);
  const [warning, setWarning] = useState<QualityWarningDetails | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const previews = useMemo(() => (typeof URL.createObjectURL === "function" ? files.map((f) => URL.createObjectURL(f)) : []), [files]);
  useEffect(() => () => previews.forEach((u) => URL.revokeObjectURL(u)), [previews]);

  async function upload(anyway: boolean) {
    if (!files.length) {
      setError(new ApiError(422, "invalid_document", ""));
      return;
    }
    setBusy(true);
    setError(null);
    setSent(false);
    const form = new FormData();
    form.append("doc_type", docType);
    form.append("upload_anyway", anyway ? "true" : "false");
    files.forEach((f) => form.append("images", f, f.name));
    try {
      const created = await api.request<DocumentView>("POST", patientId ? `/patients/${patientId}/documents` : "/documents", { body: form });
      if (docBase) navigate(`${docBase}/${created.id}`);
      else {
        retake();
        setSent(true);
      }
    } catch (e) {
      if (e instanceof ApiError && e.code === "image_quality_warning") setWarning(e.details as unknown as QualityWarningDetails);
      else setError(e);
    } finally {
      setBusy(false);
    }
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    upload(false);
  };

  const retake = () => {
    setWarning(null);
    setFiles([]);
    if (input.current) {
      input.current.value = "";
      input.current.focus();
    }
  };

  return (
    <>
      <h1>{t("capture.title")}</h1>
      <form onSubmit={onSubmit} className="card" noValidate>
        <div className="field">
          <label htmlFor="doc-type">{t("capture.type")}</label>
          <select id="doc-type" value={docType} onChange={(e) => setDocType(e.target.value as DocType)}>
            {DOC_TYPES.map((d) => <option key={d} value={d}>{t(`doc.${d}`)}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="pages">{t("capture.files")}</label>
          <input id="pages" ref={input} type="file" accept="image/jpeg,image/png" multiple aria-describedby="pages-tip"
                 onChange={(e) => { setFiles(Array.from(e.target.files ?? []).slice(0, 10)); setWarning(null); setError(null); }} />
          <span id="pages-tip" className="hint">{t("capture.tip")}</span>
        </div>
        {previews.length > 0 && (
          <ul className="thumbs">
            {previews.map((src, i) => <li key={src}><img src={src} alt={t("verify.imageAlt", { n: formatNumber(i + 1, lang) })} /></li>)}
          </ul>
        )}
        <ErrorNote error={error} />
        {sent && <p className="ok-note" role="status">{t("capture.sent")}</p>}
        {warning ? (
          <div className="stack" role="alert">
            <p className="error-note" style={{ color: "var(--reported)", background: "var(--reported-soft)", borderColor: "var(--reported-line)" }}>
              <AlertTriangle size={18} aria-hidden="true" />{t("capture.poor")}
            </p>
            <ul className="list">
              {warning.pages.map((p) => (
                <li key={p.page} className="card">
                  <strong>{t("common.page", { n: formatNumber(p.page, lang) })}</strong>
                  <ul>
                    {p.guidance.map((g) => (
                      // the guidance text exists in Bangla only (capture/guidance.py); English shows the reason name
                      <li key={g.code} lang={lang === "bn" && g.bn ? "bn" : "en"}>{lang === "bn" && g.bn ? g.bn : t(`q.${g.code}`)}</li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
            <p className="muted">{t("capture.anywayNote")}</p>
            <div className="actions">
              <button type="button" className="btn-primary" onClick={retake}>{t("capture.retake")}</button>
              <button type="button" disabled={busy} onClick={() => upload(true)}>{t("capture.anyway")}</button>
            </div>
          </div>
        ) : (
          <button type="submit" className="btn-primary" disabled={busy}>
            <Upload size={20} aria-hidden="true" />{busy ? t("capture.uploading") : t("capture.upload")}
          </button>
        )}
      </form>

      {docBase && <DocList patientId={patientId ?? claims?.sub ?? ""} base={docBase} title={listTitle} />}
    </>
  );
}

/** A patient's documents, each linking to `${base}/{id}`. The server decides what this viewer may list. */
export function DocList({ patientId, base, title = "capture.yourDocs" }: { patientId: string; base: string; title?: Key }) {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const docs = useLoad(() => api.request<DocumentView[]>("GET", `/patients/${patientId}/documents`), [patientId]);
  return (
    <Section id="your-docs" title={t(title)}>
      {docs.loading ? <Loading /> : <ErrorNote error={docs.error} />}
      {docs.data?.length === 0 && <p className="muted">{t("capture.noDocs")}</p>}
      <ul className="list">
        {docs.data?.map((d) => (
          <li key={d.id}>
            <Link to={`${base}/${d.id}`} className="card row">
              <span><strong>{t(`doc.${d.doc_type}`)}</strong><br /><span className="muted">{formatDate(d.created_at, lang)}</span></span>
              <StatusChip status={d.status} />
            </Link>
          </li>
        ))}
      </ul>
    </Section>
  );
}

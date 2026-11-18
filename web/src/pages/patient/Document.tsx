import { AlertTriangle, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import type { Client } from "../../api/client";
import type { DocumentView, ExtractedField, ExtractionResponse, FieldRow } from "../../api/types";
import { ConfirmDialog, ErrorNote, Loading, StatusChip } from "../../components/ui";
import { formatDate, formatNumber, useI18n } from "../../i18n/i18n";
import { bn, type Key } from "../../i18n/strings";
import { useLoad, useSession } from "../../session";

type Draft = Record<string, string | Array<Record<string, string>>>;

const isField = (v: unknown): v is ExtractedField => !!v && typeof v === "object" && "confidence" in v;
const label = (name: string): Key | null => (`f.${name}` in bn ? (`f.${name}` as Key) : null);
const DATE_FIELDS = /_date$/;

/** The editable copy of an extraction: the accepted value, else the raw reading (to be checked), else empty. Non-field keys
 * (for example `catalog_matches`, drug-name candidates) are not edited here. */
function toDraft(fields: Record<string, unknown>): Draft {
  const draft: Draft = {};
  for (const [name, v] of Object.entries(fields)) {
    if (Array.isArray(v)) draft[name] = v.map((row: FieldRow) => Object.fromEntries(Object.entries(row).map(([k, f]) => [k, f.value ?? f.raw ?? ""])));
    else if (isField(v)) draft[name] = DATE_FIELDS.test(name) && v.value ? dayFirst(v.value) : v.value ?? v.raw ?? "";
  }
  return draft;
}

/** An accepted ISO date shown day first, as written in Bangladesh; the server accepts both forms (extraction.parse). */
const dayFirst = (iso: string) => (/^\d{4}-\d{2}-\d{2}$/.test(iso) ? iso.split("-").reverse().join("/") : iso);

const toBody = (draft: Draft) => Object.fromEntries(Object.entries(draft).map(([k, v]) => [k, Array.isArray(v)
  ? v.map((row) => Object.fromEntries(Object.entries(row).map(([s, x]) => [s, x.trim() || null])))
  : v.trim() || null]));

function PageImage({ api, id, n }: { api: Client; id: string; n: number }) {
  const { t, lang } = useI18n();
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let url: string | null = null;
    api.request<Blob>("GET", `/documents/${id}/images/${n}`, { binary: true }).then((blob) => {
      if (typeof URL.createObjectURL === "function") setSrc((url = URL.createObjectURL(blob)));
    }, () => setSrc(null));
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [api, id, n]);
  return src ? <img loading="lazy" decoding="async" src={src} alt={t("verify.imageAlt", { n: formatNumber(n, lang) })} /> : <Loading />;
}

function FieldInput({ id, name, value, source, threshold, onChange }:
  { id: string; name: string; value: string; source?: ExtractedField; threshold: number; onChange: (v: string) => void }) {
  const { t, lang } = useI18n();
  const key = label(name);
  const low = !!source && source.raw !== null && !source.error && source.confidence < threshold;
  const unread = !!source?.error;
  const note = `${id}-note`;
  return (
    <div className={`field${low || unread ? " low" : ""}`}>
      <label htmlFor={id}>{key ? t(key) : name}</label>
      <input id={id} value={value} onChange={(e) => onChange(e.target.value)} aria-describedby={low || unread || DATE_FIELDS.test(name) ? note : undefined} />
      {(low || unread) ? (
        <span id={note} className="flag"><AlertTriangle size={16} aria-hidden="true" />
          {unread ? t("verify.unread") : t("verify.low", { value: formatNumber(source!.confidence, lang, { maximumFractionDigits: 2 }) })}
        </span>
      ) : DATE_FIELDS.test(name) && <span id={note} className="hint">{t("f.dateHint")}</span>}
    </div>
  );
}

function Verify({ doc, data, threshold, onDone }:
  { doc: DocumentView; data: NonNullable<ExtractionResponse["extraction"]>; threshold: number; onDone: () => void }) {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const [draft, setDraft] = useState<Draft>(() => toDraft(data.fields));
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);
  const fields = data.fields as Record<string, unknown>;

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      onDone();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  const confirm = () => act(async () => {
    await api.request("PUT", `/documents/${doc.id}/review`, { body: { fields: toBody(draft) } });
    await api.request("POST", `/documents/${doc.id}/confirm`);
  });
  const reject = () => {
    setAsking(false);
    act(() => api.request("POST", `/documents/${doc.id}/reject`));
  };

  const setRow = (group: string, i: number, sub: string, v: string) => setDraft((d) => {
    const rows = [...(d[group] as Array<Record<string, string>>)];
    rows[i] = { ...rows[i], [sub]: v };
    return { ...d, [group]: rows };
  });
  const subFields = (group: string) => {
    const first = (fields[group] as FieldRow[] | undefined)?.[0];
    return first ? Object.keys(first) : ["name_as_written", "strength", "form", "dose_instruction", "duration"];
  };

  return (
    <div className="verify">
      <section className="paper" aria-labelledby="paper-title">
        <h2 id="paper-title">{t("verify.image")}</h2>
        {doc.images.map((img) => <PageImage key={img.n} api={api} id={doc.id} n={img.n} />)}
      </section>
      <section aria-labelledby="check-title">
        <h2 id="check-title">{t("verify.title")}</h2>
        <p className="muted">{t("verify.intro")}</p>
        {data.printed_name_check === "not_the_same" && <p className="error-note" role="note">{t("verify.nameMismatch")}</p>}
        <form onSubmit={(e) => { e.preventDefault(); confirm(); }} noValidate>
          {Object.entries(draft).map(([name, value]) => Array.isArray(value) ? (
            <div key={name}>
              {value.map((row, i) => (
                <fieldset key={i}>
                  <legend>{t("verify.medicine", { n: formatNumber(i + 1, lang) })}</legend>
                  {Object.keys(row).map((sub) => (
                    <FieldInput key={sub} id={`${name}-${i}-${sub}`} name={sub} value={row[sub]} threshold={threshold}
                                source={(fields[name] as FieldRow[] | undefined)?.[i]?.[sub]} onChange={(v) => setRow(name, i, sub, v)} />
                  ))}
                  <button type="button" onClick={() => setDraft((d) => ({ ...d, [name]: (d[name] as unknown[]).filter((_, j) => j !== i) as Draft[string] }))}>
                    <Trash2 size={18} aria-hidden="true" />{t("verify.removeMedicine", { n: formatNumber(i + 1, lang) })}
                  </button>
                </fieldset>
              ))}
              <button type="button" onClick={() => setDraft((d) => ({ ...d, [name]: [...(d[name] as Array<Record<string, string>>),
                Object.fromEntries(subFields(name).map((s) => [s, ""]))] }))}>
                <Plus size={18} aria-hidden="true" />{t("verify.addMedicine")}
              </button>
            </div>
          ) : (
            <FieldInput key={name} id={`f-${name}`} name={name} value={value} threshold={threshold}
                        source={fields[name] as ExtractedField} onChange={(v) => setDraft((d) => ({ ...d, [name]: v }))} />
          ))}
          <ErrorNote error={error} />
          <div className="actions">
            <button type="submit" className="btn-primary" disabled={busy}>{t("verify.confirm")}</button>
            <button type="button" disabled={busy} onClick={() => setAsking(true)}>{t("verify.reject")}</button>
          </div>
        </form>
        <ConfirmDialog open={asking} title={t("verify.rejectAsk")} confirmLabel={t("verify.rejectYes")} onConfirm={reject} onCancel={() => setAsking(false)} />
      </section>
    </div>
  );
}

/** M2/M3: a document's state, and the side-by-side check when it needs review. Raw M6 safety alerts are never shown to the
 * patient (owner decision 2026-11-15). A verifier uses it too, with no timeline link (`toTimeline` null): verifiers never read it. */
export function DocumentPage({ toTimeline = "/patient/timeline" }: { toTimeline?: string | null }) {
  const { id = "" } = useParams();
  const { t, lang } = useI18n();
  const { api } = useSession();
  const doc = useLoad(() => api.request<DocumentView>("GET", `/documents/${id}`), [id]);
  const extraction = useLoad(() => api.request<ExtractionResponse>("GET", `/documents/${id}/extraction`), [id]);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  const reload = () => { doc.reload(); extraction.reload(); };
  // The worker reads a new document within seconds: check again every 3 s while it waits, for at most 2 minutes
  // (without a worker, as in the mock, it stays waiting and the manual-entry button is there).
  const waiting = doc.data?.status === "uploaded" || doc.data?.status === "extracting";
  useEffect(() => {
    if (!waiting) return;
    const until = Date.now() + 120_000;
    const timer = setInterval(() => (Date.now() > until ? clearInterval(timer) : reload()), 3000);
    return () => clearInterval(timer);
  }, [waiting, id]); // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (path: string) => {
    setError(null);
    try {
      await api.request("POST", path);
      reload();
    } catch (e) {
      setError(e);
    }
  };

  if (doc.loading && !doc.data) return <Loading />;
  if (!doc.data) return <ErrorNote error={doc.error} />;
  const d = doc.data;
  return (
    <>
      <div className="row">
        <h1>{t(`doc.${d.doc_type}`)} · {formatDate(d.created_at, lang)}</h1>
        <StatusChip status={d.status} />
      </div>
      <ErrorNote error={error} />
      {done && d.status === "verified" && (
        <p className="ok-note" role="status">{toTimeline ? <>{t("verify.done")} <Link to={toTimeline}>{t("verify.toTimeline")}</Link></> : t("verify.doneForPatient")}</p>
      )}
      {d.status === "uploaded" && (
        <div className="stack"><p className="notice">{t("docpage.uploaded")}</p>
          <div className="actions"><button type="button" className="btn-primary" onClick={() => act(`/documents/${id}/manual-entry`)}>{t("docpage.manual")}</button></div></div>
      )}
      {d.status === "extracting" && (
        <div className="stack"><p className="notice">{t("docpage.extracting")}</p>
          <div className="actions"><button type="button" onClick={reload}>{t("docpage.refresh")}</button></div></div>
      )}
      {d.status === "extraction_failed" && (
        <div className="stack"><p className="notice">{t("docpage.failed")}</p>
          <div className="actions">
            <button type="button" className="btn-primary" onClick={() => act(`/documents/${id}/retry-extraction`)}>{t("docpage.retry")}</button>
            <button type="button" onClick={() => act(`/documents/${id}/manual-entry`)}>{t("docpage.manual")}</button>
          </div></div>
      )}
      {d.status === "verified" && !done && <p className="ok-note">{t("docpage.verified")}</p>}
      {d.status === "rejected" && <p className="notice">{t("docpage.rejected")}</p>}
      {d.status === "needs_review" && (extraction.data?.extraction
        ? <Verify doc={d} data={extraction.data.extraction} threshold={extraction.data.threshold} onDone={() => { setDone(true); reload(); }} />
        : extraction.loading ? <Loading /> : <ErrorNote error={extraction.error} />)}
    </>
  );
}

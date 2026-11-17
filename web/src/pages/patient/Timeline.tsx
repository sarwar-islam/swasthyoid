import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router";
import type { EventType, Provenance, TimelineEvent } from "../../api/types";
import { ErrorNote, Loading, ProvenanceBadge } from "../../components/ui";
import { formatDate, formatNumber, localDigits, useI18n } from "../../i18n/i18n";
import { bn, type Key } from "../../i18n/strings";
import { useLoad, useSession } from "../../session";

type Filter = "all" | Provenance;
// the field that names an entry, first of each type in summary/build.py FIELDS; a type without one has no title line
const TITLE_KEYS = ["name_as_written", "test_name", "facility_name", "allergy_text", "value", "follow_up_date"];
const TYPES: EventType[] = ["medication", "lab_result", "visit", "prescription", "vital_reading", "diagnosis", "allergy", "follow_up"];

/** "2026-11" -> "নভেম্বর ২০২৬" / "November 2026": the month heading of a group. */
function monthLabel(ym: string, lang: "bn" | "en"): string {
  return localDigits(new Intl.DateTimeFormat(lang === "bn" ? "bn-BD" : "en-GB", { month: "long", year: "numeric", timeZone: "UTC" })
    .format(new Date(`${ym}-01T00:00:00Z`)), lang);
}

function EventCard({ event, older, docBase }: { event: TimelineEvent; older: TimelineEvent[]; docBase: string | null }) {
  const { t, lang } = useI18n();
  const field = (k: string): string => (`f.${k}` in bn ? t(`f.${k}` as Key) : k);
  const titleKey = TITLE_KEYS.find((k) => event.payload[k]);
  const title = titleKey && event.payload[titleKey];
  return (
    <article id={`event-${event.event_id}`} tabIndex={-1} className={`card event ${event.verification_status}`} aria-labelledby={`ev-${event.event_id}`}>
      <span className="tl-marker" aria-hidden="true" />
      <p className="tl-date muted">{formatDate(event.date, lang)}</p>
      <div className="row">
        <h3 id={`ev-${event.event_id}`} className="tl-heading">
          <span className="tl-category">{t(`tl.${event.event_type}` as Key)}</span>
          {/* the record's own words, as written; nothing is made up when there is none */}
          {title && <bdi className="tl-title">{title}</bdi>}
        </h3>
        <ProvenanceBadge value={event.verification_status} />
      </div>
      <dl>
        {Object.entries(event.payload).filter(([k]) => k !== titleKey).map(([k, v]) => (
          // values as written keep their own digits (owner decision 2026-11-17)
          <div key={k} style={{ display: "contents" }}><dt>{field(k)}</dt><dd><bdi>{v}</bdi></dd></div>
        ))}
      </dl>
      <div className="row">
        {event.version > 1 && <span className="muted">{t("tl.corrected", { n: formatNumber(event.version, lang) })}</span>}
        {event.source_document_id && docBase && <Link to={`${docBase}/${event.source_document_id}`}>{t("tl.source")}</Link>}
        {event.verification_status === "document_verified" && !event.source_document_id &&
          <span className="muted">{t("tl.sourceUnavailable")}</span>}
      </div>
      <p className="tl-ids muted">
        <span className="id-chip">{t("tl.eventId")} <bdi>{event.event_id}</bdi></span>
        {event.source_document_id && <span className="id-chip">{t("tl.docId")} <bdi>{event.source_document_id}</bdi></span>}
      </p>
      {older.length > 0 && (
        <details>
          <summary>{t("tl.history")}</summary>
          <ul className="list">
            {older.map((o) => (
              <li key={o.event_id} className="muted">
                {formatDate(o.recorded_at, lang)}: <bdi>{Object.values(o.payload).join(", ")}</bdi>
              </li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}

/** M4: the patient's own timeline. Corrections are new events (invariant 5): a corrected event shows its latest version, with
 * the earlier ones under "correction history". Patient-reported entries are always labelled and can be filtered on their own. */
export function Timeline() {
  const { claims } = useSession();
  return <TimelineView patientId={claims?.sub ?? ""} docBase="/patient/documents" title />;
}

/** A timeline for any portal. `docBase` null hides source links (the viewer may not see documents). The event named in the URL
 * hash (a summary citation) is scrolled to and focused. */
export function TimelineView({ patientId, docBase, title = false }: { patientId: string; docBase: string | null; title?: boolean }) {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const events = useLoad(() => api.request<TimelineEvent[]>("GET", `/patients/${patientId}/timeline`), [patientId]);
  const [filter, setFilter] = useState<Filter>("all");
  const [type, setType] = useState<"all" | EventType>("all");
  const { hash } = useLocation();
  useEffect(() => {
    const target = hash && document.getElementById(hash.slice(1));
    if (target) {
      target.scrollIntoView?.({ block: "center" });
      target.focus();
    }
  }, [hash, events.data]);

  const all = events.data ?? [];
  const superseded = new Set(all.map((e) => e.supersedes).filter(Boolean));
  const history = (e: TimelineEvent): TimelineEvent[] => {
    const chain: TimelineEvent[] = [];
    for (let prev = all.find((x) => x.event_id === e.supersedes); prev; prev = all.find((x) => x.event_id === prev!.supersedes)) chain.push(prev);
    return chain;
  };
  const current = all.filter((e) => !superseded.has(e.event_id));
  const shown = current
    .filter((e) => (filter === "all" || e.verification_status === filter) && (type === "all" || e.event_type === type))
    .sort((a, b) => b.date.localeCompare(a.date));
  const months = [...new Set(shown.map((e) => e.date.slice(0, 7)))];

  return (
    <>
      {title && <h1>{t("tl.title")}</h1>}
      <fieldset className="segmented">
        <legend className="sr-only">{t("tl.filter")}</legend>
        {(["all", "document_verified", "patient_reported"] as const).map((f) => (
          <label key={f}>
            <input type="radio" name="provenance" value={f} checked={filter === f} onChange={() => setFilter(f)} />
            {t(f === "all" ? "tl.all" : f === "document_verified" ? "tl.verified" : "tl.reported")}
          </label>
        ))}
      </fieldset>
      <fieldset className="segmented chips">
        <legend className="sr-only">{t("tl.type")}</legend>
        {(["all", ...TYPES] as const).map((f) => (
          <label key={f}>
            <input type="radio" name="event-type" value={f} checked={type === f} onChange={() => setType(f)} />
            {t(f === "all" ? "tl.all" : `tl.${f}` as Key)}
          </label>
        ))}
      </fieldset>
      {events.loading ? <Loading lines={3} /> : <ErrorNote error={events.error} onRetry={events.reload} />}
      {/* empty never means healthy: it only says no records are here yet */}
      {!events.loading && !events.error && current.length === 0 && <p className="muted">{t("tl.empty")}</p>}
      {!events.loading && current.length > 0 && shown.length === 0 && (
        <p className="muted">{t("tl.noMatch")} <button type="button" className="btn-link" onClick={() => { setFilter("all"); setType("all"); }}>
          {t("tl.clearFilters")}</button></p>
      )}
      {months.map((m) => (
        <section key={m} className="tl-month" aria-labelledby={`m-${m}`}>
          <h2 id={`m-${m}`} className="tl-month-title">{monthLabel(m, lang)}</h2>
          <div className="tl-rail">
            {shown.filter((e) => e.date.startsWith(m)).map((e) => <EventCard key={e.event_id} event={e} older={history(e)} docBase={docBase} />)}
          </div>
        </section>
      ))}
    </>
  );
}

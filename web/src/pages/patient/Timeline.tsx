import { useState } from "react";
import { Link } from "react-router";
import type { Provenance, TimelineEvent } from "../../api/types";
import { ErrorNote, Loading, ProvenanceBadge } from "../../components/ui";
import { formatDate, formatNumber, localDigits, useI18n } from "../../i18n/i18n";
import { bn, type Key } from "../../i18n/strings";
import { useLoad, useSession } from "../../session";

type Filter = "all" | Provenance;

function EventCard({ event, older }: { event: TimelineEvent; older: TimelineEvent[] }) {
  const { t, lang } = useI18n();
  const field = (k: string): string => (`f.${k}` in bn ? t(`f.${k}` as Key) : k);
  return (
    <article className={`card event ${event.verification_status}`} aria-labelledby={`ev-${event.event_id}`}>
      <div className="row">
        <h2 id={`ev-${event.event_id}`} style={{ fontSize: "1.1rem", margin: 0 }}>
          {t(`tl.${event.event_type}` as Key)} · {formatDate(event.date, lang)}
        </h2>
        <ProvenanceBadge value={event.verification_status} />
      </div>
      <dl>
        {Object.entries(event.payload).map(([k, v]) => (
          <div key={k} style={{ display: "contents" }}><dt>{field(k)}</dt><dd>{localDigits(v, lang)}</dd></div>
        ))}
      </dl>
      <div className="row">
        {event.version > 1 && <span className="muted">{t("tl.corrected", { n: formatNumber(event.version, lang) })}</span>}
        {event.source_document_id && <Link to={`/patient/documents/${event.source_document_id}`}>{t("tl.source")}</Link>}
      </div>
      {older.length > 0 && (
        <details>
          <summary>{t("tl.history")}</summary>
          <ul className="list">
            {older.map((o) => (
              <li key={o.event_id} className="muted">
                {formatDate(o.recorded_at, lang)}: {Object.values(o.payload).map((v) => localDigits(v, lang)).join(", ")}
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
  const { t } = useI18n();
  const { api, claims } = useSession();
  const events = useLoad(() => api.request<TimelineEvent[]>("GET", `/patients/${claims?.sub}/timeline`), [claims?.sub]);
  const [filter, setFilter] = useState<Filter>("all");

  const all = events.data ?? [];
  const superseded = new Set(all.map((e) => e.supersedes).filter(Boolean));
  const history = (e: TimelineEvent): TimelineEvent[] => {
    const chain: TimelineEvent[] = [];
    for (let prev = all.find((x) => x.event_id === e.supersedes); prev; prev = all.find((x) => x.event_id === prev!.supersedes)) chain.push(prev);
    return chain;
  };
  const shown = all
    .filter((e) => !superseded.has(e.event_id) && (filter === "all" || e.verification_status === filter))
    .sort((a, b) => b.date.localeCompare(a.date));

  return (
    <>
      <h1>{t("tl.title")}</h1>
      <fieldset className="segmented">
        <legend className="sr-only">{t("tl.filter")}</legend>
        {(["all", "document_verified", "patient_reported"] as const).map((f) => (
          <label key={f}>
            <input type="radio" name="provenance" value={f} checked={filter === f} onChange={() => setFilter(f)} />
            {t(f === "all" ? "tl.all" : f === "document_verified" ? "tl.verified" : "tl.reported")}
          </label>
        ))}
      </fieldset>
      {events.loading ? <Loading /> : <ErrorNote error={events.error} />}
      {!events.loading && shown.length === 0 && <p className="muted">{t("tl.empty")}</p>}
      <div className="list">{shown.map((e) => <EventCard key={e.event_id} event={e} older={history(e)} />)}</div>
    </>
  );
}

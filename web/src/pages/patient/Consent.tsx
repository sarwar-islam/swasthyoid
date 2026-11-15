import { Ban, CheckCircle2, ShieldOff } from "lucide-react";
import { useState } from "react";
import type { AccessEntry, Consent } from "../../api/types";
import { ConfirmDialog, ErrorNote, Loading, Section } from "../../components/ui";
import { formatDate, formatNumber, localDigits, useI18n } from "../../i18n/i18n";
import type { Key } from "../../i18n/strings";
import { useLoad, useSession } from "../../session";

const CLOSED = ["expired", "revoked", "declined"];

/** M1/C1 Consent Center: who can see the record, one-tap revoke (confirmed), waiting requests, caregiver approvals, the
 * cloud-AI opt-in (not available: FRD question 5 is open) and the access history from the audit log. */
export function ConsentCenter() {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const consents = useLoad(() => api.request<Consent[]>("GET", "/consents"), []);
  const history = useLoad(() => api.request<AccessEntry[]>("GET", "/me/access-history"), []);
  const [revoking, setRevoking] = useState<Consent | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<string | null>(null);

  const what = (c: Consent) => c.allowed_categories.map((k) => t(`cat.${k}` as Key)).join(", ");
  const name = (c: Consent) => c.grantee_name ?? t("history.someone");
  const all = consents.data ?? [];
  const doctors = all.filter((c) => c.purpose === "TIMELINE" && c.status === "active");
  const pendingDoctors = all.filter((c) => c.purpose === "TIMELINE" && c.status === "pending");
  const caregivers = all.filter((c) => c.purpose === "CAREGIVER" && (c.status === "pending" || c.status === "active"));
  const past = all.filter((c) => CLOSED.includes(c.status));

  async function act(path: string, message: string | null = null) {
    setError(null);
    setDone(null);
    try {
      await api.request("POST", path);
      setDone(message);
      consents.reload();
      history.reload();
    } catch (e) {
      setError(e);
    }
  }

  const revokeButton = (c: Consent) => (
    <button type="button" className="btn-danger" onClick={() => setRevoking(c)}><ShieldOff size={18} aria-hidden="true" />{t("consent.revoke")}</button>
  );

  return (
    <>
      <h1>{t("consent.title")}</h1>
      <ErrorNote error={error ?? consents.error} />
      {done && <p className="ok-note" role="status">{done}</p>}
      {consents.loading && <Loading />}

      <Section id="doctors" title={t("consent.doctors")}>
        {!consents.loading && doctors.length === 0 && <p className="muted">{t("consent.noDoctors")}</p>}
        <ul className="list">
          {doctors.map((c) => (
            <li key={c.id} className="card">
              <p><strong>{name(c)}</strong></p>
              <p className="muted">{t("consent.sees", { what: what(c) })}</p>
              {c.expires_at && <p className="muted">{t("consent.expires", { date: formatDate(c.expires_at, lang) })}</p>}
              {revokeButton(c)}
            </li>
          ))}
        </ul>
      </Section>

      {pendingDoctors.length > 0 && (
        <Section id="pending" title={t("consent.pending")}>
          <ul className="list">
            {pendingDoctors.map((c) => <li key={c.id} className="card notice">{t("consent.pendingDoctor", { name: name(c) })}</li>)}
          </ul>
        </Section>
      )}

      {caregivers.length > 0 && (
        <Section id="caregivers" title={t("consent.caregivers")}>
          <ul className="list">
            {caregivers.map((c) => (
              <li key={c.id} className="card">
                <p>{t("consent.caregiverAsk", { name: name(c), tail: localDigits(c.grantee_phone_tail ?? "", lang),
                  days: formatNumber(c.requested_days ?? 0, lang), what: what(c) })}</p>
                {c.status === "pending" ? (
                  <div className="actions">
                    <button type="button" className="btn-primary" onClick={() => act(`/caregiver-authorizations/${c.id}/approve`)}>
                      <CheckCircle2 size={18} aria-hidden="true" />{t("consent.approve")}
                    </button>
                    <button type="button" onClick={() => act(`/caregiver-authorizations/${c.id}/decline`)}><Ban size={18} aria-hidden="true" />{t("consent.decline")}</button>
                  </div>
                ) : (
                  <>
                    {c.expires_at && <p className="muted">{t("consent.expires", { date: formatDate(c.expires_at, lang) })}</p>}
                    {revokeButton(c)}
                  </>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section id="cloud" title={t("cloud.title")}>
        <label className="switch">
          <input type="checkbox" role="switch" checked={false} disabled aria-describedby="cloud-note" onChange={() => undefined} />
          {t("cloud.title")}
        </label>
        <p id="cloud-note" className="muted">{t("cloud.note")}</p>
      </Section>

      <Section id="history" title={t("history.title")}>
        {history.loading ? <Loading /> : <ErrorNote error={history.error} />}
        {history.data?.length === 0 && <p className="muted">{t("history.empty")}</p>}
        <ul className="list">
          {history.data?.map((h, i) => (
            <li key={`${h.at}-${i}`} className="card row">
              <span><strong>{h.actor_name ?? t("history.someone")}</strong><br /><span className="muted">{formatDate(h.at, lang)}</span></span>
              <span className={`chip ${h.result === "allow" ? "chip-verified" : "chip-extraction_failed"}`}>
                {h.result === "allow" ? <CheckCircle2 size={14} aria-hidden="true" /> : <Ban size={14} aria-hidden="true" />}
                {t(h.result === "allow" ? "history.allow" : "history.deny")}
              </span>
            </li>
          ))}
        </ul>
      </Section>

      {past.length > 0 && (
        <details className="section">
          <summary>{t("consent.past")}</summary>
          <ul className="list">
            {past.map((c) => <li key={c.id} className="muted">{name(c)} · {t(`consent.status.${c.status}` as Key)}</li>)}
          </ul>
        </details>
      )}

      <ConfirmDialog open={!!revoking} title={revoking ? t("consent.revokeAsk", { name: name(revoking) }) : ""}
                     confirmLabel={t("consent.revokeYes")} onCancel={() => setRevoking(null)}
                     onConfirm={() => { const c = revoking!; setRevoking(null); act(`/consents/${c.id}/revoke`, t("consent.revoked")); }} />
    </>
  );
}

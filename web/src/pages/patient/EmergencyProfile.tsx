import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import type { EmergencyField, EmergencyProfile as Profile } from "../../api/types";
import { ErrorNote, Loading, Section } from "../../components/ui";
import { localDigits, toAsciiDigits, useI18n } from "../../i18n/i18n";
import type { Key } from "../../i18n/strings";
import { useLoad, useSession } from "../../session";

const FIELDS: EmergencyField[] = ["blood_group", "allergies", "active_medications", "conditions", "emergency_contacts"];

/** M10 (feature-flagged): the patient turns the minimal emergency card on and picks which verified fields it shows. Only
 * verified data is offered; a field with nothing verified cannot be chosen. Off until the patient turns it on. */
export function EmergencyProfile() {
  const { t, lang } = useI18n();
  const { api } = useSession();
  const loaded = useLoad(() => api.request<Profile>("GET", "/me/emergency-profile"), []);
  const [draft, setDraft] = useState<Profile | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { if (loaded.data) setDraft(loaded.data); }, [loaded.data]);

  if (!draft) return loaded.error ? <ErrorNote error={loaded.error} /> : <Loading />;

  const values = (f: EmergencyField): string[] => {
    const a = draft.available;
    if (f === "blood_group") return a.blood_group ? [a.blood_group] : [];
    if (f === "emergency_contacts") return draft.contacts.filter((c) => c.name.trim()).map((c) => `${c.name} · ${localDigits(c.phone, lang)}`);
    return a[f];
  };
  const toggle = (f: EmergencyField) => setDraft({ ...draft, fields: draft.fields.includes(f) ? draft.fields.filter((x) => x !== f) : [...draft.fields, f] });
  const setContact = (i: number, key: "name" | "phone", v: string) =>
    setDraft({ ...draft, contacts: draft.contacts.map((c, j) => (j === i ? { ...c, [key]: v } : c)) });

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaved(false);
    try {
      const contacts = draft.contacts.map((c) => ({ name: c.name.trim(), phone: toAsciiDigits(c.phone.trim()) }));
      setDraft(await api.request<Profile>("PUT", "/me/emergency-profile", { body: { enabled: draft.enabled, fields: draft.fields, contacts } }));
      setSaved(true);
    } catch (err) {
      setError(err);
    }
  };

  return (
    <>
      <h1>{t("profile.title")}</h1>
      <p className="notice">{t("profile.intro")}</p>
      <form onSubmit={save} className="card section" noValidate>
        <label className="switch">
          <input type="checkbox" role="switch" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />
          {t("profile.enable")}
        </label>
        <fieldset className="section">
          <legend>{t("profile.fields")}</legend>
          {FIELDS.map((f) => {
            const offered = f === "emergency_contacts" || values(f).length > 0;
            return (
              <label key={f} className="check">
                <input type="checkbox" checked={draft.fields.includes(f)} disabled={!offered} onChange={() => toggle(f)} />
                <span>{t(`profile.f.${f}` as Key)}{!offered && <span className="muted"> · {t("profile.noVerified")}</span>}</span>
              </label>
            );
          })}
        </fieldset>
        <fieldset>
          <legend>{t("profile.contacts")}</legend>
          {draft.contacts.map((c, i) => (
            <div key={i} className="bp-pair">
              <div className="field"><label htmlFor={`cn-${i}`}>{t("profile.contactName")}</label>
                <input id={`cn-${i}`} value={c.name} onChange={(e) => setContact(i, "name", e.target.value)} /></div>
              <div className="field"><label htmlFor={`cp-${i}`}>{t("profile.contactPhone")}</label>
                <input id={`cp-${i}`} type="tel" inputMode="tel" value={c.phone} onChange={(e) => setContact(i, "phone", e.target.value)} /></div>
              <button type="button" onClick={() => setDraft({ ...draft, contacts: draft.contacts.filter((_, j) => j !== i) })}>
                <Trash2 size={18} aria-hidden="true" />{t("profile.removeContact")}
              </button>
            </div>
          ))}
          <button type="button" onClick={() => setDraft({ ...draft, contacts: [...draft.contacts, { name: "", phone: "" }] })}>
            <Plus size={18} aria-hidden="true" />{t("profile.addContact")}
          </button>
        </fieldset>
        <ErrorNote error={error} />
        {saved && <p className="ok-note" role="status">{t("profile.saved")}</p>}
        <button type="submit" className="btn-primary">{t("profile.save")}</button>
      </form>

      <Section id="preview" title={t("profile.preview")}>
        {!draft.enabled ? <p className="muted">{t("profile.off")}</p> : (
          <dl className="card event">
            {draft.fields.map((f) => (
              <div key={f} style={{ display: "contents" }}><dt>{t(`profile.f.${f}` as Key)}</dt><dd>{values(f).join(", ") || "—"}</dd></div>
            ))}
          </dl>
        )}
      </Section>
    </>
  );
}

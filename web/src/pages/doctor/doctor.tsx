import { AlertTriangle, BadgeCheck, ShieldAlert } from "lucide-react";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Link, Outlet } from "react-router";
import type { DoctorConsent, StaffMe } from "../../api/types";
import { localDigits, useI18n } from "../../i18n/i18n";
import { useLoad, useSession } from "../../session";

/** Consents this doctor confirmed in this session, in memory only (like the token): a reload forgets them. The server stays the
 * judge of every read; this list only remembers which patients to show. */
const OpenPatients = createContext<{ open: DoctorConsent[]; remember: (c: DoctorConsent) => void } | null>(null);

export function useOpenPatients() {
  const value = useContext(OpenPatients);
  if (!value) throw new Error("useOpenPatients needs the doctor portal");
  return value;
}

/** Seconds left until `iso` (0 once passed), ticking every second. */
export function useSecondsLeft(iso: string | null): number {
  const left = () => (iso ? Math.max(0, Math.floor((Date.parse(iso) - Date.now()) / 1000)) : 0);
  const [seconds, setSeconds] = useState(left);
  useEffect(() => {
    setSeconds(left());
    const timer = setInterval(() => setSeconds(left()), 1000);
    return () => clearInterval(timer);
  }, [iso]); // `left` reads only `iso`
  return seconds;
}

export function clock(seconds: number, lang: "bn" | "en"): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return localDigits(`${pad(Math.floor(seconds / 3600))}:${pad(Math.floor((seconds % 3600) / 60))}:${pad(seconds % 60)}`, lang);
}

/** The signed-in staff member's own status (GET /me for staff: APPROVED, not built; mocked). */
export function useMe() {
  const { api } = useSession();
  return useLoad(() => api.request<StaffMe>("GET", "/me"), []);
}

/** Around every doctor page: the status banner when the doctor is not verified, and the session's open patients. */
export function DoctorFrame() {
  const { t } = useI18n();
  const me = useMe();
  const [open, setOpen] = useState<DoctorConsent[]>([]);
  const remember = (c: DoctorConsent) => setOpen((list) => [c, ...list.filter((x) => x.patient_id !== c.patient_id)]);
  const status = me.data?.status;
  const banner: ReactNode = !me.data || status === "verified" ? null : (
    <div className={`status-banner ${status}`} role="status">
      {status === "suspended" ? <ShieldAlert size={20} aria-hidden="true" /> : <AlertTriangle size={20} aria-hidden="true" />}
      <span>{t(status === "suspended" ? "dstatus.suspended" : me.data.credential ? "dstatus.pending" : "dstatus.none")}</span>
      <Link to="/doctor/credentials">{t("dstatus.toCredentials")}</Link>
    </div>
  );
  return (
    <OpenPatients.Provider value={{ open, remember }}>
      {banner}
      <Outlet />
    </OpenPatients.Provider>
  );
}

export function StatusChipStaff({ status }: { status: StaffMe["status"] }) {
  const { t } = useI18n();
  return <span className={`chip ${status === "verified" ? "chip-verified" : "chip-needs_review"}`}>
    {status === "verified" && <BadgeCheck size={14} aria-hidden="true" />}{t(`dstatus.label.${status}`)}</span>;
}

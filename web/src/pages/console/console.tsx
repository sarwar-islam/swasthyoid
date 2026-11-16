import { useState, type ReactNode } from "react";
import { Navigate } from "react-router";
import { useSession } from "../../session";
import { STAFF_NAV, visible } from "../../shells/Shells";

/** The console's first page for this role (the rule registry for a reviewer, credential approvals for an admin). */
export function ConsoleIndex() {
  const { claims } = useSession();
  const first = visible(STAFF_NAV.console.items, claims?.role)[0];
  return first ? <Navigate to={first.to} replace /> : null;
}

/** A console page for one role only; the other role is sent to its own first page. The server refuses it anyway. */
export function OnlyRole({ role, children }: { role: "clinical_reviewer" | "admin"; children: ReactNode }) {
  const { claims } = useSession();
  return claims?.role === role ? <>{children}</> : <Navigate to="/console" replace />;
}

/** One write at a time: `run` clears the last error, keeps `busy` while it works, and then calls `done`. */
export function useAction(done: () => void) {
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function run(action: () => Promise<unknown>): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      await action();
      done();
      return true;
    } catch (e) {
      setError(e);
      return false;
    } finally {
      setBusy(false);
    }
  }
  return { error, busy, run, setError };
}

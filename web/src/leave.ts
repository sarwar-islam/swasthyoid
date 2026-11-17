import { useEffect } from "react";

// UX-2: what signing out would lose, read when the sign-out button is pressed. A page adds its reason while it holds one.
const reasons = new Set<"assist">();

export function useLeaveWarning(reason: "assist", active: boolean) {
  useEffect(() => {
    if (!active) return;
    reasons.add(reason);
    return () => { reasons.delete(reason); };
  }, [reason, active]);
}

export const leaveReasons = () => [...reasons];

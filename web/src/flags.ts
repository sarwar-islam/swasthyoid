// M10 Emergency Access is conditional (FRD M10: only with the clinical reviewer's and the lawyer's approval). Off unless the build
// sets VITE_FEATURE_EMERGENCY_ACCESS=1; when off, no emergency-profile, break-glass or review screen is reachable. Read on each
// use (a getter), so a test can switch it with vi.stubEnv.
export const flags = {
  get emergencyAccess() {
    return import.meta.env.VITE_FEATURE_EMERGENCY_ACCESS === "1";
  },
};

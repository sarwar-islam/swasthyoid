import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Navigate, Outlet, useLocation } from "react-router";
import { CSRF_HEADER, createClient, type Client, type Transport } from "./api/client";
import type { TokenPair } from "./api/types";
import { Loading } from "./components/ui";

export interface Claims {
  sub: string;
  role: string;
}

/** The token's claims for routing and display only. The server checks every request; nothing here is trusted. */
export function readClaims(token: string | null): Claims | null {
  try {
    const part = token?.split(".")[1];
    if (!part) return null;
    const json = JSON.parse(atob(part.replace(/-/g, "+").replace(/_/g, "/")));
    return typeof json.sub === "string" && typeof json.role === "string" ? { sub: json.sub, role: json.role } : null;
  } catch {
    return null;
  }
}

export type Account = "patient" | "staff";
const accountOf = (role: string): Account => (role === "patient" ? "patient" : "staff");

// W2 owner decision (a), 2026-11-17, the same values as the server (identity/sessions.py): with no input for this long the
// screen signs out, so an unattended device stops showing the record. The server also ends the session on its own clock.
export const IDLE_MS: Record<Account, number> = { patient: 30 * 60_000, staff: 15 * 60_000 };

// Not secret (the refresh cookie is): the device id ties that cookie to this browser, so every tab shares it.
const DEVICE_KEY = "swasthyoid.device";
// Set by sign-out, cleared by sign-in: a sign-out that could not reach the server leaves the cookie behind, and this keeps a
// reload from bringing that session back.
const signedOutKey = (account: Account) => `swasthyoid.signedOut.${account}`;

/** Read a key, after setting it (a string) or removing it (null). Storage may be blocked: then nothing is kept. */
function store(key: string, value?: string | null): string | null {
  try {
    if (value === null) localStorage.removeItem(key);
    else if (value !== undefined) localStorage.setItem(key, value);
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

interface Session {
  api: Client;
  claims: Claims | null;
  deviceId: string;
  signIn: (tokens: TokenPair) => void;
  signOut: () => Promise<void>;
  signOutEverywhere: () => Promise<void>;
  expired: boolean; // the session ended (idle, signed out elsewhere, suspended) and could not be renewed
  /** After a reload: a new access token from the refresh cookie, tried once per kind of account. */
  restore: (account: Account) => void;
  restored: Record<Account, boolean>; // restore() for this account has finished, whatever the result
}

const SessionContext = createContext<Session | null>(null);

/** W2 (owner decision S8): the 15-minute access token lives in memory only; the refresh token is an HttpOnly cookie the page
 * cannot read. A refused request renews the access token once and is sent again; a reload renews it from the cookie. */
export function SessionProvider({ transport, initialToken = null, children }:
  { transport: Transport; initialToken?: string | null; children: ReactNode }) {
  const tokenRef = useRef<string | null>(initialToken);
  const [token, setToken] = useState<string | null>(initialToken);
  const [expired, setExpired] = useState(false);
  const [restored, setRestored] = useState<Record<Account, boolean>>({ patient: false, staff: false });
  const deviceId = useMemo(() => store(DEVICE_KEY) ?? store(DEVICE_KEY, crypto.randomUUID()) ?? crypto.randomUUID(), []);
  const setAccess = useCallback((access: string | null) => {
    tokenRef.current = access;
    setToken(access);
  }, []);
  const settle = useCallback((account: Account) => setRestored((r) => (r[account] ? r : { ...r, [account]: true })), []);

  // One renewal at a time, in this tab (`pending`) and across tabs (navigator.locks): a refresh token works once, and two tabs
  // sending the same one would look like a stolen token and end the session.
  const pending = useRef<Promise<boolean> | null>(null);
  const renew = useCallback((account: Account): Promise<boolean> => {
    if (store(signedOutKey(account)) === "1") return Promise.resolve(false);
    const run = async () => {
      const response = await transport({ method: "POST", path: "/auth/refresh", body: { device_id: deviceId, account },
                                         headers: { Accept: "application/json", [CSRF_HEADER]: "1" } });
      const access = response.status === 200 ? (response.body as Partial<TokenPair> | null)?.access_token : undefined;
      const role = readClaims(access ?? null)?.role;
      if (!access || !role || accountOf(role) !== account) return false;
      setAccess(access);
      return true;
    };
    pending.current ??= (typeof navigator !== "undefined" && navigator.locks
      ? navigator.locks.request(`swasthyoid-refresh-${account}`, run) : run())
      .catch(() => false)
      .finally(() => { pending.current = null; });
    return pending.current;
  }, [transport, deviceId, setAccess]);

  const end = useCallback((account: Account | null) => {
    setAccess(null);
    setExpired(true);
    if (account) settle(account);
  }, [setAccess, settle]);

  // a 401 on a signed-in request: renew once and send it again; if that fails the session is over, and RequireRole sends the
  // user to sign in again with a note saying why
  const api = useMemo(() => createClient(async (request) => {
    const response = await transport(request);
    if (response.status !== 401 || !request.headers.Authorization) return response;
    const role = readClaims(tokenRef.current)?.role;
    if (role && await renew(accountOf(role)) && tokenRef.current) {
      return transport({ ...request, headers: { ...request.headers, Authorization: `Bearer ${tokenRef.current}` } });
    }
    end(role ? accountOf(role) : null);
    return response;
  }, () => tokenRef.current), [transport, renew, end]);

  const restore = useCallback((account: Account) => {
    if (restored[account] || tokenRef.current) return;
    renew(account).finally(() => settle(account));
  }, [restored, renew, settle]);

  const signIn = useCallback((tokens: TokenPair) => {
    const role = readClaims(tokens.access_token)?.role;
    if (role) store(signedOutKey(accountOf(role)), null);
    setAccess(tokens.access_token);
    setExpired(false);
  }, [setAccess]);

  // the idle timeout on screen: no pointer, key, touch or scroll input for IDLE_MS
  const role = readClaims(token)?.role;
  useEffect(() => {
    if (!role) return;
    let timer = 0;
    const reset = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => end(accountOf(role)), IDLE_MS[accountOf(role)]);
    };
    const events = ["pointerdown", "keydown", "scroll", "touchstart"] as const;
    events.forEach((e) => window.addEventListener(e, reset, { passive: true, capture: true }));
    reset();
    return () => {
      window.clearTimeout(timer);
      events.forEach((e) => window.removeEventListener(e, reset, { capture: true }));
    };
  }, [role, end]);

  // W2: the server ends the session first (a token that was copied stops working at once) and clears the refresh cookie; the
  // token is dropped here even if that call fails, so signing out never leaves the user signed in on this screen
  const leave = useCallback(async (path: "/auth/logout" | "/auth/logout-all") => {
    const role = readClaims(tokenRef.current)?.role;
    if (role) {
      store(signedOutKey(accountOf(role)), "1");
      settle(accountOf(role));
    }
    try {
      if (tokenRef.current) await api.request("POST", path);
    } catch {
      // offline or already ended: the token still goes, and it runs out within 15 minutes
    }
    setAccess(null);
  }, [api, setAccess, settle]);
  const signOut = useCallback(() => leave("/auth/logout"), [leave]);
  const signOutEverywhere = useCallback(() => leave("/auth/logout-all"), [leave]);
  const value = useMemo(() => ({ api, claims: readClaims(token), deviceId, signIn, signOut, signOutEverywhere, expired, restore,
                                 restored }),
    [api, token, deviceId, signIn, signOut, signOutEverywhere, expired, restore, restored]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession needs a SessionProvider");
  return value;
}

/** Child routes only for a signed-in user of this role (or one of these roles); everyone else goes to `login`, which returns to
 * the page asked for (a QR link opened before signing in). After a reload it first tries the refresh cookie. */
export function RequireRole({ role, login }: { role: string | string[]; login: string }) {
  const { claims, restore, restored } = useSession();
  const { pathname } = useLocation();
  const roles = [role].flat();
  const account = accountOf(roles[0]);
  useEffect(() => {
    if (!claims) restore(account);
  }, [claims, account, restore]);
  if (claims && roles.includes(claims.role)) return <Outlet />;
  if (!claims && !restored[account]) return <Loading />;
  return <Navigate to={login} replace state={{ from: pathname }} />;
}

/** Load data on mount and when `deps` change. `reload()` runs the load again. */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[]) {
  const [state, setState] = useState<{ data?: T; error?: unknown; loading: boolean }>({ loading: true });
  const [round, setRound] = useState(0);
  useEffect(() => {
    let live = true;
    setState((s) => ({ ...s, loading: true }));
    load().then((data) => live && setState({ data, loading: false }), (error) => live && setState({ error, loading: false }));
    return () => {
      live = false;
    };
  }, [...deps, round]); // `load` is a new closure every render; `deps` says when it really changed
  return { ...state, reload: () => setRound((n) => n + 1) };
}

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Navigate, Outlet, useLocation } from "react-router";
import { createClient, type Client, type Transport } from "./api/client";
import type { TokenPair } from "./api/types";

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

interface Session {
  api: Client;
  claims: Claims | null;
  deviceId: string;
  signIn: (tokens: TokenPair) => void;
  signOut: () => void;
  expired: boolean; // the server refused the token (it expired after 15 minutes, or the account was suspended)
}

const SessionContext = createContext<Session | null>(null);

/** Tokens live in memory only (never in browser storage): reloading the page signs the user out. */
export function SessionProvider({ transport, initialToken = null, children }:
  { transport: Transport; initialToken?: string | null; children: ReactNode }) {
  const tokenRef = useRef<string | null>(initialToken);
  const [token, setToken] = useState<string | null>(initialToken);
  const [expired, setExpired] = useState(false);
  const deviceId = useMemo(() => crypto.randomUUID(), []); // one per tab session
  // a 401 on a signed-in request means the token is no longer accepted: sign out, so RequireRole sends the user to sign in
  // again (the web does not refresh tokens; docs/ROUTES.md)
  const api = useMemo(() => createClient(async (request) => {
    const response = await transport(request);
    if (response.status === 401 && request.headers.Authorization) {
      tokenRef.current = null;
      setToken(null);
      setExpired(true);
    }
    return response;
  }, () => tokenRef.current), [transport]);
  const signIn = useCallback((tokens: TokenPair) => {
    tokenRef.current = tokens.access_token;
    setToken(tokens.access_token);
    setExpired(false);
  }, []);
  const signOut = useCallback(() => {
    tokenRef.current = null;
    setToken(null);
  }, []);
  const value = useMemo(() => ({ api, claims: readClaims(token), deviceId, signIn, signOut, expired }),
    [api, token, deviceId, signIn, signOut, expired]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession needs a SessionProvider");
  return value;
}

/** Child routes only for a signed-in user of this role (or one of these roles); everyone else goes to `login`, which returns to
 * the page asked for (a QR link opened before signing in). */
export function RequireRole({ role, login }: { role: string | string[]; login: string }) {
  const { claims } = useSession();
  const { pathname } = useLocation();
  return claims && [role].flat().includes(claims.role) ? <Outlet /> : <Navigate to={login} replace state={{ from: pathname }} />;
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

/**
 * Session plumbing: `<SessionProvider>`, `useSession()`, and helpers that
 * talk to the backend's /api/v1/me, /auth/google, /auth/logout endpoints.
 *
 * The provider loads /me once on mount so protected routes can decide
 * what to render synchronously from `useSession().status`. All mutations
 * (login, logout) flow through the context so every page sees fresh
 * state immediately. The actual HTTP calls live in `@time2leave/shared`
 * so the mobile app can re-use the same plumbing with its bearer-token
 * transport.
 */
import {
    createContext,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useRef,
    useState,
    type ReactNode,
} from "react";

import {
    deleteAccount as sharedDeleteAccount,
    fetchAuthConfig as sharedFetchAuthConfig,
    fetchMe as sharedFetchMe,
    loginDev as sharedLoginDev,
    loginWithGoogleCredential as sharedLoginWithGoogleCredential,
    logout as sharedLogout,
    type AuthConfig,
    type SessionUser,
} from "@time2leave/shared";

import { isApiError } from "~/lib/api";
import { apiFetch } from "~/lib/api";
import { API } from "~/constants/path";

export type { AuthConfig, SessionUser };
export type SessionStatus = "loading" | "authenticated" | "anonymous";

type SessionState = {
    status: SessionStatus;
    user: SessionUser | null;
    authConfig: AuthConfig | null;
    refresh: () => Promise<void>;
    loginWithGoogleCredential: (credential: string) => Promise<SessionUser>;
    loginDev: (email: string, name?: string) => Promise<SessionUser>;
    logout: () => Promise<void>;
    /**
     * Permanently delete the signed-in user's account on the backend
     * (DELETE /api/v1/me) and mirror the local state change `logout`
     * would do. Errors are *re-thrown* (unlike `logout`, which swallows
     * them) so the calling Settings page can surface "we couldn't
     * delete your account, try again" instead of pretending to succeed
     * while their data lives on. Required by Apple App Review
     * Guideline 5.1.1(v); see also `apps/mobile/app/trips/settings.tsx`.
     */
    deleteAccount: () => Promise<void>;
};

const SessionContext = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<SessionUser | null>(null);
    const [status, setStatus] = useState<SessionStatus>("loading");
    const [authConfig, setAuthConfig] = useState<AuthConfig | null>(null);
    const didInitialLoad = useRef(false);

    const refresh = useCallback(async () => {
        try {
            const me = await sharedFetchMe(apiFetch, API);
            setUser(me);
            setStatus(me ? "authenticated" : "anonymous");
        } catch (err) {
            if (isApiError(err) && err.status === 401) {
                setUser(null);
                setStatus("anonymous");
                return;
            }
            // Network or 500: treat as anonymous but keep status resolved so
            // protected routes don't hang in "loading" forever.
            setUser(null);
            setStatus("anonymous");
        }
    }, []);

    useEffect(() => {
        if (didInitialLoad.current) return;
        didInitialLoad.current = true;
        void (async () => {
            const [config] = await Promise.all([
                sharedFetchAuthConfig(apiFetch, API),
            ]);
            setAuthConfig(config);
            await refresh();
        })();
    }, [refresh]);

    const loginWithGoogleCredential = useCallback(
        async (credential: string) => {
            const authed = await sharedLoginWithGoogleCredential(
                apiFetch,
                API,
                credential,
            );
            setUser(authed);
            setStatus("authenticated");
            return authed;
        },
        [],
    );

    const loginDev = useCallback(async (email: string, name?: string) => {
        const authed = await sharedLoginDev(apiFetch, API, email, name);
        setUser(authed);
        setStatus("authenticated");
        return authed;
    }, []);

    const logout = useCallback(async () => {
        await sharedLogout(apiFetch, API);
        setUser(null);
        setStatus("anonymous");
    }, []);

    const deleteAccount = useCallback(async () => {
        // Intentionally NOT best-effort. If the DELETE fails (e.g.
        // 401 because the cookie expired, 500 from a backend hiccup),
        // we re-throw so the Settings page renders an error banner
        // and the user can retry. Local state is only cleared on
        // success — leaving a half-deleted local view while the
        // backend still has all the data would be worse than the
        // current "nothing happened" state.
        await sharedDeleteAccount(apiFetch, API);
        setUser(null);
        setStatus("anonymous");
    }, []);

    const value = useMemo<SessionState>(
        () => ({
            status,
            user,
            authConfig,
            refresh,
            loginWithGoogleCredential,
            loginDev,
            logout,
            deleteAccount,
        }),
        [
            status,
            user,
            authConfig,
            refresh,
            loginWithGoogleCredential,
            loginDev,
            logout,
            deleteAccount,
        ],
    );

    return (
        <SessionContext.Provider value={value}>
            {children}
        </SessionContext.Provider>
    );
}

export function useSession(): SessionState {
    const ctx = useContext(SessionContext);
    if (ctx === null) {
        throw new Error("useSession must be used inside <SessionProvider>");
    }
    return ctx;
}

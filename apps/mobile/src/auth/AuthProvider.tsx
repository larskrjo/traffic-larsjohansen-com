/**
 * Mobile auth context.
 *
 * Mirrors the web app's `SessionProvider` but persists the bearer JWT
 * via `expo-secure-store` (Keychain on iOS, Keystore on Android) and
 * reads/writes the in-memory copy attached to every API request by
 * `apiFetch`'s `prepareInit` hook.
 *
 * The provider:
 *   1. On mount, hydrates the stored token (if any), pings `/me`, and
 *      transitions `status` from `loading` → `authenticated` /
 *      `anonymous`.
 *   2. Exposes `signInWithGoogle(idToken)` and `signInDev(email)` —
 *      both wrap the shared API helpers, persist the returned
 *      `session_token`, and flip `status` synchronously.
 *   3. Exposes `signOut()` which clears the stored token and posts to
 *      `/auth/logout` (best-effort).
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
    isApiError,
    loginDev as sharedLoginDev,
    loginWithAppleCredential as sharedLoginWithAppleCredential,
    loginWithGoogleCredential as sharedLoginWithGoogleCredential,
    logout as sharedLogout,
    type AuthConfig,
    type AuthedUserResponse,
    type SessionUser,
} from "@time2leave/shared";

import { apiFetch, getApi } from "~/api/client";
import {
    clearStoredSession,
    readStoredSession,
    setCurrentToken,
    writeStoredSession,
} from "~/api/storage";

export type AuthStatus = "loading" | "authenticated" | "anonymous";

type AuthContextValue = {
    status: AuthStatus;
    user: SessionUser | null;
    authConfig: AuthConfig | null;
    refresh: () => Promise<void>;
    signInWithGoogle: (idToken: string) => Promise<SessionUser>;
    signInWithApple: (
        identityToken: string,
        name: string | null,
    ) => Promise<SessionUser>;
    signInDev: (email: string, name?: string) => Promise<SessionUser>;
    signOut: () => Promise<void>;
    /**
     * Permanently delete the signed-in user's account on the backend
     * (DELETE /api/v1/me) AND clear every scrap of local state, the
     * same way `signOut` does. The provider transitions to
     * `anonymous` synchronously on the way out so the route guard in
     * `apps/mobile/app/trips/_layout.tsx` redirects to the splash on
     * the next render — no manual `router.replace` needed.
     *
     * Errors from the backend call are *re-thrown* (not swallowed
     * the way `signOut` swallows them) so the calling Settings screen
     * can show a "delete failed" message and let the user retry. We
     * only clear local state on success.
     *
     * Required by Apple App Review Guideline 5.1.1(v) — every iOS
     * submission gets rejected without this path.
     */
    deleteAccount: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function persistAndAdoptToken(authed: AuthedUserResponse): void {
    const token = authed.session_token ?? null;
    if (token) {
        setCurrentToken(token);
        void writeStoredSession({
            token,
            expiresAt: authed.session_expires_at ?? null,
        });
    }
}

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<SessionUser | null>(null);
    const [status, setStatus] = useState<AuthStatus>("loading");
    const [authConfig, setAuthConfig] = useState<AuthConfig | null>(null);
    const didInitialLoad = useRef(false);

    const refresh = useCallback(async () => {
        try {
            const me = await sharedFetchMe(apiFetch, getApi());
            setUser(me);
            setStatus(me ? "authenticated" : "anonymous");
            if (me === null) {
                // Token might be expired/invalid — drop it so we stop
                // attaching a stale Authorization header.
                setCurrentToken(null);
                await clearStoredSession();
            }
        } catch (err) {
            if (isApiError(err) && err.status === 401) {
                setCurrentToken(null);
                await clearStoredSession();
            }
            setUser(null);
            setStatus("anonymous");
        }
    }, []);

    useEffect(() => {
        if (didInitialLoad.current) return;
        didInitialLoad.current = true;
        void (async () => {
            const stored = await readStoredSession();
            if (stored) setCurrentToken(stored.token);
            const [config] = await Promise.all([
                sharedFetchAuthConfig(apiFetch, getApi()),
            ]);
            setAuthConfig(config);
            await refresh();
        })();
    }, [refresh]);

    const signInWithGoogle = useCallback(async (idToken: string) => {
        const authed = await sharedLoginWithGoogleCredential(
            apiFetch,
            getApi(),
            idToken,
            { wantsToken: true },
        );
        persistAndAdoptToken(authed);
        const me: SessionUser = {
            id: authed.id,
            email: authed.email,
            name: authed.name,
            picture_url: authed.picture_url,
            is_admin: authed.is_admin,
        };
        setUser(me);
        setStatus("authenticated");
        return me;
    }, []);

    const signInWithApple = useCallback(
        async (identityToken: string, name: string | null) => {
            const authed = await sharedLoginWithAppleCredential(
                apiFetch,
                getApi(),
                identityToken,
                name,
                { wantsToken: true },
            );
            persistAndAdoptToken(authed);
            const me: SessionUser = {
                id: authed.id,
                email: authed.email,
                name: authed.name,
                picture_url: authed.picture_url,
                is_admin: authed.is_admin,
            };
            setUser(me);
            setStatus("authenticated");
            return me;
        },
        [],
    );

    const signInDev = useCallback(async (email: string, name?: string) => {
        const authed = await sharedLoginDev(
            apiFetch,
            getApi(),
            email,
            name,
            { wantsToken: true },
        );
        persistAndAdoptToken(authed);
        const me: SessionUser = {
            id: authed.id,
            email: authed.email,
            name: authed.name,
            picture_url: authed.picture_url,
            is_admin: authed.is_admin,
        };
        setUser(me);
        setStatus("authenticated");
        return me;
    }, []);

    const signOut = useCallback(async () => {
        // Best-effort: still clear local state if the network call fails
        // (e.g. user signs out while offline).
        try {
            await sharedLogout(apiFetch, getApi());
        } catch {
            // intentional swallow
        }
        setCurrentToken(null);
        await clearStoredSession();
        setUser(null);
        setStatus("anonymous");
    }, []);

    const deleteAccount = useCallback(async () => {
        // Server-side deletion is intentionally *not* best-effort: if
        // the DELETE fails (e.g. offline, 401 because the bearer
        // expired between the user opening Settings and tapping the
        // button) we re-throw so the Settings screen can show "We
        // couldn't delete your account, try again." rather than
        // silently signing the user out while their data lives on
        // forever in the backend.
        await sharedDeleteAccount(apiFetch, getApi());
        // Identical to `signOut` from here down: drop the bearer
        // token, wipe secure storage, flip status. The route guard
        // in `app/trips/_layout.tsx` then redirects to "/" on the
        // next render.
        setCurrentToken(null);
        await clearStoredSession();
        setUser(null);
        setStatus("anonymous");
    }, []);

    const value = useMemo<AuthContextValue>(
        () => ({
            status,
            user,
            authConfig,
            refresh,
            signInWithGoogle,
            signInWithApple,
            signInDev,
            signOut,
            deleteAccount,
        }),
        [
            status,
            user,
            authConfig,
            refresh,
            signInWithGoogle,
            signInWithApple,
            signInDev,
            signOut,
            deleteAccount,
        ],
    );

    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
    const ctx = useContext(AuthContext);
    if (ctx === null) {
        throw new Error("useAuth must be used inside <AuthProvider>");
    }
    return ctx;
}

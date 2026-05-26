/**
 * API client helpers for auth.
 *
 * Mobile callers should pass `wantsToken: true` so the backend echoes
 * the session JWT back in the response body — the React Native client
 * persists it in `expo-secure-store` and attaches it to subsequent
 * requests as `Authorization: Bearer <jwt>`.
 *
 * Web callers leave `wantsToken` unset so the response only carries
 * the user projection; the session is delivered via the HttpOnly
 * `tlh_session` cookie as before.
 */
import type { ApiFetch } from "./api";
import type { ApiPaths } from "./paths";
import type {
    AuthConfig,
    AuthedUserResponse,
    SessionUser,
} from "./types";

export type LoginOptions = {
    /** When true, also request a bearer-token-shaped response. */
    wantsToken?: boolean;
};

function tokenInit(opts: LoginOptions | undefined): RequestInit {
    return opts?.wantsToken
        ? { headers: { "X-Client": "mobile" } }
        : {};
}

export async function fetchMe(
    apiFetch: ApiFetch,
    paths: ApiPaths,
): Promise<SessionUser | null> {
    const body = await apiFetch<SessionUser | { user: null }>(paths.me);
    if (body && "email" in body) return body;
    return null;
}

export async function fetchAuthConfig(
    apiFetch: ApiFetch,
    paths: ApiPaths,
): Promise<AuthConfig> {
    try {
        return await apiFetch<AuthConfig>(paths.authConfig);
    } catch {
        return {
            google_oauth_client_id: null,
            apple_sign_in_enabled: false,
            dev_login_enabled: false,
        };
    }
}

export async function loginWithGoogleCredential(
    apiFetch: ApiFetch,
    paths: ApiPaths,
    credential: string,
    opts?: LoginOptions,
): Promise<AuthedUserResponse> {
    const init = tokenInit(opts);
    return apiFetch<AuthedUserResponse>(paths.authGoogle, {
        method: "POST",
        body: JSON.stringify({ credential }),
        ...init,
    });
}

/**
 * Exchange an Apple Sign-In identity token (and optional first-run
 * display name) for a session.
 *
 * `name` is *only* present on the user's first authorization for the
 * app — Apple's privacy design hides it on subsequent sign-ins. The
 * mobile client should pass it through verbatim from the
 * `expo-apple-authentication` response so the backend can persist
 * the user's preferred display name on first sign-up.
 */
export async function loginWithAppleCredential(
    apiFetch: ApiFetch,
    paths: ApiPaths,
    identityToken: string,
    name: string | null,
    opts?: LoginOptions,
): Promise<AuthedUserResponse> {
    const init = tokenInit(opts);
    return apiFetch<AuthedUserResponse>(paths.authApple, {
        method: "POST",
        body: JSON.stringify({ identity_token: identityToken, name }),
        ...init,
    });
}

export async function loginDev(
    apiFetch: ApiFetch,
    paths: ApiPaths,
    email: string,
    name?: string,
    opts?: LoginOptions,
): Promise<AuthedUserResponse> {
    const init = tokenInit(opts);
    return apiFetch<AuthedUserResponse>(paths.authDevLogin, {
        method: "POST",
        body: JSON.stringify({ email, name }),
        ...init,
    });
}

export async function logout(
    apiFetch: ApiFetch,
    paths: ApiPaths,
): Promise<void> {
    await apiFetch<{ status: string }>(paths.authLogout, {
        method: "POST",
    });
}

/**
 * Permanently delete the signed-in user's account and every row that
 * hangs off it (trips, samples, audit log). On success the backend
 * clears the session cookie as part of the response, and a stale
 * bearer token kept on a mobile client degrades to anonymous on the
 * next request because the underlying user row no longer exists.
 *
 * The caller is responsible for the *client-side* cleanup that
 * mirrors a regular sign-out (clearing any in-memory user state,
 * dropping any bearer token from secure storage, navigating back to
 * the splash). This helper just makes the DELETE.
 *
 * Apple App Review 5.1.1(v) requires this path to exist on any app
 * that supports account creation, which we do via "Sign in with
 * Apple" — so the App Store submission is wired to this endpoint.
 */
export async function deleteAccount(
    apiFetch: ApiFetch,
    paths: ApiPaths,
): Promise<void> {
    await apiFetch<null>(paths.deleteAccount, { method: "DELETE" });
}

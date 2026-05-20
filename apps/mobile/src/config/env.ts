/**
 * Strict env loader for the mobile app.
 *
 * Every variable is **required**. There are no fallbacks, no
 * graceful-degradation branches, and no "if configured" checks
 * scattered through the rest of the codebase: by the time anything
 * else mounts, `loadEnvOnce()` has either returned a fully-typed
 * `Env` object or filed a `Missing` report that the root layout
 * renders as a setup-required screen.
 *
 * The set of required vars is keyed off `EXPO_PUBLIC_APP_ENV`:
 *
 *   APP_ENV=local      → dev-login is the only sign-in path
 *     - EXPO_PUBLIC_API_BASE_URL
 *     - EXPO_PUBLIC_GOOGLE_MAPS_API_KEY
 *     - EXPO_PUBLIC_DEV_LOGIN_EMAIL
 *
 *   APP_ENV=prod       → Google Sign-In is the only sign-in path
 *     - EXPO_PUBLIC_API_BASE_URL
 *     - EXPO_PUBLIC_GOOGLE_MAPS_API_KEY
 *     - EXPO_PUBLIC_GOOGLE_OAUTH_WEB_CLIENT_ID
 *     - EXPO_PUBLIC_GOOGLE_OAUTH_IOS_CLIENT_ID
 *
 * Why two distinct modes (instead of "set everything and we'll pick"):
 *   - It removes the "is dev-login enabled?" runtime branch entirely;
 *     each build target has exactly one sign-in surface.
 *   - It mirrors the backend's `APP_ENV=local|prod` gate of
 *     `enable_dev_login`, so a misconfigured pair fails the same way
 *     on both sides.
 *   - The Setup Required screen can give exact, copy-pasteable
 *     instructions per mode.
 */
export type AppEnv = "local" | "prod";

export type LocalEnv = {
    appEnv: "local";
    apiBaseUrl: string;
    googleMapsApiKey: string;
    devLoginEmail: string;
};

export type ProdEnv = {
    appEnv: "prod";
    apiBaseUrl: string;
    googleMapsApiKey: string;
    googleOAuthWebClientId: string;
    googleOAuthIosClientId: string;
};

export type Env = LocalEnv | ProdEnv;

export type MissingVar = {
    name: string;
    description: string;
    example: string;
};

export type EnvLoadResult =
    | { ok: true; env: Env }
    | { ok: false; appEnv: AppEnv | "unset"; missing: MissingVar[] };

/**
 * Validate one already-resolved env value.
 *
 * ⚠️ This intentionally does NOT do `process.env[name]` itself —
 * Metro's `EXPO_PUBLIC_*` inlining only fires for **static** property
 * accesses (`process.env.EXPO_PUBLIC_FOO`), not dynamic ones
 * (`process.env[name]`). If we read the env var here, every callsite
 * would compile down to a dynamic lookup that's always `undefined` in
 * a production JS bundle — which is exactly the bug we shipped in
 * builds #3–#4 on 5 May / 20 May 2026 (`EXPO_PUBLIC_APP_ENV` worked
 * because it was the only static read; the four other vars all
 * routed through here and disappeared from the bundle).
 *
 * The fix is to keep every `process.env.EXPO_PUBLIC_X` access at the
 * loadEnv() callsite (one literal per var) and pass the already-read
 * value into this helper.
 */
function readRequired(
    name: string,
    value: string | undefined,
    description: string,
    example: string,
    missing: MissingVar[],
): string {
    const trimmed = value?.trim() ?? "";
    if (trimmed.length === 0) {
        missing.push({ name, description, example });
        return "";
    }
    return trimmed;
}

export function loadEnv(): EnvLoadResult {
    const missing: MissingVar[] = [];

    // Every `process.env.EXPO_PUBLIC_*` below MUST stay as a literal
    // static property access — see `readRequired`'s docstring. If you
    // refactor any of these to a helper that takes a name string and
    // does `process.env[name]`, the value will silently disappear
    // from the production JS bundle and `loadEnv()` will fall through
    // to the SetupRequired screen on every install.

    const rawAppEnv = process.env.EXPO_PUBLIC_APP_ENV?.trim();
    if (rawAppEnv !== "local" && rawAppEnv !== "prod") {
        return {
            ok: false,
            appEnv: "unset",
            missing: [
                {
                    name: "EXPO_PUBLIC_APP_ENV",
                    description:
                        'Sign-in mode for this build. Use "local" for dev-login (no Google Cloud setup required) or "prod" for native Google Sign-In.',
                    example: "local",
                },
            ],
        };
    }
    const appEnv: AppEnv = rawAppEnv;

    const apiBaseUrl = readRequired(
        "EXPO_PUBLIC_API_BASE_URL",
        process.env.EXPO_PUBLIC_API_BASE_URL,
        "Root URL of the FastAPI backend. For dev on a real phone this MUST be your laptop's LAN IP (find it with `ipconfig getifaddr en0`) — `localhost` from the phone means the phone itself.",
        appEnv === "local"
            ? "http://192.168.1.42:8000"
            : "https://api.time2leave.com",
        missing,
    );
    const googleMapsApiKey = readRequired(
        "EXPO_PUBLIC_GOOGLE_MAPS_API_KEY",
        process.env.EXPO_PUBLIC_GOOGLE_MAPS_API_KEY,
        "Google Maps Platform key with the Places API enabled. Powers the address autocomplete on the new-trip form.",
        "AIzaSyA...rest-of-key",
        missing,
    );

    if (appEnv === "local") {
        const devLoginEmail = readRequired(
            "EXPO_PUBLIC_DEV_LOGIN_EMAIL",
            process.env.EXPO_PUBLIC_DEV_LOGIN_EMAIL,
            "Email used by POST /api/v1/auth/dev-login on the backend. Must be on the backend's auth allowlist (see backend AUTH_ALLOWLIST_BOOTSTRAP / ADMIN_EMAILS).",
            "dev@example.com",
            missing,
        );
        if (missing.length > 0) {
            return { ok: false, appEnv, missing };
        }
        return {
            ok: true,
            env: { appEnv, apiBaseUrl, googleMapsApiKey, devLoginEmail },
        };
    }

    const googleOAuthWebClientId = readRequired(
        "EXPO_PUBLIC_GOOGLE_OAUTH_WEB_CLIENT_ID",
        process.env.EXPO_PUBLIC_GOOGLE_OAUTH_WEB_CLIENT_ID,
        'Web OAuth client ID from Google Cloud Console. @react-native-google-signin requires the *web* client ID as the `webClientId` arg even on iOS — that\'s what becomes the `aud` claim of the ID token, which the backend matches against its `GOOGLE_OAUTH_CLIENT_ID` list.',
        "123456789-abc.apps.googleusercontent.com",
        missing,
    );
    const googleOAuthIosClientId = readRequired(
        "EXPO_PUBLIC_GOOGLE_OAUTH_IOS_CLIENT_ID",
        process.env.EXPO_PUBLIC_GOOGLE_OAUTH_IOS_CLIENT_ID,
        "iOS OAuth client ID (bundle ID `com.time2leave.app`). app.config.ts auto-derives the iOS URL scheme from this and registers it with the @react-native-google-signin config plugin.",
        "123456789-xyz.apps.googleusercontent.com",
        missing,
    );

    if (missing.length > 0) {
        return { ok: false, appEnv, missing };
    }
    return {
        ok: true,
        env: {
            appEnv,
            apiBaseUrl,
            googleMapsApiKey,
            googleOAuthWebClientId,
            googleOAuthIosClientId,
        },
    };
}

let _cached: EnvLoadResult | null = null;

/**
 * Memoized `loadEnv()`. Safe to call from anywhere — env is inlined
 * by Expo at bundle time, so the result never changes during a
 * running app session.
 */
export function loadEnvOnce(): EnvLoadResult {
    if (_cached === null) {
        _cached = loadEnv();
    }
    return _cached;
}

/**
 * Convenience: assert env is valid and return it. Use only inside
 * components that the root layout has already gated on a successful
 * `loadEnvOnce()`. Throws otherwise so a misuse fails loudly in dev.
 */
export function requireEnv(): Env {
    const r = loadEnvOnce();
    if (!r.ok) {
        throw new Error(
            "requireEnv() called before env was validated by RootLayout. This is a bug; ensure the caller is mounted under <RootLayout>'s 'env.ok' branch.",
        );
    }
    return r.env;
}

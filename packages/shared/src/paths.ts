/**
 * Endpoint paths for the FastAPI backend.
 *
 * Both clients call exactly the same routes, so we centralize them here
 * as a `baseUrl`-bound factory. Web reads `import.meta.env.VITE_API_BASE_URL`,
 * mobile reads `process.env.EXPO_PUBLIC_API_BASE_URL`, and each then
 * passes the resolved string to `createApiPaths()`.
 *
 * The trip identifier is a 10-hex-char public slug (e.g. `"a1b2c3d4e5"`),
 * not an auto-incrementing integer — see `TripSummary.id` in `types.ts`.
 */
export type ApiPaths = {
    readonly me: string;
    /**
     * Account deletion (Apple App Review 5.1.1(v) requirement). Same
     * URL as `me` — the HTTP method (DELETE vs GET) disambiguates,
     * and the shared `deleteAccount()` helper hides that detail from
     * UI code.
     */
    readonly deleteAccount: string;
    readonly authGoogle: string;
    readonly authApple: string;
    readonly authLogout: string;
    readonly authDevLogin: string;
    readonly authConfig: string;
    readonly trips: string;
    readonly tripQuota: string;
    readonly trip: (id: string) => string;
    readonly tripHeatmap: (id: string) => string;
    readonly tripBackfillStatus: (id: string) => string;
    readonly adminAllowlist: string;
    readonly adminAllowlistEntry: (email: string) => string;
};

export function createApiPaths(baseUrl: string): ApiPaths {
    return {
        me: `${baseUrl}/api/v1/me`,
        deleteAccount: `${baseUrl}/api/v1/me`,
        authGoogle: `${baseUrl}/api/v1/auth/google`,
        authApple: `${baseUrl}/api/v1/auth/apple`,
        authLogout: `${baseUrl}/api/v1/auth/logout`,
        authDevLogin: `${baseUrl}/api/v1/auth/dev-login`,
        authConfig: `${baseUrl}/api/v1/auth/config`,
        trips: `${baseUrl}/api/v1/trips`,
        tripQuota: `${baseUrl}/api/v1/trips/quota`,
        trip: (id: string) => `${baseUrl}/api/v1/trips/${id}`,
        tripHeatmap: (id: string) => `${baseUrl}/api/v1/trips/${id}/heatmap`,
        tripBackfillStatus: (id: string) =>
            `${baseUrl}/api/v1/trips/${id}/backfill-status`,
        adminAllowlist: `${baseUrl}/api/v1/admin/allowlist`,
        adminAllowlistEntry: (email: string) =>
            `${baseUrl}/api/v1/admin/allowlist/${encodeURIComponent(email)}`,
    } as const;
}

import { index, route, type RouteConfig } from "@react-router/dev/routes";

export default [
    index("routes/splash.tsx"),
    route("trips", "routes/trips.tsx"),
    route("trips/new", "routes/trips.new.tsx"),
    route("trips/:tripId", "routes/trips.$tripId.tsx"),
    route("settings", "routes/settings.tsx"),
    route("admin/allowlist", "routes/admin.allowlist.tsx"),
    // Public legal / contact pages. Required by App Store Connect's
    // Support URL + Privacy Policy URL fields; both must resolve
    // without authentication.
    route("support", "routes/support.tsx"),
    route("privacy", "routes/privacy.tsx"),
    route("*", "routes/unknown.tsx"),
] satisfies RouteConfig;

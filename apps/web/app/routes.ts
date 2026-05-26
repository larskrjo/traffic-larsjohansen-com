import { index, route, type RouteConfig } from "@react-router/dev/routes";

export default [
    index("routes/splash.tsx"),
    route("trips", "routes/trips.tsx"),
    route("trips/new", "routes/trips.new.tsx"),
    route("trips/:tripId", "routes/trips.$tripId.tsx"),
    route("settings", "routes/settings.tsx"),
    route("admin/allowlist", "routes/admin.allowlist.tsx"),
    route("*", "routes/unknown.tsx"),
] satisfies RouteConfig;

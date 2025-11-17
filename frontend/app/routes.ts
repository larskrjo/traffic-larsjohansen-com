import {index, route, type RouteConfig} from "@react-router/dev/routes";

export default [
    index("routes/index.tsx"),
    route("/*", "routes/unknown.tsx")
] satisfies RouteConfig;

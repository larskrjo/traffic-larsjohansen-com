import {isRouteErrorResponse, Links, Meta, Outlet, Scripts, ScrollRestoration,} from "react-router";

import type {Route} from "./+types/root";
import "./styles/app.css";

import '@fontsource/roboto/300.css';
import '@fontsource/roboto/400.css';
import '@fontsource/roboto/500.css';
import '@fontsource/roboto/700.css';

import {CssBaseline, ThemeProvider} from '@mui/material';
import InitColorSchemeScript from '@mui/material/InitColorSchemeScript';

import {theme} from './styles/theme';
import Loading from "~/components/Loading";


export function meta({}: Route.MetaArgs) {
    return [
        { title: "Traffic Commute Heatmap" },
        { name: "description", content: "Commute time heatmap visualization" },
    ];
}

export const links: Route.LinksFunction = () => [
  { rel: "preconnect", href: "https://fonts.googleapis.com" },
  {
    rel: "preconnect",
    href: "https://fonts.gstatic.com",
    crossOrigin: "anonymous",
  },
  {
    rel: "stylesheet",
    href: "https://fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,100..900;1,14..32,100..900&display=swap",
  },
];

export function HydrateFallback() {
    return <Loading />
}

export function Layout({ children }: { children: React.ReactNode }) {
  return (
  <html lang="en" data-mui-color-scheme="light">
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <Meta />
        <Links />
      </head>
      <body suppressHydrationWarning>
        <InitColorSchemeScript
          attribute="[data-mui-color-scheme='%s']"
          defaultMode="light"
        />

        {/* 2) Match defaultMode with the script */}
        <ThemeProvider theme={theme}>
          <CssBaseline />
          {children}
        </ThemeProvider>
        <ScrollRestoration />
        <Scripts />
      </body>
    </html>
  );
}

export default function App() {
  return <Outlet />;
}

export function ErrorBoundary({ error }: Route.ErrorBoundaryProps) {
  let message = "Oops!";
  let details = "An unexpected error occurred.";
  let stack: string | undefined;

  if (isRouteErrorResponse(error)) {
    message = error.status === 404 ? "404" : "Error";
    details =
      error.status === 404
        ? "The requested page could not be found."
        : error.statusText || details;
  } else if (error && error instanceof Error) {
    details = error.message;
    stack = error.stack;
  }

  return (
      <main className="main-error-container">
          <h1>{message}</h1>
          <p>{details}</p>
          {stack && (
              <pre className="stack-block">
                  <code>{stack}</code>
              </pre>
          )}
      </main>
  );
}

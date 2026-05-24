# time2leave

Know exactly when to leave. Sign in with Google, save up to a few
"trips" (origin → destination address pairs), and see a
15-minute-resolution heatmap of expected drive times for the current
week, in both directions, 06:00 – 21:00, every day Mon-Sun. The
upcoming week becomes available too as soon as it's been refreshed,
so most of the time you can flip between "this week" and "next week".

Lives at https://time2leave.com.

- **Backend** — FastAPI + MySQL + APScheduler. Monday-01:00-PT job samples
  Google's Routes Matrix API for every active trip and stores per-slot
  durations in `commute_samples`. Per-user trip caps and a hard ceiling on
  weekly Routes Matrix calls keep the API budget under control.
- **Frontend** — React Router 7 SPA (SSR disabled) with MUI. Animated
  splash for logged-out users, Google Identity Services sign-in,
  authenticated trips list / new-trip form / detail view with both
  directions and live backfill polling.
- **Auth** — Stateless JWT session cookies, gated by an email allowlist
  managed in the `auth_allowlist` table (admin endpoints + bootstrap-
  from-env).

## Repo layout

This is an npm workspaces monorepo:

```
apps/
  web/        # React Router 7 SPA — the existing browser app
  mobile/     # Expo / React Native app for iOS + Android (see apps/mobile/README.md)
packages/
  shared/    # @time2leave/shared — pure TS types + API client + helpers
backend/      # FastAPI service (unchanged location)
```

Both clients call the same backend and re-use `@time2leave/shared` for
types, the API client, time/slot helpers, and heatmap math.

## Quickstart

The fastest path on a fresh checkout is the interactive bootstrap
script — it walks you through prereq checks, **installs the `t2l`
CLI to `~/.local/bin` with tab-completion**, installs deps, creates
`backend/.env`, configures the mobile app's env via GCP Secret
Manager, and brings up the dev stack. Every step prompts before
touching anything and is safe to re-run any time:

```bash
./setup.sh
```

The `t2l` install is a **symlink** into this checkout, so `git pull`
is enough to pick up new CLI commands — you only need to re-run
`./setup.sh` if you started from a fresh clone or if the repo moved
on disk.

After the first run, open a new terminal (or `source ~/.zshrc`) and
drive everything through `t2l` — one verb per component, one flag for
whether you mean local or remote. **Tab-complete every subcommand
and flag.**

```bash
t2l up be                 # mysql + api in docker (local)
t2l up fe                 # web on http://localhost:5173 (local)
t2l up ios                # Metro for the mobile app (local)

t2l deploy be             # ssh + redeploy api.time2leave.com
t2l deploy fe             # build + push web to time2leave.com (S3 + CloudFront)
t2l deploy app --ota --message "<msg>"            # OTA via EAS Update
t2l deploy app --build --platform ios --submit    # full build + TestFlight
```

Run `t2l --help` for the full reference including `--rebuild` for
backend (force recreate containers) and iOS (full native rebuild).
The CLI is a thin wrapper over the existing Make targets and EAS /
S3 / SSH workflows — anything `t2l` does can also be done via
`make <target>` or `npm run eas -- …` directly:

```bash
make install      # set up backend venv + JS workspace node_modules
make dev-be       # equivalent of 't2l up be'
make dev-fe       # equivalent of 't2l up fe'
make deploy-frontend   # equivalent of 't2l deploy fe'
```

For the mobile app, the canonical runtime is a **development build**
(not Expo Go — see `apps/mobile/README.md` for why). First build
takes ~5–10 minutes; afterwards Metro hot-reloads JS instantly:

```bash
npm run env:pull:mobile -- local       # hydrate apps/mobile/.env from GCP
npm run build:ios:mobile               # one-time: build + install on iPhone simulator
t2l up ios                             # day-to-day: Metro only
```

Open http://localhost:5173, click **"Continue as dev user"** (the
seeded `dev@example.com` is pre-allowlisted) — you'll land on `/trips`
with one trip already populated. No Google Maps API key, OAuth client,
or AWS credentials required.

> **Upgrading from the single-user schema?** The `docker-entrypoint-initdb.d`
> scripts only run on a fresh MySQL volume. Run `make clean && t2l up be`
> once to wipe the old `commute_slots`-era volume and let the new
> multi-user schema + dev-user seed apply.

Run `make help` for the full Make target list (`test`, `typecheck`,
`logs`, `seed`, `clean`, …) — these stay around for granular tasks
that aren't part of the `t2l` surface.

## Architecture

```
                          (Monday 01:00 PT — APScheduler, prod)
                                     │
                                     ▼
                    enumerate active trips (per user)
                                     │
              CommuteProvider — Google Routes Matrix  |  FixtureProvider
                                     │
                                     ▼
              MySQL  commute_samples  (trip_id, week, direction, hhmm, …)
                                     │
                                     ▼
                          FastAPI  /api/v1/...
       /auth/google · /auth/dev-login · /me · /auth/logout
       /trips · /trips/{id} · /trips/{id}/heatmap
       /admin/allowlist · /admin/run-data-gathering
                                     │
                                     ▼
              React SPA (CloudFront → S3 in prod, Vite dev server locally)
```

### Data lifecycle

| Event | What happens |
| --- | --- |
| User creates a trip | `POST /trips` returns the new trip immediately and kicks off two background backfills (current week + next week) via `backfill_trip_for_week` so both weeks are usable right away. The frontend polls `/backfill-status` every 4 s and re-renders the heatmap as cells fill in. |
| Monday 01:00 PT cron | `main()` enumerates every active trip, refuses to start if `slots_per_trip × trips > MAX_WEEKLY_ROUTES_CALLS`, then upserts empty samples for next week before filling them via the configured `CommuteProvider`. Running just after the Pacific week rollover keeps both the current and next week populated for ~99% of the week. |
| User deletes a trip | Soft-delete (`deleted_at = NOW()`); samples are preserved but the trip stops being refreshed and disappears from `/trips`. |

### Quotas and cost ceilings

| Knob | Default | Purpose |
| --- | --- | --- |
| `MAX_TRIPS_PER_USER` | 1 | Hard cap on active trips per non-admin user. |
| `MAX_TRIPS_PER_ADMIN` | 2 | Elevated per-user cap for emails in `ADMIN_EMAILS`. |
| `MAX_TRIPS_TOTAL` | 10 | Global hard cap. New trips return 409 once reached. |
| `MAX_TRIP_MUTATIONS_PER_WEEK` | 1 | Per-user rolling-7-day cap on trip creates + address-changing patches (each one fires a fresh Routes Matrix backfill for *both* the current and next week ≈ $16.80). Returns 429 when exceeded. |
| `MAX_WEEKLY_ROUTES_CALLS` | 150 000 | Weekly Mon-01:00-PT cron aborts before any call if it would exceed this. |
| Slots per trip per week | 60 × 7 × 2 = 840 | (60 quarter-hours of 06:00-21:00) × 7 days × 2 directions. |

## Backend

Location: [`backend/`](backend/).

### Layout
- Entry point: [`app/main.py`](backend/app/main.py) — `create_app()` factory wires routers, lifecycle, and APScheduler.
- Configuration: [`app/config.py`](backend/app/config.py) — typed `Settings` via `pydantic-settings`. In prod, secrets overlay from AWS Secrets Manager.
- Auth: [`app/auth/`](backend/app/auth) — Google ID-token verification, JWT session issuance/verification, FastAPI dependencies.
- Services: [`app/services/`](backend/app/services) — `users`, `trips`, `allowlist` business logic.
- Routers:
  - [`app/api/auth_api.py`](backend/app/api/auth_api.py) — `/auth/google`, `/auth/dev-login`, `/auth/logout`, `/me`, `/auth/config`.
  - [`app/api/trips_api.py`](backend/app/api/trips_api.py) — per-user trip CRUD + heatmap + backfill status.
  - [`app/api/admin_api.py`](backend/app/api/admin_api.py) — allowlist management + manual data-gathering trigger. Gated by `is_admin` (computed from `ADMIN_EMAILS`).
  - [`app/api/healthcheck_api.py`](backend/app/api/healthcheck_api.py) — liveness + scheduler status.
- Data gathering: [`app/job/data_gathering.py`](backend/app/job/data_gathering.py) (`main`, `backfill_trip_for_week`) + pluggable [`app/job/providers.py`](backend/app/job/providers.py) (`GoogleRoutesProvider`, `FixtureProvider`).
- DB layer: [`app/db/db.py`](backend/app/db/db.py) — lazy `MySQLConnectionPool` + `Database` context manager.

### Environment variables

All values have sensible local defaults (see [`backend/.env.example`](backend/.env.example)).

| Var | Default | Notes |
| --- | --- | --- |
| `APP_ENV` | `local` | `local`, `dev`, or `prod`. Legacy `DEVELOPMENT_MODE` is accepted as an alias. |
| `MYSQL_HOST` / `PORT` / `USER` / `PASSWORD` / `DATABASE` | `localhost` / `3306` / `root` / `Abcd1234` / `time2leave` | In prod these are overlaid by AWS Secrets Manager secret `MySecret` in `us-west-2`. The prod database name is still set explicitly via `MYSQL_DATABASE` in `backend/docker-compose.yml`. |
| `DATA_PROVIDER` | `fixture` | `google` to hit the Routes Matrix API (requires `GOOGLE_MAPS_API_KEY`). |
| `GOOGLE_MAPS_API_KEY` | _unset_ | Required for `DATA_PROVIDER=google`. |
| `GOOGLE_OAUTH_CLIENT_ID` | _unset_ | Required for the real Google sign-in. Local dev uses `ENABLE_DEV_LOGIN` instead. |
| `SESSION_SECRET` | `dev-only-change-me` | HMAC secret for session JWTs. **Always set in prod** (loaded from AWS Secrets Manager). |
| `SESSION_COOKIE_NAME` | `tlh_session` | Cookie name for the session JWT. |
| `SESSION_COOKIE_DOMAIN` | _unset_ | Set to e.g. `.time2leave.com` so api/frontend share cookies. |
| `SESSION_TTL_HOURS` | `168` | One week. |
| `ENABLE_DEV_LOGIN` | `true` | `POST /auth/dev-login` is mounted only when this is true. Forced off in prod. |
| `ADMIN_EMAILS` | _empty_ | Comma-separated. These users get `is_admin: true` and admin endpoints. |
| `AUTH_ALLOWLIST_BOOTSTRAP` | _empty_ | Comma-separated. Inserted into `auth_allowlist` on every startup (idempotent). |
| `MAX_TRIPS_PER_USER` / `MAX_TRIPS_PER_ADMIN` / `MAX_TRIPS_TOTAL` / `MAX_TRIP_MUTATIONS_PER_WEEK` / `MAX_WEEKLY_ROUTES_CALLS` | `1` / `2` / `10` / `1` / `150000` | Quota / cost guardrails. |
| `ALLOWED_ORIGINS` | `http://localhost:5173, http://127.0.0.1:5173` | Comma-separated CORS origins (outside prod). Prod always allows exactly `https://time2leave.com` and `https://www.time2leave.com`. |
| `MYSQL_HOST_PORT` / `API_HOST_PORT` / `FRONTEND_HOST_PORT` | `3307` / `8000` / `5173` | Host-side ports published by `docker-compose.dev.yml`. MySQL defaults to `3307` so it doesn't clash with a Homebrew/system MySQL on `3306`. Override if any of these are taken on your machine. |

### Inviting people

Add their email to the allowlist via the admin API:

```bash
# requires being signed in as an ADMIN_EMAILS user; uses your browser cookie
curl -X POST https://api.time2leave.com/api/v1/admin/allowlist \
     -H 'Content-Type: application/json' \
     --cookie "tlh_session=$YOUR_SESSION_JWT" \
     -d '{"email": "friend@example.com"}'
```

Or pre-load on startup with `AUTH_ALLOWLIST_BOOTSTRAP=alice@x.com,bob@y.com`.

### Running backend alone

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
APP_ENV=local uvicorn app.main:app --reload
```

If MySQL isn't running, start just the DB:

```bash
docker compose -f backend/docker-compose.dev.yml up -d mysql
```

### Tests

```bash
make test            # unit + API (no network, no docker)
make test-integration  # docker-backed end-to-end tests (testcontainers)
make typecheck       # mypy + tsc
```

## Web

Location: [`apps/web/`](apps/web/).

- `app/routes/splash.tsx` — animated landing page for logged-out users.
- `app/routes/trips.tsx` — list of the user's trips + new-trip CTA.
- `app/routes/trips.new.tsx` — origin / destination form.
- `app/routes/trips.$tripId.tsx` — outbound/return tabs, per-day "best slot" summary strip, full heatmap, live backfill polling.
- `app/lib/session.tsx` — `<SessionProvider>` + `useSession()`. Fetches `/api/v1/me` and `/api/v1/auth/config` on mount.
- `app/lib/trips.ts` — thin web wrapper around `@time2leave/shared`'s typed API client.
- `app/components/ProtectedRoute.tsx` — redirects unauthenticated users to `/?next=…`.
- `app/components/TripHeatmap.tsx` — full grid with hue-mapped cells and a "best slot per day" summary chip strip.

### Running

From the **repo root** (npm workspaces):

```bash
npm install                                 # installs apps/web, apps/mobile, packages/shared
npm run dev --workspace=@time2leave/web     # http://localhost:5173
npm run test --workspace=@time2leave/web    # vitest
npm run typecheck --workspace=@time2leave/web
npm run build --workspace=@time2leave/web   # production bundle in apps/web/build/client/
```

The Google OAuth client id is fetched from the backend (`GET
/api/v1/auth/config`) so the SPA does not need its own
`VITE_GOOGLE_OAUTH_CLIENT_ID`. Web env vars (see
[`apps/web/.env.example`](apps/web/.env.example)):

| Var | Notes |
| --- | --- |
| `VITE_API_BASE_URL` | Backend base URL. Defaults to `http://localhost:8000` in dev. |
| `VITE_GOOGLE_MAPS_API_KEY` | Optional **browser-restricted** Maps JS API key used for Places autocomplete on `/trips/new`. Leave unset to get a plain text input. Must have "Maps JavaScript API" + "Places API" enabled and your dev/prod origins (e.g. `http://localhost:5173/*` and `https://time2leave.com/*`) in the HTTP referrer allowlist — otherwise Google returns `RefererNotAllowedMapError` at runtime and the app silently falls back to plain text entry. |

## Deployment

Frontend and backend deploy independently from **different machines**:

| Component | Runs on | Deployed from | Command |
| --- | --- | --- | --- |
| Backend (FastAPI in Docker) | EC2 | the EC2 host (SSH in first) | `cd backend && ./scripts/build-and-deploy.sh` |
| Frontend (static SPA) | S3 + CloudFront | **your local machine** | `make deploy-frontend` (from repo root) |

Do not try to build the frontend on EC2 — that host has no Node toolchain
and no AWS credentials for the S3/CloudFront resources. `deploy-to-s3.sh`
fails fast with a clear message if `npm` or `aws` is missing.

### Backend — Docker on EC2

One-line: `t2l deploy be` — SSHes into the EC2 box, `git pull`s, and
runs `./scripts/build-and-deploy.sh` for you. The longhand still works
if you want to drive each step manually:

```bash
# Equivalent of `t2l deploy be`, run by hand on the EC2 host:
cd /home/ec2-user/time2leave
git pull
cd backend
./scripts/build-and-deploy.sh
```

#### One-time SSH setup for `t2l deploy be`

`t2l deploy be` defaults to the `~/.ssh/config` alias **`time2leave`**.
On a fresh laptop, run it once — it prints the exact 5-line setup if
the alias isn't configured. The canonical setup:

```bash
cat >> ~/.ssh/config <<'EOF'

Host time2leave
  HostName <your-ec2-public-ipv4-dns>   # AWS Console → EC2 → Instances → Public IPv4 DNS
  User ec2-user
  IdentityFile ~/.ssh/<your-key>.pem
EOF

chmod 600 ~/.ssh/<your-key>.pem
ssh time2leave 'echo ok'                 # smoke-test
```

Alternatives: `t2l deploy be --host ec2-user@<host>` (per invocation)
or `export T2L_EC2_HOST="ec2-user@<host>"` in `~/.zshrc` (persistent,
no `~/.ssh/config` edit).

Uses [`backend/docker-compose.yml`](backend/docker-compose.yml) to run the
`time2leave-api` container on port 8485, joined to the external `shared_network`
so it can reach the sibling `mysql` container. AWS Secrets Manager secret
`MySecret` (in `us-west-2`) supplies MySQL credentials, the Google Maps API
key, the Google OAuth client id, and `session_secret`.

#### Schema is auto-applied

At app startup, `lifespan()` runs
[`app/db/schema_bootstrap.py`](backend/app/db/schema_bootstrap.py),
which opens a connection scoped to `MYSQL_DATABASE` and then:

1. Executes the table DDL from `db/init/001_schema.sql`. Every
   `CREATE TABLE` uses `IF NOT EXISTS`, so on an existing DB this is
   a no-op beyond a handful of cheap checks. New tables added to
   `001_schema.sql` get created on the next deploy automatically.
2. Runs [`app/db/migrations.py`](backend/app/db/migrations.py),
   which applies any new `NNNN_*.sql` files in
   [`backend/db/migrations/`](backend/db/migrations/) and records
   the applied filename in a `schema_migrations` tracking table so
   each migration runs exactly once. Errors that mean "already
   applied" (duplicate column / index, missing drop target) are
   swallowed — every other DDL error is propagated and the
   migration is *not* recorded, so a broken migration fails the
   deploy loudly instead of silently leaving prod half-migrated.

**Rule of thumb: any change to an existing table's structure (add /
drop column, change nullability, add unique index, …) must ship as
*both* a new `NNNN_*.sql` migration *and* the matching edit to
`001_schema.sql`** so a fresh install and an upgraded install both
end up with identical shapes. The migration files are the source of
truth for "what changed since the last deploy"; `001_schema.sql` is
the source of truth for "what shape we'd build from scratch today".
See [`.cursor/rules/db-schema-via-migrations.mdc`](.cursor/rules/db-schema-via-migrations.mdc)
for the exact workflow.

**Contract: the database itself must already exist.** `CREATE DATABASE`
and `USE` lines in the schema file are stripped before execution, so
the app user in AWS Secrets Manager only needs DDL on tables — not the
global `CREATE` privilege. Database creation is a one-time operator step:

- In dev, `docker-mysql` creates it from `MYSQL_DATABASE` on first
  volume init — already wired up in `docker-compose.dev.yml`.
- In prod, run `CREATE DATABASE time2leave;` once, as root.

The seed file (`002_seed.sql`) is local-dev only and is never applied
in prod.

Smoke tests after deploy:

```bash
curl https://api.time2leave.com/healthcheck
curl https://api.time2leave.com/healthcheck/scheduler
curl https://api.time2leave.com/api/v1/auth/config
```

### Frontend — S3 + CloudFront

From your **local machine** (requires Node 20+ and AWS CLI with creds for
bucket `time2leave-frontend` / distribution `E1XJU7E7JJA9QX`):

```bash
cd ~/code/time2leave
git pull
make deploy-frontend
```

Builds the SPA, syncs `build/client/` to `s3://time2leave-frontend`
(immutable cache for assets, `no-cache` for `index.html`), and invalidates
CloudFront. The script waits until the invalidation completes.

#### CloudFront one-time setup

`apps/web/scripts/configure-cloudfront.sh` configures two distribution-
level things that aren't part of the per-deploy artifact pipe:

  1. **Response Headers Policy** — attaches standard SPA hardening
     headers (HSTS, nosniff, frame-options, referrer-policy) plus
     `Cross-Origin-Opener-Policy: same-origin-allow-popups`, which
     Google Sign-In needs for its popup `postMessage` callback.

  2. **CustomErrorResponses for SPA routing** — rewrites S3's `403`
     and `404` to `/index.html` with HTTP `200`, so deep links like
     `/trips` or `/trips/42` are handed to the React Router SPA
     instead of returning a static "not found" from S3.

Run once after the distribution is created, after recreating it, or
when changing any of these settings. Idempotent: re-runs only update
what drifted.

```bash
./apps/web/scripts/configure-cloudfront.sh
```

### CI

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs ruff, mypy,
pytest, typecheck, vitest, and `npm run build` on every PR. Deploys remain
manual (no AWS credentials are stored in GitHub Actions).

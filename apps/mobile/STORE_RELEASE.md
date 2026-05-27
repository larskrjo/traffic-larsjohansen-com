# Store release checklist (iOS + Android)

This file tracks the human-only parts of shipping **Time2Leave** to
the App Store and Google Play. Everything else (build config, signing,
upload, OTA updates) is automated through EAS — see
[`eas.json`](eas.json).

The bundle ID `com.time2leave.app` is already reserved in
[`app.config.ts`](app.config.ts) for both platforms; the steps below
register it on each store and produce a first internal build.

> **Use the `npm run eas` wrapper, not bare `eas`.**
> The wrapper sources `apps/mobile/.env` before invoking the CLI so
> every EAS subcommand sees `EXPO_PUBLIC_APP_ENV`, `EXPO_PUBLIC_*`,
> etc. — without it `app.config.ts` throws "EXPO_PUBLIC_APP_ENV must
> be set" the moment EAS falls back to its bundled `@expo/config`
> (which doesn't auto-load `.env`). Every example below uses the
> wrapper.

## 1. Reserve the bundle ID

### Apple Developer Portal (one-time, before App Store Connect)

1. Sign in at <https://developer.apple.com/account/resources/identifiers/list>.
2. **Identifiers → + → App IDs → App** → register `com.time2leave.app`.
3. On that App ID, enable **Sign In with Apple**. The
   `expo-apple-authentication` plugin in `app.config.ts` adds the
   matching entitlement to the binary; the App ID must agree or the
   provisioning profile fails to issue.
4. Note your **Team ID** (top-right of the page when signed in, e.g.
   `TEXR74M723`). Already wired into
   [`eas.json`](eas.json) → `submit.production.ios.appleTeamId`.

### App Store Connect

1. Log in to <https://appstoreconnect.apple.com/> with the Apple ID
   on `eas.json` → `submit.production.ios.appleId`.
2. **Apps → + → New App**.
3. Fill in:
    - Platforms: **iOS**
    - Name: **NOT bare `Time2Leave`** — that's already reserved by
      somebody else. Apple's name-uniqueness check is fuzzy,
      case-insensitive, and includes 180-day reservation holds
      invisible to public search. Use the `Brand: Tagline` pattern
      so the name resolves *and* sells in storefront search:
        - `Time2Leave: Know When to Leave` (preferred — matches
          the splash headline)
        - `Time2Leave: Smart Commute`
        - `Time2Leave: Drive Time Heatmap`
      The home-screen launcher label stays `Time2Leave` (it's set by
      `name:` in `app.config.ts`, *not* the App Store listing name).
    - Primary language: English (U.S.)
    - Bundle ID: **`com.time2leave.app`** (dropdown — populated
      automatically because EAS already registered it when it
      provisioned your first build's distribution profile).
    - SKU: `time2leave-ios`
4. Hit Create. Note the **App Store Connect App ID** (10-digit
   numeric, e.g. `6766430353` for the current listing); already
   wired into [`eas.json`](eas.json) → `submit.production.ios.ascAppId`.

### Google Play Console

1. Log in to <https://play.google.com/console>.
2. **Create app**:
    - App name: `Time2Leave` (Google's uniqueness check is much
      looser than Apple's, so the bare name should work)
    - Default language: English (United States)
    - App or game: App
    - Free or paid: Free
    - Declarations: tick all required acknowledgments.
3. After creation: **App information → Set up your app** and complete
    the privacy policy link, target audience, content rating
    questionnaire, and data-safety form (see §3 below).
4. Set **package name** to `com.time2leave.app` when prompted (only
    settable on the very first internal release).

## 2. Assets

App icon, adaptive-icon, splash, and favicon PNGs all live in
[`apps/mobile/assets/`](assets/) and are generated from a single SVG
source — see [`assets/README.md`](assets/README.md). They are already
wired into [`app.config.ts`](app.config.ts) (`icon`, `splash` plugin,
`android.adaptiveIcon`, `web.favicon`), so the only action item here
is to regenerate them after any brand-mark changes:

```bash
npm --prefix apps/mobile run icons
```

`sharp` (the rasteriser used by `generate-icons.mjs`) is declared as
`optionalDependencies` in [`apps/mobile/package.json`](package.json)
on purpose: the EAS macOS cloud builder can't always resolve sharp's
prebuilt binaries, but since sharp has no runtime role in the bundle,
marking it optional lets `npm ci --include=dev` continue on the
builder if its postinstall fails. Locally, sharp installs fine and the
icons script keeps working.

Marketing screenshots (uploaded directly in App Store Connect / Play
Console; not committed to git):

- iPhone 6.7" (mandatory) — at least 3 shots showing splash, trip
  list, trip detail with heatmap, and the new-trip form.
- iPad 12.9" (only if you intend to publish for iPad — you can skip
  this and ship iPhone-only first).
- Android phone — same set; portrait, ≥1080px wide.

## 3. Apple privacy + Google data-safety

The app collects and sends to its own backend:

- **Email** (Account creation, app functionality — gated by sign-in)
- **Coarse location** (Approximate; optional — not currently used,
  declare "No" until/unless we add geofenced "leave now" alerts)
- **Postal addresses** (App functionality — origin / destination
  entered by the user; saved server-side under the user's account)

Apple "App Privacy" (App Store Connect → App → Privacy):
- Data Linked to User: **Email Address**, **Other User Content**
  (the saved trip addresses).
- Data Used to Track You: **None**.
- Tracking: **No**.

Google "Data safety" (Play Console → App content → Data safety):
- Personal info → Email address: collected, processed, **not shared**
  with third parties, encrypted in transit, optional, used for
  account management + app functionality.
- App activity → Other actions: collected (saved trip addresses),
  same disclosures as above.

App Store Connect also needs a **Privacy Policy URL** under App
Information; Apple Review will hard-reject without it. Point it at
`https://time2leave.com/privacy`.

App Store Connect → **Sign-In Information** is required because the
backend is allowlist-gated. Add an Apple-Review-only allowlist entry
(e.g. `apple-review@time2leave.com`) via the admin endpoint or
`AUTH_ALLOWLIST_BOOTSTRAP`, and put credentials for that account in
this section. Reviewers will sign in with Apple using a test Apple ID
whose email is on the allowlist.

**Google Play Data Safety → "Users can request that data is deleted"**
must be ticked **Yes**. The in-app path is documented in §7
("Account deletion"); the matching web path lives at
`https://time2leave.com/settings` so users who only use the SPA can
delete their account too.

## 4. EAS environment variables

`apps/mobile/.env` is gitignored and lives only on the developer's
machine; the EAS cloud builder reads its env from **EAS-managed
environment variables**, pushed to the `production` environment with:

```bash
cd apps/mobile
npm run eas -- env:push production --path .env --force
```

Confirm what's stored after pushing:

```bash
npm run eas -- env:list production
```

All five `EXPO_PUBLIC_*` vars from
[`src/config/env.ts`](src/config/env.ts) (in `prod` mode) must be
present:

- `EXPO_PUBLIC_APP_ENV` — `prod`
- `EXPO_PUBLIC_API_BASE_URL`
- `EXPO_PUBLIC_GOOGLE_MAPS_API_KEY`
- `EXPO_PUBLIC_GOOGLE_OAUTH_WEB_CLIENT_ID`
- `EXPO_PUBLIC_GOOGLE_OAUTH_IOS_CLIENT_ID`

### ⚠️ Metro only inlines `process.env.EXPO_PUBLIC_*` for STATIC accesses

This is the trap that ate builds #3 and #4 on 5 May / 20 May 2026 and
took two OTAs to fully recover from:

```ts
// ✅ STATIC — Metro replaces this with the inlined value at bundle time.
const url = process.env.EXPO_PUBLIC_API_BASE_URL;

// ❌ DYNAMIC — Metro sees `process.env[name]` and leaves it alone,
// because it can't tell what `name` resolves to at bundle time. The
// runtime evaluates `process.env[name]` in an empty `process.env`
// object and gets `undefined` regardless of what was set on the EAS
// builder.
function readEnv(name: string) {
    return process.env[name];
}
```

If you refactor [`src/config/env.ts`](src/config/env.ts), **every
`process.env.EXPO_PUBLIC_*` access must remain a literal at the
callsite**. The current loader (`loadEnv()`) reads each var with a
static literal and passes the value into a helper for validation —
do not "DRY this up" by hoisting the property access into a function
that takes the name as a parameter. There's a comment in `env.ts`
explaining this; preserve it.

Symptom when this regresses: the SetupRequired screen lists every
var *except* the one(s) you happen to read statically (we kept
`EXPO_PUBLIC_APP_ENV` working long after the rest broke because that
single var was read statically in `loadEnv()`'s first line).

## 5. First build + submit

```bash
# One-time:
npm install -g eas-cli
npm run eas -- login
npm run eas -- init   # links the local app to its EAS project
                      # (writes extra.eas.projectId in app.config.ts — already there)

# Production build (cloud — no Mac needed for Android,
# no Android SDK needed for iOS):
npm run eas -- build --platform ios --profile production
npm run eas -- build --platform android --profile production
```

EAS handles signing automatically: it'll create / reuse an iOS
Distribution certificate and provisioning profile, and generate /
upload an Android upload key. The first iOS build also prompts you
for an Apple Developer account login + 2FA code; sessions are cached
in `~/.app-store/auth/<apple-id>/` for subsequent builds.

Submit:

```bash
npm run eas -- submit --platform ios --latest      # → TestFlight
npm run eas -- submit --platform android --latest  # → Play Internal Testing
```

`--latest` picks up the most recent successful build for that
platform/profile pair. Processing on App Store Connect takes ~30 min;
your TestFlight internal tester list (App Store Connect → TestFlight)
sees the new build once that completes.

Smoke-test on real devices before promoting to external testers /
submitting for App Review:

- Sign in with Apple → lands on `/trips`
- Sign in with Google → lands on `/trips`
- Create a trip → heatmap loads, backfill polls, cells fill in
- Sign out + sign back in
- App Privacy: confirm the splash shows no analytics opt-in (we
  don't ship one, but verify there's nothing leaking).

## 6. Over-the-air updates with EAS Update

`expo-updates` is installed and `runtimeVersion: { policy: "appVersion" }`
is set in [`app.config.ts`](app.config.ts), so any JS-only fix can
ship without going through App Store Review. The `production` build
channel in [`eas.json`](eas.json) maps to the `production` EAS Update
branch.

```bash
cd apps/mobile
npm run eas -- update --channel production --environment production \
    --platform ios \
    --message "<one-line summary>"
```

`--environment production` makes Metro see the same env vars the
cloud build would. `--platform ios` skips the web export, which
otherwise errors because we don't ship `react-native-web`.

Existing installs pick up the new bundle on next cold start — the
default `expo-updates` config downloads in the background on launch
and applies on the *next* launch (so a single force-quit / reopen
cycle activates it). New TestFlight or App Store installs always
start from the IPA's JS bundle until they fetch their first OTA.

**Don't rely on OTAs to fix env-var-missing or other "broken on first
launch" issues** — the SetupRequired screen above is one such case;
new installs will see it for one launch before the OTA arrives, which
is a terrible first-run experience. For env / config changes that
affect first launch, do a proper `eas build` + `eas submit` cycle.

## 7. Account deletion (Apple Guideline 5.1.1(v))

Apple App Review will *reject* any iOS app with account creation that
doesn't also offer in-app account deletion. Time2Leave ships an
end-to-end delete-account flow:

- **Mobile**: `apps/mobile/app/trips/settings.tsx`. Reached from the
  trips list via the gear icon in the nav bar (top right). Section
  "Danger zone → Delete account" → iOS double-confirm Alert → calls
  `useAuth().deleteAccount()`, which hits `DELETE /api/v1/me`.
- **Web**: `apps/web/app/routes/settings.tsx` at `/settings`.
  Reached from the user-menu (avatar in the top right) → "Settings".
  Section "Danger zone" → "Delete account" → type-confirmation dialog
  (must type `DELETE`) → calls `useSession().deleteAccount()`, which
  hits the same `DELETE /api/v1/me`.
- **Backend**: `DELETE /api/v1/me` (`backend/app/api/auth_api.py`)
  calls `delete_user(user.id)` (`backend/app/services/users.py`).
  Cascade FKs do the rest: `users.id` is the FK target of
  `trips.user_id`, `trip_mutation_log.user_id`, and (via `trips.id`)
  `commute_samples.trip_id`, all with `ON DELETE CASCADE`. So one
  DELETE atomically removes the user, every trip they ever saved,
  every drive-time sample for those trips, and the full mutation
  audit log.

What deletion does NOT do (intentionally):
- It does **not** remove the email from `auth_allowlist`. That's
  operator-controlled; if the same person signs in again with the
  same provider, they get a fresh `users` row (with a new `id`) and
  no historical data. If you want them genuinely locked out you
  must remove them from the allowlist via the admin UI / API too.
- It does **not** add the JWT to a server-side blocklist. Stateless
  JWTs stay cryptographically valid until `exp`, but every protected
  route runs `get_user_by_id` on the claim's `uid` — which returns
  None once the row is gone — so stale tokens degrade to anonymous
  (401) on the next request.

App Review note copy (paste into App Store Connect → App Review
Information → Notes):

```
Account deletion: After sign-in, tap the gear icon in the top-right
of the Trips screen to open Settings. The "Danger zone" section at
the bottom has a "Delete account" button. Confirm twice and the
account is permanently deleted, all trips and history are removed,
and the user is signed out automatically. No email or support
contact is required.
```

## 7a. Reviewer cost guard (no Google Maps spend during review)

Every trip create or address edit normally triggers a ~1,680-call
Routes Matrix backfill (~$16.80 in Google Maps spend) plus a
Geocoding pre-flight per address. During App Review the reviewer
will exercise the create-trip / delete-account / re-create flow
repeatedly, which would otherwise drain real API budget.

**The mechanism:** the backend reads a `REVIEW_ACCOUNT_EMAILS`
comma-separated env var (configured in `backend/docker-compose.yml`).
For any listed email, the trips API transparently:

1. Routes the Routes Matrix backfill to the deterministic
   `FixtureProvider` — no Google network calls, no spend.
2. Swaps the Geocoding pre-flight for a no-op validator so test
   addresses like `"home"` / `"work"` aren't rejected.
3. Bumps the per-user trip cap to effectively unlimited
   (`_REVIEWER_UNLIMITED_CAP = 1,000,000`) so the test plan's
   create-many / delete-many cycle never hits the prod 1-trip cap.
4. Bypasses the rolling-7-day mutation quota so unlimited edits
   and swaps don't 429 mid-session.

The reviewer sees the same UX as a real user — heatmap fills in,
delete works, re-create works, swap works — but the operator pays
$0 for the review session.

Edge behavior worth knowing:

- Allowlist entries persist across deletions (the email stays in
  `auth_allowlist` even when the user row is gone), so the reviewer
  can re-create their account as many times as they want.
- The weekly Mon 01:00 PT cron filters out reviewer-owned trips
  before planning, so a reviewer who leaves a trip active over a
  Monday doesn't trigger 840 weekly calls. The on-demand
  on-create backfill (which is what actually fills the heatmap
  the reviewer sees) runs against the FixtureProvider regardless.
- Non-reviewer emails are completely unaffected — the global
  `data_provider=google` setting still routes real users to the
  real Routes API.

**Operator checklist before each App Review submission:**

1. Confirm `REVIEW_ACCOUNT_EMAILS` in `backend/docker-compose.yml`
   includes the reviewer email you'll hand to Apple (currently
   `my.app.store.reviewer@gmail.com`).
2. Confirm that same email is on `auth_allowlist` in production
   (one-time bootstrap via the admin endpoint; persists indefinitely).
3. After deploy, sign in with the reviewer account and create
   one trip — confirm the heatmap fills in (proves
   FixtureProvider is wired). If it stays "Building… 0 / 0",
   the env var likely didn't propagate; redeploy backend.

## 8. Post-launch

- Bump `version` in [`app.config.ts`](app.config.ts) per release.
  `runtimeVersion.policy = "appVersion"` ties OTA compatibility to
  this string, so any bump cuts a new OTA branch — only installs
  built off the matching binary version receive future updates on
  that channel.
- `eas build --auto-submit` chains build + submit in one command
  once you trust the pipeline.
- Watch <https://expo.dev/accounts/larskrjo/projects/time2leave>
  for build status, OTA history, logs, and downloadable artifacts.
- Sign-In Information in App Store Connect needs a working
  test account on the backend allowlist — Apple Review uses it on
  every resubmission, not just the first. Don't remove that
  allowlist entry.

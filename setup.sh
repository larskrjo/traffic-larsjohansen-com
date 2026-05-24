#!/usr/bin/env bash
#
# setup.sh — Interactive bootstrap for time2leave.
#
# Walks a fresh checkout through everything required to develop locally:
#
#   1. Verify required CLI tools (node, npm, python3, docker, gcloud).
#   2. Install the `t2l` CLI to ~/.local/bin + shell tab-completion.
#   3. Install JS workspace + backend Python dependencies.
#   4. Create / inspect backend/.env.
#   5. (Optional) Configure mobile env via GCP Secret Manager
#      (set + pull the per-mode required secrets).
#   6. Bring up the dev stack (mysql + backend in docker).
#   7. (Optional) First-time iOS dev build for the mobile app.
#
# Every step is **skippable** (y/n prompt with a sensible default) and
# **idempotent** — re-running this script never overwrites existing
# config without asking. Safe to run any time, including after pulling
# changes from upstream.
#
#   Usage: ./setup.sh
#

set -euo pipefail

# ----------------------------------------------------------------------------
# Pretty output (colors only when stdout is a TTY).
# ----------------------------------------------------------------------------
if [[ -t 1 ]]; then
    BOLD="$(printf '\033[1m')"
    DIM="$(printf '\033[2m')"
    GREEN="$(printf '\033[32m')"
    YELLOW="$(printf '\033[33m')"
    RED="$(printf '\033[31m')"
    BLUE="$(printf '\033[34m')"
    RESET="$(printf '\033[0m')"
else
    BOLD=""
    DIM=""
    GREEN=""
    YELLOW=""
    RED=""
    BLUE=""
    RESET=""
fi

step_num=0
TOTAL_STEPS=7
step() {
    step_num=$((step_num + 1))
    echo ""
    echo "${BOLD}${BLUE}══════════════════════════════════════════════════════════════${RESET}"
    echo "${BOLD}${BLUE}  Step ${step_num}/${TOTAL_STEPS}  $1${RESET}"
    echo "${BOLD}${BLUE}══════════════════════════════════════════════════════════════${RESET}"
}

substep() { echo ""; echo "${BOLD}→${RESET} $1"; }
ok()      { echo "  ${GREEN}✓${RESET} $1"; }
warn()    { echo "  ${YELLOW}⚠${RESET} $1"; }
fail()    { echo "  ${RED}✗${RESET} $1"; }
info()    { echo "  ${DIM}$1${RESET}"; }

# Yes/no prompt. Returns 0 on yes, 1 on no. Default = $2 ("y" or "n").
prompt_yn() {
    local question="$1"
    local default="${2:-y}"
    local yn_hint
    if [[ "$default" == "y" ]]; then yn_hint="[Y/n]"; else yn_hint="[y/N]"; fi
    local reply
    while true; do
        read -r -p "  ${BOLD}?${RESET} $question $yn_hint " reply || reply=""
        reply="${reply:-$default}"
        case "$reply" in
            [Yy]|[Yy][Ee][Ss]) return 0 ;;
            [Nn]|[Nn][Oo])     return 1 ;;
            *) echo "    Please answer y or n." ;;
        esac
    done
}

# Plain prompt with optional default. Echoes the value to stdout.
prompt_value() {
    local question="$1"
    local default="${2:-}"
    local reply
    if [[ -n "$default" ]]; then
        read -r -p "  ${BOLD}?${RESET} $question [$default]: " reply || reply=""
        echo "${reply:-$default}"
    else
        read -r -p "  ${BOLD}?${RESET} $question: " reply || reply=""
        echo "$reply"
    fi
}

# Check that a command exists on PATH; print an OS-aware install hint
# if not. Sets $HAS_<UPPERCASE_NAME>=1 / 0 on the global env.
check_cmd() {
    local cmd="$1"
    local hint="$2"
    local var="HAS_$(echo "$cmd" | tr '[:lower:]-' '[:upper:]_')"
    if command -v "$cmd" >/dev/null 2>&1; then
        ok "$cmd: $(command -v "$cmd")"
        eval "$var=1"
    else
        warn "$cmd: not installed"
        info "$hint"
        eval "$var=0"
    fi
}

# Resolve repo root (this file's directory) so we can `cd` to it
# regardless of where the user invoked the script from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ============================================================================
# Welcome
# ============================================================================
clear || true
cat <<EOF
${BOLD}time2leave — interactive setup${RESET}
${DIM}repo: ${SCRIPT_DIR}${RESET}

This script walks you through everything needed to develop locally:

  1. Verify required CLI tools
  2. Install the t2l CLI globally + tab-completion (so you can run
     't2l up be', 't2l deploy app --ota', etc. from anywhere)
  3. Install JS workspace + backend Python deps
  4. Create / inspect backend/.env
  5. (Optional) Configure mobile env via GCP Secret Manager
  6. Start the dev stack (mysql + backend in docker)
  7. (Optional) First-time iOS dev build for the mobile app

You can stop and re-run any time — every step prompts before touching
anything and detects work that's already been done. Re-running this
script after a 'git pull' also refreshes the t2l install if any CLI
files moved.

EOF

if ! prompt_yn "Ready to start?" "y"; then
    echo "Aborted."
    exit 0
fi

# ============================================================================
# Step 1 — Prerequisites
# ============================================================================
step "Prerequisite checks"

UNAME="$(uname -s)"
case "$UNAME" in
    Darwin) PLATFORM="macOS" ;;
    Linux)  PLATFORM="Linux" ;;
    *)      PLATFORM="$UNAME" ;;
esac
info "Detected platform: $PLATFORM"
echo ""

if [[ "$PLATFORM" == "macOS" ]]; then
    NODE_HINT="brew install node"
    PY_HINT="brew install python@3.12"
    DOCKER_HINT="brew install --cask docker  # then launch Docker Desktop"
    GCLOUD_HINT="brew install --cask google-cloud-sdk"
else
    NODE_HINT="See https://nodejs.org/en/download or your distro's package manager"
    PY_HINT="apt install python3 python3-venv  # or your distro's equivalent"
    DOCKER_HINT="See https://docs.docker.com/engine/install/"
    GCLOUD_HINT="See https://cloud.google.com/sdk/docs/install"
fi

check_cmd node     "$NODE_HINT"
check_cmd npm      "Comes with node"
check_cmd python3  "$PY_HINT"
check_cmd docker   "$DOCKER_HINT"
check_cmd gcloud   "$GCLOUD_HINT  (only required if you want to set up the mobile app)"

# Hard-fail only on what we can't proceed without. gcloud is only
# needed in step 4 — we'll re-check there.
if [[ "${HAS_NODE:-0}" -ne 1 || "${HAS_NPM:-0}" -ne 1 ]]; then
    fail "Node + npm are required. Install them and re-run."
    exit 1
fi
if [[ "${HAS_PYTHON3:-0}" -ne 1 ]]; then
    fail "python3 is required for the backend. Install it and re-run."
    exit 1
fi
if [[ "${HAS_DOCKER:-0}" -ne 1 ]]; then
    warn "docker is required for 'make dev-be' — install it before running step 6."
fi

# ============================================================================
# Step 2 — Install the t2l CLI globally + shell tab-completion
# ============================================================================
step "Install t2l CLI + tab-completion"

# Strategy:
#   - Symlink ~/.local/bin/t2l → $SCRIPT_DIR/t2l so the CLI auto-updates
#     whenever you `git pull` (no copy step).
#   - Append an idempotent marker-delimited block to the user's shell rc
#     that puts ~/.local/bin on PATH and sources the completion file from
#     the repo. Same auto-update story — pulling new completions in this
#     repo updates completion behaviour on the next new shell.
#   - Re-running setup.sh rewrites the block in place, so moving the
#     repo elsewhere on disk is fixed by one re-run.

BIN_DIR="$HOME/.local/bin"
T2L_SRC="$SCRIPT_DIR/t2l"
T2L_LINK="$BIN_DIR/t2l"
MARKER="time2leave CLI"
BEGIN_LINE="# >>> ${MARKER} >>>"
END_LINE="# <<< ${MARKER} <<<"

if [[ ! -x "$T2L_SRC" ]]; then
    fail "Can't find an executable t2l at $T2L_SRC — repo is in a weird state."
    info "Did the file lose its +x bit? Run: chmod +x t2l   (then re-run ./setup.sh)"
    exit 1
fi

# Strip any prior block from the rc file. Uses /BEGIN/,/END/d which is
# portable across BSD sed (macOS) and GNU sed (Linux).
strip_block() {
    local file="$1"
    [[ -f "$file" ]] || return 0
    grep -qF "$BEGIN_LINE" "$file" || return 0
    local tmp
    tmp="$(mktemp)"
    sed "/^${BEGIN_LINE}\$/,/^${END_LINE}\$/d" "$file" > "$tmp"
    # Trim trailing blank lines we may have just exposed, keep file tidy.
    awk 'BEGIN{n=0} {a[NR]=$0} END{i=NR; while(i>0 && a[i]==""){i--}; for(j=1;j<=i;j++) print a[j]}' "$tmp" > "$file"
    rm -f "$tmp"
}

# Write the block fresh. $1 = rc file, $2 = completion file extension
# (zsh or bash). Block is plain POSIX-sh so it's safe in either shell.
write_block() {
    local file="$1"
    local ext="$2"
    local completion="$SCRIPT_DIR/scripts/t2l-complete.${ext}"
    {
        echo ""
        echo "$BEGIN_LINE"
        echo "# Managed by setup.sh in $SCRIPT_DIR — safe to delete; re-run ./setup.sh to restore."
        echo "export PATH=\"\$HOME/.local/bin:\$PATH\""
        echo "[ -f \"$completion\" ] && . \"$completion\""
        echo "$END_LINE"
    } >> "$file"
}

substep "Symlink $T2L_LINK → $T2L_SRC"
mkdir -p "$BIN_DIR"
if [[ -L "$T2L_LINK" ]]; then
    current="$(readlink "$T2L_LINK")"
    if [[ "$current" == "$T2L_SRC" ]]; then
        ok "Symlink already points at this checkout."
    else
        info "Existing symlink points elsewhere ($current) — refreshing."
        ln -sfn "$T2L_SRC" "$T2L_LINK"
        ok "Symlink updated."
    fi
elif [[ -e "$T2L_LINK" ]]; then
    warn "$T2L_LINK exists and is NOT a symlink."
    if prompt_yn "Replace it with a symlink to $T2L_SRC?" "y"; then
        rm -f "$T2L_LINK"
        ln -sfn "$T2L_SRC" "$T2L_LINK"
        ok "Replaced."
    else
        fail "Refusing to clobber. The t2l command will not be on PATH."
    fi
else
    ln -sfn "$T2L_SRC" "$T2L_LINK"
    ok "Symlink created."
fi

substep "Wire up your shell rc (PATH + tab-completion)"
USER_SHELL="${SHELL##*/}"
info "Detected login shell: $USER_SHELL"

# Pick rc files. We write to whichever match $SHELL but also pick up the
# other one if it exists, so switching shells later still works.
RC_FILES=()
if [[ "$USER_SHELL" == "zsh" || -f "$HOME/.zshrc" ]]; then
    RC_FILES+=("$HOME/.zshrc:zsh")
fi
if [[ "$USER_SHELL" == "bash" ]]; then
    # bash login shells on macOS read .bash_profile; .bashrc elsewhere.
    if [[ "$PLATFORM" == "macOS" && -f "$HOME/.bash_profile" ]]; then
        RC_FILES+=("$HOME/.bash_profile:bash")
    elif [[ -f "$HOME/.bashrc" ]]; then
        RC_FILES+=("$HOME/.bashrc:bash")
    elif [[ "$PLATFORM" == "macOS" ]]; then
        RC_FILES+=("$HOME/.bash_profile:bash")
    else
        RC_FILES+=("$HOME/.bashrc:bash")
    fi
elif [[ -f "$HOME/.bashrc" ]]; then
    # User is on zsh but has a .bashrc around — keep it in sync defensively.
    RC_FILES+=("$HOME/.bashrc:bash")
fi

if (( ${#RC_FILES[@]} == 0 )); then
    warn "Couldn't figure out which shell rc to edit. Add this line to it manually:"
    info "    [ -f \"$SCRIPT_DIR/scripts/t2l-complete.$USER_SHELL\" ] && . \"$SCRIPT_DIR/scripts/t2l-complete.$USER_SHELL\""
else
    for entry in "${RC_FILES[@]}"; do
        file="${entry%%:*}"
        ext="${entry##*:}"
        touch "$file"
        strip_block "$file"
        write_block "$file" "$ext"
        ok "Updated $file"
    done
fi

substep "Activate the changes in this shell session"
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    info "Your current shell still has the old PATH. To use 't2l' right now"
    info "without opening a new terminal, run:"
    echo ""
    if [[ "$USER_SHELL" == "zsh" ]]; then
        echo "    source ~/.zshrc"
    elif [[ "$USER_SHELL" == "bash" && "$PLATFORM" == "macOS" ]]; then
        echo "    source ~/.bash_profile"
    elif [[ "$USER_SHELL" == "bash" ]]; then
        echo "    source ~/.bashrc"
    else
        echo "    exec \$SHELL -l"
    fi
    echo ""
else
    ok "$BIN_DIR is already on this shell's PATH — try: t2l --help"
fi

# ============================================================================
# Step 3 — Install dependencies
# ============================================================================
step "Install dependencies"

substep "JS workspace (apps/web, apps/mobile, packages/shared)"
if [[ -d node_modules && -d apps/web/node_modules ]]; then
    ok "node_modules already present"
    if prompt_yn "Re-run 'npm install' anyway (e.g. after pulling new deps)?" "n"; then
        npm install
    fi
else
    info "This pulls all workspace deps (~1-2 minutes on a clean checkout)."
    if prompt_yn "Run 'npm install' now?" "y"; then
        npm install
    else
        warn "Skipping — run 'npm install' manually before starting any of the apps."
    fi
fi

substep "Backend Python venv (backend/.venv) + dev deps"
if [[ -d backend/.venv ]]; then
    ok "backend/.venv already exists"
    if prompt_yn "Reinstall deps into it (refresh after pulling)?" "n"; then
        backend/.venv/bin/pip install -e "backend/.[dev]"
    fi
else
    info "Creates backend/.venv and installs the package in editable mode with [dev] extras."
    if prompt_yn "Create the venv and install deps now?" "y"; then
        python3 -m venv backend/.venv
        backend/.venv/bin/pip install --upgrade pip
        backend/.venv/bin/pip install -e "backend/.[dev]"
    else
        warn "Skipping — run 'make install-be' manually before backend tests."
    fi
fi

# ============================================================================
# Step 4 — Backend env
# ============================================================================
step "Backend env (backend/.env)"

if [[ -f backend/.env ]]; then
    ok "backend/.env already exists"
    info "Edit it directly if you need to change ADMIN_EMAILS, GOOGLE_OAUTH_CLIENT_ID,"
    info "DATA_PROVIDER, etc. Defaults work for local dev with the fixture provider."
    if prompt_yn "Show its contents now?" "n"; then
        echo ""
        sed 's/^/    /' backend/.env
        echo ""
    fi
else
    info "backend/.env doesn't exist yet. The example file has working defaults"
    info "for local dev (DATA_PROVIDER=fixture, ENABLE_DEV_LOGIN=true,"
    info "ADMIN_EMAILS=dev@example.com)."
    if prompt_yn "Create backend/.env from backend/.env.example?" "y"; then
        cp backend/.env.example backend/.env
        ok "Created backend/.env"
        info "Tweak it later if you need to change anything (it is gitignored)."
    else
        warn "Skipping — backend/config.py defaults will apply, but you may want a .env later."
    fi
fi

# ============================================================================
# Step 5 — Mobile env via GCP Secret Manager
# ============================================================================
step "Mobile env (GCP Secret Manager)"

info "The mobile app's env is strict: every required EXPO_PUBLIC_* var lives in"
info "GCP Secret Manager and is pulled into apps/mobile/.env via:"
info "    npm run env:pull:mobile -- <local|prod>"
info "This step walks you through creating those secrets and doing the first pull."
echo ""

if ! prompt_yn "Set up the mobile app now?" "n"; then
    info "Skipped. Run this script again any time to do the mobile setup."
else
    if [[ "${HAS_GCLOUD:-0}" -ne 1 ]]; then
        fail "gcloud is required for the mobile setup."
        info "Install: $GCLOUD_HINT"
        info "Then re-run ./setup.sh"
        exit 1
    fi

    substep "GCP authentication"
    ACTIVE_ACCOUNT="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null || true)"
    if [[ -n "$ACTIVE_ACCOUNT" ]]; then
        ok "Logged in as: $ACTIVE_ACCOUNT"
        if prompt_yn "Switch to a different account?" "n"; then
            gcloud auth login
        fi
    else
        warn "No active gcloud account."
        if prompt_yn "Run 'gcloud auth login' now?" "y"; then
            gcloud auth login
        else
            fail "Mobile setup requires authentication. Aborting this step."
            exit 1
        fi
    fi

    substep "GCP project"
    CURRENT_PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
    if [[ -n "$CURRENT_PROJECT" && "$CURRENT_PROJECT" != "(unset)" ]]; then
        ok "Current project: $CURRENT_PROJECT"
        if prompt_yn "Use this project?" "y"; then
            PROJECT="$CURRENT_PROJECT"
        else
            PROJECT="$(prompt_value "Project ID")"
            gcloud config set project "$PROJECT" >/dev/null
            ok "Set project to $PROJECT"
        fi
    else
        warn "No project configured."
        PROJECT="$(prompt_value "Enter your GCP project ID")"
        if [[ -z "$PROJECT" ]]; then
            fail "Project ID is required."
            exit 1
        fi
        gcloud config set project "$PROJECT" >/dev/null
        ok "Set project to $PROJECT"
    fi

    substep "Enable Secret Manager API"
    info "Idempotent — does nothing if already enabled."
    if prompt_yn "Run 'gcloud services enable secretmanager.googleapis.com'?" "y"; then
        gcloud services enable secretmanager.googleapis.com --project="$PROJECT"
        ok "Secret Manager API ready on $PROJECT"
    fi

    substep "Pick a mode"
    echo ""
    echo "    ${BOLD}local${RESET} — dev-login is the only sign-in path. No Google Cloud OAuth"
    echo "            client setup needed. Best for day-to-day UI iteration."
    echo "            Required vars: 3"
    echo ""
    echo "    ${BOLD}prod${RESET}  — native Google Sign-In is the only sign-in path. Used for"
    echo "            TestFlight / Play Internal Testing builds."
    echo "            Required vars: 4 (incl. iOS + Web OAuth client IDs)"
    echo ""
    while true; do
        MODE="$(prompt_value "Mode" "local")"
        case "$MODE" in
            local|prod) break ;;
            *) echo "    Please answer 'local' or 'prod'." ;;
        esac
    done
    ok "Mode = $MODE"

    # Per-var hints. Keys must exactly match the names in
    # apps/mobile/src/config/env.ts and apps/mobile/scripts/pull-env.sh.
    declare -a VARS
    if [[ "$MODE" == "local" ]]; then
        VARS=(
            EXPO_PUBLIC_API_BASE_URL
            EXPO_PUBLIC_GOOGLE_MAPS_API_KEY
            EXPO_PUBLIC_DEV_LOGIN_EMAIL
        )
    else
        VARS=(
            EXPO_PUBLIC_API_BASE_URL
            EXPO_PUBLIC_GOOGLE_MAPS_API_KEY
            EXPO_PUBLIC_GOOGLE_OAUTH_WEB_CLIENT_ID
            EXPO_PUBLIC_GOOGLE_OAUTH_IOS_CLIENT_ID
        )
    fi

    var_hint() {
        case "$1" in
            EXPO_PUBLIC_API_BASE_URL)
                echo "Backend root URL the phone hits. From a real phone use your laptop's LAN IP"
                echo "    (e.g. http://192.168.1.42:8000), NOT localhost. From the iOS simulator"
                echo "    'http://localhost:8000' works; from the Android emulator use"
                echo "    'http://10.0.2.2:8000'. Find your LAN IP with: ipconfig getifaddr en0"
                ;;
            EXPO_PUBLIC_GOOGLE_MAPS_API_KEY)
                echo "Google Maps Platform API key with the Places API enabled. Used by the"
                echo "    new-trip address autocomplete. Get one at:"
                echo "    https://console.cloud.google.com/google/maps-apis/credentials"
                ;;
            EXPO_PUBLIC_DEV_LOGIN_EMAIL)
                echo "Email used by POST /api/v1/auth/dev-login. Must be on the backend's auth"
                echo "    allowlist (ADMIN_EMAILS or AUTH_ALLOWLIST_BOOTSTRAP in backend/.env)."
                echo "    For local dev, 'dev@example.com' (the seeded user) is a safe default."
                ;;
            EXPO_PUBLIC_GOOGLE_OAUTH_WEB_CLIENT_ID)
                echo "Web OAuth client ID from Google Cloud Console > APIs & Services >"
                echo "    Credentials. Used as 'webClientId' even on iOS — it becomes the 'aud'"
                echo "    claim of the ID token, which the backend verifies against its"
                echo "    GOOGLE_OAUTH_CLIENT_ID list. Use the SAME web client ID as apps/web."
                echo "    Format: 123456-abc.apps.googleusercontent.com"
                ;;
            EXPO_PUBLIC_GOOGLE_OAUTH_IOS_CLIENT_ID)
                echo "iOS OAuth client ID for bundle 'com.time2leave.app'. apps/mobile/app.config.ts"
                echo "    auto-derives the iOS URL scheme from this and registers it with the"
                echo "    @react-native-google-signin config plugin."
                echo "    Format: 123456-xyz.apps.googleusercontent.com"
                ;;
        esac
    }

    substep "Set or rotate the ${#VARS[@]} required secret(s)"
    info "Each value is read silently — it never appears on screen and never lands"
    info "in shell history."

    for var in "${VARS[@]}"; do
        echo ""
        secret="time2leave-mobile-${MODE}-${var}"
        if gcloud secrets describe "$secret" --project="$PROJECT" >/dev/null 2>&1; then
            ok "$secret already exists"
            echo "    ${DIM}$(var_hint "$var")${RESET}"
            if prompt_yn "    Rotate it (set a new value)?" "n"; then
                bash apps/mobile/scripts/set-env-var.sh "$MODE" "$var"
            fi
        else
            warn "$secret does not exist yet"
            echo "    ${DIM}$(var_hint "$var")${RESET}"
            if prompt_yn "    Set it now?" "y"; then
                bash apps/mobile/scripts/set-env-var.sh "$MODE" "$var"
            else
                warn "    Skipping. The mobile app will refuse to start until this is set."
            fi
        fi
    done

    substep "Pull secrets into apps/mobile/.env"
    if prompt_yn "Run 'npm run env:pull:mobile -- $MODE' now?" "y"; then
        if bash apps/mobile/scripts/pull-env.sh "$MODE"; then
            ok "apps/mobile/.env hydrated for mode = $MODE"
        else
            warn "Pull failed — see the error above. You can re-run with:"
            info "    npm run env:pull:mobile -- $MODE"
        fi
    fi
fi

# ============================================================================
# Step 6 — Bring up the dev stack
# ============================================================================
step "Start the dev stack"

if [[ "${HAS_DOCKER:-0}" -ne 1 ]]; then
    warn "docker is not installed — skipping. Install Docker Desktop and run 'make dev-be' later."
else
    info "Starts mysql + backend in docker (detached). Schema + dev user are seeded"
    info "automatically on the first run."
    if prompt_yn "Run 'make dev-be' now?" "y"; then
        make dev-be
    else
        info "Skipped. Start it later with: make dev-be"
    fi
fi

# ============================================================================
# Step 7 — First-time iOS dev build
# ============================================================================
step "First-time iOS dev build (mobile app)"

info "The mobile app runs as a development build (not Expo Go) because it"
info "ships native modules Expo Go can't host. The first build takes ~5–10"
info "minutes (xcodebuild + CocoaPods); afterwards 'npm run dev:mobile' just"
info "starts Metro and you tap the installed app on the simulator."
echo ""

if [[ ! -f apps/mobile/.env ]]; then
    warn "apps/mobile/.env doesn't exist yet — run step 5 of setup first, then"
    warn "re-run this script to do the iOS build."
elif [[ "$PLATFORM" != "macOS" ]]; then
    warn "iOS builds require macOS + Xcode — skipping on $PLATFORM."
    info "On Linux you can still run the Android build via 'npm run build:android:mobile'"
    info "(needs Android Studio + ANDROID_HOME). Or use EAS for cloud builds:"
    info "    eas build --profile development --platform ios"
elif ! command -v xcodebuild >/dev/null 2>&1; then
    warn "Xcode is not installed — skipping the iOS build."
    info "Install Xcode from the App Store (~15 GB) and the Command Line Tools:"
    info "    xcode-select --install"
    info "Then run 'npm run build:ios:mobile' yourself."
elif ! command -v pod >/dev/null 2>&1; then
    warn "CocoaPods is not installed — skipping the iOS build."
    info "Install with:  brew install cocoapods   # or: sudo gem install cocoapods"
    info "Then run 'npm run build:ios:mobile' yourself."
else
    if prompt_yn "Run 'npm run build:ios:mobile' now (~5–10 min)?" "n"; then
        info "Building... Watch the output in this terminal. The simulator will"
        info "open and the app will install + launch on success."
        cd apps/mobile && npm run ios && cd "$SCRIPT_DIR"
        ok "Built + launched. Day-to-day from now on: 'npm run dev:mobile'."
    else
        info "Skipped. Run it later with: npm run build:ios:mobile"
    fi
fi

# ============================================================================
# Done
# ============================================================================
echo ""
echo "${BOLD}${GREEN}══════════════════════════════════════════════════════════════${RESET}"
echo "${BOLD}${GREEN}  All done.${RESET}"
echo "${BOLD}${GREEN}══════════════════════════════════════════════════════════════${RESET}"
echo ""
echo "${BOLD}Next:${RESET}"
echo "  ${DIM}# Everything in one CLI (tab-complete the subcommands):${RESET}"
echo "  t2l --help                         ${DIM}list every command${RESET}"
echo "  t2l up be                          ${DIM}local backend (mysql + api in Docker)${RESET}"
echo "  t2l up fe                          ${DIM}local web on http://localhost:5173${RESET}"
echo "  t2l up ios                         ${DIM}Expo Metro for the mobile app${RESET}"
echo "  t2l deploy app --ota --message     ${DIM}OTA update via EAS Update${RESET}"
echo ""
echo "  ${DIM}# If 't2l' isn't found yet, open a new terminal or:${RESET}"
echo "  source ~/.zshrc                    ${DIM}(or ~/.bash_profile / ~/.bashrc)${RESET}"
echo ""
echo "${BOLD}Docs:${RESET}"
echo "  README.md                          ${DIM}top-level overview + CLI reference${RESET}"
echo "  apps/mobile/README.md              ${DIM}mobile setup + dev-build workflow${RESET}"
echo "  make help                          ${DIM}lower-level Make targets${RESET}"
echo ""
echo "${BOLD}Re-run anytime:${RESET}  ./setup.sh   ${DIM}(refreshes the t2l install + completion)${RESET}"
echo ""

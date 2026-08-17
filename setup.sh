#!/usr/bin/env bash
#
# tg-dl — one-shot setup wizard for a Linux server.
#
# Usage:
#   bash setup.sh                 # interactive wizard
#   NONINTERACTIVE=1 bash setup.sh # use env vars / defaults, no prompts
#
# Supported env vars (for non-interactive / CI use):
#   BOT_TOKEN, OWNER_ID, CHANNEL_ID, TELEGRAM_API_ID, TELEGRAM_API_HASH,
#   ALLOWED_USERS, DOWNLOAD_DIR, NO_SYSTEMD=1, SKIP_DEPS=1, SKIP_START=1

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths & helpers
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_DIR="${SCRIPT_DIR}/aria2-bot"
ENV_FILE="${BOT_DIR}/.env"
CONF_FILE="${BOT_DIR}/aria2.conf"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { printf "${GREEN}[INFO]${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}[WARN]${NC} %s\n" "$*"; }
err()   { printf "${RED}[ERROR]${NC} %s\n" "$*"; }
step()  { printf "\n${CYAN}==> ${NC}%s\n" "$*"; }

# Prompt helper: asks and returns the value in REPLY (uses default if empty).
ask() {
    local prompt="$1" default="$2" input
    if [[ "${NONINTERACTIVE:-0}" == "1" ]]; then
        REPLY="${default}"
        return 0
    fi
    if [[ -n "${default}" ]]; then
        read -r -p "$(printf "${CYAN}${prompt}${NC} [${default}]: ")" input || true
    else
        read -r -p "$(printf "${CYAN}${prompt}${NC}: ")" input || true
    fi
    REPLY="${input:-${default}}"
}

# ---------------------------------------------------------------------------
# 0. Check we are in the repo
# ---------------------------------------------------------------------------
step "Checking repository layout"
if [[ ! -d "${BOT_DIR}" ]]; then
    err "Cannot find ${BOT_DIR}. Run this script from the repo root."
    exit 1
fi

# ---------------------------------------------------------------------------
# 1. Detect OS + package manager
# ---------------------------------------------------------------------------
step "Detecting operating system"
if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    info "Distro: ${PRETTY_NAME:-unknown}"
else
    ID="unknown"
fi

detect_installer() {
    if command -v apt-get >/dev/null 2>&1; then echo "apt-get"
    elif command -v dnf >/dev/null 2>&1; then echo "dnf"
    elif command -v yum >/dev/null 2>&1; then echo "yum"
    elif command -v pacman >/dev/null 2>&1; then echo "pacman"
    elif command -v zypper >/dev/null 2>&1; then echo "zypper"
    elif command -v apk >/dev/null 2>&1; then echo "apk"
    else echo "unknown"; fi
}
INSTALLER="$(detect_installer)"
if [[ "${INSTALLER}" == "unknown" ]]; then
    err "No supported package manager found. Install aria2, megatools, ffmpeg, python3 and yt-dlp manually, then re-run with SKIP_DEPS=1."
fi
info "Package manager: ${INSTALLER}"

# ---------------------------------------------------------------------------
# 2. Install system dependencies
# ---------------------------------------------------------------------------
if [[ "${SKIP_DEPS:-0}" != "1" ]]; then
    step "Installing system dependencies (aria2, megatools, ffmpeg, python3, yt-dlp)"
    case "${INSTALLER}" in
        apt-get)
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -y
            apt-get install -y aria2 megatools ffmpeg python3 python3-pip python3-venv curl
            ;;
        dnf|yum)
            dnf install -y aria2 megatools ffmpeg python3 python3-pip curl
            ;;
        pacman)
            pacman -S --noconfirm aria2 megatools ffmpeg python python-pip curl
            ;;
        zypper)
            zypper -n install aria2 megatools ffmpeg python3 python3-pip curl
            ;;
        apk)
            apk add --no-cache aria2 megatools ffmpeg python3 py3-pip curl
            ;;
    esac

    if command -v yt-dlp >/dev/null 2>&1; then
        info "yt-dlp already present: $(yt-dlp --version)"
    else
        info "Installing yt-dlp"
        python3 -m pip install --break-system-packages -U yt-dlp || python3 -m pip install -U yt-dlp
    fi
else
    info "Skipping system dependency install (SKIP_DEPS=1)"
fi

# ---------------------------------------------------------------------------
# 3. Install python requirements
# ---------------------------------------------------------------------------
step "Installing python requirements"
if ! command -v python3 >/dev/null 2>&1; then
    err "python3 not found."
    exit 1
fi

PYTHON_BIN="python3"
USE_VENV=0
if [[ "${INSTALLER}" == "apk" || "${ID}" == "alpine" ]]; then
    info "Alpine detected: installing requirements globally"
    python3 -m pip install --break-system-packages -r "${BOT_DIR}/requirements.txt" || \
        python3 -m pip install -r "${BOT_DIR}/requirements.txt"
elif [[ -x "${BOT_DIR}/.venv/bin/python" && -x "${BOT_DIR}/.venv/bin/pip" ]]; then
    info "Existing virtual environment found at ${BOT_DIR}/.venv"
    USE_VENV=1
else
    info "Creating virtual environment at ${BOT_DIR}/.venv"
    if python3 -m venv "${BOT_DIR}/.venv" && [[ -x "${BOT_DIR}/.venv/bin/pip" ]]; then
        USE_VENV=1
    else
        warn "venv creation failed (missing python3-venv?) — installing globally instead"
        python3 -m pip install --break-system-packages -r "${BOT_DIR}/requirements.txt" || \
            python3 -m pip install -r "${BOT_DIR}/requirements.txt"
    fi
fi
if [[ "${USE_VENV}" == "1" ]]; then
    "${BOT_DIR}/.venv/bin/pip" install --upgrade pip
    "${BOT_DIR}/.venv/bin/pip" install -r "${BOT_DIR}/requirements.txt"
    PYTHON_BIN="${BOT_DIR}/.venv/bin/python"
fi

# ---------------------------------------------------------------------------
# 4. Gather Telegram configuration
# ---------------------------------------------------------------------------
step "Gathering Telegram configuration"

# Pull existing values from a previous .env so the wizard can pre-fill them.
if [[ -f "${ENV_FILE}" ]]; then
    warn "Existing .env found — pre-filling defaults from it (enter to keep)."
fi
env_val() { # $1 = key, reads from existing .env
    local key="$1"
    if [[ -f "${ENV_FILE}" ]]; then
        sed -n "s/^${key}=//p" "${ENV_FILE}" | head -n1
    fi
    return 0
}

ask "BOT_TOKEN (from @BotFather)"                 "$(env_val BOT_TOKEN)"
BOT_TOKEN="${REPLY}"
ask "OWNER_ID (your numeric Telegram ID)"         "$(env_val OWNER_ID)"
OWNER_ID="${REPLY}"
ask "CHANNEL_ID (private channel, bot must be admin)" "$(env_val CHANNEL_ID)"
CHANNEL_ID="${REPLY}"
ask "TELEGRAM_API_ID (from my.telegram.org, for >49MiB uploads)" "$(env_val TELEGRAM_API_ID)"
TELEGRAM_API_ID="${REPLY}"
ask "TELEGRAM_API_HASH"                           "$(env_val TELEGRAM_API_HASH)"
TELEGRAM_API_HASH="${REPLY}"
ask "ALLOWED_USERS (comma-separated, empty=everyone)" "$(env_val ALLOWED_USERS)"
ALLOWED_USERS="${REPLY}"

# ---------------------------------------------------------------------------
# 4b. Optional media-downloader services (bypass YouTube bot-check)
#
#   cobalt  — self-hosted via docker compose, tunnels media through its own
#             server so your IP is never seen by YouTube. Recommended.
#   koutube — Cloudflare Workers service that returns direct links via
#             Invidious. Requires a Cloudflare account (deploy manually).
# ---------------------------------------------------------------------------
COBALT_API_URL="${COBALT_API_URL:-$(env_val COBALT_API_URL)}"
KOUTUBE_BASE_URL="${KOUTUBE_BASE_URL:-$(env_val KOUTUBE_BASE_URL)}"

deploy_cobalt() {
    step "Deploying cobalt via docker compose"
    if ! command -v docker >/dev/null 2>&1; then
        err "docker not found. Install docker first, then re-run this wizard (or set COBALT_API_URL manually)."
        return 1
    fi
    local cobalt_dir="${BOT_DIR}/cobalt"
    mkdir -p "${cobalt_dir}"
    cat > "${cobalt_dir}/docker-compose.yml" <<'EOF'
services:
    cobalt:
        image: ghcr.io/imputnet/cobalt:11
        init: true
        read_only: true
        restart: unless-stopped
        container_name: cobalt
        ports:
            - 127.0.0.1:9000:9000/tcp
        environment:
            API_URL: "http://127.0.0.1:9000/"
EOF
    docker compose -f "${cobalt_dir}/docker-compose.yml" up -d || {
        docker-compose -f "${cobalt_dir}/docker-compose.yml" up -d
    }
    sleep 3
    COBALT_API_URL="http://127.0.0.1:9000"
    info "cobalt deployed locally at ${COBALT_API_URL} (config: ${cobalt_dir}/docker-compose.yml)"
}

if [[ "${NONINTERACTIVE:-0}" != "1" ]]; then
    ask "Deploy cobalt (self-hosted YouTube downloader, Docker)? [y/N]" ""
    if [[ "${REPLY,,}" == "y" || "${REPLY,,}" == "yes" ]]; then
        deploy_cobalt || true
    fi
    if [[ -z "${COBALT_API_URL}" ]]; then
        ask "Cobalt instance URL (empty=skip; e.g. http://127.0.0.1:9000)" ""
        COBALT_API_URL="${REPLY}"
    fi
    if [[ -n "${KOUTUBE_BASE_URL}" && "${KOUTUBE_BASE_URL}" != "public" ]]; then
        : # keep existing koutube URL
    else
        ask "Koutube for YouTube? (self-hosted URL, 'public' for koutu.be, empty=skip)" "${KOUTUBE_BASE_URL:-}"
        if [[ -n "${REPLY}" ]]; then
            if [[ "${REPLY,,}" == "public" ]]; then
                KOUTUBE_BASE_URL="https://koutu.be"
            else
                KOUTUBE_BASE_URL="${REPLY}"
            fi
        fi
    fi
fi

if [[ -z "${BOT_TOKEN}" || "${BOT_TOKEN}" == "your-bot-token-here" ]]; then
    err "BOT_TOKEN is required. Get one from https://t.me/BotFather"
    exit 1
fi

# ---------------------------------------------------------------------------
# 5. Choose download directory
# ---------------------------------------------------------------------------
step "Choosing download directory"
ask "DOWNLOAD_DIR (temp storage, cleaned after upload)" "$(env_val DOWNLOAD_DIR)"
DOWNLOAD_DIR="${REPLY:-${BOT_DIR}/downloads}"
mkdir -p "${DOWNLOAD_DIR}"

# ---------------------------------------------------------------------------
# 6. Generate .env
# ---------------------------------------------------------------------------
step "Writing ${ENV_FILE}"
cat > "${ENV_FILE}" <<EOF
# Generated by setup.sh on $(date)
BOT_TOKEN=${BOT_TOKEN}
OWNER_ID=${OWNER_ID}
ALLOWED_USERS=${ALLOWED_USERS}

# Private channel used to store downloaded files + logs. Add the bot as admin.
CHANNEL_ID=${CHANNEL_ID}

# aria2 RPC settings (must match aria2.conf)
ARIA2_RPC_URL=http://127.0.0.1:6800/jsonrpc
ARIA2_SECRET=aria2botsecret

# Directory where downloaded files are stored
DOWNLOAD_DIR=${DOWNLOAD_DIR}

# MTProto credentials for files up to 2 GiB (from https://my.telegram.org)
TELEGRAM_API_ID=${TELEGRAM_API_ID}
TELEGRAM_API_HASH=${TELEGRAM_API_HASH}

# Cooldown between requests for non-authorized users (seconds)
COOLDOWN_SECONDS=10

# Channel cache lifetime for re-sending the same link (days)
CACHE_TTL_DAYS=7

# Split threshold / part size for very large files (bytes)
SPLIT_THRESHOLD=2147483648
SPLIT_PART_SIZE=1610612736

# Timeout for external tools (yt-dlp etc.)
PROCESS_MAX_TIMEOUT=3700

# Proxy for yt-dlp / direct downloads (optional)
HTTP_PROXY=

# Comma-separated proxy list used by yt-dlp, rotated per request.
# Upload proxies.json to the bot to manage these at runtime instead.
YTDLP_PROXIES=

# Optional cookies file for yt-dlp (cookies.txt exported from your browser)
YTDLP_COOKIES=

# Koutube instance for direct YouTube links (self-hosted or public koutu.be).
# Empty disables koutube (falls back to dlapi / yt-dlp).
KOUTUBE_BASE_URL=${KOUTUBE_BASE_URL}

# Self-hosted cobalt instance (https://github.com/imputnet/cobalt).
# Cobalt tunnels media through its own server — YouTube never sees your IP.
# Empty disables cobalt.
COBALT_API_URL=${COBALT_API_URL}
EOF
chmod 600 "${ENV_FILE}"
info ".env written"

# ---------------------------------------------------------------------------
# 7. Point aria2.conf at the chosen download dir
# ---------------------------------------------------------------------------
step "Patching aria2.conf download dir"
if [[ -f "${CONF_FILE}" ]]; then
    grep -q '^dir=' "${CONF_FILE}" || echo "dir=${DOWNLOAD_DIR}" >> "${CONF_FILE}"
    sed -i "s|^dir=.*|dir=${DOWNLOAD_DIR}|" "${CONF_FILE}"
else
    warn "aria2.conf missing — writing a default one"
    cat > "${CONF_FILE}" <<EOF
enable-rpc=true
rpc-listen-all=true
rpc-listen-port=6800
rpc-secret=aria2botsecret
rpc-allow-origin-all=true
dir=${DOWNLOAD_DIR}
max-concurrent-downloads=5
continue=true
input-file=${BOT_DIR}/session.txt
save-session=${BOT_DIR}/session.txt
save-session-interval=60
EOF
fi
info "aria2.conf updated"

# ---------------------------------------------------------------------------
# 8. Start aria2 daemon
# ---------------------------------------------------------------------------
step "Starting aria2 RPC daemon"
if pgrep -f "aria2c.*aria2.conf" >/dev/null 2>&1; then
    info "aria2 already running"
else
    if command -v aria2c >/dev/null 2>&1; then
        aria2c --conf-path="${CONF_FILE}" >/dev/null 2>&1 &
        disown
        sleep 1
        info "aria2 started (RPC on 127.0.0.1:6800)"
    else
        warn "aria2c not found — start it later:  aria2c --conf-path=${CONF_FILE}"
    fi
fi

# ---------------------------------------------------------------------------
# 9. Optional systemd service
# ---------------------------------------------------------------------------
if [[ "${NO_SYSTEMD:-0}" != "1" ]] && command -v systemctl >/dev/null 2>&1 && [[ "$(id -u)" == "0" ]]; then
    step "Installing systemd service 'tg-dl'"
    SERVICE="/etc/systemd/system/tg-dl.service"
    if [[ ! -f "${SERVICE}" ]]; then
        cat > "${SERVICE}" <<EOF
[Unit]
Description=Telegram download manager bot (tg-dl)
After=network.target

[Service]
Type=simple
WorkingDirectory=${BOT_DIR}
ExecStart=${PYTHON_BIN} bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
        systemctl daemon-reload
        systemctl enable --now tg-dl
        info "systemd service installed and started:  systemctl status tg-dl"
    else
        warn "Systemd service already exists — skipping (edit ${SERVICE} manually if needed)"
    fi
else
    step "Starting the bot directly (no systemd)"
    if [[ "${SKIP_START:-0}" != "1" ]]; then
        cd "${BOT_DIR}"
        if [[ -n "${BOT_TOKEN}" ]]; then
            nohup "${PYTHON_BIN}" bot.py >"${BOT_DIR}/bot.log" 2>&1 &
            disown
            sleep 2
            info "Bot started in background — logs: ${BOT_DIR}/bot.log"
        fi
    fi
fi

# ---------------------------------------------------------------------------
# 10. Summary
# ---------------------------------------------------------------------------
step "Setup complete"
cat <<EOF

${GREEN}Your bot is configured:${NC}
  Bot dir:       ${BOT_DIR}
  Config file:   ${ENV_FILE}
  Download dir:  ${DOWNLOAD_DIR}
  aria2 RPC:     127.0.0.1:6800 (secret: aria2botsecret)
  Cobalt:        ${COBALT_API_URL:-disabled}
  Koutube:       ${KOUTUBE_BASE_URL:-disabled}

Next steps:
  1. Open Telegram and message your bot.
  2. Make sure the bot is an ADMIN of channel ${CHANNEL_ID:-<your channel>}.
  3. For YouTube bot-check issues, send cookies.txt / proxies.json to the bot.

To check the bot:   ${PYTHON_BIN} ${BOT_DIR}/bot.py  (run in foreground)
To view logs:       tail -f ${BOT_DIR}/bot.log
${NC}
EOF

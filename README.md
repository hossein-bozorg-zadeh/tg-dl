# tg-dl — Telegram Download Manager Bot

A full-featured Telegram download manager that runs on any Linux server. Powered by **aria2**, **yt-dlp**, **megatools** and **Telethon**.

Send any link (or a `.torrent` file) to the bot and it downloads the file on the server, then uploads it back to you on Telegram — with live progress bars, format/quality pickers for media, and a 7-day channel cache.

## Features

- **Downloads everything**
  - HTTP / HTTPS / FTP direct links
  - Magnet links & `.torrent` files (via aria2)
  - Mega.nz (via megatools)
  - MediaFire (direct-link resolver)
  - YouTube — quality/format selection menu (1080p/720p/... + MP3)
  - 1000+ sites supported by yt-dlp (Twitch, Vimeo, TikTok, Instagram, ...)
- **Quality & format picker** — when a source exposes multiple formats, the bot shows a button menu to choose from
- **YouTube bot-detection workarounds** — self-hosted cobalt instance (tunnels media through its own server), self-hosted Koutube instance (direct links via Invidious), cookies file, rotating proxy list, and a server-side download API fallback (dlapi) so your server's IP doesn't get blocked
- **Live progress bars** — download and upload progress are shown in an in-place edited message
- **Uploads up to 2 GiB** via MTProto (Telethon); files larger than 2 GiB are **split** into parts < 1.5 GiB
- **Private-channel storage** — every file is uploaded to the owner's private channel and indexed
- **7-day cache** — requesting the same link again within 7 days re-sends it from the channel instantly (no re-download)
- **No server retention** — local files and progress messages are deleted after upload
- **Admin panel** — owner can grant/revoke access for friends, all in-chat via buttons
- **Pause / resume / cancel / status / list** for active downloads
- **Per-user custom thumbnails**

## How it works

```
Telegram user <-> Bot (aiogram + Telethon) <-> aria2 RPC (port 6800) <-> internet
                                    |
                                    +-> owner's private channel (file storage + logs)
```

- **aria2** runs as a daemon exposing a JSON-RPC endpoint on port 6800. The bot calls methods like `aria2.addUri` and `aria2.tellStatus`.
- **aiogram** handles Telegram Bot API messages and inline buttons.
- **Telethon** (MTProto) handles large file uploads (> 49 MiB up to 2 GiB).
- **yt-dlp** probes and downloads media sites; **megatools** handles Mega; **ffmpeg** muxes/transcodes when needed.
- **cobalt** (optional, self-hosted) tunnels media through its own server — YouTube never sees your IP, so no bot-detection.
- **Koutube** (optional, self-hosted) proxies YouTube through Invidious and returns direct download links.

## Project layout

```
aria2-bot/
├── bot.py             # main bot: handlers, download/upload flow, admin panel
├── config.py          # all settings loaded from .env (incl. proxy/cookie loaders)
├── aria2_client.py    # async JSON-RPC client for aria2
├── downloaders.py     # URL detection + mega/mediafire/aria2 download helpers
├── parsing.py         # link format parsing (URL|name|user|pass, URL * name)
├── ytdlp.py           # yt-dlp probe, download, format/quality builders, proxy+cookie handling
├── cobalt.py          # client for a self-hosted cobalt instance (tunnel media downloads)
├── koutube.py         # client for a Koutube instance (direct YouTube links via Invidious)
├── dlapi.py           # client for dlapi.yebekhe.workers.dev (server-side download fallback)
├── media.py           # video/audio metadata (hachoir)
├── db.py              # JSON persistence: admins list + file cache index (7-day TTL)
├── store.py           # request store, thumbnails, cooldown
├── aria2.conf         # aria2 RPC daemon config
├── requirements.txt   # python dependencies
└── .env.example       # config template (copy to .env)
```

## Requirements

- Linux server (any modern distro), Python 3.10+
- System packages: `aria2`, `megatools`, `ffmpeg`, `yt-dlp`
- Python packages: see `requirements.txt`
- Telegram: a bot token, a private channel, and an API ID/HASH (for large uploads)

---

## Full setup guide

### 1. Create the Telegram bot

1. Talk to [@BotFather](https://t.me/BotFather), send `/newbot`, and get your **bot token** (like `5332112:AAE...`).
2. Create a **private channel** in Telegram (the bot uses it to store uploaded files for the cache).
3. Add your bot as an **admin** of that channel (give it "Post Messages" + "Edit Messages" permission).
4. Get your channel ID — forward a message from the channel to [@userinfobot](https://t.me/userinfobot), or just run the bot once and read the `Storage channel:` line in its log.
5. Get an **API ID + API hash** from https://my.telegram.org → *API development tools*. Required for uploading files larger than 49 MiB.

### 2. Install dependencies

```bash
# Debian / Ubuntu
apt-get update
apt-get install -y aria2 megatools ffmpeg python3 python3-pip git

# Install yt-dlp (the pip package is usually fine too)
pip3 install --break-system-packages -U yt-dlp

# Python packages for the bot
pip3 install --break-system-packages aiogram python-dotenv aiohttp telethon hachoir yt-dlp
```

Or, inside the repo:

```bash
pip3 install --break-system-packages -r aria2-bot/requirements.txt
```

### 3. Get the code

```bash
git clone https://github.com/hossein-bozorg-zadeh/tg-dl.git
cd tg-dl/aria2-bot
```

### 4. Run the setup wizard (recommended)

A one-shot interactive wizard walks you through everything: it installs system
dependencies, creates a virtualenv, prompts for your Telegram settings, writes
`.env`, patches `aria2.conf`, starts aria2, optionally installs a systemd
service, and optionally configures a Koutube instance for YouTube downloads.

```bash
cd tg-dl
bash setup.sh
```

It will ask you for:

- `BOT_TOKEN` — from @BotFather
- `OWNER_ID` — your numeric Telegram ID
- `CHANNEL_ID` — your private channel (bot must be admin)
- `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` — for >49 MiB uploads
- `ALLOWED_USERS` — optional extra users (comma-separated)
- **Deploy cobalt?** — the wizard can spin up a self-hosted cobalt instance via Docker (recommended: tunnels YouTube media through its own server, no bot-check)
- `COBALT_API_URL` — your cobalt instance URL, or empty to skip
- `KOUTUBE_BASE_URL` — enter `public` for the public koutu.be, a self-hosted URL, or leave empty to skip (see the Koutube guide below)

Non-interactive / scripted installs are supported too:

```bash
BOT_TOKEN=... OWNER_ID=... CHANNEL_ID=... \
NONINTERACTIVE=1 bash setup.sh
```

### 5. Manual setup (alternative)

If you prefer to configure things by hand, follow the steps below instead of
running the wizard.

#### 5.1 Configure the bot

```bash
cp .env.example .env
nano .env
```

| Variable | Description |
|---|---|
| `BOT_TOKEN` | From @BotFather (**required**) |
| `OWNER_ID` | Your numeric Telegram ID — full admin (**required**) |
| `CHANNEL_ID` | Private channel ID; bot must be admin (**required**) |
| `TELEGRAM_API_ID` | From my.telegram.org — enables >49 MiB uploads |
| `TELEGRAM_API_HASH` | Same as above |
| `ALLOWED_USERS` | Comma-separated user IDs allowed to use the bot (empty = everyone) |
| `ARIA2_RPC_URL` | aria2 JSON-RPC URL (default `http://127.0.0.1:6800/jsonrpc`) |
| `ARIA2_SECRET` | Must match `rpc-secret` in `aria2.conf` |
| `DOWNLOAD_DIR` | Where downloads are staged (cleaned after upload) |
| `COOLDOWN_SECONDS` | Cooldown between requests for non-authorized users |
| `CACHE_TTL_DAYS` | Channel-cache lifetime for re-sending the same link (default 7) |
| `SPLIT_THRESHOLD` | Files above this size are split (default 2 GiB) |
| `SPLIT_PART_SIZE` | Split part size (default 1.5 GiB) |
| `PROCESS_MAX_TIMEOUT` | Timeout for external tools like yt-dlp |
| `HTTP_PROXY` | Single proxy for yt-dlp / direct downloads (optional) |
| `YTDLP_PROXIES` | Comma-separated proxy list, rotated per yt-dlp request |
| `YTDLP_COOKIES` | Path to a `cookies.txt` for YouTube (fixes bot-check) |
| `COBALT_API_URL` | Self-hosted cobalt instance URL (tunnels media; e.g. `http://127.0.0.1:9000`); empty = disabled |
| `KOUTUBE_BASE_URL` | Koutube instance for direct YouTube links (self-hosted or `https://koutu.be`); empty = disabled |

### 5.2 Fix the aria2 download dir

Edit `aria2.conf` and make sure `dir=` points to your real download directory:

```
dir=/path/to/your/downloads
```

### 5.3 Start aria2

```bash
aria2c --conf-path=aria2.conf
```

Verify the RPC is up:

```bash
curl http://127.0.0.1:6800/jsonrpc -d '{"jsonrpc":"2.0","id":"1","method":"aria2.getVersion","params":["token:aria2botsecret"]}'
```

### 5.4 Run the bot

```bash
python3 bot.py
```

You should see logs like:

```
INFO aria2bot: Storage channel: my channel
INFO telethon.network.mtprotosender: Connection complete!
INFO aiogram.dispatcher: Run polling for bot @YourBot
```

### 5.5 Run as a service (recommended)

Create `/etc/systemd/system/tg-dl.service`:

```ini
[Unit]
Description=Telegram download manager bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/tg-dl/aria2-bot
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now tg-dl
```

---

## Usage

Just send a link to the bot. It detects the type automatically.

| Input | Behavior |
|---|---|
| `https://.../file.zip` | Direct download, then upload |
| `magnet:?xt=...` | Torrent download via aria2 |
| `file.torrent` (attachment) | Torrent download via aria2 |
| `https://mega.nz/...` | Mega download via megatools |
| `https://www.mediafire.com/...` | MediaFire link resolution |
| `https://youtube.com/watch?v=...` | Quality/format picker (video + MP3) |

### Link formats

```
URL                                  → normal download
URL|filename.ext                     → download with a custom file name
URL|name.mp4|user|pass               → login-protected URL
URL * name.mp4                       → alternate rename format
```

### Commands

| Command | Description |
|---|---|
| `/start` | Welcome menu (glass buttons) + admin panel |
| `/help` | List commands |
| `/list` | Show active, queued, and finished downloads |
| `/status <gid>` | Check one download |
| `/pause <gid>` | Pause a download |
| `/resume <gid>` | Resume a download |
| `/cancel <gid>` | Cancel and remove a download |
| `/thumb` | View your custom thumbnail |
| `/delthumb` | Delete your thumbnail |

### Format-selection menu

When a source has multiple formats (YouTube, and many yt-dlp sites), the bot shows a button menu:

```
🎥 YouTube detected — pick a quality/format:
🎬 1080p (mp4) 77.16 MiB
🎬 720p (mp4) 25.23 MiB
🎬 480p (mp4) 13.45 MiB
🎵 MP3 (320k)
```

Tap a button and the bot downloads then uploads with a live progress bar.

### Admin panel

The owner can press **🛠️ Admin** in `/start` to open the panel:

- **Add user** — grant access to friends; multiple IDs at once (spaces, commas, or newlines)
- **Remove user** — revoke access
- **List users** — see who has access

### Cookies & proxies (YouTube bot-check fixes)

If YouTube shows *"Sign in to confirm you're not a bot"*, the bot tries these
in order:

1. **cobalt** (if `COBALT_API_URL` is set) — tunnels the media through its own server, so your server's IP never talks to YouTube. See the self-hosting guide below.
2. **Koutube** (if `KOUTUBE_BASE_URL` is set) — generates direct download links on another server via Invidious.
3. **dlapi fallback** — `dlapi.yebekhe.workers.dev` (a free server-side downloader). Used automatically when the services above are disabled or unreachable.
4. **yt-dlp with cookies/proxies** — as a last resort.

You can also help yt-dlp directly:

1. **Upload cookies** — export `cookies.txt` from your logged-in browser ("Get cookies.txt LOCALLY" extension) and send the file to the bot. Only the owner can do this.
2. **Upload proxies** — name your file `proxies.json` (any `.json`/`.txt`/`.csv` with `prox` in the name also works) and send it to the bot. It accepts almost any format: arrays of strings, JSON objects, plain text (one per line), etc. The bot rotates a random proxy per request.

   Supported proxy formats (examples):
   ```json
   ["http://1.2.3.4:8080", "socks5://user:pass@5.6.7.8:1080"]
   [{"ip": "1.1.1.1", "port": 8080, "protocol": "http"}]
   {"proxies": ["1.2.3.4:8080", "socks5://5.6.7.8:1080"]}
   ```
   Plain text works too:
   ```
   1.2.3.4:8080
   socks5://5.6.7.8:1080
   ```

> Tip: free/datacenter proxies are often flagged by YouTube too. Residential proxies (Bright Data, Oxylabs, Smartproxy, or your own home IP) work best.

### Self-host cobalt (recommended for personal servers)

[cobalt](https://github.com/imputnet/cobalt) is a media downloader that works
like a fancy proxy: it fetches the media on its own server and **tunnels** the
file back to you. Your server's IP is never seen by YouTube, so the
"Sign in to confirm you're not a bot" wall disappears entirely. It also covers
Twitter, Instagram, TikTok, SoundCloud, Reddit and more.

The bot has a built-in client for any cobalt instance (`cobalt.py`). Set
`COBALT_API_URL` in `.env` and the bot uses it as the **primary** YouTube path.

The wizard can deploy cobalt for you automatically. To do it by hand:

```bash
# 1. Install Docker: https://docs.docker.com/engine/install/
# 2. Create a compose file
mkdir -p ~/cobalt && cat > ~/cobalt/docker-compose.yml <<'EOF'
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

# 3. Start it
cd ~/cobalt && docker compose up -d
```

Then point the bot at it:

```bash
# in aria2-bot/.env
COBALT_API_URL=http://127.0.0.1:9000
```

> The public `api.cobalt.tools` is bot-protected and explicitly **not** meant
> for other projects — always self-host your own instance.

### Self-host Koutube (recommended for personal servers)

[Koutube](https://github.com/iGerman00/koutube) is a Cloudflare Workers service
that returns direct YouTube download links via Invidious. Because the links are
generated on Cloudflare's servers, **your server's IP is never seen by YouTube**,
so the "Sign in to confirm you're not a bot" wall disappears entirely.

The bot has a built-in client for any Koutube instance (`koutube.py`). Set
`KOUTUBE_BASE_URL` in `.env` to point at your instance, and the bot uses it as
the **primary** YouTube download path.

#### Deploy Koutube to your Cloudflare account

```bash
# 1. Install wrangler (Cloudflare's CLI) + clone koutube
npm install -g wrangler
git clone https://github.com/iGerman00/koutube.git
cd koutube

# 2. Install dependencies
npm i

# 3. Create a D1 database in Cloudflare:
#    https://dash.cloudflare.com -> Workers & Pages -> D1 -> Create database
#    Copy the database ID, then edit wrangler.toml and replace the
#    d1_databases.database_id with your own. Example:
#
#    [[d1_databases]]
#    binding = "D1_DB"
#    database_id = "1234abcd-5678-ef90-1234-5678ef901234"
#    database_name = "koutube-db"

# 4. Initialize the database and deploy
npm run init-remote-db
wrangler deploy
```

You'll get a URL like `https://koutube.yourdomain.workers.dev`.

> Optional: to get more reliable, un-throttled downloads, host your own private
> [Invidious](https://docs.invidious.io/installation/) instance and point koutube
> at it via the `IV_DOMAIN` / `IV_AUTH` secrets (`npx wrangler secret put ...`).

#### Point the bot at it

```bash
# in aria2-bot/.env
KOUTUBE_BASE_URL=https://koutube.yourdomain.workers.dev
```

Or, when using the wizard, enter the URL when asked for `KOUTUBE_BASE_URL`.

> The public instance `https://koutu.be` works too but is rate-limited (10 RPS)
> and Cloudflare-blocked from some datacenter IPs. Self-hosting is recommended.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Sign in to confirm you're not a bot" | Upload `cookies.txt` and/or `proxies.json` to the bot (see above) |
| Files > 49 MiB not uploading | Set `TELEGRAM_API_ID` + `TELEGRAM_API_HASH` in `.env` |
| Bot says "Failed to add torrent" | Make sure aria2 is running (`systemctl status tg-dl` or check `aria2.getVersion`) |
| "Storage channel" error | Add the bot as admin of `CHANNEL_ID` |
| Proxy errors like "Host unreachable" | The proxy is dead; test it: `curl -x http://ip:port -m 5 https://api.ipify.org` |

## License

This project is open source.

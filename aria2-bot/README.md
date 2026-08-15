# Aria2 Telegram Bot

A full-featured Telegram download manager backed by the original [aria2](https://github.com/aria2/aria2) running on a Linux server. The bot talks to aria2 over its JSON-RPC interface.

## Features

- Download via HTTP/HTTPS/FTP, magnet links, `.torrent` files
- **Mega.nz** links (via megatools) and **MediaFire** links (direct-link resolver)
- Live **progress bars** for downloads and uploads (edit-in-place message)
- **Glass-styled buttons** (Telegram Bot API 9.4 button `style`: primary / success / danger)
- Uploads up to **2 GiB** via MTProto (Telethon); files >2 GiB are **split** into parts <1.5 GiB
- **Private-channel storage**: every file is uploaded to the owner's channel and logged there
- **7-day cache**: the same link requested again within 7 days is resent instantly from the channel (no re-download); after 7 days without requests it is downloaded fresh
- **No server retention**: local files and progress messages are deleted after upload
- **Admin panel**: owner can grant/revoke access for friends, all in-chat via buttons
- Pause, resume, cancel, status, list

## Architecture

```
Telegram user <-> Bot (Python/aiogram + Telethon) <-> aria2 RPC (JSON-RPC, port 6800) <-> internet
                                    |
                                    +-> owner's private channel (file storage + logs)
```

aria2 runs as a daemon (`aria2c`) exposing a JSON-RPC endpoint on port 6800.
The bot is an async Python app that calls RPC methods like `aria2.addUri` and `aria2.tellStatus`.

## Setup

### 1. Install dependencies

```bash
apt-get install -y aria2 megatools
pip install -r requirements.txt
```

### 2. Configure the bot

```bash
cp .env.example .env
```

Edit `.env`:

- `BOT_TOKEN` — from [@BotFather](https://t.me/BotFather)
- `OWNER_ID` — your Telegram user ID (full admin)
- `CHANNEL_ID` — your private channel ID. **Add the bot as an admin of this channel first.**
  Get the ID by forwarding a channel post to [@userinfobot](https://t.me/userinfobot).
- `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` — from https://my.telegram.org (required for >49 MiB uploads)
- `ALLOWED_USERS` — optional initial user list

### 3. Start aria2 daemon

```bash
aria2c --conf-path=aria2.conf
```

`ARIA2_SECRET` in `.env` must match `rpc-secret` in `aria2.conf`.

### 4. Run the bot

```bash
python3 bot.py
```

## Commands

| Command | Description |
|---|---|
| `<any link>` | Just send a URL/magnet and the bot downloads it |
| `/start` | Welcome menu (glass buttons) + admin panel |
| `/help` | List commands |
| `/list` | Show active, queued, and finished downloads |
| `/status <gid>` | Check one download |
| `/pause <gid>` | Pause a download |
| `/resume <gid>` | Resume a download |
| `/cancel <gid>` | Cancel and remove a download |

Send a `.torrent` file to the bot to start a torrent download.

### Admin panel

The owner can press the **🛠️ Admin** button in `/start` to open the panel:

- Add user (grant access to friends)
- Remove user (revoke access)
- List users

## Files

- `aria2.conf` — aria2 daemon config (RPC, download dir, session persistence)
- `aria2_client.py` — async JSON-RPC client for aria2
- `downloaders.py` — URL detection + Mega/MediaFire/aria2 download logic
- `db.py` — JSON persistence: admins list + file cache index (7-day TTL)
- `bot.py` — Telegram bot entry point
- `config.py` — settings loaded from `.env`
- `downloads/` — temporary staging (cleaned after upload)

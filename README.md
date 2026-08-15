# tg-dl

A full-featured Telegram download manager bot that runs on a Linux server.

## Features

- **aria2** powered downloads — HTTP/HTTPS/FTP direct links, magnet & torrent
- **yt-dlp** — YouTube (quick audio/video), plus 1000+ sites (Twitch, Vimeo, TikTok, ...)
- **Mega.nz** downloads via megatools
- **MediaFire** link resolution
- Format-selection menus when a source exposes multiple formats
- Per-user custom thumbnails
- Link formats: `URL`, `URL|filename.ext`, `URL|name|user|pass`, `URL * name`
- Channel-backed storage cache — same link re-requested within 7 days is re-sent instantly
- Files up to 2 GiB in one piece; larger files split into &lt;1.5 GiB parts
- MTProto (Telethon) uploads up to 2 GiB
- Admin panel to grant/revoke user access
- Progress bars for download & upload, glass-style buttons

## Structure

```
aria2-bot/
├── bot.py             # main bot (handlers, download/upload flow)
├── config.py          # env-driven configuration
├── aria2_client.py    # aria2 JSON-RPC client
├── downloaders.py     # mega / mediafire / aria2 helpers
├── parsing.py         # link format parsing
├── ytdlp.py           # yt-dlp probe, download, format builders
├── media.py           # video/audio metadata (hachoir)
├── db.py              # admins + file cache index
├── store.py           # request store, thumbnails, cooldown
├── aria2.conf         # aria2 RPC daemon config
└── requirements.txt
```

## Setup

1. Copy `.env.example` to `.env` and fill in:
   - `BOT_TOKEN` — from @BotFather
   - `OWNER_ID` — your Telegram numeric ID
   - `CHANNEL_ID` — private channel (add the bot as admin)
   - `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` — for large file uploads
2. Install dependencies: `pip install -r requirements.txt`
3. Start aria2: `aria2c --conf-path=aria2-bot/aria2.conf`
4. Run the bot: `python3 aria2-bot/bot.py`

Requires `aria2c`, `megatools`, `ffmpeg`, `yt-dlp` on the host.

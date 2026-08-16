# Aria2 Telegram Bot

This is the bot code used by the **tg-dl** repository.

See the full setup, usage, and troubleshooting guide in the **[root README](../README.md)**.

Quick start:

```bash
cp .env.example .env   # fill in BOT_TOKEN, OWNER_ID, CHANNEL_ID, ...
aria2c --conf-path=aria2.conf
python3 bot.py
```

Key modules:

- `bot.py` — main bot: handlers, download/upload flow, admin panel, YouTube menu
- `config.py` — settings loaded from `.env`, proxy/cookie loaders
- `aria2_client.py` — async JSON-RPC client for aria2
- `downloaders.py` — URL detection + mega/mediafire/aria2 download helpers
- `parsing.py` — link format parsing (`URL|name|user|pass`, `URL * name`)
- `ytdlp.py` — yt-dlp probe, download, format builders, proxy + cookie handling
- `dlapi.py` — dlapi.yebekhe.workers.dev fallback for server-side downloads
- `media.py` — video/audio metadata (hachoir)
- `db.py` — admins list + 7-day file cache index (JSON persistence)
- `store.py` — request store, thumbnails, cooldown
- `aria2.conf` — aria2 RPC daemon config

import asyncio
import base64
import hashlib
import inspect
import logging
import os
import re
import shutil
import time

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ButtonStyle, ParseMode
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Message
from telethon import TelegramClient
from telethon.tl.types import DocumentAttributeFilename

import config
import db
import downloaders
import media
import parsing
import store
import ytdlp
from aria2_client import Aria2Client, _fmt_size, _fmt_speed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("aria2bot")

aria2 = Aria2Client(config.ARIA2_RPC_URL, config.ARIA2_SECRET)

bot = Bot(
    token=config.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

mtproto: TelegramClient | None = None

URL_SCHEMES = ("http://", "https://", "ftp://", "magnet:?")
BAR_FULL = "▓"
BAR_EMPTY = "░"
MAX_FORMAT_BUTTONS = 24


# --------------------------------------------------------------------------
# UI helpers
# --------------------------------------------------------------------------

def bar(pct: float, width: int = 16) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = int(width * pct / 100.0)
    return BAR_FULL * filled + BAR_EMPTY * (width - filled)


def btn(text: str, callback_data: str, style: str = "primary") -> InlineKeyboardButton:
    # Telegram only supports danger/success/primary; secondary == default look.
    if style == "secondary":
        style = "primary"
    return InlineKeyboardButton(text=text, callback_data=callback_data, style=style)


def is_owner(user_id: int) -> bool:
    return config.OWNER_ID and user_id == config.OWNER_ID


def allowed(user_id: int) -> bool:
    return db.is_allowed(user_id)


def guard(func):
    sig = inspect.signature(func)

    async def wrapper(message: Message, *args, **kwargs):
        if message.from_user and not allowed(message.from_user.id):
            logger.warning("Denied access for user %s", message.from_user.id)
            await message.answer("⛔ You don't have access to this bot.")
            return
        accepted = {k: v for k, v in kwargs.items() if k in sig.parameters}
        return await func(message, *args, **accepted)

    return wrapper


def guard_owner(func):
    sig = inspect.signature(func)

    async def wrapper(message: Message, *args, **kwargs):
        if message.from_user and not is_owner(message.from_user.id):
            await message.answer("⛔ Owner only.")
            return
        accepted = {k: v for k, v in kwargs.items() if k in sig.parameters}
        return await func(message, *args, **accepted)

    return wrapper


def clean_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip()


def url_digest(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def main_menu() -> InlineKeyboardMarkup:
    kb = [
        [
            btn("📥 Download", "menu:dl", "primary"),
            btn("📋 Status", "menu:list", "primary"),
        ],
        [
            btn("⏸️ Pause", "menu:pause", "secondary"),
            btn("▶️ Resume", "menu:resume", "success"),
            btn("🗑️ Cancel", "menu:cancel", "danger"),
        ],
        [
            btn("ℹ️ About", "menu:about", "secondary"),
            btn("🛠️ Admin", "menu:admin", "danger"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def welcome_text(name: str = "there") -> str:
    return (
        f"👋 <b>Welcome, {name}!</b>\n\n"
        "I'm a full download manager running on a Linux server, powered by <b>aria2</b> and <b>yt-dlp</b>.\n\n"
        "📥 <b>What I can download</b>\n"
        "• HTTP/HTTPS/FTP direct links\n"
        "• Magnet links & BitTorrent (.torrent files)\n"
        "• 🅼 Mega.nz links\n"
        "• 📁 MediaFire links\n"
        "• 🎬 YouTube videos & audio\n"
        "• 🌐 1000+ sites supported by yt-dlp\n\n"
        "🔤 <b>Link formats</b>\n"
        "• <code>URL</code> — normal download\n"
        "• <code>URL|filename.ext</code> — custom file name\n"
        "• <code>URL|name.mp4|user|pass</code> — login-protected\n"
        "• <code>URL * name.mp4</code> — alternate rename format\n\n"
        "🎥 <b>YouTube</b> — send a link and choose Audio (MP3) or Video (MP4).\n"
        "🔀 <b>Format menu</b> — when a source has many formats, I'll show you a choice.\n"
        "🖼️ <b>Thumbnails</b> — send a photo to save your thumbnail, <code>/thumb</code> to view it.\n\n"
        "🔄 <b>Caching</b> — files are saved in the owner's private channel; same link within 7 days is resent instantly. Nothing stays on the server.\n"
        "📦 <b>Large files</b> — up to 2 GiB in one piece, bigger files split into &lt;1.5 GiB parts.\n"
        "🔒 <b>Privacy</b> — your files go only to you (and the storage channel), never shared.\n\n"
        "🔤 <b>Commands</b>\n"
        "/help — all abilities & link formats\n"
        "/about — about this bot\n"
        "/list — show all downloads\n"
        "/status &lt;gid&gt; · /pause &lt;gid&gt; · /resume &lt;gid&gt; · /cancel &lt;gid&gt;\n"
        "/thumb · /delthumb — manage your thumbnail\n"
        "/admin — admin panel (owner)\n"
    )


def help_text() -> str:
    return (
        "📖 <b>How to use this bot</b>\n\n"
        "Just send a message containing a link, and I'll download and upload it back to Telegram.\n\n"
        "<b>Supported sources</b>\n"
        "• Direct file URLs (HTTP/HTTPS/FTP)\n"
        "• BitTorrent magnet links &amp; .torrent files\n"
        "• Mega.nz and MediaFire\n"
        "• YouTube (quick audio/video)\n"
        "• 1000+ sites via yt-dlp (Twitch, Vimeo, TikTok, Twitter/X, Facebook...)\n\n"
        "<b>Link formats</b>\n"
        "1. <b>Direct link</b>\n"
        "   <code>https://example.com/file.mp4</code>\n\n"
        "2. <b>Direct link + custom file name</b>\n"
        "   <code>https://example.com/file.mp4|my-video.mp4</code>\n\n"
        "3. <b>Login-protected URL</b>\n"
        "   <code>https://example.com/file|my-file.mp4|username|password</code>\n\n"
        "4. <b>Alternate rename format</b>\n"
        "   <code>https://example.com/file.mp4 * renamed.mp4</code>\n\n"
        "<b>YouTube</b>\n"
        "Send any YouTube link. Choose <b>Audio</b> (MP3) or <b>Video</b> (MP4) when prompted.\n\n"
        "<b>Format selection</b>\n"
        "If the source exposes multiple formats, a menu appears — pick the one you want.\n\n"
        "<b>Thumbnails</b>\n"
        "Send a JPG photo to save it as your custom thumbnail.\n"
        "/thumb — view your thumbnail\n"
        "/delthumb — remove it\n\n"
        "<b>Other commands</b>\n"
        "/start — main menu\n"
        "/about — about this bot\n"
        "/list — active &amp; finished downloads\n"
        "/status &lt;gid&gt; · /pause &lt;gid&gt; · /resume &lt;gid&gt; · /cancel &lt;gid&gt;\n"
        "/admin — admin panel (owner)\n"
    )


def about_text() -> str:
    return (
        "ℹ️ <b>About this bot</b>\n\n"
        "A full-featured download manager powered by:\n"
        "• <b>aria2</b> — multi-connection downloads (HTTP/FTP/BitTorrent)\n"
        "• <b>yt-dlp</b> — 1000+ media sites\n"
        "• <b>megatools</b> — Mega.nz\n"
        "• <b>Telethon (MTProto)</b> — uploads up to 2 GiB\n\n"
        "Runs as a daemon + Telegram bot on a Linux server.\n\n"
        "Send a link to get started!"
    )


def admin_cmds_text() -> str:
    return (
        "🛠️ <b>Admin commands</b>\n\n"
        "/admin — open the admin panel\n"
        "• Add user — grant access to a friend (by numeric Telegram ID)\n"
        "• Remove user — revoke access\n"
        "• List users — show everyone with access\n\n"
        "The owner controls everything; granted users can only download files.\n"
    )


# --------------------------------------------------------------------------
# Command handlers
# --------------------------------------------------------------------------

@dp.message(CommandStart())
@guard
async def cmd_start(message: Message):
    name = message.from_user.first_name if message.from_user else "there"
    logger.info("User %s started the bot", message.from_user.id if message.from_user else None)
    await message.answer(welcome_text(name), reply_markup=main_menu(), link_preview_options=LinkPreviewOptions(is_disabled=True))


@dp.message(Command("help"))
@guard
async def cmd_help(message: Message):
    await message.answer(help_text(), link_preview_options=LinkPreviewOptions(is_disabled=True))


@dp.message(Command("about"))
@guard
async def cmd_about(message: Message):
    await message.answer(about_text(), link_preview_options=LinkPreviewOptions(is_disabled=True))


@dp.message(Command("admin"))
@guard_owner
async def cmd_admin(message: Message):
    await message.answer(admin_cmds_text(), reply_markup=admin_panel_kb())


@dp.callback_query(lambda c: c.data and c.data.startswith("menu:"))
async def on_menu_cb(cb: CallbackQuery, state: FSMContext):
    action = cb.data.split(":", 1)[1]
    if action == "admin":
        if cb.from_user and not is_owner(cb.from_user.id):
            await cb.answer("⛔ Owner only", show_alert=True)
            return
        await cb.answer()
        await cb.message.edit_text(admin_panel_text(), reply_markup=admin_panel_kb())
        return
    if action == "about":
        await cb.answer()
        await cb.message.edit_text(about_text(), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("🏠 Back", "menu:home", "secondary")]]))
        return
    if action == "home":
        await cb.answer()
        name = cb.from_user.first_name if cb.from_user else "there"
        await cb.message.edit_text(welcome_text(name), reply_markup=main_menu())
        return
    if action == "dl":
        await cb.answer()
        await cb.message.edit_text(
            "📥 <b>Send me a link</b> to download.\n\n"
            "Formats:\n"
            "<code>URL</code> · <code>URL|filename.ext</code>\n"
            "<code>URL|name.ext|user|pass</code> · <code>URL * name.ext</code>\n\n"
            "You can also use <code>/dl URL</code>.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("🏠 Back", "menu:home", "secondary")]]),
        )
        return
    if action in ("list", "pause", "resume", "cancel"):
        await cb.answer()
        await show_downloads(cb.message, action)
        return
    await cb.answer()


@dp.callback_query(lambda c: c.data and c.data.startswith("dlact:"))
async def on_dlact_cb(cb: CallbackQuery):
    parts = cb.data.split(":")
    if len(parts) != 3:
        await cb.answer()
        return
    _, action, gid = parts
    try:
        if action == "pause":
            await aria2.pause(gid)
            await cb.answer("⏸️ Paused")
        elif action == "resume":
            await aria2.unpause(gid)
            await cb.answer("▶️ Resumed")
        elif action == "cancel":
            await aria2.remove(gid)
            await aria2.remove_result(gid)
            await cb.answer("🗑️ Removed")
        else:
            await cb.answer()
            return
    except RuntimeError as e:
        await cb.answer(f"❌ {e}", show_alert=True)
        return
    await show_downloads(cb.message, "list")


async def show_downloads(message: Message, action: str):
    """Render the download list for menu actions. Each download gets an action button."""
    try:
        items = await aria2.all_status()
    except RuntimeError as e:
        try:
            await message.edit_text(f"❌ aria2 RPC error: {e}")
        except Exception:
            pass
        return
    if not items:
        kb = InlineKeyboardMarkup(inline_keyboard=[[btn("🏠 Back", "menu:home", "secondary")]])
        try:
            await message.edit_text("📭 No downloads.", reply_markup=kb)
        except Exception:
            pass
        return

    from aria2_client import Aria2Client
    text = "\n\n".join(Aria2Client.format_status(it) for it in items[:6])
    rows = []
    for it in items[:6]:
        gid = it.get("gid")
        if not gid:
            continue
        label = f"🆔 {gid[:8]}"
        if action == "list":
            rows.append([btn(label, f"dlact:nothing:{gid}", "primary")])
        elif action == "pause":
            rows.append([btn(f"⏸️ {gid[:8]}", f"dlact:pause:{gid}", "danger")])
        elif action == "resume":
            rows.append([btn(f"▶️ {gid[:8]}", f"dlact:resume:{gid}", "success")])
        elif action == "cancel":
            rows.append([btn(f"🗑️ {gid[:8]}", f"dlact:cancel:{gid}", "danger")])
    rows.append([btn("🏠 Back", "menu:home", "secondary")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    try:
        await message.edit_text(f"<pre>{text}</pre>", reply_markup=kb)
    except Exception:
        pass


# --------------------------------------------------------------------------
# Thumbnails
# --------------------------------------------------------------------------

@dp.message(F.photo)
@guard
async def save_thumbnail(message: Message):
    if not message.from_user:
        return
    largest = message.photo[-1]
    file = await bot.get_file(largest.file_id)
    data = await bot.download_file(file.file_path)
    store.save_thumbnail(message.from_user.id, data)
    await message.answer("🖼️ Custom thumbnail saved. It will be used on your video/audio uploads.")


@dp.message(Command("thumb"))
@guard
async def cmd_thumb(message: Message):
    if not message.from_user:
        return
    path = store.get_thumbnail(message.from_user.id)
    if not path:
        await message.answer("You don't have a thumbnail yet. Send a JPG image to save one.")
        return
    await message.answer_photo(FSInputFile(path), caption="Your custom thumbnail.")


@dp.message(Command("delthumb"))
@guard
async def cmd_delthumb(message: Message):
    if not message.from_user:
        return
    if store.delete_thumbnail(message.from_user.id):
        await message.answer("Your thumbnail was removed.")
    else:
        await message.answer("You don't have a thumbnail saved.")


# --------------------------------------------------------------------------
# Downloads (intake)
# --------------------------------------------------------------------------

def _filter_link_parts(parts: list[str]) -> list[str]:
    return [p for p in parts if p.startswith(("http://", "https://", "ftp://", "magnet:?"))]


@dp.message(F.text, StateFilter(None))
@guard
async def handle_text(message: Message):
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        return
    if not parsing.extract_link_text(text):
        await message.answer("Send me a link (HTTP/HTTPS/FTP/magnet/Mega/MediaFire/YouTube) or a <b>.torrent</b> file.")
        return
    await process_link(message, text)


@dp.message(F.document | F.video_note)
@guard
async def handle_torrent_file(message: Message):
    if message.document and message.document.file_name and message.document.file_name.endswith(".torrent"):
        buf = await bot.download(message.document)
        b64 = base64.b64encode(buf).decode()
        try:
            gid = await aria2.add_torrent(b64)
        except RuntimeError as e:
            await message.answer(f"❌ Failed to add torrent: {e}")
            return
        await message.answer(f"✅ Torrent added to queue.\n🆔 <code>{gid}</code>")
        return
    if message.video_note:
        await message.answer("❌ Send a link, not a video note. 🙂")


@dp.message(Command("dl"))
@guard
async def cmd_dl(message: Message):
    text = (message.text or "").strip()
    args = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""
    reply = message.reply_to_message.text if message.reply_to_message else ""
    combined = (args + " " + reply).strip()
    if not parsing.extract_link_text(combined):
        await message.answer("❌ Usage: <code>/dl URL</code> (or just send the link)")
        return
    await process_link(message, combined)


async def process_link(message: Message, raw_text: str):
    uid = message.from_user.id
    chat_id = message.chat.id

    blocked = store.cooldown_check(uid, config.COOLDOWN_SECONDS)
    if blocked:
        await message.answer(f"⏳ Please wait before starting another request. Try again in about {max(1, round(blocked / 60))} minute(s).")
        return

    parsed = parsing.parse_user_input(raw_text)
    url = parsed.source_url
    kind = downloaders.detect(url)
    logger.info("Incoming link | user=%s chat=%s kind=%s url=%s", uid, chat_id, kind, url[:120])

    # 7-day cache: same link requested within CACHE_TTL_DAYS is re-sent from the channel
    cached = db.find_file(url)
    if cached and cached.get("parts"):
        age = time.time() - cached.get("last_request", 0)
        if age < config.CACHE_TTL_DAYS * 86400:
            db.touch_file(url)
            await message.answer("♻️ <b>Already downloaded</b> — resending from cache...")
            if await resend_cached(cached, chat_id):
                return
    db.touch_file(url)

    # YouTube / yt-dlp quick flow
    if parsing.is_probable_youtube_url(url):
        token = store.create_request("youtube_quick", parsed, ytdlp.build_quick_youtube_options())
        await message.answer("🎥 <b>YouTube link detected</b> — how do you want it?", reply_markup=format_kb(token))
        return

    # Mega / MediaFire get dedicated downloaders
    if kind == "mega":
        options = [{"option_id": "mega", "label": "🅼 Download from Mega", "send_type": "document", "mode": "mega"}]
        token = store.create_request("mega", parsed, options, {})
        await message.answer("🅼 <b>Mega link detected</b>", reply_markup=format_kb(token))
        return

    if kind == "mediafire":
        options = [{"option_id": "mediafire", "label": "📁 Download from MediaFire", "send_type": "document", "mode": "mediafire"}]
        token = store.create_request("mediafire", parsed, options, {})
        await message.answer("📁 <b>MediaFire link detected</b>", reply_markup=format_kb(token))
        return

    # Try yt-dlp probe for media sites (not direct file links)
    info = None
    if not parsing.is_direct_file_url(url):
        try:
            info = await ytdlp.probe_url(parsed, config)
        except Exception as e:
            logger.info("yt-dlp probe failed, falling back to direct: %s", e)
            info = None

    if info:
        options = ytdlp.build_ytdlp_options(info)
        request_type = "ytdlp_selection"
        if not options:
            options = ytdlp.build_direct_options(parsed, info=info)
            request_type = "direct_download"
    else:
        options = ytdlp.build_direct_options(parsed, info=None)
        request_type = "direct_download"

    token = store.create_request(request_type, parsed, options, info or {})
    await message.answer("🔽 Choose how to download:", reply_markup=format_kb(token))


def format_kb(token: str) -> InlineKeyboardMarkup:
    rec = store.load_request(token)
    if not rec:
        return InlineKeyboardMarkup(inline_keyboard=[[btn("Expired", "req:expired", "danger")]])
    rows = []
    for opt in rec["options"][:MAX_FORMAT_BUTTONS]:
        rows.append([InlineKeyboardButton(text=opt["label"], callback_data=f"req:{token}:{opt['option_id']}", style=ButtonStyle.PRIMARY)])
    rows.append([btn("❌ Close", "req:close", "secondary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(lambda c: c.data and c.data.startswith("req:"))
async def on_request_cb(cb: CallbackQuery):
    if not cb.message:
        await cb.answer()
        return
    parts = cb.data.split(":")
    if parts[1] == "expired":
        await cb.message.edit_text("That request has expired. Send the link again.")
        await cb.answer()
        return
    if parts[1] == "close":
        await cb.message.delete()
        await cb.answer()
        return
    if len(parts) < 3:
        await cb.answer()
        return
    token, option_id = parts[1], parts[2]
    rec = store.load_request(token)
    if not rec:
        await cb.message.edit_text("That request has expired. Send the link again.")
        await cb.answer()
        return
    option = next((o for o in rec["options"] if o["option_id"] == option_id), None)
    if not option:
        await cb.message.edit_text("That option is no longer available. Send the link again.")
        await cb.answer()
        return

    # Rebuild ParsedInput from stored dict
    parsed = parsing.ParsedInput(
        source_url=rec["parsed"]["source_url"],
        custom_file_name=rec["parsed"].get("custom_file_name"),
        username=rec["parsed"].get("username"),
        password=rec["parsed"].get("password"),
    )
    work_dir = store.work_directory(token)
    status_msg = cb.message

    try:
        if rec["request_type"] == "youtube_quick":
            artifact = await ytdlp.download_quick_youtube(parsed, option, config, work_dir, progress_cb=_progress_cb(status_msg))
        elif rec["request_type"] == "mega":
            artifact = await mega_download(parsed, option, config, work_dir, status_msg=status_msg)
        elif rec["request_type"] == "mediafire":
            artifact = await mediafire_download(parsed, option, config, work_dir, status_msg=status_msg)
        elif rec["request_type"] == "direct_download":
            artifact = await direct_download(parsed, option, config, work_dir, info=rec.get("info") or None, status_msg=status_msg)
        else:
            artifact = await ytdlp.download_selected_format(parsed, option, rec.get("info") or {}, config, work_dir, progress_cb=_progress_cb(status_msg))

        artifact.setdefault("_url", rec["parsed"]["source_url"])
        await upload_artifact(chat_id=cb.message.chat.id, user_id=cb.from_user.id, artifact=artifact, status_msg=status_msg)
    except Exception as exc:
        logger.exception("Request action failed | token=%s option=%s", token, option_id)
        try:
            await status_msg.edit_text(f"{'❌ I could not process that link.'}\n<code>{exc}</code>")
        except Exception:
            pass
    finally:
        store.delete_request(token)
        shutil.rmtree(work_dir, ignore_errors=True)
        await cb.answer()


async def _progress_cb(status_msg: Message):
    last = {"t": 0}

    async def cb(pct: float, speed: str):
        now = time.time()
        if now - last["t"] < 0.8:
            return
        last["t"] = now
        try:
            await status_msg.edit_text(
                f"📥 <b>Downloading</b>\n<code>{bar(pct)}</code> {pct:.1f}%\n⚡ {speed}"
            )
        except Exception:
            pass

    return cb


async def direct_download(parsed, option, settings, work_dir, info=None, status_msg=None):
    """Download a direct file. Prefers aria2; falls back to streaming download."""
    url = parsed.source_url
    suggested_ext = (info or {}).get("ext")
    file_name = parsed.custom_file_name or ""
    ext = option.get("file_ext") or suggested_ext

    # Custom-name aria2 path
    if file_name:
        work_dir = work_dir.resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
        out_name = file_name
        if ext and not out_name.lower().endswith(f".{ext.lower()}"):
            out_name = f"{out_name}.{ext}"
        out_name = clean_filename(out_name)
        opts = {"dir": str(work_dir), "out": out_name}
        if parsed.username:
            opts["http-user"] = parsed.username
            opts["ftp-user"] = parsed.username
        if parsed.password:
            opts["http-passwd"] = parsed.password
            opts["ftp-passwd"] = parsed.password
        gid = await aria2.add_uri([url], opts)

        async def progress_cb(done, total, speed):
            if not status_msg:
                return
            pct = (done / total * 100) if total > 0 else 0
            try:
                await status_msg.edit_text(
                    f"📥 <b>Downloading {out_name}</b>\n<code>{bar(pct)}</code> {pct:.1f}%\n"
                    f"📦 {_fmt_size(done)} / {_fmt_size(total)}\n⚡ {_fmt_speed(speed)}"
                )
            except Exception:
                pass

        st = await downloaders.wait_aria2(aria2, gid, progress_cb)
        if st.get("status") != "complete":
            raise RuntimeError(st.get("errorMessage", "download failed"))
        path = os.path.join(work_dir, out_name)
        if not os.path.exists(path):
            files = [f.get("path") for f in (st.get("files") or []) if f.get("path") and os.path.exists(f.get("path"))]
            path = files[0] if files else None
            if not path:
                raise RuntimeError("No file after download")
        return {"path": path, "file_name": os.path.basename(path), "send_type": option.get("send_type", "document"), "caption": parsed.custom_file_name or os.path.basename(path)}

    # Default aria2 path (no custom name)
    gid, _ = await downloaders.download_with_aria2(aria2, url, str(work_dir))

    async def progress_cb(done, total, speed):
        if not status_msg:
            return
        pct = (done / total * 100) if total > 0 else 0
        try:
            await status_msg.edit_text(
                f"📥 <b>Downloading</b>\n<code>{bar(pct)}</code> {pct:.1f}%\n"
                f"📦 {_fmt_size(done)} / {_fmt_size(total)}\n⚡ {_fmt_speed(speed)}"
            )
        except Exception:
            pass

    st = await downloaders.wait_aria2(aria2, gid, progress_cb)
    if st.get("status") != "complete":
        raise RuntimeError(st.get("errorMessage", "download failed"))
    files = [f.get("path") for f in (st.get("files") or []) if f.get("path") and os.path.exists(f.get("path"))]
    if not files:
        raise RuntimeError("No file after download")
    path = files[0]
    return {"path": path, "file_name": os.path.basename(path), "send_type": option.get("send_type", "document"), "caption": parsed.custom_file_name or os.path.basename(path)}


async def mega_download(parsed, option, settings, work_dir, status_msg=None):
    """Download a Mega.nz link via megadl."""
    if not status_msg:
        raise RuntimeError("status message required")

    async def progress_cb(done, total, speed):
        pct = (done / total * 100) if total > 0 else 0
        try:
            await status_msg.edit_text(
                f"🅼 <b>Downloading from Mega</b>\n<code>{bar(pct)}</code> {pct:.1f}%\n"
                f"📦 {_fmt_size(done)} / {_fmt_size(total)}"
            )
        except Exception:
            pass

    path, size = await downloaders.download_mega(parsed.source_url, str(work_dir), progress_cb)
    out_name = os.path.basename(path)
    if parsed.custom_file_name:
        _, ext = os.path.splitext(out_name)
        final_name = clean_filename(parsed.custom_file_name)
        if ext and not final_name.lower().endswith(ext.lower()):
            final_name = f"{final_name}{ext}"
        final_path = os.path.join(os.path.dirname(path), final_name)
        os.replace(path, final_path)
        path = final_path
        out_name = os.path.basename(path)
    return {
        "path": path,
        "file_name": out_name,
        "send_type": "document",
        "caption": out_name,
        "_url": parsed.source_url,
    }


async def mediafire_download(parsed, option, settings, work_dir, status_msg=None):
    """Resolve a MediaFire page to a direct URL, then download with aria2."""
    if not status_msg:
        raise RuntimeError("status message required")
    try:
        await status_msg.edit_text("🔍 Resolving MediaFire link...")
    except Exception:
        pass
    direct_url = await downloaders.resolve_mediafire(parsed.source_url)

    gid, _ = await downloaders.download_with_aria2(aria2, direct_url, str(work_dir))

    async def progress_cb(done, total, speed):
        pct = (done / total * 100) if total > 0 else 0
        try:
            await status_msg.edit_text(
                f"📁 <b>Downloading from MediaFire</b>\n<code>{bar(pct)}</code> {pct:.1f}%\n"
                f"📦 {_fmt_size(done)} / {_fmt_size(total)}\n⚡ {_fmt_speed(speed)}"
            )
        except Exception:
            pass

    st = await downloaders.wait_aria2(aria2, gid, progress_cb)
    if st.get("status") != "complete":
        raise RuntimeError(st.get("errorMessage", "MediaFire download failed"))
    files = [f.get("path") for f in (st.get("files") or []) if f.get("path") and os.path.exists(f.get("path"))]
    if not files:
        raise RuntimeError("No file after MediaFire download")
    path = files[0]
    out_name = os.path.basename(path)
    if parsed.custom_file_name:
        _, ext = os.path.splitext(out_name)
        final_name = clean_filename(parsed.custom_file_name)
        if ext and not final_name.lower().endswith(ext.lower()):
            final_name = f"{final_name}{ext}"
        final_path = os.path.join(os.path.dirname(path), final_name)
        os.replace(path, final_path)
        path = final_path
        out_name = os.path.basename(path)
    return {
        "path": path,
        "file_name": out_name,
        "send_type": "document",
        "caption": out_name,
        "_url": parsed.source_url,
    }


# --------------------------------------------------------------------------
# Uploads + channel storage
# --------------------------------------------------------------------------

def split_file(path: str, part_size: int) -> list[str]:
    """Split a large file into parts of at most part_size bytes. Returns part paths."""
    total = os.path.getsize(path)
    n = max(1, -(-total // part_size))
    base, name = os.path.dirname(path), os.path.basename(path)
    parts: list[str] = []
    with open(path, "rb") as fh:
        for i in range(n):
            part = os.path.join(base, f"{name}.{i + 1:03d}")
            with open(part, "wb") as out:
                remaining = part_size
                while remaining > 0:
                    chunk = fh.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    out.write(chunk)
                    remaining -= len(chunk)
            parts.append(part)
    return parts


async def resend_cached(cached: dict, chat_id: int) -> bool:
    """Re-send a previously cached file from the channel to the user. Returns True on success."""
    parts = cached.get("parts") or []
    if not parts or not config.CHANNEL_ID:
        return False
    try:
        for p in parts:
            msg_id = p.get("msg_id")
            if not msg_id:
                continue
            if mtproto is not None:
                await mtproto.forward_messages(chat_id, [msg_id], from_peer=config.CHANNEL_ID)
            else:
                await bot.copy_message(chat_id, config.CHANNEL_ID, msg_id)
        return True
    except Exception as e:
        logger.error("cache re-send failed: %s", e)
        return False


def _msg_id(msg) -> int:
    """Normalize message id from either an aiogram Message (.message_id) or Telethon (.id)."""
    if msg is None:
        return 0
    mid = getattr(msg, "message_id", None)
    if mid is None:
        mid = getattr(msg, "id", 0)
    return int(mid)


async def upload_artifact(chat_id: int, user_id: int, artifact: dict, status_msg: Message):
    path = artifact["path"]
    name = artifact["file_name"]
    send_type = artifact.get("send_type", "document")
    caption = artifact.get("caption", name)
    size = os.path.getsize(path)
    cache_key = artifact.get("_url") or name

    # Privacy: file goes only to the requesting user (and storage channel).
    thumb = store.get_thumbnail(user_id)
    try:
        await status_msg.edit_text(f"⬆️ Uploading <b>{name}</b>…", parse_mode=ParseMode.HTML)
    except Exception:
        pass

    # Files above the Telegram size cap are split into parts and uploaded as documents.
    if size <= config.MAX_MT_PROTO_SIZE:
        parts = [path]
    else:
        try:
            parts = split_file(path, config.SPLIT_PART_SIZE)
        except Exception as e:
            logger.error("split failed: %s", e)
            await status_msg.edit_text(
                f"⚠️ <b>{name}</b> ({_fmt_size(size)}) is too large for Telegram and splitting failed.\nFile kept on server.\n<code>{path}</code>",
                parse_mode=ParseMode.HTML,
            )
            return

    upload_cb = _upload_progress_cb(status_msg, name)

    # Step 1: store in channel (cache) + log
    stored_parts: list[dict] = []
    if config.CHANNEL_ID:
        for part_path in parts:
            part_name = os.path.basename(part_path) if len(parts) > 1 else name
            try:
                chan_msg_id = await upload_to_channel(part_path, part_name, progress_cb=upload_cb)
                stored_parts.append({"name": part_name, "msg_id": chan_msg_id})
            except Exception as e:
                logger.error("channel upload failed: %s", e)
        if stored_parts:
            db.set_file_parts(cache_key, name, size, stored_parts)
            log_rec = (
                f"📄 <b>New download</b>\n"
                f"File: <b>{name}</b>\nSize: {_fmt_size(size)}"
                + (f"\nParts: {len(stored_parts)}" if len(stored_parts) > 1 else "")
                + f"\nRequested by: <code>{user_id}</code>"
            )
            try:
                await bot.send_message(config.CHANNEL_ID, log_rec, parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.error("channel log failed: %s", e)

    # Step 2: send to user (parts as documents, single file with media type + thumbnail)
    for i, part_path in enumerate(parts):
        part_name = os.path.basename(part_path) if len(parts) > 1 else name
        part_send_type = "document" if len(parts) > 1 else send_type
        part_caption = f"{caption} (part {i + 1}/{len(parts)})" if len(parts) > 1 else caption
        await send_media(chat_id, part_path, part_name, part_send_type, part_caption, thumb, status_msg, progress_cb=upload_cb)
    try:
        await status_msg.delete()
    except Exception:
        pass


def _upload_progress_cb(status_msg: Message, name: str):
    last = {"t": 0, "pct": -1}

    async def cb(done: int, total: int, speed: int = 0):
        now = time.time()
        if now - last["t"] < 1.0:
            return
        last["t"] = now
        pct = (done / total * 100) if total > 0 else 0
        if pct - last["pct"] < 0.8:
            return
        last["pct"] = pct
        try:
            await status_msg.edit_text(
                f"⬆️ <b>Uploading {name}</b>\n<code>{bar(pct)}</code> {pct:.1f}%\n"
                f"📦 {_fmt_size(done)} / {_fmt_size(total)}"
                + (f"\n⚡ {_fmt_speed(speed)}" if speed else "")
            )
        except Exception:
            pass

    return cb


async def send_media(chat_id: int, path: str, name: str, send_type: str, caption: str, thumb: str | None, status_msg: Message, progress_cb=None):
    size = os.path.getsize(path)
    thumb_input = FSInputFile(thumb) if thumb and os.path.isfile(thumb) else None

    if size <= config.MAX_BOTAPI_SIZE:
        if send_type == "video":
            width, height, duration = media.video_metadata(path)
            await bot.send_video(chat_id, FSInputFile(path), caption=caption, width=width, height=height, duration=duration, supports_streaming=True, thumbnail=thumb_input)
        elif send_type == "audio":
            duration = media.audio_duration(path)
            await bot.send_audio(chat_id, FSInputFile(path), caption=caption, title=name, duration=duration, thumbnail=thumb_input)
        else:
            await bot.send_document(chat_id, FSInputFile(path), caption=caption, thumbnail=thumb_input)
        return

    if size <= config.MAX_MT_PROTO_SIZE and mtproto is not None:
        await mtproto.send_file(
            chat_id,
            path,
            caption=caption,
            force_document=(send_type == "document"),
            attributes=[DocumentAttributeFilename(file_name=name)],
            part_size_kib=1024,
            file_size=size,
            progress_callback=progress_cb,
        )
        return

    await status_msg.edit_text(
        f"⚠️ <b>{name}</b> ({_fmt_size(size)}) is too large for Telegram.\nFile kept on server.\n<code>{path}</code>",
        parse_mode=ParseMode.HTML,
    )


async def upload_to_channel(path: str, name: str, progress_cb=None) -> int:
    size = os.path.getsize(path)
    if size <= config.MAX_BOTAPI_SIZE:
        with open(path, "rb") as fh:
            msg = await bot.send_document(config.CHANNEL_ID, BufferedInputFile(fh.read(), filename=name))
            return _msg_id(msg)
    if mtproto is not None:
        msg = await mtproto.send_file(
            config.CHANNEL_ID,
            path,
            attributes=[DocumentAttributeFilename(file_name=name)],
            part_size_kib=1024,
            file_size=size,
            progress_callback=progress_cb,
        )
        return _msg_id(msg)
    raise RuntimeError(f"File {name} is {_fmt_size(size)}, larger than Bot API limit, and MTProto is not configured")


# --------------------------------------------------------------------------
# Status / control commands
# --------------------------------------------------------------------------

@dp.message(Command("list"))
@guard
async def cmd_list(message: Message):
    try:
        items = await aria2.all_status()
    except RuntimeError as e:
        await message.answer(f"❌ aria2 RPC error: {e}")
        return
    if not items:
        await message.answer("📭 No downloads.")
        return
    from aria2_client import Aria2Client
    text = "\n\n".join(Aria2Client.format_status(it) for it in items[:6])
    await message.answer(f"<pre>{text}</pre>")


@dp.message(Command("status"))
@guard
async def cmd_status(message: Message):
    gid = (message.text.split() + [""])[1]
    if not gid:
        await message.answer("❌ Usage: <code>/status GID</code>")
        return
    from aria2_client import Aria2Client
    try:
        st = await aria2.get_status(gid)
    except RuntimeError as e:
        await message.answer(f"❌ {e}")
        return
    await message.answer(f"<pre>{Aria2Client.format_status(st)}</pre>")


@dp.message(Command("pause"))
@guard
async def cmd_pause(message: Message):
    gid = (message.text.split() + [""])[1]
    if not gid:
        await message.answer("❌ Usage: <code>/pause GID</code>")
        return
    try:
        await aria2.pause(gid)
        await message.answer(f"⏸️ Paused <code>{gid}</code>")
    except RuntimeError as e:
        await message.answer(f"❌ {e}")


@dp.message(Command("resume"))
@guard
async def cmd_resume(message: Message):
    gid = (message.text.split() + [""])[1]
    if not gid:
        await message.answer("❌ Usage: <code>/resume GID</code>")
        return
    try:
        await aria2.unpause(gid)
        await message.answer(f"▶️ Resumed <code>{gid}</code>")
    except RuntimeError as e:
        await message.answer(f"❌ {e}")


@dp.message(Command("cancel"))
@guard
async def cmd_cancel(message: Message):
    gid = (message.text.split() + [""])[1]
    if not gid:
        await message.answer("❌ Usage: <code>/cancel GID</code>")
        return
    try:
        await aria2.remove(gid)
        await aria2.remove_result(gid)
        await message.answer(f"🗑️ Removed <code>{gid}</code>")
    except RuntimeError as e:
        await message.answer(f"❌ {e}")


# --------------------------------------------------------------------------
# Admin panel
# --------------------------------------------------------------------------

class AdminState(StatesGroup):
    add_user = State()


def admin_panel_text() -> str:
    admins = db.get_admins()
    lines = [f"🛠️ <b>Admin Panel</b>\n\nOwner: <code>{config.OWNER_ID}</code>\n\n<b>Granted users:</b>"]
    if admins:
        for a in admins:
            lines.append(f"• <code>{a}</code>")
    else:
        lines.append("• (none)")
    lines.append(f"\nChannel: <code>{config.CHANNEL_ID}</code>")
    return "\n".join(lines)


def admin_panel_kb() -> InlineKeyboardMarkup:
    kb = [
        [btn("➕ Add user", "admin:add", "success")],
        [btn("🗑️ Remove user", "admin:remove", "danger")],
        [btn("📋 List users", "admin:list", "primary")],
        [btn("🏠 Back", "admin:home", "secondary")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


@dp.callback_query(lambda c: c.data and c.data.startswith("admin:"))
async def on_admin_cb(cb: CallbackQuery, state: FSMContext):
    if cb.from_user and not is_owner(cb.from_user.id):
        await cb.answer("⛔ Owner only", show_alert=True)
        return
    action = cb.data.split(":", 1)[1]
    if action == "add":
        await cb.answer()
        await state.set_state(AdminState.add_user)
        await cb.message.edit_text(
            "Send the Telegram numeric ID(s) to grant access.\n"
            "You can send several at once — separated by spaces, commas or newlines.\n"
            "(e.g. <code>123456789 987654321 555111222</code>)\n"
            "Send /cancel to abort."
        )
    elif action == "remove":
        await cb.answer()
        admins = db.get_admins()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🚫 {a}", callback_data=f"del:{a}", style=ButtonStyle.DANGER)]
            for a in admins
        ] + [[btn("🏠 Back", "admin:home", "secondary")]])
        await cb.message.edit_text("Select a user to remove:", reply_markup=kb)
    elif action == "list":
        await cb.answer()
        await cb.message.edit_text(admin_panel_text(), reply_markup=admin_panel_kb())
    elif action == "home":
        await cb.answer()
        await state.clear()
        await cb.message.edit_text(admin_panel_text(), reply_markup=admin_panel_kb())
    else:
        await cb.answer()


@dp.callback_query(lambda c: c.data and c.data.startswith("del:"))
async def on_del_cb(cb: CallbackQuery):
    if cb.from_user and not is_owner(cb.from_user.id):
        await cb.answer("⛔ Owner only", show_alert=True)
        return
    uid = int(cb.data.split(":", 1)[1])
    db.remove_admin(uid)
    await cb.answer(f"Removed {uid}")
    await cb.message.edit_text(admin_panel_text(), reply_markup=admin_panel_kb())


@dp.message(AdminState.add_user)
@guard_owner
async def admin_add_user(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    ids = re.split(r"[\s,;]+", text)
    ids = [i for i in ids if i.isdigit()]
    if not ids:
        await message.answer(
            "❌ That doesn't look like numeric user IDs.\n"
            "Send one or more IDs separated by spaces/commas/newlines.\n"
            "Example: <code>123456 789012 345678</code>\n"
            "Or send /cancel."
        )
        return
    added = []
    for i in ids:
        uid = int(i)
        if uid in db.get_admins() or uid == config.OWNER_ID:
            continue
        db.add_admin(uid)
        added.append(uid)
        try:
            await bot.send_message(uid, "🎉 You now have access to the downloader bot. Send /start to begin.")
        except Exception as e:
            logger.warning("could not notify new user %s: %s", uid, e)
    await state.clear()
    if not added:
        await message.answer("⚠️ All provided IDs already have access.")
        return
    names = " ".join(f"<code>{u}</code>" for u in added)
    await message.answer(f"✅ Granted access to {len(added)} user(s):\n{names}")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

async def init_mtproto():
    global mtproto
    if not config.TELEGRAM_API_ID or not config.TELEGRAM_API_HASH:
        logger.warning("TELEGRAM_API_ID / TELEGRAM_API_HASH not set. Files >49 MiB won't be uploadable.")
        return
    mtproto = TelegramClient("mtproto_session", config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH)
    await mtproto.start(bot_token=config.BOT_TOKEN)
    logger.info("MTProto client connected")


async def main():
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")
    if config.CHANNEL_ID:
        try:
            ch = await bot.get_chat(config.CHANNEL_ID)
            logger.info("Storage channel: %s", getattr(ch, "title", config.CHANNEL_ID))
        except Exception as e:
            logger.warning("Could not access channel %s: %s. Add the bot as channel admin!", config.CHANNEL_ID, e)
    await init_mtproto()
    logger.info("Starting bot polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

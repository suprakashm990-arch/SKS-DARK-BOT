import os
import sys
import re
import time
import logging
import asyncio
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import quote
from datetime import datetime, timedelta

import requests
from telethon import TelegramClient, events, Button
from telethon.errors import (
    UsernameInvalidError,
    UsernameNotOccupiedError,
    ChannelPrivateError,
    FloodWaitError,
)

# ============================================================
# PREMIUM MOD BOT - FIXED VERSION
#
# IMPORTANT:
# 1) This bot does NOT call iter_messages/get_history.
#    Telegram restricts history requests for bot accounts.
# 2) Channel posts are indexed when the bot receives them.
# 3) Bot must be ADMIN in the source channel to receive new posts.
# 4) Owner commands work by numeric Telegram OWNER_ID.
# 5) /defaultchannel @PRMMOD is OWNER ONLY.
# 6) /setup in a group is allowed for the OWNER or GROUP ADMINS.
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

print("🚀 PREMIUM MOD BOT BOOTING...")

# ---------------- ENV ----------------

API_ID = os.getenv("TG_API_ID")
API_HASH = os.getenv("TG_API_HASH")
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")

FIREBASE_URL = os.getenv(
    "FIREBASE_URL",
    "https://sks-9865a-default-rtdb.firebaseio.com/",
)

OWNER_ID = int(os.getenv("OWNER_ID", "8587571289"))

if not API_ID or not API_HASH or not BOT_TOKEN:
    print("❌ TG_API_ID / TG_API_HASH / TG_BOT_TOKEN missing")
    sys.exit(1)

try:
    API_ID = int(API_ID)
except ValueError:
    print("❌ TG_API_ID must be a number")
    sys.exit(1)

bot = TelegramClient(
    "premium_mod_public_bot",
    API_ID,
    API_HASH,
)

START_TIME = datetime.now()
BOT_ME = None

# User ID -> setup state
SETUP = {}

# Group ID -> asyncio lock
SEARCH_LOCKS = {}

# Channel ID -> entity cache
CHANNEL_CACHE = {}


# ============================================================
# BASIC HELPERS
# ============================================================

def now_text():
    return datetime.now().strftime("%d-%m-%Y %H:%M:%S")


def get_lock(group_id):
    group_id = int(group_id)
    if group_id not in SEARCH_LOCKS:
        SEARCH_LOCKS[group_id] = asyncio.Lock()
    return SEARCH_LOCKS[group_id]


def sender_id_from_event(event):
    """Robust owner ID extraction, including channel messages."""
    sid = getattr(event, "sender_id", None)
    if isinstance(sid, int):
        return sid

    try:
        from_id = getattr(event.message, "from_id", None)
        uid = getattr(from_id, "user_id", None)
        if uid:
            return int(uid)
    except Exception:
        pass

    return None


def is_owner(event):
    sid = sender_id_from_event(event)
    return sid == OWNER_ID


async def is_group_admin(event):
    """Check the person who sent the command, never the bot itself."""
    if not event.is_group:
        return False

    if is_owner(event):
        return True

    sid = sender_id_from_event(event)
    if not sid:
        return False

    try:
        permissions = await bot.get_permissions(
            event.chat_id,
            sid,
        )
        return bool(getattr(permissions, "is_admin", False))
    except Exception as e:
        logging.warning("Admin check failed: %s", e)
        return False


async def safe_reply(event, text, **kwargs):
    try:
        return await event.reply(text, **kwargs)
    except Exception as e:
        logging.error("Reply failed: %s", e)
        return None


# ============================================================
# FIREBASE
# ============================================================

def firebase_request(method, path, data=None):
    try:
        url = FIREBASE_URL.rstrip("/") + "/" + path.lstrip("/")
        return requests.request(
            method,
            url,
            json=data,
            timeout=15,
        )
    except Exception as e:
        logging.error("Firebase %s error: %s", method, e)
        return None


def firebase_get(path):
    response = firebase_request("GET", path)

    if response is not None and response.status_code == 200:
        try:
            return response.json()
        except Exception:
            return None

    if response is not None:
        logging.error(
            "Firebase GET %s -> HTTP %s",
            path,
            response.status_code,
        )

    return None


def firebase_put(path, data):
    response = firebase_request("PUT", path, data)

    if response is not None and response.status_code in (200, 201):
        return True

    if response is not None:
        logging.error(
            "Firebase PUT %s -> HTTP %s",
            path,
            response.status_code,
        )

    return False


def firebase_delete(path):
    response = firebase_request("DELETE", path)

    return bool(
        response is not None
        and response.status_code in (200, 204)
    )


def firebase_online():
    response = firebase_request("GET", ".")
    return bool(
        response is not None
        and response.status_code == 200
    )


# ============================================================
# CONFIG / MAPPING
# ============================================================

def group_path(group_id):
    return f"groups/{int(group_id)}"


def default_channel_path():
    return "config/default_channel"


def get_group_mapping(group_id):
    data = firebase_get(group_path(group_id))
    return data if isinstance(data, dict) else {}


def get_default_channel():
    data = firebase_get(default_channel_path())
    return data if isinstance(data, dict) else {}


def save_group_mapping(group_id, channel):
    data = {
        "group_id": int(group_id),
        "channel_id": int(channel.id),
        "channel_title": getattr(channel, "title", "Unknown"),
        "channel_username": getattr(channel, "username", None),
        "updated_at": int(time.time()),
        "configured_by": OWNER_ID,
    }

    return firebase_put(
        group_path(group_id),
        data,
    )


def save_default_channel(channel):
    data = {
        "channel_id": int(channel.id),
        "channel_title": getattr(channel, "title", "Unknown"),
        "channel_username": getattr(channel, "username", None),
        "updated_at": int(time.time()),
        "configured_by": OWNER_ID,
    }

    return firebase_put(
        default_channel_path(),
        data,
    )


def delete_group_mapping(group_id):
    CHANNEL_CACHE.pop(int(group_id), None)
    return firebase_delete(group_path(group_id))


async def resolve_entity(value):
    value = (value or "").strip()

    if value.startswith("https://t.me/"):
        value = value.rstrip("/").split("/")[-1]

    if value.startswith("http://t.me/"):
        value = value.rstrip("/").split("/")[-1]

    if value.startswith("@"):
        value = value[1:]

    try:
        if re.fullmatch(r"-?\d+", value):
            return await bot.get_entity(int(value))

        return await bot.get_entity(value)

    except (
        UsernameInvalidError,
        UsernameNotOccupiedError,
        ChannelPrivateError,
    ):
        return None

    except Exception as e:
        logging.error("Entity resolve %r failed: %s", value, e)
        return None


async def channel_from_config(config):
    if not config:
        return None

    cid = config.get("channel_id")
    username = config.get("channel_username")

    cache_key = str(cid or username or "")
    if cache_key in CHANNEL_CACHE:
        return CHANNEL_CACHE[cache_key]

    try:
        if username:
            channel = await bot.get_entity(username)
        elif cid:
            channel = await bot.get_entity(int(cid))
        else:
            return None

        CHANNEL_CACHE[cache_key] = channel
        return channel

    except Exception as e:
        logging.error("Configured channel resolve failed: %s", e)
        return None


async def get_group_channel(group_id):
    custom = get_group_mapping(group_id)

    if custom:
        channel = await channel_from_config(custom)
        if channel:
            return channel

    default = get_default_channel()
    return await channel_from_config(default)


# ============================================================
# NORMALIZATION / SEARCH
# ============================================================

REQUEST_WORDS = {
    "do", "de", "dedo", "bhejo", "bhej", "send",
    "link", "links", "download", "downloadlink",
    "please", "plz", "pls", "bhai", "bro",
    "mujhe", "mera", "meri", "chahiye", "chaiye",
    "hai", "kya", "ka", "ki", "ke", "ko",
    "me", "mein", "par", "pe", "se",
    "wala", "wali", "version", "latest", "new",
    "mod", "apk", "app", "unlock", "premium",
    "share", "pls", "please",
}


def normalize(text):
    if not text:
        return ""

    text = unicodedata.normalize("NFKC", str(text)).lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(
        r"[_\-/.,:;|+*=~`'\"()\[\]{}<>!?]+",
        " ",
        text,
    )

    text = "".join(
        ch if ch.isalnum() or ch.isspace() else " "
        for ch in text
    )

    return re.sub(r"\s+", " ", text).strip()


def compact(text):
    return normalize(text).replace(" ", "")


def extract_app_query(text):
    words = normalize(text).split()
    cleaned = [
        w for w in words
        if w not in REQUEST_WORDS
    ]
    return " ".join(cleaned).strip()


def similarity(a, b):
    a = normalize(a)
    b = normalize(b)

    if not a or not b:
        return 0.0

    if a in b:
        return 100.0

    ac = compact(a)
    bc = compact(b)

    if ac and ac in bc:
        return 98.0

    return max(
        SequenceMatcher(None, a, b).ratio() * 100,
        SequenceMatcher(None, ac, bc).ratio() * 100,
    )


# ============================================================
# CHANNEL POST INDEX
# ============================================================

def channel_index_path(channel_id):
    return f"channel_posts/{int(channel_id)}"


def save_channel_post(event):
    """Save every received channel post to Firebase."""
    try:
        message = event.message
        channel = event.chat

        if not channel:
            return

        channel_id = int(channel.id)
        text = (message.raw_text or "").strip()

        if not text:
            return

        data = {
            "message_id": int(message.id),
            "channel_id": channel_id,
            "channel_title": getattr(channel, "title", "Unknown"),
            "channel_username": getattr(channel, "username", None),
            "text": text[:12000],
            "date": int(time.time()),
        }

        firebase_put(
            f"{channel_index_path(channel_id)}/{message.id}",
            data,
        )

        logging.info(
            "INDEXED channel=%s post=%s",
            channel_id,
            message.id,
        )

    except Exception as e:
        logging.error("Channel indexing error: %s", e)


@bot.on(events.NewMessage(incoming=True))
async def channel_post_indexer(event):
    try:
        # Broadcast channels are channels but not groups.
        if not event.is_channel or event.is_group:
            return

        await save_channel_post(event)

    except Exception as e:
        logging.error("Channel post handler error: %s", e)


def post_score(query, text):
    q = normalize(query)
    t = normalize(text)

    if not q or not t:
        return 0.0

    if q in t:
        return 100.0

    qc = compact(q)
    tc = compact(t)

    if qc and qc in tc:
        return 98.0

    # Compare the query against each word/window instead of
    # comparing it against a huge caption only.
    best = similarity(q, t)

    q_words = q.split()
    t_words = t.split()

    if len(q_words) > 1:
        n = len(q_words)
        for i in range(
            max(0, len(t_words) - n + 1)
        ):
            window = " ".join(
                t_words[i:i + n]
            )
            best = max(
                best,
                similarity(q, window),
            )

    return best


def load_index(channel_id):
    data = firebase_get(
        channel_index_path(channel_id)
    )
    return data if isinstance(data, dict) else {}


async def search_index(channel, query):
    posts = load_index(int(channel.id))

    if not posts:
        return None, 0.0

    best = None
    best_score = 0.0

    for value in posts.values():
        if not isinstance(value, dict):
            continue

        text = value.get("text", "")
        score = post_score(query, text)

        if score > best_score:
            best_score = score
            best = value

    if best and best_score >= 60:
        return best, best_score

    return None, best_score


# ============================================================
# TELEGRAM POST LINK
# ============================================================

def post_link(channel, message_id):
    username = getattr(channel, "username", None)

    if username:
        return f"https://t.me/{username}/{message_id}"

    cid = getattr(channel, "id", None)

    if cid:
        return f"https://t.me/c/{cid}/{message_id}"

    return None


def share_link(url, text):
    return (
        "https://t.me/share/url"
        f"?url={quote(url, safe='')}"
        f"&text={quote(text, safe='')}"
    )


def result_buttons(url, app_name):
    return [[
        Button.url("📥 OPEN POST", url),
        Button.url(
            "📤 SHARE",
            share_link(
                url,
                f"{app_name.upper()} available here",
            ),
        ),
    ]]


# ============================================================
# /START / /ID / /PING
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/start(?:\s+.*)?$"))
async def start_command(event):
    await safe_reply(
        event,
        "👋 **PREMIUM MOD BOT**\n\n"
        "🔎 App ka naam bhejo.\n"
        "Example: `Kuku TV do`\n\n"
        "Commands:\n"
        "/ping\n"
        "/id\n"
        "/help",
        parse_mode="md",
    )


@bot.on(events.NewMessage(pattern=r"^/id$"))
async def id_command(event):
    sid = sender_id_from_event(event)

    await safe_reply(
        event,
        "🆔 **YOUR TELEGRAM ID**\n\n"
        f"`{sid}`\n\n"
        f"👑 Owner configured ID: `{OWNER_ID}`\n"
        f"✅ Owner match: {'YES' if sid == OWNER_ID else 'NO'}",
        parse_mode="md",
    )


@bot.on(events.NewMessage(pattern=r"^/ping$"))
async def ping_command(event):
    uptime = datetime.now() - START_TIME
    total = int(uptime.total_seconds())
    hours = total // 3600
    minutes = (total % 3600) // 60

    fb = firebase_online()

    group_text = "N/A"
    if event.is_group:
        channel = await get_group_channel(event.chat_id)
        group_text = (
            "SET"
            if channel
            else "NOT SET"
        )

    await safe_reply(
        event,
        "🟢 **BOT ONLINE**\n\n"
        f"⏱️ Uptime: `{hours}h {minutes}m`\n"
        "📡 Telegram: ✅ CONNECTED\n"
        f"🔥 Firebase: {'✅ ONLINE' if fb else '❌ ERROR'}\n"
        "👥 Public Multi-User: ✅ ON\n"
        "🧠 Fuzzy Search: ✅ ON\n"
        "📤 Share Button: ✅ ON\n"
        f"📢 Group Channel: `{group_text}`",
        parse_mode="md",
    )


# ============================================================
# OWNER: /DEFAULTCHANNEL
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/defaultchannel(?:\s+(.+))?$"))
async def default_channel_command(event):
    if not is_owner(event):
        await safe_reply(
            event,
            "❌ **Sirf bot owner ye command use kar sakta hai.**\n\n"
            f"Detected ID: `{sender_id_from_event(event)}`",
            parse_mode="md",
        )
        return

    value = event.pattern_match.group(1)

    if not value:
        current = get_default_channel()

        if current:
            await safe_reply(
                event,
                "🌐 **DEFAULT CHANNEL**\n\n"
                f"📢 {current.get('channel_title', 'Unknown')}\n"
                f"🔗 @{current.get('channel_username') or 'Private'}\n"
                f"🆔 `{current.get('channel_id')}`",
                parse_mode="md",
            )
        else:
            await safe_reply(
                event,
                "⚠️ Default channel set nahi hai.\n\n"
                "Use:\n"
                "`/defaultchannel @PRMMOD`",
                parse_mode="md",
            )
        return

    await safe_reply(
        event,
        "🔎 Default channel resolve kar raha hoon...",
    )

    channel = await resolve_entity(value)

    if not channel:
        await safe_reply(
            event,
            "❌ **Channel resolve nahi hua.**\n\n"
            "Public channel ka exact username/link bhejo.\n"
            "Example: `/defaultchannel @PRMMOD`",
            parse_mode="md",
        )
        return

    if not save_default_channel(channel):
        await safe_reply(
            event,
            "❌ Channel resolve hua, lekin Firebase save failed.",
        )
        return

    await safe_reply(
        event,
        "✅ **DEFAULT CHANNEL SAVED**\n\n"
        f"📢 **{getattr(channel, 'title', 'Unknown')}**\n"
        f"🔗 `@{getattr(channel, 'username', None) or 'Private'}`\n"
        f"🆔 `{channel.id}`\n\n"
        "⚠️ New channel posts search ke liye bot ko "
        "is channel ka ADMIN banana zaroori hai.",
        parse_mode="md",
    )


# ============================================================
# GROUP /SETUP
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/setup(?:\s+(.+))?$"))
async def setup_command(event):
    if not event.is_group:
        await safe_reply(
            event,
            "⚠️ `/setup` group ke andar use karo.",
            parse_mode="md",
        )
        return

    if not await is_group_admin(event):
        await safe_reply(
            event,
            "❌ **Group admin permission verify nahi hui.**\n\n"
            "Sirf group admin ya bot owner `/setup` use kar sakta hai.",
            parse_mode="md",
        )
        return

    value = event.pattern_match.group(1)

    if not value:
        SETUP[sender_id_from_event(event)] = {
            "group_id": int(event.chat_id),
            "created_at": time.time(),
        }

        await safe_reply(
            event,
            "⚙️ **GROUP SETUP**\n\n"
            "Source channel ka username/link bhejo.\n\n"
            "Example:\n"
            "`@PRMMOD`\n\n"
            "Cancel: `/cancel`",
            parse_mode="md",
        )
        return

    await complete_group_setup(event, value.strip())


async def complete_group_setup(event, value):
    channel = await resolve_entity(value)

    if not channel:
        await safe_reply(
            event,
            "❌ Channel identify nahi hua.",
        )
        return

    if not save_group_mapping(event.chat_id, channel):
        await safe_reply(
            event,
            "❌ Firebase mein group mapping save nahi hui.",
        )
        return

    SETUP.pop(sender_id_from_event(event), None)

    await safe_reply(
        event,
        "✅ **GROUP SETUP COMPLETE**\n\n"
        f"📢 Channel: **{getattr(channel, 'title', 'Unknown')}**\n"
        f"🔗 Username: `@{getattr(channel, 'username', None) or 'Private'}`\n"
        f"👥 Group ID: `{event.chat_id}`\n\n"
        "🔎 Ab users app name bhej sakte hain.",
        parse_mode="md",
    )


@bot.on(events.NewMessage(pattern=r"^/cancel$"))
async def cancel_command(event):
    sid = sender_id_from_event(event)
    SETUP.pop(sid, None)

    await safe_reply(
        event,
        "✅ Setup mode cancel ho gaya.",
    )


# Setup text handler
@bot.on(events.NewMessage(incoming=True))
async def setup_text_handler(event):
    if not event.is_group:
        return

    text = (event.raw_text or "").strip()
    if not text or text.startswith("/"):
        return

    sid = sender_id_from_event(event)
    state = SETUP.get(sid)

    if not state:
        return

    if int(state["group_id"]) != int(event.chat_id):
        return

    if not await is_group_admin(event):
        SETUP.pop(sid, None)
        await safe_reply(
            event,
            "❌ Group admin permission verify nahi hui.",
        )
        return

    await complete_group_setup(event, text)


# ============================================================
# GROUP STATUS / DIAGNOSTIC
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/status$"))
async def status_command(event):
    if not event.is_group:
        await safe_reply(
            event,
            "⚠️ `/status` group mein use karo.",
        )
        return

    custom = get_group_mapping(event.chat_id)
    default = get_default_channel()

    await safe_reply(
        event,
        "📊 **BOT STATUS**\n\n"
        f"🤖 Telegram: {'✅ CONNECTED' if BOT_ME else '❌'}\n"
        f"🔥 Firebase: {'✅ ONLINE' if firebase_online() else '❌ ERROR'}\n\n"
        "🌐 **DEFAULT CHANNEL**\n"
        f"{'✅ SET' if default else '❌ NOT SET'}\n\n"
        "👥 **THIS GROUP**\n"
        f"Custom channel: {'✅ SET' if custom else '❌ NOT SET'}\n"
        "↪️ Fallback: Default channel\n\n"
        f"🔎 Effective channel: "
        f"{'✅ READY' if await get_group_channel(event.chat_id) else '❌ NOT READY'}",
        parse_mode="md",
    )


@bot.on(events.NewMessage(pattern=r"^/diagnostic$"))
async def diagnostic_command(event):
    sid = sender_id_from_event(event)

    channel = None
    if event.is_group:
        channel = await get_group_channel(event.chat_id)

    await safe_reply(
        event,
        "⚠️ **BOT DIAGNOSTIC**\n\n"
        f"🤖 Telegram Client: {'✅' if BOT_ME else '❌'}\n"
        f"🔥 Firebase: {'✅ ONLINE' if firebase_online() else '❌ ERROR'}\n"
        f"👤 Your ID: `{sid}`\n"
        f"👑 Owner ID: `{OWNER_ID}`\n"
        f"🛡 Owner Match: {'✅ YES' if is_owner(event) else '❌ NO'}\n"
        f"👥 Group Admin: "
        f"{'N/A' if not event.is_group else ('✅ YES' if await is_group_admin(event) else '❌ NO')}\n\n"
        f"🔎 Search Engine: {'READY' if channel else 'BLOCKED'}\n"
        "🧠 Fuzzy Search: ON\n"
        "📤 Share Button: ON\n\n"
        "⚠️ IMPORTANT\n"
        "Telegram bot accounts cannot use GetHistoryRequest.\n"
        "Therefore this bot indexes NEW channel posts into Firebase.\n"
        "Bot ko source channel ka ADMIN banana zaroori hai.",
        parse_mode="md",
    )


# ============================================================
# GROUP SEARCH
# ============================================================

@bot.on(events.NewMessage(incoming=True))
async def public_group_search(event):
    try:
        if not event.is_group:
            return

        text = (event.raw_text or "").strip()

        if not text or text.startswith("/"):
            return

        # Setup handler owns setup input.
        sid = sender_id_from_event(event)
        if sid in SETUP:
            state = SETUP[sid]
            if int(state["group_id"]) == int(event.chat_id):
                return

        channel = await get_group_channel(event.chat_id)

        if not channel:
            # Do not spam the group on every normal message.
            return

        query = extract_app_query(text)

        if not query or len(compact(query)) < 2:
            return

        async with get_lock(event.chat_id):
            logging.info(
                "SEARCH group=%s user=%s query=%r channel=%r",
                event.chat_id,
                sid,
                query,
                getattr(channel, "title", "Unknown"),
            )

            post, score = await search_index(
                channel,
                query,
            )

            if not post:
                logging.info(
                    "NOT FOUND query=%r score=%.1f",
                    query,
                    score,
                )
                return

            message_id = post.get("message_id")
            url = post_link(
                channel,
                message_id,
            )

            if not url:
                await safe_reply(
                    event,
                    "⚠️ Match mila, lekin post link generate nahi hua.",
                )
                return

            preview = (post.get("text") or "").strip()
            if len(preview) > 900:
                preview = preview[:900].rstrip() + "..."

            reply = (
                "👋 **Mil gaya!**\n\n"
                f"📱 Search: **{query.upper()}**\n"
                f"📢 Channel: **{getattr(channel, 'title', 'Unknown')}**\n"
                f"🎯 Match: **{score:.0f}%**\n\n"
            )

            if preview:
                reply += (
                    "📝 **Post:**\n"
                    f"{preview}\n\n"
                )

            reply += "👇 Open ya Share karo:"

            await safe_reply(
                event,
                reply,
                buttons=result_buttons(
                    url,
                    query,
                ),
                parse_mode="md",
                link_preview=False,
            )

    except FloodWaitError as e:
        logging.warning(
            "FloodWait %ss",
            e.seconds,
        )
        await asyncio.sleep(e.seconds)

    except Exception as e:
        logging.exception(
            "PUBLIC SEARCH ERROR: %s",
            e,
        )


# ============================================================
# HELP
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/help$"))
async def help_command(event):
    await safe_reply(
        event,
        "🤖 **PREMIUM MOD BOT**\n\n"
        "🔎 Search:\n"
        "`Kuku TV do`\n"
        "`KukuTV link`\n"
        "`BulletShorts do`\n\n"
        "👑 Owner:\n"
        "`/defaultchannel @PRMMOD`\n\n"
        "👥 Group Admin/Owner:\n"
        "`/setup @PRMMOD`\n"
        "`/status`\n"
        "`/diagnostic`\n"
        "`/reset`\n\n"
        "🧪 Other:\n"
        "`/start`\n"
        "`/ping`\n"
        "`/id`\n"
        "`/help`",
        parse_mode="md",
    )


@bot.on(events.NewMessage(pattern=r"^/reset$"))
async def reset_command(event):
    if not event.is_group:
        return

    if not await is_group_admin(event):
        await safe_reply(
            event,
            "❌ Sirf group admin ya owner `/reset` use kar sakta hai.",
        )
        return

    if delete_group_mapping(event.chat_id):
        await safe_reply(
            event,
            "✅ Custom group channel reset ho gaya.\n"
            "Ab default channel use hoga.",
        )
    else:
        await safe_reply(
            event,
            "❌ Firebase mapping delete nahi hui.",
        )


# ============================================================
# STARTUP / KEEP ALIVE
# ============================================================

async def github_keep_alive():
    while True:
        try:
            elapsed = datetime.now() - START_TIME

            if elapsed >= timedelta(hours=5, minutes=45):
                token = os.getenv("MY_GITHUB_TOKEN")
                repo = os.getenv("GITHUB_REPOSITORY")

                print("🔄 GitHub safe reboot requested")

                if token and repo:
                    url = (
                        f"https://api.github.com/repos/{repo}"
                        "/actions/workflows/run-bot.yml/dispatches"
                    )

                    headers = {
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {token}",
                        "X-GitHub-Api-Version": "2022-11-28",
                    }

                    try:
                        r = requests.post(
                            url,
                            headers=headers,
                            json={"ref": "main"},
                            timeout=15,
                        )
                        print(
                            "GitHub dispatch status:",
                            r.status_code,
                        )
                    except Exception as e:
                        logging.error(
                            "GitHub dispatch error: %s",
                            e,
                        )

                os._exit(0)

        except Exception as e:
            logging.error(
                "Keep-alive error: %s",
                e,
            )

        await asyncio.sleep(300)


async def main():
    global BOT_ME

    print("⏳ Starting Telegram Client...")

    await bot.start(
        bot_token=BOT_TOKEN
    )

    BOT_ME = await bot.get_me()

    print("✅ Telegram Client Started!")
    print(
        f"🤖 @{getattr(BOT_ME, 'username', 'unknown')} "
        f"ID={BOT_ME.id}"
    )
    print(f"👑 OWNER_ID={OWNER_ID}")
    print("🔥 Firebase indexing: ON")
    print("🧠 Fuzzy search: ON")
    print("🟢 BOT ONLINE - waiting for messages...")

    asyncio.create_task(
        github_keep_alive()
    )

    await bot.run_until_disconnected()


if __name__ == "__main__":
    try:
        bot.loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("🛑 Bot stopped.")
    except Exception as e:
        print(
            f"❌ FATAL: {type(e).__name__}: {e}"
        )
        raise

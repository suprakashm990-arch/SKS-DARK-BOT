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
    ChatAdminRequiredError,
    FloodWaitError,
)

# ============================================================
# PREMIUM MOD PUBLIC SEARCH BOT
# Telethon + Firebase
#
# PUBLIC MODE:
#   Every group can configure its own channel with /setup.
#   Mapping is saved in Firebase by GROUP ID.
#
# SEARCH:
#   Telegram server search first, then recent-post scan.
#   Caption/text both are searched.
#   Small spelling/spacing mistakes are tolerated.
#
# OWNER:
#   OWNER_ID keeps access to owner-only controls.
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

print("🚀 PREMIUM MOD BOT BOOTING...")

# -------------------- ENV --------------------

API_ID = os.environ.get("TG_API_ID")
API_HASH = os.environ.get("TG_API_HASH")
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")

FIREBASE_URL = "https://sks-9865a-default-rtdb.firebaseio.com/"
OWNER_ID = 8587571289

# Recent history fallback. 2500 is a good balance for GitHub Actions.
SCAN_LIMIT = 2500

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

# user_id -> setup state
SETUP = {}

# group_id -> asyncio.Lock()
SEARCH_LOCKS = {}

# group_id -> (channel_entity, saved_at)
CHANNEL_CACHE = {}

BOT_ME = None


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


def is_owner(event):
    return event.sender_id == OWNER_ID


async def safe_delete(message, delay=0):
    if delay:
        await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


# ============================================================
# FIREBASE
# ============================================================

def firebase_get(path):
    try:
        url = FIREBASE_URL.rstrip("/") + "/" + path.lstrip("/")
        response = requests.get(url, timeout=12)

        if response.status_code == 200:
            return response.json()

        logging.error(
            "Firebase GET %s -> HTTP %s",
            path,
            response.status_code,
        )
    except Exception as e:
        logging.error("Firebase GET error: %s", e)

    return None


def firebase_put(path, data):
    try:
        url = FIREBASE_URL.rstrip("/") + "/" + path.lstrip("/")
        response = requests.put(
            url,
            json=data,
            timeout=12,
        )

        if response.status_code in (200, 201):
            return True

        logging.error(
            "Firebase PUT %s -> HTTP %s",
            path,
            response.status_code,
        )
    except Exception as e:
        logging.error("Firebase PUT error: %s", e)

    return False


def firebase_delete(path):
    try:
        url = FIREBASE_URL.rstrip("/") + "/" + path.lstrip("/")
        response = requests.delete(url, timeout=12)
        return response.status_code in (200, 204)
    except Exception as e:
        logging.error("Firebase DELETE error: %s", e)

    return False


# ============================================================
# GROUP -> CHANNEL MAPPING
# ============================================================

def mapping_path(group_id):
    return f"groups/{int(group_id)}"


def get_mapping(group_id):
    data = firebase_get(mapping_path(group_id))
    return data if isinstance(data, dict) else {}


def save_mapping(group_id, channel):
    data = {
        "group_id": int(group_id),
        "channel_id": int(channel.id),
        "channel_title": getattr(channel, "title", "Unknown"),
        "channel_username": getattr(channel, "username", None),
        "updated_at": int(time.time()),
        "configured_by": OWNER_ID,
    }

    ok = firebase_put(mapping_path(group_id), data)

    if ok:
        CHANNEL_CACHE[int(group_id)] = (channel, time.time())

    return ok


def delete_mapping(group_id):
    CHANNEL_CACHE.pop(int(group_id), None)
    return firebase_delete(mapping_path(group_id))


async def get_group_channel(group_id):
    group_id = int(group_id)

    # Short in-memory cache.
    cached = CHANNEL_CACHE.get(group_id)
    if cached:
        channel, saved_at = cached
        if time.time() - saved_at < 300:
            return channel

    mapping = get_mapping(group_id)

    if not mapping:
        return None

    channel_id = mapping.get("channel_id")
    username = mapping.get("channel_username")

    if not channel_id and not username:
        return None

    try:
        if channel_id:
            channel = await bot.get_entity(int(channel_id))
        else:
            channel = await bot.get_entity(username)

        CHANNEL_CACHE[group_id] = (channel, time.time())
        return channel

    except Exception as e:
        logging.error(
            "Group %s channel resolve failed: %s",
            group_id,
            e,
        )
        return None


# ============================================================
# OPTIONAL MANUAL FILTER LINKS
# ============================================================

def safe_key(value):
    value = str(value).strip().lower()
    for char in ".#$[]/":
        value = value.replace(char, "_")
    return value[:100]


def get_filter_links():
    data = firebase_get("links")
    return data if isinstance(data, dict) else {}


def save_filter_link(app_name, download_link):
    return firebase_put(
        f"links/{safe_key(app_name)}",
        {
            "name": app_name.strip(),
            "link": download_link.strip(),
            "updated_at": int(time.time()),
        },
    )


# ============================================================
# TEXT NORMALIZATION / FUZZY SEARCH
# ============================================================

REQUEST_WORDS = {
    "do", "de", "dedo", "bhejo", "bhej", "send",
    "link", "links", "download", "downloadlink",
    "please", "plz", "pls", "bhai", "bro",
    "mujhe", "mera", "meri", "chahiye", "chaiye",
    "hai", "kya", "ka", "ki", "ke", "ko",
    "me", "mein", "par", "pe", "se", "wala", "wali",
    "version", "latest", "new", "mod", "apk", "app",
    "unlock", "premium", "share",
}


def normalize(text):
    if not text:
        return ""

    text = unicodedata.normalize("NFKC", str(text)).lower()

    # URLs do not help identify the app name.
    text = re.sub(r"https?://\S+", " ", text)

    # Keep letters/numbers and convert separators to spaces.
    text = re.sub(r"[_\-/.,:;|+*=~`'\"()\[\]{}<>!?]+", " ", text)

    text = "".join(
        char if char.isalnum() or char.isspace() else " "
        for char in text
    )

    return re.sub(r"\s+", " ", text).strip()


def compact(text):
    return normalize(text).replace(" ", "")


def extract_app_query(text):
    words = normalize(text).split()

    cleaned = [
        word for word in words
        if word not in REQUEST_WORDS
    ]

    return " ".join(cleaned).strip()


def similarity(a, b):
    a_n = normalize(a)
    b_n = normalize(b)

    if not a_n or not b_n:
        return 0

    if a_n in b_n:
        return 100

    a_c = compact(a_n)
    b_c = compact(b_n)

    if a_c and a_c in b_c:
        return 98

    direct = SequenceMatcher(
        None,
        a_n,
        b_n,
    ).ratio() * 100

    compact_score = SequenceMatcher(
        None,
        a_c,
        b_c,
    ).ratio() * 100

    # Best individual word similarity.
    word_best = 0

    for query_word in a_n.split():
        if len(query_word) < 2:
            continue

        for post_word in b_n.split():
            score = SequenceMatcher(
                None,
                query_word,
                post_word,
            ).ratio() * 100

            word_best = max(word_best, score)

    return max(
        direct,
        compact_score,
        word_best,
    )


def post_score(query, post_text):
    """
    Scores the requested app against the complete post.
    Exact/compact matches win.
    A fuzzy score of >=60 is accepted.
    """

    query_n = normalize(query)
    text_n = normalize(post_text)

    if not query_n or not text_n:
        return 0

    if query_n in text_n:
        return 100

    query_c = compact(query_n)
    text_c = compact(text_n)

    if query_c and query_c in text_c:
        return 98

    best = similarity(query_n, text_n)

    query_words = query_n.split()
    post_words = text_n.split()

    # Compare short consecutive windows so a long caption
    # doesn't destroy the app-name score.
    if len(query_words) > 1:
        size = len(query_words)

        for index in range(
            0,
            max(0, len(post_words) - size + 1),
        ):
            window = " ".join(
                post_words[index:index + size]
            )

            best = max(
                best,
                similarity(query_n, window),
            )

    return best


# ============================================================
# TELEGRAM ENTITY RESOLUTION
# ============================================================

def extract_username(value):
    value = (value or "").strip()

    if value.startswith("@"):
        return value[1:]

    match = re.match(
        r"^(?:https?://)?(?:www\.)?t\.me/"
        r"([A-Za-z0-9_]+)(?:/.*)?$",
        value,
    )

    if match:
        username = match.group(1)

        if username not in ("c", "joinchat"):
            return username

    return None


async def resolve_entity(value):
    value = (value or "").strip()

    username = extract_username(value)

    try:
        if username:
            return await bot.get_entity(username)

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
        logging.error(
            "Resolve entity %r failed: %s",
            value,
            e,
        )
        return None


async def validate_channel(channel):
    try:
        # This confirms that the bot can actually read the channel.
        await bot.get_messages(
            channel,
            limit=3,
        )
        return True, None

    except ChatAdminRequiredError:
        return (
            False,
            "Channel read/admin permission required.",
        )

    except ChannelPrivateError:
        return (
            False,
            "Channel private hai ya bot channel ka member nahi hai.",
        )

    except FloodWaitError as e:
        return (
            False,
            f"Telegram FloodWait: {e.seconds} seconds.",
        )

    except Exception as e:
        return False, str(e)


# ============================================================
# CHANNEL SEARCH
# ============================================================

async def search_channel(channel, query):
    if not query:
        return None, 0, "empty-query"

    best_message = None
    best_score = 0
    seen = set()

    # Telegram server-side search.
    search_terms = [normalize(query)]

    for word in normalize(query).split():
        if len(word) >= 3:
            search_terms.append(word)

    for term in search_terms[:5]:
        try:
            async for message in bot.iter_messages(
                channel,
                search=term,
                limit=100,
            ):
                if not message:
                    continue

                if message.id in seen:
                    continue

                seen.add(message.id)

                post_text = message.raw_text or ""

                if not post_text:
                    continue

                score = post_score(
                    query,
                    post_text,
                )

                if score > best_score:
                    best_score = score
                    best_message = message

                if score >= 98:
                    return (
                        best_message,
                        best_score,
                        "telegram-search",
                    )

        except FloodWaitError as e:
            logging.warning(
                "Telegram search FloodWait: %ss",
                e.seconds,
            )
            await asyncio.sleep(e.seconds)

        except Exception as e:
            logging.warning(
                "Telegram server search error: %s",
                e,
            )

    # Direct recent-history fallback.
    try:
        scanned = 0

        async for message in bot.iter_messages(
            channel,
            limit=SCAN_LIMIT,
        ):
            if not message:
                continue

            post_text = message.raw_text or ""

            if not post_text:
                continue

            scanned += 1

            score = post_score(
                query,
                post_text,
            )

            if score > best_score:
                best_score = score
                best_message = message

            if score >= 98:
                return (
                    best_message,
                    best_score,
                    "history-scan",
                )

            if scanned >= SCAN_LIMIT:
                break

    except FloodWaitError as e:
        logging.warning(
            "History scan FloodWait: %ss",
            e.seconds,
        )

    except Exception as e:
        logging.error(
            "History scan error: %s",
            e,
        )

    if best_message and best_score >= 60:
        return (
            best_message,
            best_score,
            "fuzzy-history",
        )

    return None, best_score, "not-found"


# ============================================================
# LINKS / BUTTONS
# ============================================================

def post_link(channel, message):
    username = getattr(
        channel,
        "username",
        None,
    )

    if username:
        return f"https://t.me/{username}/{message.id}"

    channel_id = getattr(
        channel,
        "id",
        None,
    )

    if channel_id:
        return f"https://t.me/c/{channel_id}/{message.id}"

    return None


def share_link(url, text):
    base = "https://t.me/share/url"

    return (
        base
        + "?url=" + quote(url, safe="")
        + "&text=" + quote(text, safe="")
    )


def result_buttons(post_url, app_name):
    buttons = []

    if post_url:
        buttons.append(
            [
                Button.url(
                    "📥 OPEN POST",
                    post_url,
                ),
                Button.url(
                    "📤 SHARE",
                    share_link(
                        post_url,
                        f"{app_name.upper()} available here",
                    ),
                ),
            ]
        )

    return buttons


# ============================================================
# SETUP
# ============================================================

async def send_setup_help(event):
    await event.reply(
        "⚙️ **GROUP SETUP**\n\n"
        "Is group ke liye jis Telegram channel se search karna hai "
        "uska link bhejo.\n\n"
        "Example:\n"
        "`https://t.me/PRMMOD`\n\n"
        "Private channel ho to bot ko pehle us channel mein add/admin karo.\n\n"
        "❌ Setup cancel: `/cancel`",
        parse_mode="md",
    )


@bot.on(events.NewMessage(pattern=r"^/setup(?:\s+(.+))?$"))
async def setup_command(event):
    if not event.is_group:
        await event.reply(
            "⚠️ `/setup` group ke andar use karo."
        )
        return

    value = event.pattern_match.group(1)

    if value:
        # One-message setup.
        await complete_setup(
            event,
            value.strip(),
        )
        return

    SETUP[event.sender_id] = {
        "type": "channel",
        "group_id": event.chat_id,
        "created_at": time.time(),
    }

    await send_setup_help(event)


@bot.on(events.NewMessage(pattern=r"^/cancel$"))
async def cancel_command(event):
    SETUP.pop(event.sender_id, None)

    await event.reply(
        "✅ Current setup mode cancel ho gaya."
    )


async def complete_setup(event, value):
    if not event.is_group:
        await event.reply(
            "⚠️ Channel setup group ke andar karo."
        )
        return

    await event.reply(
        "🔎 Channel check kar raha hoon..."
    )

    channel = await resolve_entity(value)

    if not channel:
        await event.reply(
            "❌ **Channel identify nahi hua.**\n\n"
            "Public channel ka exact `https://t.me/...` link bhejo.\n"
            "Private channel ho to bot ko channel mein add/admin karo.",
            parse_mode="md",
        )
        return

    ok, error = await validate_channel(channel)

    if not ok:
        await event.reply(
            "❌ **Channel access problem**\n\n"
            f"`{error}`",
            parse_mode="md",
        )
        return

    if not save_mapping(event.chat_id, channel):
        await event.reply(
            "❌ Channel mil gaya, lekin Firebase mein mapping save nahi hui."
        )
        return

    title = getattr(
        channel,
        "title",
        "Unknown",
    )

    username = getattr(
        channel,
        "username",
        None,
    )

    SETUP.pop(event.sender_id, None)

    username_text = (
        f"@{username}"
        if username
        else "Private / ID based"
    )

    await event.reply(
        "✅ **SETUP COMPLETE**\n\n"
        f"📢 Channel: **{title}**\n"
        f"🔗 Username: `{username_text}`\n"
        f"👥 Group ID: `{event.chat_id}`\n\n"
        "🔎 Ab is group ke users app name likhenge aur "
        "bot isi mapped channel mein search karega.",
        parse_mode="md",
    )


# ============================================================
# SETUP STATE HANDLER
# ============================================================

@bot.on(events.NewMessage(incoming=True))
async def setup_message_handler(event):
    if not event.is_group:
        return

    # Commands are handled by their own handlers.
    text = (event.raw_text or "").strip()

    if not text or text.startswith("/"):
        return

    state = SETUP.get(event.sender_id)

    if not state:
        return

    if state.get("group_id") != event.chat_id:
        return

    if state.get("type") != "channel":
        return

    await complete_setup(
        event,
        text,
    )


# ============================================================
# NORMAL PUBLIC SEARCH
# ============================================================

@bot.on(events.NewMessage(incoming=True))
async def public_group_search(event):
    try:
        if not event.is_group:
            return

        text = (event.raw_text or "").strip()

        if not text or text.startswith("/"):
            return

        # If this user is currently entering setup data,
        # setup_message_handler owns this message.
        if event.sender_id in SETUP:
            state = SETUP[event.sender_id]
            if state.get("group_id") == event.chat_id:
                return

        # Only search when this group has a configured channel.
        channel = await get_group_channel(event.chat_id)

        if not channel:
            return

        query = extract_app_query(text)

        if not query or len(compact(query)) < 2:
            return

        # Prevent multiple simultaneous expensive channel scans
        # when several users request the same thing together.
        async with get_lock(event.chat_id):
            logging.info(
                "SEARCH group=%s user=%s query=%r channel=%r",
                event.chat_id,
                event.sender_id,
                query,
                getattr(channel, "title", "Unknown"),
            )

            # ------------------------------------------------
            # Firebase manual link database first.
            # ------------------------------------------------
            filters = get_filter_links()

            for key, value in filters.items():
                if isinstance(value, dict):
                    saved_name = value.get("name", key)
                    saved_link = value.get("link")
                else:
                    saved_name = key
                    saved_link = value

                if not saved_link:
                    continue

                score = similarity(
                    query,
                    saved_name,
                )

                if score >= 85:
                    await event.reply(
                        "👋 **Mil gaya!**\n\n"
                        f"📥 **{str(saved_name).upper()}**\n"
                        f"🔗 {saved_link}",
                        parse_mode="md",
                        link_preview=False,
                    )
                    return

            # ------------------------------------------------
            # Live channel search.
            # ------------------------------------------------
            message, score, method = await search_channel(
                channel,
                query,
            )

            if not message:
                logging.info(
                    "NOT FOUND group=%s query=%r score=%s method=%s",
                    event.chat_id,
                    query,
                    round(score, 1),
                    method,
                )
                return

            url = post_link(
                channel,
                message,
            )

            if not url:
                await event.reply(
                    "⚠️ Post mil gaya, lekin Telegram post link generate nahi hua."
                )
                return

            title = getattr(
                channel,
                "title",
                "Channel",
            )

            # Show the actual matching post text so the admin/user
            # can see what was matched.
            preview = (message.raw_text or "").strip()

            if len(preview) > 700:
                preview = preview[:700].rstrip() + "..."

            reply = (
                "👋 **Mil gaya!**\n\n"
                f"📱 Search: **{query.upper()}**\n"
                f"📢 Channel: **{title}**\n"
                f"🎯 Match: **{score:.0f}%**\n\n"
            )

            if preview:
                reply += (
                    "📝 **Post:**\n"
                    f"{preview}\n\n"
                )

            reply += "👇 Post open/share karne ke liye:"

            await event.reply(
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
            "Group search FloodWait: %ss",
            e.seconds,
        )

    except Exception as e:
        logging.exception(
            "PUBLIC SEARCH ERROR: %s",
            e,
        )


# ============================================================
# MANUAL FILTER COMMAND
# OWNER ONLY
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/filter\s+(.+?)\s+(https?://\S+)$"))
async def filter_command(event):
    if not is_owner(event):
        return

    app_name = event.pattern_match.group(1).strip()
    link = event.pattern_match.group(2).strip()

    if save_filter_link(
        app_name,
        link,
    ):
        await event.reply(
            "✅ **FILTER SAVED**\n\n"
            f"📱 {app_name.upper()}\n"
            f"🔗 {link}",
            parse_mode="md",
        )
    else:
        await event.reply(
            "❌ Firebase mein filter save nahi hua."
        )


# ============================================================
# KILL POST
# OWNER ONLY
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/killpost$"))
async def killpost_command(event):
    if not is_owner(event):
        return

    if not event.is_reply:
        await event.reply(
            "⚠️ Jis post ko delete karna hai usko reply karke `/killpost` bhejo."
        )
        return

    reply_message = await event.get_reply_message()

    try:
        await reply_message.delete()
    except Exception:
        pass

    await safe_delete(event, 0)

    confirmation = await bot.send_message(
        event.chat_id,
        "🗑️ **Post Deleted!**",
        parse_mode="md",
    )

    await safe_delete(
        confirmation,
        5,
    )


# ============================================================
# DIAGNOSTIC
# ============================================================

async def diagnostic_text(event):
    lines = [
        "⚠️ **BOT DIAGNOSTIC**",
        "",
        "👤 Public Multi-User: ✅",
    ]

    mapping = get_mapping(event.chat_id)

    if mapping:
        lines.append("👥 Group Mapping: ✅")
    else:
        lines.append("👥 Group Mapping: ❌")

    firebase_ok = firebase_get(".") is not None

    lines.append(
        "🔥 Firebase: "
        + ("✅" if firebase_ok else "❌")
    )

    channel = None

    if mapping:
        channel = await get_group_channel(
            event.chat_id
        )

    if channel:
        lines.append("📢 Channel Access: ✅")
        lines.append(
            f"📡 Channel: {getattr(channel, 'title', 'Unknown')}"
        )
    else:
        lines.append("📢 Channel Access: ❌")

    if BOT_ME:
        lines.append(
            f"🤖 Bot: @{getattr(BOT_ME, 'username', None) or 'unknown'}"
        )

    lines.extend(
        [
            "",
            "🔎 Search: "
            + ("READY" if channel else "BLOCKED"),
            "",
            "Common cause if search does not start:",
            "1. Group mein BotFather Privacy Mode ON.",
            "2. Bot group ke normal messages receive nahi kar raha.",
            "3. Channel private hai aur bot member/admin nahi.",
            "4. Firebase group mapping missing.",
        ]
    )

    return "\n".join(lines)


@bot.on(events.NewMessage(pattern=r"^/diagnostic$"))
async def diagnostic_command(event):
    if not event.is_group:
        await event.reply(
            "⚠️ `/diagnostic` group mein use karo."
        )
        return

    await event.reply(
        await diagnostic_text(event),
        parse_mode="md",
    )


# ============================================================
# PING
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/ping$"))
async def ping_command(event):
    uptime = datetime.now() - START_TIME

    hours = int(
        uptime.total_seconds() // 3600
    )

    minutes = int(
        (uptime.total_seconds() % 3600) // 60
    )

    mapping = (
        get_mapping(event.chat_id)
        if event.is_group
        else {}
    )

    channel_ok = bool(mapping)

    await event.reply(
        "🟢 **BOT ONLINE**\n\n"
        f"⏱️ Uptime: {hours}h {minutes}m\n"
        "🔎 Live Search: ON\n"
        f"🔥 Firebase: {'ON' if firebase_get('.') is not None else 'ERROR'}\n"
        f"👥 Public Multi-User: ON\n"
        f"📢 Group Channel: {'SET' if channel_ok else 'NOT SET'}\n"
        "🧠 Fuzzy Search: ON\n"
        "📤 Share Button: ON\n"
        "🧪 Diagnostic System: ON",
        parse_mode="md",
    )


# ============================================================
# MAPPING STATUS / RESET
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/status$"))
async def status_command(event):
    if not event.is_group:
        return

    mapping = get_mapping(
        event.chat_id
    )

    if not mapping:
        await event.reply(
            "❌ Is group ka channel setup nahi hai.\n"
            "Use `/setup`",
            parse_mode="md",
        )
        return

    await event.reply(
        "📌 **GROUP MAPPING**\n\n"
        f"👥 Group: `{event.chat_id}`\n"
        f"📢 Channel: **{mapping.get('channel_title', 'Unknown')}**\n"
        f"🆔 Channel ID: `{mapping.get('channel_id')}`\n"
        f"🔗 Username: `{mapping.get('channel_username') or 'Private'}`\n\n"
        "🔎 Live Search: ON",
        parse_mode="md",
    )


@bot.on(events.NewMessage(pattern=r"^/reset$"))
async def reset_command(event):
    if not event.is_group:
        return

    # Anyone who can configure this group can reset its mapping.
    if not is_owner(event):
        try:
            permissions = await event.client.get_permissions(
                event.chat_id,
                event.sender_id,
            )

            if not permissions.is_admin:
                await event.reply(
                    "❌ Sirf group admin ya owner `/reset` kar sakta hai."
                )
                return
        except Exception:
            return

    if delete_mapping(event.chat_id):
        await event.reply(
            "✅ Is group ka channel mapping delete ho gaya.\n"
            "Ab `/setup` karke naya channel set karo."
        )
    else:
        await event.reply(
            "❌ Firebase mapping delete nahi hui."
        )


# ============================================================
# HELP / COMMANDS
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/help$"))
async def help_command(event):
    await event.reply(
        "🤖 **PREMIUM MOD PUBLIC BOT**\n\n"
        "👥 **Public Group Setup**\n"
        "`/setup` — group ka channel set karo\n"
        "`/status` — current mapping dekho\n"
        "`/reset` — mapping reset karo\n"
        "`/diagnostic` — problem check karo\n"
        "`/cancel` — setup cancel karo\n"
        "`/ping` — bot status\n\n"
        "🔎 **Search Example**\n"
        "`Kuku TV do`\n"
        "`KukuTV link`\n"
        "`Kuku Tvv dedo`\n"
        "`BulletShorts do`\n\n"
        "Bot mapped channel ke post caption/text ko "
        "search karke matching post ka OPEN + SHARE button dega.",
        parse_mode="md",
    )


# ============================================================
# ROSE / JOIN MESSAGE CLEANER
# ============================================================

async def delete_later(message, delay):
    try:
        await asyncio.sleep(delay)
        await message.delete()
    except Exception:
        pass


@bot.on(events.NewMessage(incoming=True))
async def clean_bot_welcome(event):
    try:
        if not event.is_group:
            return

        sender = await event.get_sender()

        if not sender or not getattr(
            sender,
            "bot",
            False,
        ):
            return

        if BOT_ME and sender.id == BOT_ME.id:
            return

        text = (event.raw_text or "").lower()

        welcome_words = (
            "welcome",
            "joined",
            "made it",
            "hello",
            "hey",
        )

        if any(
            word in text
            for word in welcome_words
        ):
            asyncio.create_task(
                delete_later(
                    event,
                    300,
                )
            )

    except Exception as e:
        logging.warning(
            "Welcome cleaner error: %s",
            e,
        )


@bot.on(events.ChatAction)
async def clean_join_service_message(event):
    try:
        if event.is_group and (
            event.user_joined
            or event.user_added
        ):
            asyncio.create_task(
                delete_later(
                    event,
                    300,
                )
            )
    except Exception:
        pass


# ============================================================
# GITHUB KEEP-ALIVE
# ============================================================

async def github_keep_alive():
    while True:
        try:
            elapsed = datetime.now() - START_TIME

            # Restart before GitHub's normal job timeout.
            if elapsed >= timedelta(
                hours=5,
                minutes=45,
            ):
                print(
                    "🔄 [GITHUB SAFE REBOOT] Restarting workflow..."
                )

                github_token = os.environ.get(
                    "MY_GITHUB_TOKEN"
                )

                repo_name = os.environ.get(
                    "GITHUB_REPOSITORY"
                )

                if github_token and repo_name:
                    url = (
                        "https://api.github.com/repos/"
                        f"{repo_name}/actions/workflows/run-bot.yml/dispatches"
                    )

                    headers = {
                        "Accept": (
                            "application/vnd.github+json"
                        ),
                        "Authorization": (
                            f"Bearer {github_token}"
                        ),
                        "X-GitHub-Api-Version": "2022-11-28",
                    }

                    try:
                        response = requests.post(
                            url,
                            headers=headers,
                            json={"ref": "main"},
                            timeout=15,
                        )

                        print(
                            "GitHub dispatch:",
                            response.status_code,
                        )

                    except Exception as e:
                        logging.error(
                            "GitHub restart request failed: %s",
                            e,
                        )

                # Let the current workflow end only after
                # dispatch request was attempted.
                os._exit(0)

        except Exception as e:
            logging.error(
                "Keep-alive error: %s",
                e,
            )

        await asyncio.sleep(300)


# ============================================================
# GLOBAL ERROR REPORTER
# ============================================================

async def error_reporter():
    while True:
        await asyncio.sleep(600)


# ============================================================
# STARTUP
# ============================================================

async def main():
    global BOT_ME

    print("⏳ Starting Telegram Client...")

    try:
        await bot.start(
            bot_token=BOT_TOKEN
        )
    except Exception as e:
        print(
            f"❌ Telegram login/start failed: {e}"
        )
        raise

    BOT_ME = await bot.get_me()

    print(
        "✅ Telegram Client Started!"
    )

    print(
        f"🤖 Logged in as: "
        f"@{getattr(BOT_ME, 'username', None) or 'unknown'} "
        f"(ID: {BOT_ME.id})"
    )

    print(
        "🌍 PUBLIC MULTI-USER SEARCH: ON"
    )
    print(
        "🔥 FIREBASE GROUP MAPPING: ON"
    )
    print(
        "🧠 FUZZY SEARCH: ON"
    )
    print(
        "📤 SHARE BUTTON: ON"
    )

    # These tasks keep the process alive and handle
    # GitHub Actions automatic restart.
    asyncio.create_task(
        github_keep_alive()
    )

    asyncio.create_task(
        error_reporter()
    )

    print(
        "🟢 BOT ONLINE - waiting for messages..."
    )

    # IMPORTANT:
    # Do NOT omit this. Without it GitHub Actions
    # finishes immediately after startup.
    await bot.run_until_disconnected()


if __name__ == "__main__":
    try:
        bot.loop.run_until_complete(
            main()
        )

    except KeyboardInterrupt:
        print("🛑 Bot stopped by user.")

    except Exception as e:
        print(
            f"❌ FATAL BOT ERROR: {type(e).__name__}: {e}"
        )
        raise

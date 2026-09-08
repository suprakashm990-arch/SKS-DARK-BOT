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
# PREMIUM MOD BOT
# STABLE PUBLIC + PRIVATE SEARCH VERSION
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

print("================================================")
print("🚀 PREMIUM MOD BOT BOOTING...")
print("================================================")

# ============================================================
# CONFIG
# ============================================================

API_ID = os.getenv("TG_API_ID")
API_HASH = os.getenv("TG_API_HASH")
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")

FIREBASE_URL = "https://sks-9865a-default-rtdb.firebaseio.com/"

OWNER_ID = 8587571289

# Maximum recent channel posts to scan
SCAN_LIMIT = 1500

# Cache lifetime
CHANNEL_CACHE_SECONDS = 300

# ============================================================
# ENV CHECK
# ============================================================

if not API_ID:
    print("❌ TG_API_ID missing")
    sys.exit(1)

if not API_HASH:
    print("❌ TG_API_HASH missing")
    sys.exit(1)

if not BOT_TOKEN:
    print("❌ TG_BOT_TOKEN missing")
    sys.exit(1)

try:
    API_ID = int(API_ID)
except ValueError:
    print("❌ TG_API_ID must be a number")
    sys.exit(1)

# ============================================================
# TELEGRAM CLIENT
# ============================================================

bot = TelegramClient(
    "premium_mod_public_bot",
    API_ID,
    API_HASH,
)

START_TIME = datetime.now()

BOT_ME = None

# user_id -> setup information
SETUP_STATE = {}

# group_id -> cached channel
CHANNEL_CACHE = {}

# group_id -> lock
SEARCH_LOCKS = {}


# ============================================================
# GENERAL HELPERS
# ============================================================

def get_search_lock(chat_id):
    chat_id = int(chat_id)

    if chat_id not in SEARCH_LOCKS:
        SEARCH_LOCKS[chat_id] = asyncio.Lock()

    return SEARCH_LOCKS[chat_id]


def is_owner(event):
    return event.sender_id == OWNER_ID


def normalize(text):
    if not text:
        return ""

    text = unicodedata.normalize(
        "NFKC",
        str(text)
    ).lower()

    # Remove URLs
    text = re.sub(
        r"https?://\S+",
        " ",
        text
    )

    # Convert separators to spaces
    text = re.sub(
        r"[_\-/.,:;|+*=~`'\"()\[\]{}<>!?]+",
        " ",
        text
    )

    # Keep letters/numbers/spaces
    text = "".join(
        c if c.isalnum() or c.isspace() else " "
        for c in text
    )

    return re.sub(
        r"\s+",
        " ",
        text
    ).strip()


def compact(text):
    return normalize(text).replace(" ", "")


# ============================================================
# REQUEST WORDS
# ============================================================

REQUEST_WORDS = {
    "do",
    "de",
    "dedo",
    "bhejo",
    "bhej",
    "send",
    "link",
    "links",
    "download",
    "downloadlink",
    "please",
    "plz",
    "pls",
    "bhai",
    "bro",
    "mujhe",
    "mera",
    "meri",
    "chahiye",
    "chaiye",
    "hai",
    "kya",
    "ka",
    "ki",
    "ke",
    "ko",
    "me",
    "mein",
    "par",
    "pe",
    "se",
    "wala",
    "wali",
    "version",
    "latest",
    "new",
    "mod",
    "apk",
    "app",
    "unlock",
    "premium",
    "share",
}


def extract_app_query(text):
    words = normalize(text).split()

    result = [
        word
        for word in words
        if word not in REQUEST_WORDS
    ]

    return " ".join(result).strip()


# ============================================================
# FUZZY SEARCH
# ============================================================

def similarity(a, b):
    a = normalize(a)
    b = normalize(b)

    if not a or not b:
        return 0

    if a == b:
        return 100

    if a in b:
        return 100

    ac = compact(a)
    bc = compact(b)

    if ac and ac in bc:
        return 98

    direct = (
        SequenceMatcher(
            None,
            a,
            b
        ).ratio()
        * 100
    )

    compact_score = (
        SequenceMatcher(
            None,
            ac,
            bc
        ).ratio()
        * 100
    )

    best_word = 0

    for qw in a.split():
        if len(qw) < 2:
            continue

        for pw in b.split():
            score = (
                SequenceMatcher(
                    None,
                    qw,
                    pw
                ).ratio()
                * 100
            )

            best_word = max(
                best_word,
                score
            )

    return max(
        direct,
        compact_score,
        best_word
    )


def post_score(query, post_text):
    query = normalize(query)
    post_text = normalize(post_text)

    if not query or not post_text:
        return 0

    if query in post_text:
        return 100

    qc = compact(query)
    pc = compact(post_text)

    if qc and qc in pc:
        return 98

    best = similarity(
        query,
        post_text
    )

    qwords = query.split()
    pwords = post_text.split()

    # Window comparison
    if len(qwords) > 1:

        size = len(qwords)

        for i in range(
            0,
            max(
                0,
                len(pwords) - size + 1
            )
        ):
            window = " ".join(
                pwords[
                    i:i + size
                ]
            )

            best = max(
                best,
                similarity(
                    query,
                    window
                )
            )

    return best


# ============================================================
# FIREBASE
# IMPORTANT:
# requests is blocking, so all Firebase operations
# will be called using asyncio.to_thread()
# ============================================================

def firebase_get_sync(path):
    try:
        url = (
            FIREBASE_URL.rstrip("/")
            + "/"
            + path.lstrip("/")
        )

        response = requests.get(
            url,
            timeout=10
        )

        if response.status_code == 200:
            return response.json()

        logging.error(
            "Firebase GET failed: %s %s",
            response.status_code,
            path
        )

    except Exception as e:
        logging.error(
            "Firebase GET error: %s",
            e
        )

    return None


def firebase_put_sync(path, data):
    try:
        url = (
            FIREBASE_URL.rstrip("/")
            + "/"
            + path.lstrip("/")
        )

        response = requests.put(
            url,
            json=data,
            timeout=10
        )

        if response.status_code in (
            200,
            201
        ):
            return True

        logging.error(
            "Firebase PUT failed: %s %s",
            response.status_code,
            path
        )

    except Exception as e:
        logging.error(
            "Firebase PUT error: %s",
            e
        )

    return False


def firebase_delete_sync(path):
    try:
        url = (
            FIREBASE_URL.rstrip("/")
            + "/"
            + path.lstrip("/")
        )

        response = requests.delete(
            url,
            timeout=10
        )

        return response.status_code in (
            200,
            204
        )

    except Exception as e:
        logging.error(
            "Firebase DELETE error: %s",
            e
        )

    return False


async def firebase_get(path):
    return await asyncio.to_thread(
        firebase_get_sync,
        path
    )


async def firebase_put(path, data):
    return await asyncio.to_thread(
        firebase_put_sync,
        path,
        data
    )


async def firebase_delete(path):
    return await asyncio.to_thread(
        firebase_delete_sync,
        path
    )


# ============================================================
# GROUP MAPPING
# ============================================================

def mapping_path(chat_id):
    return f"groups/{int(chat_id)}"


async def get_mapping(chat_id):
    data = await firebase_get(
        mapping_path(chat_id)
    )

    if isinstance(data, dict):
        return data

    return {}


async def save_mapping(chat_id, channel):
    data = {
        "group_id": int(chat_id),
        "channel_id": int(channel.id),
        "channel_title": getattr(
            channel,
            "title",
            "Unknown"
        ),
        "channel_username": getattr(
            channel,
            "username",
            None
        ),
        "updated_at": int(
            time.time()
        ),
        "configured_by": OWNER_ID,
    }

    ok = await firebase_put(
        mapping_path(chat_id),
        data
    )

    if ok:
        CHANNEL_CACHE[int(chat_id)] = (
            channel,
            time.time()
        )

    return ok


async def delete_mapping(chat_id):
    CHANNEL_CACHE.pop(
        int(chat_id),
        None
    )

    return await firebase_delete(
        mapping_path(chat_id)
    )


# ============================================================
# CHANNEL RESOLUTION
# ============================================================

def extract_username(value):
    value = (
        value or ""
    ).strip()

    if value.startswith("@"):
        return value[1:]

    match = re.match(
        r"^(?:https?://)?"
        r"(?:www\.)?"
        r"t\.me/"
        r"([A-Za-z0-9_]+)"
        r"(?:/.*)?$",
        value
    )

    if match:
        username = match.group(1)

        if username not in (
            "c",
            "joinchat"
        ):
            return username

    return None


async def resolve_channel(value):
    value = (
        value or ""
    ).strip()

    if not value:
        return None

    username = extract_username(
        value
    )

    try:

        if username:
            print(
                f"🔎 Resolving public channel: @{username}"
            )

            return await bot.get_entity(
                username
            )

        if re.fullmatch(
            r"-?\d+",
            value
        ):
            print(
                f"🔎 Resolving channel ID: {value}"
            )

            return await bot.get_entity(
                int(value)
            )

        return await bot.get_entity(
            value
        )

    except (
        UsernameInvalidError,
        UsernameNotOccupiedError,
        ChannelPrivateError
    ):
        return None

    except Exception as e:
        logging.error(
            "Channel resolve error: %s",
            e
        )

        return None


async def validate_channel(channel):
    try:

        # Try to read messages.
        messages = await bot.get_messages(
            channel,
            limit=1
        )

        # Even an empty channel is accessible.
        print(
            f"✅ Channel access OK: "
            f"{getattr(channel, 'title', 'Unknown')}"
        )

        return True, None

    except ChatAdminRequiredError:
        return (
            False,
            "Bot ko channel read karne ki permission nahi hai."
        )

    except ChannelPrivateError:
        return (
            False,
            "Channel private hai. Bot ko channel mein add karo."
        )

    except FloodWaitError as e:
        return (
            False,
            f"Telegram FloodWait: {e.seconds} seconds."
        )

    except Exception as e:
        return (
            False,
            str(e)
        )


async def get_group_channel(chat_id):
    chat_id = int(chat_id)

    # Cache
    cached = CHANNEL_CACHE.get(
        chat_id
    )

    if cached:

        channel, saved_at = cached

        if (
            time.time()
            - saved_at
            < CHANNEL_CACHE_SECONDS
        ):
            return channel

    mapping = await get_mapping(
        chat_id
    )

    if not mapping:
        return None

    channel_id = mapping.get(
        "channel_id"
    )

    username = mapping.get(
        "channel_username"
    )

    try:

        if channel_id:
            channel = await bot.get_entity(
                int(channel_id)
            )

        elif username:
            channel = await bot.get_entity(
                username
            )

        else:
            return None

        CHANNEL_CACHE[chat_id] = (
            channel,
            time.time()
        )

        return channel

    except Exception as e:

        logging.error(
            "Group channel resolve failed: %s",
            e
        )

        return None


# ============================================================
# FILTER LINKS
# ============================================================

def safe_key(value):
    value = (
        str(value)
        .strip()
        .lower()
    )

    for char in (
        ".",
        "#",
        "$",
        "[",
        "]",
        "/"
    ):
        value = value.replace(
            char,
            "_"
        )

    return value[:100]


async def get_filter_links():
    data = await firebase_get(
        "links"
    )

    return (
        data
        if isinstance(data, dict)
        else {}
    )


async def save_filter_link(
    app_name,
    download_link
):
    return await firebase_put(
        f"links/{safe_key(app_name)}",
        {
            "name": app_name.strip(),
            "link": download_link.strip(),
            "updated_at": int(
                time.time()
            )
        }
    )


# ============================================================
# SEARCH CHANNEL POSTS
# ============================================================

async def search_channel(
    channel,
    query
):
    if not query:
        return (
            None,
            0,
            "empty-query"
        )

    best_message = None
    best_score = 0
    seen = set()

    # --------------------------------------------------------
    # Telegram server search
    # --------------------------------------------------------

    search_terms = []

    normalized_query = normalize(
        query
    )

    if normalized_query:
        search_terms.append(
            normalized_query
        )

    for word in normalized_query.split():

        if (
            len(word) >= 3
            and word not in search_terms
        ):
            search_terms.append(
                word
            )

    for term in search_terms[:5]:

        try:

            print(
                f"🔎 Telegram search: {term}"
            )

            async for message in bot.iter_messages(
                channel,
                search=term,
                limit=100
            ):

                if not message:
                    continue

                if message.id in seen:
                    continue

                seen.add(
                    message.id
                )

                post_text = (
                    message.raw_text
                    or ""
                ).strip()

                if not post_text:
                    continue

                score = post_score(
                    query,
                    post_text
                )

                if score > best_score:
                    best_score = score
                    best_message = message

                if score >= 98:
                    return (
                        best_message,
                        best_score,
                        "telegram-search"
                    )

        except FloodWaitError as e:

            logging.warning(
                "Search FloodWait: %ss",
                e.seconds
            )

            await asyncio.sleep(
                e.seconds
            )

        except Exception as e:

            logging.warning(
                "Telegram search error: %s",
                e
            )

    # --------------------------------------------------------
    # Recent history fallback
    # --------------------------------------------------------

    try:

        print(
            f"🔎 History scan: {SCAN_LIMIT} posts"
        )

        scanned = 0

        async for message in bot.iter_messages(
            channel,
            limit=SCAN_LIMIT
        ):

            if not message:
                continue

            post_text = (
                message.raw_text
                or ""
            ).strip()

            if not post_text:
                continue

            scanned += 1

            score = post_score(
                query,
                post_text
            )

            if score > best_score:
                best_score = score
                best_message = message

            if score >= 98:
                return (
                    best_message,
                    best_score,
                    "history-scan"
                )

            if scanned >= SCAN_LIMIT:
                break

    except FloodWaitError as e:

        logging.warning(
            "History FloodWait: %ss",
            e.seconds
        )

        return (
            None,
            best_score,
            "floodwait"
        )

    except Exception as e:

        logging.error(
            "History scan error: %s",
            e
        )

    # Fuzzy result
    if (
        best_message
        and best_score >= 70
    ):
        return (
            best_message,
            best_score,
            "fuzzy-history"
        )

    return (
        None,
        best_score,
        "not-found"
    )


# ============================================================
# POST LINK
# ============================================================

def post_link(
    channel,
    message
):
    username = getattr(
        channel,
        "username",
        None
    )

    if username:
        return (
            f"https://t.me/"
            f"{username}/"
            f"{message.id}"
        )

    channel_id = getattr(
        channel,
        "id",
        None
    )

    if channel_id:

        # Telegram private channel IDs normally need
        # -100 removed from the public t.me/c format.
        cid = str(
            channel_id
        )

        if cid.startswith("-100"):
            cid = cid[4:]

        return (
            f"https://t.me/c/"
            f"{cid}/"
            f"{message.id}"
        )

    return None


def share_link(
    url,
    text
):
    return (
        "https://t.me/share/url"
        "?url="
        + quote(
            url,
            safe=""
        )
        + "&text="
        + quote(
            text,
            safe=""
        )
    )


def result_buttons(
    url,
    app_name
):
    if not url:
        return None

    return [
        [
            Button.url(
                "📥 OPEN POST",
                url
            ),
            Button.url(
                "📤 SHARE",
                share_link(
                    url,
                    f"{app_name.upper()} available here"
                )
            )
        ]
    ]


# ============================================================
# ADMIN CHECK
# ============================================================

async def is_group_admin(event):

    if is_owner(event):
        return True

    try:

        permissions = (
            await event.client.get_permissions(
                event.chat_id,
                event.sender_id
            )
        )

        return bool(
            permissions.is_admin
        )

    except Exception:
        return False


# ============================================================
# START
# ============================================================

async def handle_start(event):

    await event.reply(
        "👋 **Welcome to PREMIUM MOD BOT**\n\n"
        "🤖 Bot successfully online hai.\n\n"
        "🔎 Group mein app name bhejo:\n"
        "`Kuku TV do`\n"
        "`BulletShorts link`\n\n"
        "⚙️ Group admin setup ke liye:\n"
        "`/setup`\n\n"
        "📊 Status:\n"
        "`/ping`",
        parse_mode="md"
    )


# ============================================================
# PING
# ============================================================

async def handle_ping(event):

    uptime = (
        datetime.now()
        - START_TIME
    )

    total_seconds = int(
        uptime.total_seconds()
    )

    hours = (
        total_seconds
        // 3600
    )

    minutes = (
        total_seconds % 3600
    ) // 60

    firebase_ok = False

    try:
        firebase_test = await firebase_get(
            "."
        )

        # Firebase may return None if database root
        # is empty, so test by HTTP indirectly is not
        # perfect. Still useful.
        firebase_ok = (
            firebase_test is not None
        )

    except Exception:
        firebase_ok = False

    group_channel = None

    if event.is_group:
        group_channel = await get_group_channel(
            event.chat_id
        )

    await event.reply(
        "🟢 **BOT ONLINE**\n\n"
        f"⏱️ Uptime: `{hours}h {minutes}m`\n"
        "📡 Telegram: ✅ CONNECTED\n"
        f"🔥 Firebase: "
        f"{'✅ CONNECTED' if firebase_ok else '⚠️ CHECK'}\n"
        "👥 Public Multi-User: ✅ ON\n"
        "🧠 Fuzzy Search: ✅ ON\n"
        "📤 Share Button: ✅ ON\n"
        "🧪 Diagnostic: ✅ ON\n"
        + (
            "📢 Group Channel: ✅ SET"
            if group_channel
            else "📢 Group Channel: ⚠️ NOT SET"
            if event.is_group
            else "📢 Group Channel: N/A (private chat)"
        ),
        parse_mode="md"
    )


# ============================================================
# SETUP
# ============================================================

async def handle_setup(
    event,
    argument=None
):

    if not event.is_group:

        await event.reply(
            "⚠️ `/setup` group ke andar use karo."
        )

        return

    if not await is_group_admin(event):

        await event.reply(
            "❌ Sirf group admin/owner channel setup kar sakta hai."
        )

        return

    if argument:

        await complete_setup(
            event,
            argument.strip()
        )

        return

    SETUP_STATE[
        event.sender_id
    ] = {
        "group_id": event.chat_id,
        "created_at": time.time()
    }

    await event.reply(
        "⚙️ **GROUP CHANNEL SETUP**\n\n"
        "Ab jis channel mein search karna hai uska "
        "exact username/link bhejo.\n\n"
        "Example:\n"
        "`@mychannel`\n"
        "`https://t.me/mychannel`\n\n"
        "Private channel ke liye bot ko pehle channel "
        "mein add karo.\n\n"
        "❌ Cancel: `/cancel`",
        parse_mode="md"
    )


async def complete_setup(
    event,
    value
):

    if not event.is_group:
        return

    if not await is_group_admin(event):

        await event.reply(
            "❌ Sirf group admin channel setup kar sakta hai."
        )

        return

    checking = await event.reply(
        "🔎 **Channel check ho raha hai...**",
        parse_mode="md"
    )

    channel = await resolve_channel(
        value
    )

    if not channel:

        await checking.edit(
            "❌ **CHANNEL NOT FOUND**\n\n"
            "Channel identify nahi hua.\n\n"
            "Public channel ka exact:\n"
            "`@username`\n"
            "ya\n"
            "`https://t.me/username`\n\n"
            "Private channel ho to bot ko channel mein add karo.",
            parse_mode="md"
        )

        return

    ok, error = await validate_channel(
        channel
    )

    if not ok:

        await checking.edit(
            "❌ **CHANNEL ACCESS ERROR**\n\n"
            f"{error}\n\n"
            "Private channel hai to bot ko channel mein "
            "add/admin karo.",
            parse_mode="md"
        )

        return

    saved = await save_mapping(
        event.chat_id,
        channel
    )

    if not saved:

        await checking.edit(
            "❌ Channel mil gaya, lekin Firebase mapping "
            "save nahi hui.\n\n"
            "Firebase URL/rules check karo."
        )

        return

    SETUP_STATE.pop(
        event.sender_id,
        None
    )

    title = getattr(
        channel,
        "title",
        "Unknown"
    )

    username = getattr(
        channel,
        "username",
        None
    )

    username_text = (
        f"@{username}"
        if username
        else "Private Channel"
    )

    await checking.edit(
        "✅ **SETUP COMPLETE**\n\n"
        f"📢 Channel: **{title}**\n"
        f"🔗 Username: `{username_text}`\n"
        f"🆔 Channel ID: `{channel.id}`\n"
        f"👥 Group ID: `{event.chat_id}`\n\n"
        "🔎 Ab isi channel ke posts search honge.\n\n"
        "Example:\n"
        "`BulletShorts do`\n"
        "`Kuku TV link`",
        parse_mode="md"
    )


# ============================================================
# STATUS
# ============================================================

async def handle_status(event):

    if not event.is_group:

        await event.reply(
            "⚠️ `/status` group mein use karo."
        )

        return

    mapping = await get_mapping(
        event.chat_id
    )

    if not mapping:

        await event.reply(
            "❌ **CHANNEL NOT SET**\n\n"
            "Is group mein channel configured nahi hai.\n"
            "Use `/setup`",
            parse_mode="md"
        )

        return

    channel = await get_group_channel(
        event.chat_id
    )

    if channel:

        access = "✅ WORKING"

    else:

        access = "❌ ACCESS FAILED"

    await event.reply(
        "📌 **GROUP MAPPING STATUS**\n\n"
        f"👥 Group ID: `{event.chat_id}`\n"
        f"📢 Channel: **{mapping.get('channel_title', 'Unknown')}**\n"
        f"🆔 Channel ID: `{mapping.get('channel_id')}`\n"
        f"🔗 Username: `{mapping.get('channel_username') or 'Private'}`\n"
        f"📡 Channel Access: {access}\n\n"
        "🧠 Search: READY",
        parse_mode="md"
    )


# ============================================================
# DIAGNOSTIC
# ============================================================

async def handle_diagnostic(event):

    lines = [
        "⚠️ **BOT DIAGNOSTIC**",
        "",
        "🤖 Telegram Client: ✅",
    ]

    # Firebase
    try:

        firebase_data = await firebase_get(
            "."
        )

        lines.append(
            "🔥 Firebase: "
            + (
                "✅"
                if firebase_data is not None
                else "⚠️ CHECK"
            )
        )

    except Exception as e:

        lines.append(
            "🔥 Firebase: ❌"
        )

        lines.append(
            f"Firebase error: `{str(e)[:200]}`"
        )

    if event.is_group:

        lines.append(
            f"👥 Group ID: `{event.chat_id}`"
        )

        mapping = await get_mapping(
            event.chat_id
        )

        if not mapping:

            lines.append(
                "🗂️ Group Mapping: ❌ NOT FOUND"
            )

            lines.append(
                "💡 `/setup` karo."
            )

        else:

            lines.append(
                "🗂️ Group Mapping: ✅"
            )

            channel = await get_group_channel(
                event.chat_id
            )

            if channel:

                lines.append(
                    "📢 Channel Access: ✅"
                )

                lines.append(
                    "📡 Channel: "
                    f"**{getattr(channel, 'title', 'Unknown')}**"
                )

                try:

                    await bot.get_messages(
                        channel,
                        limit=1
                    )

                    lines.append(
                        "📖 Channel Read: ✅"
                    )

                except Exception as e:

                    lines.append(
                        "📖 Channel Read: ❌"
                    )

                    lines.append(
                        f"`{str(e)[:180]}`"
                    )

            else:

                lines.append(
                    "📢 Channel Access: ❌"
                )

    else:

        lines.append(
            "👤 Private Chat: ✅"
        )

    lines.extend(
        [
            "",
            "🔎 Search Engine: READY",
            "🧠 Fuzzy Search: ON",
            "📤 Share Button: ON",
            "",
            "⚠️ Agar group mein normal message "
            "receive nahi hota:",
            "BotFather → /setprivacy → Disable",
        ]
    )

    await event.reply(
        "\n".join(lines),
        parse_mode="md"
    )


# ============================================================
# RESET
# ============================================================

async def handle_reset(event):

    if not event.is_group:
        return

    if not await is_group_admin(event):
        await event.reply(
            "❌ Sirf group admin/owner reset kar sakta hai."
        )
        return

    ok = await delete_mapping(
        event.chat_id
    )

    if ok:

        await event.reply(
            "✅ **GROUP MAPPING RESET**\n\n"
            "Purana channel remove ho gaya.\n"
            "Ab `/setup` karke naya channel set karo.",
            parse_mode="md"
        )

    else:

        await event.reply(
            "❌ Firebase mapping delete nahi hui."
        )


# ============================================================
# CANCEL
# ============================================================

async def handle_cancel(event):

    SETUP_STATE.pop(
        event.sender_id,
        None
    )

    await event.reply(
        "✅ Setup cancel ho gaya."
    )


# ============================================================
# HELP
# ============================================================

async def handle_help(event):

    await event.reply(
        "🤖 **PREMIUM MOD BOT**\n\n"
        "📌 **Commands**\n\n"
        "`/start` — Start bot\n"
        "`/ping` — Bot status\n"
        "`/setup` — Group channel setup\n"
        "`/status` — Channel mapping\n"
        "`/diagnostic` — Full problem check\n"
        "`/reset` — Channel mapping reset\n"
        "`/cancel` — Setup cancel\n"
        "`/help` — Help\n\n"
        "🔎 **Search**\n"
        "Group mein simply app name bhejo:\n\n"
        "`Kuku TV do`\n"
        "`KukuTV link`\n"
        "`BulletShorts do`\n"
        "`Bullet Shorts link`\n\n"
        "Bot configured channel ke posts mein search karega.",
        parse_mode="md"
    )


# ============================================================
# FILTER COMMAND
# ============================================================

async def handle_filter(
    event,
    argument
):

    if not is_owner(event):
        return

    if not argument:
        await event.reply(
            "Usage:\n"
            "`/filter AppName https://example.com/link`",
            parse_mode="md"
        )
        return

    match = re.match(
        r"^(.+?)\s+(https?://\S+)$",
        argument.strip()
    )

    if not match:

        await event.reply(
            "❌ Format galat hai.\n\n"
            "Example:\n"
            "`/filter KukuTV https://example.com/link`",
            parse_mode="md"
        )

        return

    app_name = match.group(1).strip()
    link = match.group(2).strip()

    ok = await save_filter_link(
        app_name,
        link
    )

    if ok:

        await event.reply(
            "✅ **FILTER SAVED**\n\n"
            f"📱 {app_name}\n"
            f"🔗 {link}",
            parse_mode="md"
        )

    else:

        await event.reply(
            "❌ Firebase mein save nahi hua."
        )


# ============================================================
# NORMAL SEARCH
# ============================================================

async def handle_search(event):

    text = (
        event.raw_text
        or ""
    ).strip()

    if not text:
        return

    # Never search commands
    if text.startswith("/"):
        return

    chat_id = event.chat_id

    # --------------------------------------------------------
    # SETUP STATE
    # --------------------------------------------------------

    state = SETUP_STATE.get(
        event.sender_id
    )

    if state:

        # Expire setup after 10 minutes
        if (
            time.time()
            - state.get(
                "created_at",
                0
            )
            > 600
        ):

            SETUP_STATE.pop(
                event.sender_id,
                None
            )

        elif state.get(
            "group_id"
        ) == chat_id:

            await complete_setup(
                event,
                text
            )

            return

    # --------------------------------------------------------
    # Get configured channel
    # --------------------------------------------------------

    if event.is_group:

        channel = await get_group_channel(
            chat_id
        )

    else:

        # For private chat, use OWNER_ID's configured
        # default channel if configured.
        #
        # To avoid mixing group mappings, private search
        # uses Firebase/default_channel.
        channel = None

        default_data = await firebase_get(
            "default_channel"
        )

        if isinstance(
            default_data,
            dict
        ):

            cid = default_data.get(
                "channel_id"
            )

            username = default_data.get(
                "channel_username"
            )

            try:

                if cid:
                    channel = await bot.get_entity(
                        int(cid)
                    )

                elif username:
                    channel = await bot.get_entity(
                        username
                    )

            except Exception as e:

                logging.error(
                    "Default channel error: %s",
                    e
                )

    if not channel:

        # Do not spam groups without setup.
        if event.is_group:
            return

        await event.reply(
            "⚠️ **Search channel configured nahi hai.**\n\n"
            "Owner ko Firebase mein `default_channel` "
            "configure karna hoga.",
            parse_mode="md"
        )

        return

    # --------------------------------------------------------
    # Extract app name
    # --------------------------------------------------------

    query = extract_app_query(
        text
    )

    if not query:
        return

    if len(compact(query)) < 2:
        return

    print(
        "================================================"
    )

    print(
        f"🔎 SEARCH REQUEST"
    )

    print(
        f"Chat: {chat_id}"
    )

    print(
        f"User: {event.sender_id}"
    )

    print(
        f"Query: {query}"
    )

    print(
        f"Channel: "
        f"{getattr(channel, 'title', 'Unknown')}"
    )

    print(
        "================================================"
    )

    # --------------------------------------------------------
    # Prevent simultaneous expensive scans
    # --------------------------------------------------------

    lock_id = (
        chat_id
        if event.is_group
        else OWNER_ID
    )

    async with get_search_lock(
        lock_id
    ):

        # ----------------------------------------------------
        # Firebase manual links FIRST
        # ----------------------------------------------------

        try:

            filters = await get_filter_links()

            for key, value in filters.items():

                if isinstance(
                    value,
                    dict
                ):

                    saved_name = value.get(
                        "name",
                        key
                    )

                    saved_link = value.get(
                        "link"
                    )

                else:

                    saved_name = key
                    saved_link = value

                if not saved_link:
                    continue

                score = similarity(
                    query,
                    saved_name
                )

                if score >= 85:

                    await event.reply(
                        "👋 **Mil gaya!**\n\n"
                        f"📱 **{str(saved_name).upper()}**\n\n"
                        f"🔗 {saved_link}",
                        parse_mode="md",
                        link_preview=False
                    )

                    return

        except Exception as e:

            logging.warning(
                "Filter search error: %s",
                e
            )

        # ----------------------------------------------------
        # Live Telegram search
        # ----------------------------------------------------

        message, score, method = (
            await search_channel(
                channel,
                query
            )
        )

        if not message:

            print(
                f"❌ NOT FOUND | "
                f"query={query!r} "
                f"score={score:.1f} "
                f"method={method}"
            )

            # Only respond in private chat.
            if not event.is_group:

                await event.reply(
                    "❌ **Nahi mila**\n\n"
                    f"🔎 Search: `{query}`\n"
                    f"🎯 Best match: `{score:.0f}%`\n\n"
                    "Channel mein is app ka post nahi mila.",
                    parse_mode="md"
                )

            return

        # ----------------------------------------------------
        # Generate post URL
        # ----------------------------------------------------

        url = post_link(
            channel,
            message
        )

        if not url:

            await event.reply(
                "⚠️ Post mil gaya, lekin Telegram post URL "
                "generate nahi ho saka."
            )

            return

        title = getattr(
            channel,
            "title",
            "Channel"
        )

        preview = (
            message.raw_text
            or ""
        ).strip()

        if len(preview) > 500:
            preview = (
                preview[:500]
                + "..."
            )

        reply = (
            "👋 **Mil gaya!**\n\n"
            f"📱 Search: **{query.upper()}**\n"
            f"📢 Channel: **{title}**\n"
            f"🎯 Match: **{score:.0f}%**\n"
            f"🔎 Method: `{method}`\n\n"
        )

        if preview:

            reply += (
                "📝 **Post:**\n"
                f"{preview}\n\n"
            )

        reply += (
            "👇 **Post open/share karo:**"
        )

        await event.reply(
            reply,
            buttons=result_buttons(
                url,
                query
            ),
            parse_mode="md",
            link_preview=False
        )

        print(
            f"✅ FOUND | "
            f"query={query!r} "
            f"score={score:.1f} "
            f"method={method}"
        )


# ============================================================
# CENTRAL MESSAGE HANDLER
#
# IMPORTANT:
# Ek hi NewMessage handler rakha gaya hai.
# Isse multiple handlers ke conflict ka problem nahi hoga.
# ============================================================

@bot.on(
    events.NewMessage(
        incoming=True
    )
)
async def central_message_handler(event):

    try:

        text = (
            event.raw_text
            or ""
        ).strip()

        print(
            f"📨 MESSAGE | "
            f"chat={event.chat_id} | "
            f"user={event.sender_id} | "
            f"group={event.is_group} | "
            f"text={text!r}"
        )

        if not text:
            return

        # ----------------------------------------------------
        # COMMAND PARSER
        # Supports /ping and /ping@botusername
        # ----------------------------------------------------

        command_match = re.match(
            r"^/([A-Za-z0-9_]+)"
            r"(?:@([A-Za-z0-9_]+))?"
            r"(?:\s+(.*))?$",
            text,
            re.S
        )

        if command_match:

            command = (
                command_match.group(1)
                .lower()
            )

            bot_username = (
                command_match.group(2)
            )

            argument = (
                command_match.group(3)
                or ""
            ).strip()

            # If command is targeted at another bot,
            # ignore it.
            if (
                bot_username
                and BOT_ME
                and bot_username.lower()
                != (
                    getattr(
                        BOT_ME,
                        "username",
                        ""
                    )
                    or ""
                ).lower()
            ):
                return

            print(
                f"⚡ COMMAND: /{command}"
            )

            if command == "start":

                await handle_start(
                    event
                )

            elif command == "ping":

                await handle_ping(
                    event
                )

            elif command == "help":

                await handle_help(
                    event
                )

            elif command == "setup":

                await handle_setup(
                    event,
                    argument
                    if argument
                    else None
                )

            elif command == "status":

                await handle_status(
                    event
                )

            elif command == "diagnostic":

                await handle_diagnostic(
                    event
                )

            elif command == "reset":

                await handle_reset(
                    event
                )

            elif command == "cancel":

                await handle_cancel(
                    event
                )

            elif command == "filter":

                await handle_filter(
                    event,
                    argument
                )

            return

        # ----------------------------------------------------
        # SETUP MESSAGE
        # ----------------------------------------------------

        state = SETUP_STATE.get(
            event.sender_id
        )

        if (
            state
            and state.get(
                "group_id"
            ) == event.chat_id
        ):

            await complete_setup(
                event,
                text
            )

            return

        # ----------------------------------------------------
        # NORMAL SEARCH
        # ----------------------------------------------------

        await handle_search(
            event
        )

    except FloodWaitError as e:

        logging.warning(
            "Telegram FloodWait: %s seconds",
            e.seconds
        )

        # Don't crash the bot.
        await asyncio.sleep(
            e.seconds
        )

    except Exception as e:

        logging.exception(
            "❌ MESSAGE HANDLER ERROR"
        )

        # Try to tell user/admin
        try:

            await event.reply(
                "⚠️ **Bot mein internal error aaya.**\n\n"
                f"Error: `{type(e).__name__}`\n\n"
                "Admin `/diagnostic` se check kar sakta hai.",
                parse_mode="md"
            )

        except Exception:
            pass


# ============================================================
# PRIVATE DEFAULT CHANNEL SETUP
# OWNER ONLY
#
# Usage:
# /defaultchannel @channelname
# ============================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/defaultchannel(?:\s+(.+))?$",
        incoming=True
    )
)
async def default_channel_command(event):

    if not is_owner(event):
        return

    value = event.pattern_match.group(1)

    if not value:

        await event.reply(
            "Usage:\n"
            "`/defaultchannel @channelname`",
            parse_mode="md"
        )

        return

    channel = await resolve_channel(
        value
    )

    if not channel:

        await event.reply(
            "❌ Channel nahi mila."
        )

        return

    ok, error = await validate_channel(
        channel
    )

    if not ok:

        await event.reply(
            f"❌ Channel access failed:\n{error}"
        )

        return

    data = {
        "channel_id": int(
            channel.id
        ),
        "channel_title": getattr(
            channel,
            "title",
            "Unknown"
        ),
        "channel_username": getattr(
            channel,
            "username",
            None
        ),
        "updated_at": int(
            time.time()
        )
    }

    saved = await firebase_put(
        "default_channel",
        data
    )

    if saved:

        await event.reply(
            "✅ **DEFAULT CHANNEL SET**\n\n"
            f"📢 {getattr(channel, 'title', 'Unknown')}\n"
            f"🆔 `{channel.id}`\n"
            f"🔗 `@{getattr(channel, 'username', None) or 'Private'}`",
            parse_mode="md"
        )

    else:

        await event.reply(
            "❌ Firebase save failed."
        )


# ============================================================
# GITHUB KEEP ALIVE
# ============================================================

async def github_keep_alive():

    while True:

        try:

            elapsed = (
                datetime.now()
                - START_TIME
            )

            # Restart before normal workflow timeout
            if elapsed >= timedelta(
                hours=5,
                minutes=30
            ):

                print(
                    "🔄 Preparing safe GitHub restart..."
                )

                token = os.getenv(
                    "MY_GITHUB_TOKEN"
                )

                repository = os.getenv(
                    "GITHUB_REPOSITORY"
                )

                if token and repository:

                    workflow_file = (
                        "run-bot.yml"
                    )

                    url = (
                        "https://api.github.com/repos/"
                        f"{repository}/actions/workflows/"
                        f"{workflow_file}/dispatches"
                    )

                    headers = {
                        "Accept":
                            "application/vnd.github+json",
                        "Authorization":
                            f"Bearer {token}",
                        "X-GitHub-Api-Version":
                            "2022-11-28",
                    }

                    try:

                        response = (
                            await asyncio.to_thread(
                                requests.post,
                                url,
                                headers=headers,
                                json={
                                    "ref": "main"
                                },
                                timeout=15
                            )
                        )

                        print(
                            "GitHub dispatch:",
                            response.status_code
                        )

                    except Exception as e:

                        logging.error(
                            "GitHub dispatch error: %s",
                            e
                        )

                # Stop this process after restart
                # request was attempted.
                os._exit(0)

        except Exception as e:

            logging.error(
                "Keep alive error: %s",
                e
            )

        await asyncio.sleep(
            300
        )


# ============================================================
# SETUP EXPIRY CLEANER
# ============================================================

async def setup_cleaner():

    while True:

        try:

            current = time.time()

            expired = []

            for user_id, state in list(
                SETUP_STATE.items()
            ):

                created = state.get(
                    "created_at",
                    current
                )

                if (
                    current - created
                    > 600
                ):
                    expired.append(
                        user_id
                    )

            for user_id in expired:

                SETUP_STATE.pop(
                    user_id,
                    None
                )

        except Exception as e:

            logging.warning(
                "Setup cleaner error: %s",
                e
            )

        await asyncio.sleep(
            60
        )


# ============================================================
# START BOT
# ============================================================

async def main():

    global BOT_ME

    print(
        "⏳ Connecting to Telegram..."
    )

    try:

        await bot.start(
            bot_token=BOT_TOKEN
        )

    except Exception as e:

        print(
            "❌ Telegram login failed:"
        )

        print(
            f"{type(e).__name__}: {e}"
        )

        raise

    BOT_ME = await bot.get_me()

    print(
        "================================================"
    )

    print(
        "✅ TELEGRAM CONNECTED"
    )

    print(
        f"🤖 Bot: "
        f"@{getattr(BOT_ME, 'username', 'unknown')}"
    )

    print(
        f"🆔 Bot ID: {BOT_ME.id}"
    )

    print(
        "👥 PUBLIC MULTI-USER: ON"
    )

    print(
        "🔥 FIREBASE: ON"
    )

    print(
        "🧠 FUZZY SEARCH: ON"
    )

    print(
        "📤 SHARE BUTTON: ON"
    )

    print(
        "🧪 DIAGNOSTIC: ON"
    )

    print(
        "================================================"
    )

    asyncio.create_task(
        github_keep_alive()
    )

    asyncio.create_task(
        setup_cleaner()
    )

    print(
        "🟢 BOT ONLINE - WAITING FOR MESSAGES..."
    )

    print(
        "================================================"
    )

    # CRITICAL:
    # Keep Telegram client alive.
    await bot.run_until_disconnected()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:

        bot.loop.run_until_complete(
            main()
        )

    except KeyboardInterrupt:

        print(
            "🛑 Bot stopped."
        )

    except Exception as e:

        print(
            "❌ FATAL ERROR:"
        )

        print(
            f"{type(e).__name__}: {e}"
        )

        raise

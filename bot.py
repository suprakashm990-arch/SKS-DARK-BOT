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
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

print("🚀 PREMIUM MOD BOT BOOTING...")

# ============================================================
# ENV
# ============================================================

API_ID = os.environ.get("TG_API_ID")
API_HASH = os.environ.get("TG_API_HASH")
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")

FIREBASE_URL = "https://sks-9865a-default-rtdb.firebaseio.com/"

OWNER_ID = 8587571289

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

BOT_ME = None

# user_id -> setup information
SETUP = {}

# group_id -> lock
SEARCH_LOCKS = {}

# group_id -> (channel, saved_time)
CHANNEL_CACHE = {}

# default channel cache
DEFAULT_CHANNEL_CACHE = None
DEFAULT_CHANNEL_CACHE_TIME = 0


# ============================================================
# BASIC
# ============================================================

def is_owner(event):
    return event.sender_id == OWNER_ID


def get_lock(group_id):
    group_id = int(group_id)

    if group_id not in SEARCH_LOCKS:
        SEARCH_LOCKS[group_id] = asyncio.Lock()

    return SEARCH_LOCKS[group_id]


async def safe_delete(message, delay=0):
    try:
        if delay:
            await asyncio.sleep(delay)

        await message.delete()
    except Exception:
        pass


# ============================================================
# FIREBASE
# ============================================================

def firebase_request(method, path, data=None):
    try:
        url = FIREBASE_URL.rstrip("/") + "/" + path.lstrip("/")

        response = requests.request(
            method,
            url,
            json=data,
            timeout=15,
        )

        return response

    except Exception as e:
        logging.error(
            "Firebase %s error: %s",
            method,
            e,
        )

        return None


def firebase_get(path):
    response = firebase_request(
        "GET",
        path,
    )

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
    response = firebase_request(
        "PUT",
        path,
        data,
    )

    if response is not None and response.status_code in (200, 201):
        return True

    return False


def firebase_delete(path):
    response = firebase_request(
        "DELETE",
        path,
    )

    if response is not None and response.status_code in (200, 204):
        return True

    return False


def firebase_is_online():
    response = firebase_request(
        "GET",
        ".",
    )

    return (
        response is not None
        and response.status_code == 200
    )


# ============================================================
# FIREBASE DEFAULT CHANNEL
# ============================================================

def default_channel_path():
    return "config/default_channel"


def save_default_channel(channel):
    data = {
        "channel_id": int(channel.id),
        "channel_title": getattr(
            channel,
            "title",
            "Unknown",
        ),
        "channel_username": getattr(
            channel,
            "username",
            None,
        ),
        "updated_at": int(time.time()),
        "configured_by": OWNER_ID,
    }

    global DEFAULT_CHANNEL_CACHE
    global DEFAULT_CHANNEL_CACHE_TIME

    ok = firebase_put(
        default_channel_path(),
        data,
    )

    if ok:
        DEFAULT_CHANNEL_CACHE = channel
        DEFAULT_CHANNEL_CACHE_TIME = time.time()

    return ok


def delete_default_channel():
    global DEFAULT_CHANNEL_CACHE
    global DEFAULT_CHANNEL_CACHE_TIME

    DEFAULT_CHANNEL_CACHE = None
    DEFAULT_CHANNEL_CACHE_TIME = 0

    return firebase_delete(
        default_channel_path()
    )


async def get_default_channel():
    global DEFAULT_CHANNEL_CACHE
    global DEFAULT_CHANNEL_CACHE_TIME

    # 5 minute cache
    if (
        DEFAULT_CHANNEL_CACHE
        and time.time() - DEFAULT_CHANNEL_CACHE_TIME < 300
    ):
        return DEFAULT_CHANNEL_CACHE

    data = firebase_get(
        default_channel_path()
    )

    if not isinstance(data, dict):
        return None

    channel_id = data.get("channel_id")
    username = data.get("channel_username")

    if not channel_id and not username:
        return None

    try:
        if channel_id:
            channel = await bot.get_entity(
                int(channel_id)
            )
        else:
            channel = await bot.get_entity(
                username
            )

        DEFAULT_CHANNEL_CACHE = channel
        DEFAULT_CHANNEL_CACHE_TIME = time.time()

        return channel

    except Exception as e:
        logging.error(
            "Default channel resolve failed: %s",
            e,
        )

        return None


# ============================================================
# GROUP CHANNEL MAPPING
# ============================================================

def mapping_path(group_id):
    return f"groups/{int(group_id)}"


def get_mapping(group_id):
    data = firebase_get(
        mapping_path(group_id)
    )

    return data if isinstance(data, dict) else {}


def save_mapping(group_id, channel):
    data = {
        "group_id": int(group_id),
        "channel_id": int(channel.id),
        "channel_title": getattr(
            channel,
            "title",
            "Unknown",
        ),
        "channel_username": getattr(
            channel,
            "username",
            None,
        ),
        "updated_at": int(time.time()),
        "configured_by": OWNER_ID,
    }

    ok = firebase_put(
        mapping_path(group_id),
        data,
    )

    if ok:
        CHANNEL_CACHE[int(group_id)] = (
            channel,
            time.time(),
        )

    return ok


def delete_mapping(group_id):
    CHANNEL_CACHE.pop(
        int(group_id),
        None,
    )

    return firebase_delete(
        mapping_path(group_id)
    )


async def get_group_channel(group_id):
    group_id = int(group_id)

    cached = CHANNEL_CACHE.get(
        group_id
    )

    if cached:
        channel, saved_at = cached

        if time.time() - saved_at < 300:
            return channel

    mapping = get_mapping(
        group_id
    )

    if not mapping:
        return None

    channel_id = mapping.get(
        "channel_id"
    )

    username = mapping.get(
        "channel_username"
    )

    if not channel_id and not username:
        return None

    try:
        if channel_id:
            channel = await bot.get_entity(
                int(channel_id)
            )
        else:
            channel = await bot.get_entity(
                username
            )

        CHANNEL_CACHE[group_id] = (
            channel,
            time.time(),
        )

        return channel

    except Exception as e:
        logging.error(
            "Group channel resolve error: %s",
            e,
        )

        return None


async def get_search_channel(event):
    """
    Group:
        group-specific channel first
        otherwise default channel

    Private:
        default channel
    """

    if event.is_group:
        channel = await get_group_channel(
            event.chat_id
        )

        if channel:
            return channel

    return await get_default_channel()


# ============================================================
# ENTITY RESOLUTION
# ============================================================

def extract_username(value):
    value = (
        value or ""
    ).strip()

    if value.startswith("@"):
        return value[1:]

    match = re.match(
        r"^(?:https?://)?(?:www\.)?t\.me/"
        r"([A-Za-z0-9_]+)(?:/.*)?$",
        value,
    )

    if match:
        username = match.group(1)

        if username not in (
            "c",
            "joinchat",
        ):
            return username

    return None


async def resolve_entity(value):
    value = (
        value or ""
    ).strip()

    username = extract_username(
        value
    )

    try:
        if username:
            return await bot.get_entity(
                username
            )

        if re.fullmatch(
            r"-?\d+",
            value,
        ):
            return await bot.get_entity(
                int(value)
            )

        return await bot.get_entity(
            value
        )

    except (
        UsernameInvalidError,
        UsernameNotOccupiedError,
        ChannelPrivateError,
    ):
        return None

    except Exception as e:
        logging.error(
            "Entity resolve error: %s",
            e,
        )

        return None


async def validate_channel(channel):
    try:
        await bot.get_messages(
            channel,
            limit=3,
        )

        return True, None

    except ChatAdminRequiredError:
        return (
            False,
            "Bot ko channel read permission chahiye.",
        )

    except ChannelPrivateError:
        return (
            False,
            "Private channel hai. Bot ko channel mein add karo.",
        )

    except FloodWaitError as e:
        return (
            False,
            f"Telegram FloodWait {e.seconds}s.",
        )

    except Exception as e:
        return (
            False,
            str(e),
        )


# ============================================================
# TEXT SEARCH
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


def normalize(text):
    if not text:
        return ""

    text = unicodedata.normalize(
        "NFKC",
        str(text),
    ).lower()

    text = re.sub(
        r"https?://\S+",
        " ",
        text,
    )

    text = re.sub(
        r"[_\-/.,:;|+*=~`'\"()\[\]{}<>!?]+",
        " ",
        text,
    )

    text = "".join(
        char
        if char.isalnum() or char.isspace()
        else " "
        for char in text
    )

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def compact(text):
    return normalize(
        text
    ).replace(
        " ",
        "",
    )


def extract_app_query(text):
    words = normalize(
        text
    ).split()

    cleaned = [
        word
        for word in words
        if word not in REQUEST_WORDS
    ]

    return " ".join(
        cleaned
    ).strip()


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

    direct = (
        SequenceMatcher(
            None,
            a_n,
            b_n,
        ).ratio()
        * 100
    )

    compact_score = (
        SequenceMatcher(
            None,
            a_c,
            b_c,
        ).ratio()
        * 100
    )

    word_best = 0

    for query_word in a_n.split():
        if len(query_word) < 2:
            continue

        for post_word in b_n.split():
            score = (
                SequenceMatcher(
                    None,
                    query_word,
                    post_word,
                ).ratio()
                * 100
            )

            word_best = max(
                word_best,
                score,
            )

    return max(
        direct,
        compact_score,
        word_best,
    )


def post_score(query, post_text):
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

    best = similarity(
        query_n,
        text_n,
    )

    query_words = query_n.split()
    post_words = text_n.split()

    if len(query_words) > 1:
        size = len(query_words)

        for index in range(
            0,
            max(
                0,
                len(post_words) - size + 1,
            ),
        ):
            window = " ".join(
                post_words[
                    index:index + size
                ]
            )

            best = max(
                best,
                similarity(
                    query_n,
                    window,
                ),
            )

    return best


# ============================================================
# CHANNEL SEARCH
# ============================================================

async def search_channel(channel, query):
    if not query:
        return (
            None,
            0,
            "empty",
        )

    best_message = None
    best_score = 0

    seen = set()

    search_terms = [
        normalize(query)
    ]

    for word in normalize(
        query
    ).split():

        if len(word) >= 3:
            search_terms.append(
                word
            )

    # Telegram server search
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

                seen.add(
                    message.id
                )

                post_text = (
                    message.raw_text
                    or ""
                )

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
                "Search FloodWait: %ss",
                e.seconds,
            )

            await asyncio.sleep(
                e.seconds
            )

        except Exception as e:
            logging.warning(
                "Telegram search error: %s",
                e,
            )

    # Recent history fallback
    try:
        scanned = 0

        async for message in bot.iter_messages(
            channel,
            limit=SCAN_LIMIT,
        ):
            if not message:
                continue

            post_text = (
                message.raw_text
                or ""
            )

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
                    "history",
                )

            if scanned >= SCAN_LIMIT:
                break

    except FloodWaitError as e:
        logging.warning(
            "History FloodWait: %ss",
            e.seconds,
        )

    except Exception as e:
        logging.error(
            "History search error: %s",
            e,
        )

    if (
        best_message
        and best_score >= 60
    ):
        return (
            best_message,
            best_score,
            "fuzzy",
        )

    return (
        None,
        best_score,
        "not-found",
    )


# ============================================================
# LINKS
# ============================================================

def post_link(channel, message):
    username = getattr(
        channel,
        "username",
        None,
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
        None,
    )

    if channel_id:
        # Telegram private-channel link
        internal_id = str(
            channel_id
        ).replace(
            "-100",
            "",
            1,
        )

        return (
            f"https://t.me/c/"
            f"{internal_id}/"
            f"{message.id}"
        )

    return None


def share_link(url, text):
    return (
        "https://t.me/share/url"
        "?url="
        + quote(
            url,
            safe="",
        )
        + "&text="
        + quote(
            text,
            safe="",
        )
    )


def result_buttons(
    post_url,
    app_name,
):
    if not post_url:
        return []

    return [
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
    ]


# ============================================================
# START
# ============================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/start$"
    )
)
async def start_command(event):
    await event.reply(
        "👋 **Welcome to PREMIUM MOD BOT**\n\n"
        "🔎 App ka naam bhejo aur main configured "
        "Telegram channel mein search karunga.\n\n"
        "**Examples:**\n"
        "`Kuku TV do`\n"
        "`KukuTV link`\n"
        "`BulletShorts do`\n\n"
        "⚙️ Commands ke liye `/help` bhejo.",
        parse_mode="md",
    )


# ============================================================
# DEFAULT CHANNEL
# OWNER ONLY
# ============================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/defaultchannel(?:\s+(.+))?$"
    )
)
async def defaultchannel_command(event):
    if not is_owner(event):
        await event.reply(
            "❌ Sirf owner ye command use kar sakta hai."
        )
        return

    value = event.pattern_match.group(1)

    if not value:
        current = await get_default_channel()

        if current:
            username = getattr(
                current,
                "username",
                None,
            )

            await event.reply(
                "📌 **DEFAULT CHANNEL**\n\n"
                f"📢 {getattr(current, 'title', 'Unknown')}\n"
                f"🔗 @{username if username else 'Private'}",
                parse_mode="md",
            )
        else:
            await event.reply(
                "❌ Default channel configured nahi hai.\n\n"
                "Use:\n"
                "`/defaultchannel @PRMMOD`",
                parse_mode="md",
            )

        return

    await event.reply(
        "🔎 Default channel check kar raha hoon..."
    )

    channel = await resolve_entity(
        value
    )

    if not channel:
        await event.reply(
            "❌ Channel nahi mila.\n\n"
            "Example:\n"
            "`/defaultchannel @PRMMOD`",
            parse_mode="md",
        )
        return

    ok, error = await validate_channel(
        channel
    )

    if not ok:
        await event.reply(
            "❌ **Channel access failed**\n\n"
            f"`{error}`",
            parse_mode="md",
        )
        return

    if not save_default_channel(
        channel
    ):
        await event.reply(
            "❌ Channel mil gaya, lekin Firebase mein save nahi hua."
        )
        return

    username = getattr(
        channel,
        "username",
        None,
    )

    await event.reply(
        "✅ **DEFAULT CHANNEL SAVED**\n\n"
        f"📢 Channel: **{getattr(channel, 'title', 'Unknown')}**\n"
        f"🔗 Username: `{('@' + username) if username else 'Private'}`\n\n"
        "🟢 Ab private chat mein bhi search chalega.\n"
        "🟢 Jis group mein custom `/setup` nahi hai, "
        "wahan bhi ye channel use hoga.",
        parse_mode="md",
    )


@bot.on(
    events.NewMessage(
        pattern=r"^/cleardefault$"
    )
)
async def cleardefault_command(event):
    if not is_owner(event):
        return

    if delete_default_channel():
        await event.reply(
            "✅ Default channel remove ho gaya."
        )
    else:
        await event.reply(
            "❌ Default channel remove nahi hua."
        )


# ============================================================
# GROUP SETUP
# ============================================================

async def complete_setup(
    event,
    value,
):
    if not event.is_group:
        await event.reply(
            "⚠️ `/setup` group ke andar use karo.\n\n"
            "Private chat ke liye owner:\n"
            "`/defaultchannel @PRMMOD`",
            parse_mode="md",
        )
        return

    # Only owner or group admin
    if not is_owner(event):
        try:
            permissions = await bot.get_permissions(
                event.chat_id,
                event.sender_id,
            )

            if not permissions.is_admin:
                await event.reply(
                    "❌ Sirf group admin `/setup` kar sakta hai."
                )
                return

        except Exception:
            await event.reply(
                "❌ Group admin permission verify nahi ho saki."
            )
            return

    await event.reply(
        "🔎 Channel check kar raha hoon..."
    )

    channel = await resolve_entity(
        value
    )

    if not channel:
        await event.reply(
            "❌ Channel identify nahi hua.\n\n"
            "Example:\n"
            "`/setup @PRMMOD`",
            parse_mode="md",
        )
        return

    ok, error = await validate_channel(
        channel
    )

    if not ok:
        await event.reply(
            "❌ **Channel access problem**\n\n"
            f"`{error}`",
            parse_mode="md",
        )
        return

    if not save_mapping(
        event.chat_id,
        channel,
    ):
        await event.reply(
            "❌ Firebase mein group mapping save nahi hui."
        )
        return

    username = getattr(
        channel,
        "username",
        None,
    )

    await event.reply(
        "✅ **GROUP SETUP COMPLETE**\n\n"
        f"📢 Channel: **{getattr(channel, 'title', 'Unknown')}**\n"
        f"🔗 Username: `{('@' + username) if username else 'Private'}`\n\n"
        "🔎 Ab is group ke messages isi channel mein search honge.",
        parse_mode="md",
    )


@bot.on(
    events.NewMessage(
        pattern=r"^/setup(?:\s+(.+))?$"
    )
)
async def setup_command(event):
    if not event.is_group:
        await event.reply(
            "⚠️ Group mein `/setup @PRMMOD` use karo.\n\n"
            "Private chat ke liye:\n"
            "`/defaultchannel @PRMMOD`",
            parse_mode="md",
        )
        return

    value = event.pattern_match.group(1)

    if value:
        await complete_setup(
            event,
            value.strip(),
        )
        return

    SETUP[event.sender_id] = {
        "group_id": event.chat_id,
        "type": "channel",
        "created_at": time.time(),
    }

    await event.reply(
        "⚙️ **GROUP SETUP**\n\n"
        "Ab channel ka username/link bhejo.\n\n"
        "Example:\n"
        "`@PRMMOD`\n"
        "or\n"
        "`https://t.me/PRMMOD`\n\n"
        "❌ Cancel: `/cancel`",
        parse_mode="md",
    )


@bot.on(
    events.NewMessage(
        pattern=r"^/cancel$"
    )
)
async def cancel_command(event):
    SETUP.pop(
        event.sender_id,
        None,
    )

    await event.reply(
        "✅ Setup cancel ho gaya."
    )


# ============================================================
# SETUP MESSAGE HANDLER
# ============================================================

@bot.on(
    events.NewMessage(
        incoming=True
    )
)
async def setup_message_handler(event):
    if not event.is_group:
        return

    text = (
        event.raw_text
        or ""
    ).strip()

    if not text:
        return

    if text.startswith("/"):
        return

    state = SETUP.get(
        event.sender_id
    )

    if not state:
        return

    if state.get(
        "group_id"
    ) != event.chat_id:
        return

    await complete_setup(
        event,
        text,
    )

    SETUP.pop(
        event.sender_id,
        None,
    )


# ============================================================
# NORMAL SEARCH
# ============================================================

@bot.on(
    events.NewMessage(
        incoming=True
    )
)
async def public_search(event):
    try:
        text = (
            event.raw_text
            or ""
        ).strip()

        if not text:
            return

        if text.startswith("/"):
            return

        # Setup message is handled separately
        if event.is_group:
            state = SETUP.get(
                event.sender_id
            )

            if (
                state
                and state.get("group_id")
                == event.chat_id
            ):
                return

        channel = await get_search_channel(
            event
        )

        if not channel:
            # Private user gets useful message
            if not event.is_group:
                await event.reply(
                    "⚠️ Search channel configured nahi hai.\n\n"
                    "Owner ko pehle run karna hoga:\n"
                    "`/defaultchannel @PRMMOD`",
                    parse_mode="md",
                )

            return

        query = extract_app_query(
            text
        )

        if not query:
            return

        if len(
            compact(query)
        ) < 2:
            return

        lock_id = (
            event.chat_id
            if event.is_group
            else 0
        )

        async with get_lock(
            lock_id
        ):
            logging.info(
                "SEARCH | chat=%s | user=%s | query=%r | channel=%s",
                event.chat_id,
                event.sender_id,
                query,
                getattr(
                    channel,
                    "title",
                    "Unknown",
                ),
            )

            # =================================================
            # FIREBASE MANUAL FILTER
            # =================================================

            filters = firebase_get(
                "links"
            )

            if isinstance(
                filters,
                dict,
            ):
                for key, value in filters.items():

                    if isinstance(
                        value,
                        dict,
                    ):
                        saved_name = value.get(
                            "name",
                            key,
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
                        saved_name,
                    )

                    if score >= 85:
                        await event.reply(
                            "👋 **Mil gaya!**\n\n"
                            f"📱 **{str(saved_name).upper()}**\n"
                            f"🔗 {saved_link}",
                            parse_mode="md",
                            link_preview=False,
                        )
                        return

            # =================================================
            # TELEGRAM CHANNEL SEARCH
            # =================================================

            message, score, method = (
                await search_channel(
                    channel,
                    query,
                )
            )

            if not message:
                logging.info(
                    "NOT FOUND | query=%r | score=%.1f | method=%s",
                    query,
                    score,
                    method,
                )

                await event.reply(
                    "❌ **Nahi mila**\n\n"
                    f"🔎 Search: `{query}`\n"
                    "📢 Configured channel mein matching post nahi mila.",
                    parse_mode="md",
                )

                return

            url = post_link(
                channel,
                message,
            )

            if not url:
                await event.reply(
                    "⚠️ Post mil gaya, lekin post URL generate nahi ho saka."
                )
                return

            title = getattr(
                channel,
                "title",
                "Channel",
            )

            preview = (
                message.raw_text
                or ""
            ).strip()

            if len(preview) > 700:
                preview = (
                    preview[:700]
                    .rstrip()
                    + "..."
                )

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

            reply += (
                "👇 Neeche button se post open karo:"
            )

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
            "Search FloodWait: %ss",
            e.seconds,
        )

    except Exception as e:
        logging.exception(
            "PUBLIC SEARCH ERROR: %s",
            e,
        )


# ============================================================
# FILTER COMMAND
# ============================================================

def safe_key(value):
    value = str(
        value
    ).strip().lower()

    for char in ".#$[]/":
        value = value.replace(
            char,
            "_",
        )

    return value[:100]


@bot.on(
    events.NewMessage(
        pattern=r"^/filter\s+(.+?)\s+(https?://\S+)$"
    )
)
async def filter_command(event):
    if not is_owner(event):
        return

    app_name = (
        event.pattern_match
        .group(1)
        .strip()
    )

    link = (
        event.pattern_match
        .group(2)
        .strip()
    )

    ok = firebase_put(
        f"links/{safe_key(app_name)}",
        {
            "name": app_name,
            "link": link,
            "updated_at": int(
                time.time()
            ),
        },
    )

    if ok:
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
# STATUS
# ============================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/status$"
    )
)
async def status_command(event):
    default = await get_default_channel()

    lines = [
        "📊 **BOT STATUS**",
        "",
        f"🤖 Telegram: {'✅ CONNECTED' if BOT_ME else '❌'}",
        f"🔥 Firebase: {'✅ ONLINE' if firebase_is_online() else '❌ OFFLINE'}",
    ]

    if default:
        username = getattr(
            default,
            "username",
            None,
        )

        lines.extend(
            [
                "",
                "🌐 **DEFAULT CHANNEL**",
                f"📢 {getattr(default, 'title', 'Unknown')}",
                f"🔗 {('@' + username) if username else 'Private'}",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "🌐 **DEFAULT CHANNEL**",
                "❌ NOT SET",
            ]
        )

    if event.is_group:
        mapping = get_mapping(
            event.chat_id
        )

        if mapping:
            lines.extend(
                [
                    "",
                    "👥 **THIS GROUP**",
                    "✅ Custom channel configured",
                    f"📢 {mapping.get('channel_title', 'Unknown')}",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "👥 **THIS GROUP**",
                    "ℹ️ Custom channel not set",
                    "↪️ Default channel will be used",
                ]
            )
    else:
        lines.extend(
            [
                "",
                "👤 **PRIVATE CHAT**",
                "↪️ Default channel will be used",
            ]
        )

    await event.reply(
        "\n".join(lines),
        parse_mode="md",
    )


# ============================================================
# RESET GROUP
# ============================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/reset$"
    )
)
async def reset_command(event):
    if not event.is_group:
        return

    if not is_owner(event):
        try:
            permissions = await bot.get_permissions(
                event.chat_id,
                event.sender_id,
            )

            if not permissions.is_admin:
                await event.reply(
                    "❌ Sirf group admin `/reset` kar sakta hai."
                )
                return

        except Exception:
            return

    if delete_mapping(
        event.chat_id
    ):
        await event.reply(
            "✅ Group ka custom channel reset ho gaya.\n\n"
            "Ab ye group default channel use karega."
        )
    else:
        await event.reply(
            "❌ Group mapping delete nahi hui."
        )


# ============================================================
# DIAGNOSTIC
# ============================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/diagnostic$"
    )
)
async def diagnostic_command(event):

    telegram_ok = BOT_ME is not None

    firebase_ok = firebase_is_online()

    default = await get_default_channel()

    lines = [
        "⚠️ **BOT DIAGNOSTIC**",
        "",
        f"🤖 Telegram Client: {'✅' if telegram_ok else '❌'}",
        f"🔥 Firebase: {'✅ ONLINE' if firebase_ok else '❌ OFFLINE'}",
        f"🔎 Search Engine: {'READY' if default else 'BLOCKED'}",
        "🧠 Fuzzy Search: ON",
        "📤 Share Button: ON",
        "👥 Public Multi-User: ON",
    ]

    if default:
        lines.extend(
            [
                "",
                "🌐 Default Channel: ✅",
                f"📢 {getattr(default, 'title', 'Unknown')}",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "🌐 Default Channel: ❌",
                "Use `/defaultchannel @PRMMOD`",
            ]
        )

    if event.is_group:
        channel = await get_group_channel(
            event.chat_id
        )

        if channel:
            lines.extend(
                [
                    "",
                    "👥 Group Channel: ✅",
                    f"📢 {getattr(channel, 'title', 'Unknown')}",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "👥 Group Channel: ❌",
                    "Default channel fallback available if configured.",
                ]
            )
    else:
        lines.extend(
            [
                "",
                "👤 Private Chat: ✅",
            ]
        )

    lines.extend(
        [
            "",
            "⚠️ **Important**",
            "Group messages receive nahi hote to BotFather → /setprivacy → Disable karo.",
            "Private chat ke liye privacy setting ki zarurat nahi hai.",
        ]
    )

    await event.reply(
        "\n".join(lines),
        parse_mode="md",
    )


# ============================================================
# PING
# ============================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/ping$"
    )
)
async def ping_command(event):
    uptime = (
        datetime.now()
        - START_TIME
    )

    total_seconds = int(
        uptime.total_seconds()
    )

    hours = total_seconds // 3600
    minutes = (
        total_seconds % 3600
    ) // 60

    firebase_ok = firebase_is_online()

    default = await get_default_channel()

    lines = [
        "🟢 **BOT ONLINE**",
        "",
        f"⏱️ Uptime: {hours}h {minutes}m",
        "📡 Telegram: ✅ CONNECTED",
        f"🔥 Firebase: {'✅ ONLINE' if firebase_ok else '❌ OFFLINE'}",
        "👥 Public Multi-User: ✅ ON",
        "🧠 Fuzzy Search: ✅ ON",
        "📤 Share Button: ✅ ON",
        "🔎 Live Search: ON",
        f"🌐 Default Channel: {'✅ SET' if default else '❌ NOT SET'}",
    ]

    if event.is_group:
        mapping = get_mapping(
            event.chat_id
        )

        lines.append(
            "👥 Group Channel: "
            + (
                "✅ CUSTOM"
                if mapping
                else "↪️ DEFAULT"
            )
        )

    else:
        lines.append(
            "👤 Private Chat: ✅"
        )

    await event.reply(
        "\n".join(lines),
        parse_mode="md",
    )


# ============================================================
# HELP
# ============================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/help$"
    )
)
async def help_command(event):
    await event.reply(
        "🤖 **PREMIUM MOD BOT**\n\n"
        "🔎 **Search**\n"
        "Simply app name bhejo:\n"
        "`Kuku TV do`\n"
        "`KukuTV link`\n"
        "`BulletShorts do`\n\n"
        "👤 **Private Search**\n"
        "Owner pehle:\n"
        "`/defaultchannel @PRMMOD`\n\n"
        "👥 **Group**\n"
        "`/setup @PRMMOD`\n"
        "`/status`\n"
        "`/reset`\n\n"
        "🛠 **Diagnostics**\n"
        "`/ping`\n"
        "`/diagnostic`\n\n"
        "⚙️ **Owner**\n"
        "`/defaultchannel @PRMMOD`\n"
        "`/cleardefault`\n"
        "`/filter AppName https://example.com/link`\n\n"
        "🟢 Default channel set hone ke baad "
        "private aur group dono mein search chalega.",
        parse_mode="md",
    )


# ============================================================
# WELCOME CLEANER
# ============================================================

async def delete_later(
    message,
    delay,
):
    try:
        await asyncio.sleep(
            delay
        )

        await message.delete()

    except Exception:
        pass


@bot.on(
    events.NewMessage(
        incoming=True
    )
)
async def clean_bot_welcome(event):
    try:
        if not event.is_group:
            return

        sender = await event.get_sender()

        if not sender:
            return

        if not getattr(
            sender,
            "bot",
            False,
        ):
            return

        if (
            BOT_ME
            and sender.id == BOT_ME.id
        ):
            return

        text = (
            event.raw_text
            or ""
        ).lower()

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

    except Exception:
        pass


@bot.on(
    events.ChatAction
)
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
# GITHUB AUTO RESTART
# ============================================================

async def github_keep_alive():
    while True:
        try:
            elapsed = (
                datetime.now()
                - START_TIME
            )

            if elapsed >= timedelta(
                hours=5,
                minutes=45,
            ):
                print(
                    "🔄 GITHUB SAFE REBOOT"
                )

                github_token = os.environ.get(
                    "MY_GITHUB_TOKEN"
                )

                repo_name = os.environ.get(
                    "GITHUB_REPOSITORY"
                )

                if (
                    github_token
                    and repo_name
                ):
                    url = (
                        "https://api.github.com/repos/"
                        f"{repo_name}/actions/workflows/run-bot.yml/dispatches"
                    )

                    headers = {
                        "Accept":
                            "application/vnd.github+json",
                        "Authorization":
                            f"Bearer {github_token}",
                        "X-GitHub-Api-Version":
                            "2022-11-28",
                    }

                    try:
                        response = requests.post(
                            url,
                            headers=headers,
                            json={
                                "ref": "main"
                            },
                            timeout=15,
                        )

                        print(
                            "GitHub dispatch:",
                            response.status_code,
                        )

                    except Exception as e:
                        logging.error(
                            "GitHub dispatch error: %s",
                            e,
                        )

                os._exit(0)

        except Exception as e:
            logging.error(
                "Keep alive error: %s",
                e,
            )

        await asyncio.sleep(
            300
        )


# ============================================================
# MAIN
# ============================================================

async def main():
    global BOT_ME

    print(
        "⏳ Starting Telegram Client..."
    )

    try:
        await bot.start(
            bot_token=BOT_TOKEN
        )

    except Exception as e:
        print(
            f"❌ Telegram login failed: {e}"
        )
        raise

    BOT_ME = await bot.get_me()

    print(
        "✅ Telegram Client Started!"
    )

    print(
        f"🤖 Bot: @{getattr(BOT_ME, 'username', 'unknown')}"
    )

    print(
        "🌍 PRIVATE SEARCH: ON"
    )

    print(
        "👥 GROUP SEARCH: ON"
    )

    print(
        "🌐 DEFAULT CHANNEL: ON"
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

    asyncio.create_task(
        github_keep_alive()
    )

    print(
        "🟢 BOT ONLINE - waiting for messages..."
    )

    # VERY IMPORTANT
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
            f"❌ FATAL ERROR: {type(e).__name__}: {e}"
        )
        raise

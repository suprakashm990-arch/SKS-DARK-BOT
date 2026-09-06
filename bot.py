import os
import sys
import re
import time
import logging
import asyncio
import unicodedata
from datetime import datetime, timedelta

import requests
from rapidfuzz import fuzz

from telethon import TelegramClient, events, Button
from telethon.errors import (
    UsernameInvalidError,
    UsernameNotOccupiedError,
    ChannelPrivateError,
    ChatAdminRequiredError,
    FloodWaitError,
)

# ============================================================
# 🚀 PREMIUM MOD PUBLIC MULTI-USER BOT
# ============================================================

print("🚀 PREMIUM MOD BOT BOOTING...")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ============================================================
# 🔐 ENVIRONMENT
# ============================================================

API_ID = os.environ.get("TG_API_ID")
API_HASH = os.environ.get("TG_API_HASH")
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")

FIREBASE_URL = "https://sks-9865a-default-rtdb.firebaseio.com/"

# Your owner ID - owner commands always available
OWNER_ID = 8587571289

if not API_ID or not API_HASH or not BOT_TOKEN:
    print("❌ TG_API_ID / TG_API_HASH / TG_BOT_TOKEN missing")
    sys.exit(1)

API_ID = int(API_ID)

bot = TelegramClient(
    "premium_mod_public_bot",
    API_ID,
    API_HASH
)

START_TIME = datetime.now()

# ============================================================
# 🧠 SEARCH SETTINGS
# ============================================================

MIN_SCORE = 58
GOOD_SCORE = 68

# Maximum posts to inspect locally
LOCAL_SCAN_LIMIT = 2500

# Search cache
CHANNEL_CACHE = {}

# ============================================================
# 🔥 FIREBASE HELPERS
# ============================================================

def firebase_get(path):
    try:
        url = FIREBASE_URL.rstrip("/") + "/" + path.lstrip("/")
        r = requests.get(url, timeout=12)

        if r.status_code == 200:
            return r.json()

    except Exception as e:
        logging.error("Firebase GET error: %s", e)

    return None


def firebase_put(path, data):
    try:
        url = FIREBASE_URL.rstrip("/") + "/" + path.lstrip("/")
        r = requests.put(url, json=data, timeout=12)

        return r.status_code in (200, 201)

    except Exception as e:
        logging.error("Firebase PUT error: %s", e)

    return False


def firebase_delete(path):
    try:
        url = FIREBASE_URL.rstrip("/") + "/" + path.lstrip("/")
        r = requests.delete(url, timeout=12)

        return r.status_code in (200, 204)

    except Exception as e:
        logging.error("Firebase DELETE error: %s", e)

    return False


# ============================================================
# 🔐 SAFE FIREBASE KEY
# ============================================================

def safe_key(value):
    value = str(value)

    value = value.replace(".", "_")
    value = value.replace("#", "_")
    value = value.replace("$", "_")
    value = value.replace("[", "_")
    value = value.replace("]", "_")
    value = value.replace("/", "_")

    return value[:100]


# ============================================================
# 👤 USER CONFIG
#
# Each user gets own:
# /users/<USER_ID>/group
# /users/<USER_ID>/channel
# ============================================================

def get_user_config(user_id):
    data = firebase_get(f"users/{user_id}")

    if isinstance(data, dict):
        return data

    return {}


def save_user_config(user_id, config):
    return firebase_put(f"users/{user_id}", config)


# ============================================================
# 🔧 NORMALIZATION
# ============================================================

REQUEST_WORDS = {
    "do",
    "de",
    "dedo",
    "bhejo",
    "bhej",
    "send",
    "link",
    "download",
    "downloadlink",
    "apk",
    "app",
    "mod",
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
    "wala",
    "wali",
    "version",
    "latest",
    "latestversion",
}


def normalize(text):
    if not text:
        return ""

    text = unicodedata.normalize("NFKC", text)

    text = text.lower()

    # Common separators -> spaces
    text = re.sub(r"[_\-./]+", " ", text)

    # Remove emoji / symbols but keep letters/numbers
    text = "".join(
        c if c.isalnum() or c.isspace() else " "
        for c in text
    )

    text = re.sub(r"\s+", " ", text).strip()

    return text


def extract_app_query(text):
    """
    User kuch bhi likh sakta hai:

    Kuku TV do
    Kuku TV link
    kuku tv please
    BulletShorts dedo
    Bullet Shorts chahiye
    mujhe kuku tv ka mod bhejo
    """

    normalized = normalize(text)

    words = normalized.split()

    cleaned = [
        w for w in words
        if w not in REQUEST_WORDS
    ]

    query = " ".join(cleaned).strip()

    return query


# ============================================================
# 🔍 FUZZY SEARCH SCORING
# ============================================================

def calculate_score(query, post_text):
    q = normalize(query)
    t = normalize(post_text)

    if not q or not t:
        return 0

    # Exact
    if q in t:
        return 100

    # Full text similarity
    ratio = fuzz.partial_ratio(q, t)

    token_score = fuzz.token_set_ratio(q, t)

    sort_score = fuzz.token_sort_ratio(q, t)

    score = max(
        ratio,
        token_score,
        sort_score
    )

    return score


# ============================================================
# 🔗 TELEGRAM LINK RESOLVER
# ============================================================

def extract_username_from_link(value):
    if not value:
        return None

    value = value.strip()

    # @username
    if value.startswith("@"):
        return value[1:]

    # https://t.me/username
    m = re.search(
        r"(?:https?://)?t\.me/([A-Za-z0-9_]+)",
        value
    )

    if m:
        username = m.group(1)

        # Ignore special invite links
        if username not in ("c", "joinchat"):
            return username

    return None


async def resolve_telegram_entity(value):
    """
    Public username/channel:
        @PRMMOD
        https://t.me/PRMMOD

    Private channel/group:
        Bot must already be a member/admin.
    """

    value = value.strip()

    username = extract_username_from_link(value)

    try:

        if username:
            entity = await bot.get_entity(username)
        else:
            # Numeric Telegram ID
            entity = await bot.get_entity(int(value))

        return entity

    except (
        UsernameInvalidError,
        UsernameNotOccupiedError,
        ChannelPrivateError,
    ):
        return None

    except Exception as e:
        logging.error(
            "Entity resolve error [%s]: %s",
            value,
            e
        )

        return None


# ============================================================
# 🧪 CHANNEL ACCESS TEST
# ============================================================

async def test_channel(channel):
    try:
        # Read a few posts
        messages = await bot.get_messages(
            channel,
            limit=5
        )

        return True, messages

    except ChatAdminRequiredError:
        return False, "Bot ko channel access/admin permission chahiye."

    except ChannelPrivateError:
        return False, "Channel private hai ya bot channel ka member nahi hai."

    except FloodWaitError as e:
        return False, f"Telegram FloodWait: {e.seconds} seconds."

    except Exception as e:
        return False, str(e)


# ============================================================
# 🔎 SMART CHANNEL SEARCH
# ============================================================

async def search_channel(channel, query):
    """
    1. Telegram server-side search try
    2. Recent messages scan
    3. Fuzzy matching
    4. Best matching post return
    """

    if not query:
        return None

    best_message = None
    best_score = 0

    # --------------------------------------------------------
    # STEP 1: Telegram's own search
    # --------------------------------------------------------

    search_terms = []

    q = normalize(query)

    if q:
        search_terms.append(q)

        # Multi-word app:
        # Kuku TV -> Kuku
        # Bullet Shorts -> Bullet
        parts = q.split()

        for part in parts:
            if len(part) >= 3:
                search_terms.append(part)

    seen_ids = set()

    for term in search_terms[:5]:

        try:

            async for msg in bot.iter_messages(
                channel,
                search=term,
                limit=80
            ):

                if not msg:
                    continue

                if msg.id in seen_ids:
                    continue

                seen_ids.add(msg.id)

                text = msg.raw_text or ""

                if not text:
                    continue

                score = calculate_score(
                    query,
                    text
                )

                if score > best_score:
                    best_score = score
                    best_message = msg

                if score >= 95:
                    return msg

        except FloodWaitError as e:
            logging.warning(
                "Telegram FloodWait: %s seconds",
                e.seconds
            )
            await asyncio.sleep(e.seconds)

        except Exception as e:
            logging.warning(
                "Server search failed: %s",
                e
            )

    # --------------------------------------------------------
    # STEP 2: Recent posts fuzzy scan
    # --------------------------------------------------------

    try:

        scanned = 0

        async for msg in bot.iter_messages(
            channel,
            limit=LOCAL_SCAN_LIMIT
        ):

            if not msg:
                continue

            text = msg.raw_text or ""

            if not text:
                continue

            scanned += 1

            score = calculate_score(
                query,
                text
            )

            if score > best_score:
                best_score = score
                best_message = msg

            # Very strong match
            if score >= 92:
                return msg

            if scanned >= LOCAL_SCAN_LIMIT:
                break

    except FloodWaitError as e:
        logging.warning(
            "Fuzzy search FloodWait: %s seconds",
            e.seconds
        )

    except Exception as e:
        logging.error(
            "Fuzzy scan error: %s",
            e
        )

    if best_message and best_score >= MIN_SCORE:
        logging.info(
            "Search result: %s | score=%s",
            query,
            best_score
        )

        return best_message

    return None


# ============================================================
# 🔗 POST LINK
# ============================================================

def make_post_link(channel, message):
    """
    Public channel:
        https://t.me/username/message_id

    Private channel:
        https://t.me/c/channel_id/message_id
    """

    username = getattr(channel, "username", None)

    if username:
        return f"https://t.me/{username}/{message.id}"

    channel_id = getattr(channel, "id", None)

    if channel_id:
        return (
            f"https://t.me/c/"
            f"{channel_id}/"
            f"{message.id}"
        )

    return None


# ============================================================
# 🧪 DIAGNOSTIC
# ============================================================

async def diagnostic(user_id, chat_id=None):

    config = get_user_config(user_id)

    result = [
        "⚠️ **BOT DIAGNOSTIC**",
        "",
        f"👤 User ID: `{user_id}`",
    ]

    group_id = config.get("group_id")
    channel_id = config.get("channel_id")

    # GROUP
    if group_id:
        result.append("👥 Group Mapping: ✅")

        try:
            group = await bot.get_entity(int(group_id))

            result.append(
                f"💬 Group: `{getattr(group, 'title', 'Unknown')}`"
            )

        except Exception as e:
            result.append("💬 Group Resolve: ❌")
            result.append(
                f"Reason: `{str(e)[:200]}`"
            )

    else:
        result.append("👥 Group Mapping: ❌")
        result.append("Run `/setup`")

    # CHANNEL
    channel = None

    if channel_id:
        try:
            channel = await bot.get_entity(
                int(channel_id)
            )

            result.append("📢 Channel Mapping: ✅")

            result.append(
                f"📢 Channel: `{getattr(channel, 'title', 'Unknown')}`"
            )

        except Exception as e:
            result.append("📢 Channel Mapping: ❌")
            result.append(
                f"Reason: `{str(e)[:200]}`"
            )

    else:
        result.append("📢 Channel Mapping: ❌")
        result.append("Run `/setup`")

    # SEARCH TEST
    if channel:

        ok, data = await test_channel(channel)

        if ok:
            result.append("🔎 Channel Read Access: ✅")
            result.append("🧠 Search Engine: ✅")
            result.append("🔥 Firebase: ✅")

        else:
            result.append("🔎 Channel Read Access: ❌")
            result.append(
                f"Reason: `{str(data)[:250]}`"
            )

    return "\n".join(result)


# ============================================================
# /START
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/start$"))
async def start_handler(event):

    if event.is_group:

        await event.reply(
            "👋 **Premium Mod Search Bot**\n\n"
            "Mujhe group mein add karke admin/read permission dein.\n\n"
            "Owner/Admin setup ke liye:\n"
            "`/setup`"
        )

        return

    await event.reply(
        "👋 **PREMIUM MOD BOT**\n\n"
        "🔎 Smart App Search\n"
        "🧠 Fuzzy Search\n"
        "📢 Channel Post Search\n"
        "🔗 Share Button\n"
        "🔥 Firebase\n\n"
        "Group/channel setup karne ke liye:\n"
        "`/setup`"
    )


# ============================================================
# /SETUP
#
# Setup is interactive:
#
# /setup
# Bot asks channel
# Then group
#
# BEST: Run /setup inside target group.
# ============================================================

setup_sessions = {}


@bot.on(events.NewMessage(pattern=r"^/setup$"))
async def setup_start(event):

    user_id = event.sender_id

    # Security:
    # Public bot hone ke baad bhi setup sirf group
    # ke admin ko karne denge.
    if event.is_group:

        try:
            permissions = await event.client.get_permissions(
                event.chat_id,
                user_id
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

        setup_sessions[user_id] = {
            "step": "channel",
            "group_id": event.chat_id
        }

        await event.reply(
            "⚙️ **SETUP STARTED**\n\n"
            "📢 Ab **channel ka @username ya link** bhejo.\n\n"
            "Example:\n"
            "`@PRMMOD`\n"
            "`https://t.me/PRMMOD`\n\n"
            "⚠️ Bot ko us channel mein pehle add/admin karo."
        )

        return

    await event.reply(
        "⚠️ `/setup` target group ke andar run karo.\n\n"
        "Isse bot automatically us group ko mapping mein save karega."
    )


@bot.on(events.NewMessage(incoming=True))
async def setup_message_handler(event):

    user_id = event.sender_id

    if user_id not in setup_sessions:
        return

    # Commands ignored
    if event.raw_text.startswith("/"):
        return

    session = setup_sessions[user_id]

    # --------------------------------------------------------
    # CHANNEL STEP
    # --------------------------------------------------------

    if session.get("step") == "channel":

        channel_input = event.raw_text.strip()

        channel = await resolve_telegram_entity(
            channel_input
        )

        if not channel:

            await event.reply(
                "❌ **Channel identify nahi hua.**\n\n"
                "Check karo:\n"
                "• Bot channel mein added hai\n"
                "• Bot ko channel access/admin diya hai\n"
                "• Link/username correct hai\n\n"
                "Dobara channel link bhejo."
            )

            return

        ok, data = await test_channel(channel)

        if not ok:

            await event.reply(
                "❌ **Channel access problem**\n\n"
                f"`{str(data)[:500]}`\n\n"
                "Bot ko channel mein add/admin karke "
                "channel link dobara bhejo."
            )

            return

        session["channel_id"] = channel.id
        session["channel_title"] = getattr(
            channel,
            "title",
            "Unknown"
        )

        session["step"] = "confirm"

        await event.reply(
            "📢 **CHANNEL FOUND ✅**\n\n"
            f"Name: **{session['channel_title']}**\n"
            f"ID: `{channel.id}`\n\n"
            "👥 Group mapping already selected hai:\n"
            f"`{session['group_id']}`\n\n"
            "Save karne ke liye `/save` bhejo.\n"
            "Cancel ke liye `/cancel`."
        )

        return


# ============================================================
# /SAVE
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/save$"))
async def setup_save(event):

    user_id = event.sender_id

    session = setup_sessions.get(user_id)

    if not session:
        await event.reply(
            "❌ Koi active setup nahi hai.\n"
            "Target group mein `/setup` run karo."
        )
        return

    if session.get("step") != "confirm":
        await event.reply(
            "❌ Setup incomplete hai."
        )
        return

    config = {
        "group_id": session["group_id"],
        "channel_id": session["channel_id"],
        "channel_title": session.get(
            "channel_title",
            "Unknown"
        ),
        "updated_at": int(time.time())
    }

    if save_user_config(user_id, config):

        setup_sessions.pop(user_id, None)

        await event.reply(
            "✅ **SETUP COMPLETE!**\n\n"
            f"👥 Group: `{config['group_id']}`\n"
            f"📢 Channel: **{config['channel_title']}**\n"
            f"🆔 Channel ID: `{config['channel_id']}`\n\n"
            "🔎 Smart Search: ✅\n"
            "🧠 Fuzzy Search: ✅\n"
            "🔗 Share Button: ✅\n"
            "🔥 Firebase: ✅\n\n"
            "Ab user group mein likhe:\n"
            "`Kuku TV do`\n"
            "`BulletShorts link`\n"
            "`kuku tv please`\n"
            "`Bullet Shorts dedo`"
        )

    else:

        await event.reply(
            "❌ Firebase mein setup save nahi ho saka."
        )


# ============================================================
# /CANCEL
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/cancel$"))
async def cancel_setup(event):

    user_id = event.sender_id

    setup_sessions.pop(user_id, None)

    await event.reply(
        "❌ Setup cancelled."
    )


# ============================================================
# /DIAGNOSTIC
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/(diagnostic|diag)$"))
async def diagnostic_handler(event):

    user_id = event.sender_id

    # Diagnostic sirf setup owner/admin ko
    if event.is_group:

        try:
            permissions = await event.client.get_permissions(
                event.chat_id,
                user_id
            )

            if not permissions.is_admin:
                return

        except Exception:
            return

    result = await diagnostic(
        user_id,
        event.chat_id
    )

    await event.reply(result)


# ============================================================
# /PING
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/ping$"))
async def ping_handler(event):

    uptime = datetime.now() - START_TIME

    total_seconds = int(
        uptime.total_seconds()
    )

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60

    config = get_user_config(
        event.sender_id
    )

    firebase_ok = firebase_get("users") is not None

    await event.reply(
        "🟢 **BOT ONLINE**\n\n"
        f"⏱️ Uptime: **{hours}h {minutes}m**\n"
        f"👥 Public Multi-User: **ON**\n"
        f"🔎 Live Search: **ON**\n"
        f"🧠 Fuzzy Search: **ON**\n"
        f"🔥 Firebase: **{'ON' if firebase_ok else 'OFF'}**\n"
        f"🔗 Share Button: **ON**\n"
        f"🛡️ Diagnostic: **ON**\n\n"
        f"📢 Channel: "
        f"{'Configured ✅' if config.get('channel_id') else 'Not Configured ❌'}\n"
        f"👥 Group: "
        f"{'Configured ✅' if config.get('group_id') else 'Not Configured ❌'}"
    )


# ============================================================
# 🔎 MAIN GROUP SEARCH
# ============================================================

@bot.on(events.NewMessage(incoming=True))
async def group_search_handler(event):

    # Only groups
    if not event.is_group:
        return

    # Ignore bot/system
    if event.sender_id == bot.uid:
        return

    text = event.raw_text or ""

    if not text.strip():
        return

    # Commands ignored
    if text.startswith("/"):
        return

    # --------------------------------------------------------
    # Get configuration
    # --------------------------------------------------------

    # First try current user configuration
    config = get_user_config(
        event.sender_id
    )

    # If user's own config not found,
    # find owner/config associated with this group.
    if config.get("group_id") != event.chat_id:

        all_users = firebase_get("users")

        config = {}

        if isinstance(all_users, dict):

            for uid, data in all_users.items():

                if not isinstance(data, dict):
                    continue

                try:
                    if int(data.get("group_id", 0)) == int(event.chat_id):
                        config = data
                        break
                except Exception:
                    continue

    # --------------------------------------------------------
    # NO MAPPING
    # --------------------------------------------------------

    if not config:

        # Do not spam normal users.
        # Only admins get diagnostic hint.
        try:
            permissions = await event.client.get_permissions(
                event.chat_id,
                event.sender_id
            )

            if permissions.is_admin:

                await event.reply(
                    "⚠️ **Group Mapping Missing**\n\n"
                    "Is group ke liye channel configured nahi hai.\n"
                    "Admin `/setup` run kare."
                )

        except Exception:
            pass

        return

    # Make absolutely sure this is the mapped group
    if int(config.get("group_id", 0)) != int(event.chat_id):
        return

    channel_id = config.get("channel_id")

    if not channel_id:
        return

    # --------------------------------------------------------
    # EXTRACT APP NAME
    # --------------------------------------------------------

    query = extract_app_query(text)

    if not query or len(query) < 2:
        return

    logging.info(
        "SEARCH | Group=%s | User=%s | Query=%s",
        event.chat_id,
        event.sender_id,
        query
    )

    # --------------------------------------------------------
    # RESOLVE CHANNEL
    # --------------------------------------------------------

    try:

        channel = await bot.get_entity(
            int(channel_id)
        )

    except Exception as e:

        logging.error(
            "CHANNEL RESOLVE ERROR: %s",
            e
        )

        # Tell admin, not every user
        try:
            permissions = await event.client.get_permissions(
                event.chat_id,
                event.sender_id
            )

            if permissions.is_admin:

                await event.reply(
                    "❌ **Channel Resolve Error**\n\n"
                    f"`{str(e)[:500]}`\n\n"
                    "Bot ko target channel mein add/admin karo "
                    "aur `/setup` dobara karo."
                )

        except Exception:
            pass

        return

    # --------------------------------------------------------
    # SEARCH
    # --------------------------------------------------------

    try:

        found = await search_channel(
            channel,
            query
        )

    except FloodWaitError as e:

        logging.warning(
            "FloodWait %s seconds",
            e.seconds
        )

        return

    except Exception as e:

        logging.error(
            "SEARCH ERROR: %s",
            e
        )

        return

    # --------------------------------------------------------
    # NOT FOUND
    # --------------------------------------------------------

    if not found:

        # Do not send "not found" on every random message.
        # User requested bot to stay quiet when unavailable.
        return

    # --------------------------------------------------------
    # CREATE POST LINK
    # --------------------------------------------------------

    post_link = make_post_link(
        channel,
        found
    )

    if not post_link:
        return

    channel_title = getattr(
        channel,
        "title",
        "Channel"
    )

    # --------------------------------------------------------
    # SHARE BUTTON
    # --------------------------------------------------------

    share_url = (
        "https://t.me/share/url"
        "?url=" + requests.utils.quote(post_link, safe="")
        "&text=" + requests.utils.quote(
            f"{query.upper()} Download",
            safe=""
        )
    )

    buttons = [
        [
            Button.url(
                "📥 OPEN POST",
                post_link
            ),
            Button.url(
                "↗️ SHARE",
                share_url
            )
        ]
    ]

    # --------------------------------------------------------
    # REPLY
    # --------------------------------------------------------

    reply_text = (
        "👋 **Hello!**\n\n"
        f"📥 **{query.upper()}** mil gaya.\n\n"
        f"📢 Source: **{channel_title}**\n\n"
        "👇 Download/Post open karne ke liye:"
    )

    try:

        await event.reply(
            reply_text,
            buttons=buttons,
            link_preview=False
        )

        logging.info(
            "REPLIED | %s | post=%s",
            query,
            found.id
        )

    except Exception as e:

        logging.error(
            "REPLY ERROR: %s",
            e
        )


# ============================================================
# 👑 OWNER / LEGACY COMMAND PLACEHOLDER
#
# Existing Firebase filter commands can still be used.
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/filter\s+(.+?)\s+(https?://\S+)$"))
async def filter_handler(event):

    if event.sender_id != OWNER_ID:
        return

    app_name = event.pattern_match.group(1).strip().lower()
    link = event.pattern_match.group(2).strip()

    key = safe_key(app_name)

    if firebase_put(
        f"links/{key}",
        link
    ):

        await event.reply(
            "✅ **Firebase Filter Saved**\n\n"
            f"📱 App: **{app_name.upper()}**\n"
            f"🔗 Link: {link}"
        )

    else:

        await event.reply(
            "❌ Firebase save failed."
        )


# ============================================================
# 🗑️ /KILLPOST
# Owner only
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/killpost$"))
async def kill_post(event):

    if event.sender_id != OWNER_ID:
        return

    if not event.is_reply:
        await event.reply(
            "⚠️ Jis post ko delete karna hai usko reply karke `/killpost` bhejo."
        )
        return

    try:

        replied = await event.get_reply_message()

        await event.delete()

        await replied.delete()

    except Exception as e:

        logging.error(
            "Killpost error: %s",
            e
        )


# ============================================================
# 🧹 OPTIONAL ROSE WELCOME CLEANER
# ============================================================

async def delete_later(message, seconds=300):

    await asyncio.sleep(seconds)

    try:
        await message.delete()
    except Exception:
        pass


@bot.on(events.NewMessage(incoming=True))
async def welcome_cleaner(event):

    if not event.is_group:
        return

    try:

        sender = await event.get_sender()

        if not sender:
            return

        if not getattr(sender, "bot", False):
            return

        if sender.id == bot.uid:
            return

        text = (event.raw_text or "").lower()

        welcome_words = (
            "welcome",
            "joined",
            "made it",
            "hey"
        )

        if any(
            word in text
            for word in welcome_words
        ):

            asyncio.create_task(
                delete_later(
                    event,
                    300
                )
            )

    except Exception:
        pass


# ============================================================
# 🔄 SAFE GITHUB RESTART
# ============================================================

async def github_keep_alive():

    while True:

        try:

            elapsed = (
                datetime.now() -
                START_TIME
            )

            if elapsed >= timedelta(
                hours=5,
                minutes=45
            ):

                print(
                    "🔄 GitHub safe restart..."
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
                        f"{repo_name}/actions/workflows/"
                        "run-bot.yml/dispatches"
                    )

                    headers = {
                        "Accept":
                        "application/vnd.github+json",
                        "Authorization":
                        f"Bearer {github_token}"
                    }

                    try:

                        requests.post(
                            url,
                            headers=headers,
                            json={"ref": "main"},
                            timeout=15
                        )

                    except Exception as e:

                        logging.error(
                            "GitHub restart error: %s",
                            e
                        )

                os._exit(0)

        except Exception as e:

            logging.error(
                "Keep alive error: %s",
                e
            )

        await asyncio.sleep(600)


# ============================================================
# 🚀 MAIN
# ============================================================

async def main():

    print("⏳ Starting Telegram Client...")

    await bot.start(
        bot_token=BOT_TOKEN
    )

    me = await bot.get_me()

    print(
        f"✅ Bot Started: @{me.username}"
    )

    print(
        "🟢 PUBLIC MULTI-USER MODE"
    )

    print(
        "🔎 SMART FUZZY SEARCH: ON"
    )

    print(
        "🔗 SHARE BUTTON: ON"
    )

    print(
        "🔥 FIREBASE: ON"
    )

    bot.loop.create_task(
        github_keep_alive()
    )

    await bot.run_until_disconnected()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:

        bot.loop.run_until_complete(
            main()
        )

    except KeyboardInterrupt:

        print("🛑 Bot stopped.")

    except Exception as e:

        print(
            f"❌ FATAL ERROR: {e}"
        )

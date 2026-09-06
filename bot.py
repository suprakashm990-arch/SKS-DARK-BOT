import os
import sys
import re
import asyncio
import logging
from datetime import datetime
from difflib import SequenceMatcher

import requests
from telethon import TelegramClient, events, Button


# ============================================================
# 🚀 PUBLIC TELEGRAM LIVE SEARCH BOT
# ============================================================

print("🚀 PUBLIC LIVE SEARCH BOT STARTING...")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# ============================================================
# 🔐 ENVIRONMENT VARIABLES
# ============================================================

API_ID = os.environ.get("TG_API_ID")
API_HASH = os.environ.get("TG_API_HASH")
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")

# Your owner ID
OWNER_ID = 8587571289

# Firebase
FIREBASE_URL = "https://sks-9865a-default-rtdb.firebaseio.com/"


if not API_ID or not API_HASH or not BOT_TOKEN:
    print("")
    print("❌ REQUIRED GITHUB SECRETS MISSING")
    print("")
    print("TG_API_ID")
    print("TG_API_HASH")
    print("TG_BOT_TOKEN")
    print("")
    sys.exit(1)


API_ID = int(API_ID)


# ============================================================
# 🤖 TELEGRAM CLIENT
# ============================================================

bot = TelegramClient(
    "public_live_search_bot",
    API_ID,
    API_HASH
)

START_TIME = datetime.now()


# ============================================================
# ⚙️ SETUP SESSIONS
# ============================================================

setup_sessions = {}


# ============================================================
# 🔥 FIREBASE
# ============================================================

def firebase_get(path):

    try:
        url = (
            FIREBASE_URL.rstrip("/")
            + "/"
            + path.strip("/")
            + ".json"
        )

        response = requests.get(
            url,
            timeout=15
        )

        if response.status_code == 200:
            return response.json()

        logging.error(
            f"Firebase GET HTTP {response.status_code}"
        )

    except Exception as e:
        logging.error(
            f"Firebase GET ERROR: {type(e).__name__}: {e}"
        )

    return None


def firebase_put(path, data):

    try:
        url = (
            FIREBASE_URL.rstrip("/")
            + "/"
            + path.strip("/")
            + ".json"
        )

        response = requests.put(
            url,
            json=data,
            timeout=15
        )

        if response.status_code in (200, 201):
            return True

        logging.error(
            f"Firebase PUT HTTP {response.status_code}"
        )

    except Exception as e:
        logging.error(
            f"Firebase PUT ERROR: {type(e).__name__}: {e}"
        )

    return False


def firebase_delete(path):

    try:
        url = (
            FIREBASE_URL.rstrip("/")
            + "/"
            + path.strip("/")
            + ".json"
        )

        response = requests.delete(
            url,
            timeout=15
        )

        return response.status_code in (200, 204)

    except Exception as e:
        logging.error(
            f"Firebase DELETE ERROR: {type(e).__name__}: {e}"
        )

    return False


async def firebase_get_async(path):
    return await asyncio.to_thread(
        firebase_get,
        path
    )


async def firebase_put_async(path, data):
    return await asyncio.to_thread(
        firebase_put,
        path,
        data
    )


async def firebase_delete_async(path):
    return await asyncio.to_thread(
        firebase_delete,
        path
    )


# ============================================================
# 🔗 TELEGRAM CHAT RESOLVER
# ============================================================

def extract_private_chat_id(link):

    if not link:
        return None

    match = re.search(
        r"t\.me/c/(\d+)",
        link,
        re.IGNORECASE
    )

    if match:
        return int(
            "-100" + match.group(1)
        )

    return None


async def resolve_chat(value):

    value = value.strip()

    # Numeric Telegram ID
    if re.fullmatch(
        r"-100\d+",
        value
    ):
        try:
            return await bot.get_entity(
                int(value)
            )
        except Exception:
            return None

    # Private t.me/c link
    private_id = extract_private_chat_id(
        value
    )

    if private_id:

        try:
            return await bot.get_entity(
                private_id
            )
        except Exception:
            return None

    # Username / public link
    username = value

    username = re.sub(
        r"^https?://t\.me/",
        "",
        username,
        flags=re.IGNORECASE
    )

    username = username.split("?")[0]
    username = username.strip("/")

    if username.startswith("@"):
        username = username[1:]

    if "/" in username:
        username = username.split("/")[0]

    if not username:
        return None

    try:
        return await bot.get_entity(
            username
        )
    except Exception:
        return None


# ============================================================
# 👤 USER CONFIG
# ============================================================

async def get_user_config(user_id):

    return await firebase_get_async(
        f"users/{user_id}/config"
    )


async def save_user_config(
    user_id,
    config
):

    return await firebase_put_async(
        f"users/{user_id}/config",
        config
    )


# ============================================================
# 🚀 START
# ============================================================

@bot.on(events.NewMessage(
    pattern=r"^/start$"
))
async def start_handler(event):

    user_id = event.sender_id

    if not user_id:
        return

    config = await get_user_config(
        user_id
    )

    owner_message = ""

    if user_id == OWNER_ID:
        owner_message = (
            "👑 **OWNER ACCOUNT DETECTED**\n\n"
        )

    if config and config.get("active"):

        await event.reply(
            owner_message +
            "🤖 **PUBLIC LIVE SEARCH BOT**\n\n"
            "Your setup is already active.\n\n"
            "📢 Channel:\n"
            f"`{config.get('channel_link', '-')}`\n\n"
            "👥 Group:\n"
            f"`{config.get('group_link', '-')}`\n\n"
            "🟢 Live Search: **ON**\n"
            "🧠 Fuzzy Search: **ON**\n"
            "🔥 Firebase: **ON**\n"
            "📤 Share Button: **ON**\n\n"
            "⚙️ Change setup:\n"
            "`/setup`\n\n"
            "📋 View setup:\n"
            "`/mysetup`\n\n"
            "🗑️ Remove setup:\n"
            "`/reset`\n\n"
            "❤️ Status:\n"
            "`/ping`"
        )

        return

    setup_sessions[user_id] = {
        "step": "channel"
    }

    await event.reply(
        owner_message +
        "👋 **WELCOME!**\n\n"
        "This is a Public Live Search Bot.\n\n"
        "Sabse pehle apne **Telegram Channel ka link** bhejo.\n\n"
        "Example:\n"
        "`https://t.me/YourChannel`\n\n"
        "Ya:\n"
        "`@YourChannel`\n\n"
        "⚠️ Bot ko Channel mein access hona chahiye.\n\n"
        "❌ Cancel:\n"
        "`/cancel`"
    )


# ============================================================
# ⚙️ SETUP
# ============================================================

@bot.on(events.NewMessage(
    pattern=r"^/setup$"
))
async def setup_handler(event):

    user_id = event.sender_id

    setup_sessions[user_id] = {
        "step": "channel"
    }

    await event.reply(
        "⚙️ **NEW SETUP**\n\n"
        "📍 Step 1/2\n\n"
        "📢 Apne **Channel ka link** bhejo.\n\n"
        "Example:\n"
        "`https://t.me/YourChannel`\n\n"
        "Ya:\n"
        "`@YourChannel`\n\n"
        "❌ Cancel: `/cancel`"
    )


# ============================================================
# ❌ CANCEL
# ============================================================

@bot.on(events.NewMessage(
    pattern=r"^/cancel$"
))
async def cancel_handler(event):

    user_id = event.sender_id

    setup_sessions.pop(
        user_id,
        None
    )

    await event.reply(
        "❌ **SETUP CANCELLED**\n\n"
        "Dobara setup ke liye:\n"
        "`/setup`"
    )


# ============================================================
# 📋 MY SETUP
# ============================================================

@bot.on(events.NewMessage(
    pattern=r"^/mysetup$"
))
async def mysetup_handler(event):

    user_id = event.sender_id

    config = await get_user_config(
        user_id
    )

    if not config or not config.get("active"):

        await event.reply(
            "❌ Aapka setup active nahi hai.\n\n"
            "Start:\n"
            "`/setup`"
        )

        return

    await event.reply(
        "📋 **YOUR SETUP**\n\n"
        "📢 Channel:\n"
        f"`{config.get('channel_link', '-')}`\n\n"
        "👥 Group:\n"
        f"`{config.get('group_link', '-')}`\n\n"
        "🆔 Channel ID:\n"
        f"`{config.get('channel_id', '-')}`\n\n"
        "🆔 Group ID:\n"
        f"`{config.get('group_id', '-')}`\n\n"
        "🟢 Status: **ACTIVE**"
    )


# ============================================================
# 🗑️ RESET
# ============================================================

@bot.on(events.NewMessage(
    pattern=r"^/reset$"
))
async def reset_handler(event):

    user_id = event.sender_id

    config = await get_user_config(
        user_id
    )

    if not config:

        await event.reply(
            "❌ Koi active setup nahi mila."
        )

        return

    group_id = config.get(
        "group_id"
    )

    if group_id:

        await firebase_delete_async(
            f"groups/{group_id}"
        )

    await firebase_delete_async(
        f"users/{user_id}/config"
    )

    setup_sessions.pop(
        user_id,
        None
    )

    await event.reply(
        "🗑️ **SETUP REMOVED**\n\n"
        "Channel + Group mapping "
        "Firebase se remove ho gaya.\n\n"
        "Naya setup:\n"
        "`/setup`"
    )


# ============================================================
# 🧩 SETUP MESSAGE PROCESSOR
# ============================================================

@bot.on(events.NewMessage(
    incoming=True
))
async def setup_message_processor(event):

    if not event.is_private:
        return

    user_id = event.sender_id

    if not user_id:
        return

    text = (
        event.raw_text or ""
    ).strip()

    if not text:
        return

    if text.startswith("/"):
        return

    if user_id not in setup_sessions:
        return

    session = setup_sessions[user_id]

    # --------------------------------------------------------
    # CHANNEL STEP
    # --------------------------------------------------------

    if session["step"] == "channel":

        status = await event.reply(
            "⏳ **CHANNEL VERIFY KAR RAHA HOON...**"
        )

        channel = await resolve_chat(
            text
        )

        if not channel:

            await status.edit(
                "❌ **CHANNEL NOT FOUND**\n\n"
                "Link/username check karo.\n\n"
                "Example:\n"
                "`https://t.me/YourChannel`"
            )

            return

        # Must be a broadcast channel
        if not getattr(
            channel,
            "broadcast",
            False
        ):

            await status.edit(
                "❌ **INVALID CHANNEL**\n\n"
                "Ye Telegram Channel nahi lag raha.\n"
                "Actual Channel ka link bhejo."
            )

            return

        channel_id = channel.id

        session["step"] = "group"
        session["channel_id"] = channel_id
        session["channel_link"] = text

        title = getattr(
            channel,
            "title",
            "Channel"
        )

        await status.edit(
            "✅ **CHANNEL CONNECTED**\n\n"
            f"📢 {title}\n"
            f"🆔 `{channel_id}`\n\n"
            "📍 Step 2/2\n\n"
            "👥 Ab **Group ka link** bhejo.\n\n"
            "Example:\n"
            "`https://t.me/YourGroup`\n\n"
            "Ya:\n"
            "`@YourGroup`\n\n"
            "⚠️ Bot Group mein added hona chahiye."
        )

        return

    # --------------------------------------------------------
    # GROUP STEP
    # --------------------------------------------------------

    if session["step"] == "group":

        status = await event.reply(
            "⏳ **GROUP VERIFY KAR RAHA HOON...**"
        )

        group = await resolve_chat(
            text
        )

        if not group:

            await status.edit(
                "❌ **GROUP NOT FOUND**\n\n"
                "Bot ko Group mein add karo "
                "aur Group link dobara bhejo."
            )

            return

        # Reject broadcast channel
        if getattr(
            group,
            "broadcast",
            False
        ):

            await status.edit(
                "❌ **THIS IS A CHANNEL**\n\n"
                "Please Group ka link bhejo."
            )

            return

        group_id = group.id
        channel_id = session["channel_id"]

        # ----------------------------------------------------
        # CHECK GROUP ALREADY CONFIGURED
        # ----------------------------------------------------

        existing_owner = await firebase_get_async(
            f"groups/{group_id}"
        )

        if (
            existing_owner is not None
            and str(existing_owner)
            != str(user_id)
        ):

            await status.edit(
                "❌ **GROUP ALREADY CONFIGURED**\n\n"
                "Ye Group kisi aur setup ke saath "
                "connected hai."
            )

            return

        # ----------------------------------------------------
        # SAVE CONFIG
        # ----------------------------------------------------

        config = {

            "active": True,

            "user_id": user_id,

            "channel_id": channel_id,
            "channel_link": session[
                "channel_link"
            ],

            "group_id": group_id,
            "group_link": text,

            "created_at":
                datetime.utcnow().isoformat()

        }

        saved = await save_user_config(
            user_id,
            config
        )

        if not saved:

            await status.edit(
                "❌ **FIREBASE SAVE FAILED**\n\n"
                "Configuration save nahi hui."
            )

            return

        # Group -> owner mapping
        mapping_saved = await firebase_put_async(
            f"groups/{group_id}",
            str(user_id)
        )

        if not mapping_saved:

            await status.edit(
                "⚠️ **PARTIAL SETUP ERROR**\n\n"
                "User config save ho gaya, "
                "lekin Group mapping Firebase mein "
                "save nahi hui.\n\n"
                "Please `/setup` dobara karo."
            )

            return

        setup_sessions.pop(
            user_id,
            None
        )

        await status.edit(
            "🎉 **SETUP COMPLETE!**\n\n"
            f"📢 Channel:\n"
            f"`{session['channel_link']}`\n\n"
            f"👥 Group:\n"
            f"`{text}`\n\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🟢 Live Search: **ON**\n"
            "🧠 Fuzzy Search: **ON**\n"
            "🔥 Firebase: **ON**\n"
            "📤 Share Button: **ON**\n\n"
            "Ab Group mein user likh sakta hai:\n\n"
            "`Kuku TV do`\n"
            "`KukuTV link`\n"
            "`Kuku TV chahiye`\n"
            "`BulletShorts do`\n"
            "`bulletshrt link`\n\n"
            "Bot configured Channel ke posts "
            "search karega."
        )


# ============================================================
# 🧹 TEXT NORMALIZATION
# ============================================================

def normalize_text(text):

    if not text:
        return ""

    text = text.lower()

    # Separators -> spaces
    text = re.sub(
        r"[_\-./|]+",
        " ",
        text
    )

    # Keep unicode letters/numbers
    text = re.sub(
        r"[^\w\s]",
        " ",
        text,
        flags=re.UNICODE
    )

    # Multiple spaces
    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def compact_text(text):

    return re.sub(
        r"[^a-z0-9]",
        "",
        normalize_text(text)
    )


# ============================================================
# 🧠 REQUEST STOP WORDS
# ============================================================

STOP_WORDS = {
    "do",
    "de",
    "dedo",
    "dena",
    "dijiye",
    "bhejo",
    "bhej",
    "send",
    "share",
    "link",
    "links",
    "chahiye",
    "chaahiye",
    "mujhe",
    "please",
    "plz",
    "bhai",
    "bro",
    "sir",
    "hello",
    "hi",
    "hey",
    "hai",
    "ho",
    "kya",
    "ka",
    "ki",
    "ke",
    "ko",
    "mera",
    "meri",
    "mujhe",
    "apna",
    "apni",
    "download",
    "downloading",
    "apk",
    "app",
    "mod",
    "premium",
    "version",
    "latest",
    "wale",
    "wala",
    "wali",
    "se",
    "me",
    "mein",
    "par",
    "pe",
    "to",
    "aur",
    "bhi",
    "ek",
    "milega",
    "milega",
}


# ============================================================
# 🔎 EXTRACT SEARCH CANDIDATES
# ============================================================

def extract_candidates(text):

    normalized = normalize_text(
        text
    )

    if not normalized:
        return []

    words = normalized.split()

    useful_words = [
        word
        for word in words
        if word not in STOP_WORDS
        and len(word) >= 2
    ]

    candidates = []

    # Full useful phrase
    if useful_words:

        candidates.append(
            " ".join(useful_words)
        )

    # 1-5 word combinations
    max_window = min(
        5,
        len(useful_words)
    )

    for size in range(
        max_window,
        0,
        -1
    ):

        for i in range(
            0,
            len(useful_words) - size + 1
        ):

            phrase = " ".join(
                useful_words[
                    i:i + size
                ]
            )

            if phrase not in candidates:

                candidates.append(
                    phrase
                )

    # Compact variants
    compact_candidates = []

    for candidate in candidates:

        compact = compact_text(
            candidate
        )

        if (
            compact
            and compact not in compact_candidates
        ):

            compact_candidates.append(
                compact
            )

    return candidates + compact_candidates


# ============================================================
# 🧠 FUZZY SIMILARITY
# ============================================================

def similarity(a, b):

    a = compact_text(a)
    b = compact_text(b)

    if not a or not b:
        return 0.0

    if a == b:
        return 1.0

    # One inside another
    if a in b or b in a:

        shorter = min(
            len(a),
            len(b)
        )

        longer = max(
            len(a),
            len(b)
        )

        if shorter >= 4:

            return (
                0.90
                + (
                    shorter / longer
                ) * 0.08
            )

    return SequenceMatcher(
        None,
        a,
        b
    ).ratio()


# ============================================================
# 🏆 POST SCORE
# ============================================================

def score_post(
    post_text,
    candidates
):

    if not post_text:
        return 0.0

    normalized_post = normalize_text(
        post_text
    )

    compact_post = compact_text(
        post_text
    )

    if not normalized_post:
        return 0.0

    best = 0.0

    # --------------------------------------------------------
    # EXACT MATCH
    # --------------------------------------------------------

    for candidate in candidates:

        candidate_normal = normalize_text(
            candidate
        )

        candidate_compact = compact_text(
            candidate
        )

        if not candidate_compact:
            continue

        if candidate_normal in normalized_post:

            best = max(
                best,
                0.99
            )

        elif candidate_compact in compact_post:

            best = max(
                best,
                0.97
            )

    # --------------------------------------------------------
    # FUZZY MATCH
    # --------------------------------------------------------

    post_words = normalized_post.split()

    for candidate in candidates:

        candidate_words = (
            normalize_text(candidate)
            .split()
        )

        if not candidate_words:
            continue

        word_scores = []

        for cw in candidate_words:

            if len(cw) < 3:
                continue

            best_word = 0.0

            for pw in post_words:

                if len(pw) < 3:
                    continue

                current = similarity(
                    cw,
                    pw
                )

                if current > best_word:
                    best_word = current

            if best_word:
                word_scores.append(
                    best_word
                )

        if word_scores:

            avg_score = (
                sum(word_scores)
                / len(word_scores)
            )

            if avg_score >= 0.80:

                fuzzy_score = (
                    0.70
                    + avg_score * 0.27
                )

                best = max(
                    best,
                    fuzzy_score
                )

    return best


# ============================================================
# 🔍 SEARCH CHANNEL
# ============================================================

async def search_channel(
    channel_id,
    user_text
):

    candidates = extract_candidates(
        user_text
    )

    if not candidates:

        return {
            "success": False,
            "message": None,
            "score": 0.0,
            "scanned": 0,
            "error":
                "User request se app name "
                "extract nahi hua."
        }

    logging.info(
        f"🔎 Candidates: {candidates}"
    )

    best_message = None
    best_score = 0.0
    scanned = 0

    # ========================================================
    # PHASE 1 - TELEGRAM SEARCH
    # ========================================================

    try:

        queries = []

        for candidate in candidates:

            candidate_clean = (
                candidate.strip()
            )

            if len(
                compact_text(candidate_clean)
            ) < 3:
                continue

            if candidate_clean not in queries:

                queries.append(
                    candidate_clean
                )

        # Avoid excessive API calls
        queries = queries[:8]

        for query in queries:

            try:

                async for msg in bot.iter_messages(
                    channel_id,
                    search=query,
                    limit=50
                ):

                    scanned += 1

                    if not msg:
                        continue

                    post_text = (
                        msg.raw_text or ""
                    )

                    if not post_text:
                        continue

                    score = score_post(
                        post_text,
                        candidates
                    )

                    if score > best_score:

                        best_score = score
                        best_message = msg

                    if best_score >= 0.99:
                        break

                if best_score >= 0.99:
                    break

            except Exception as e:

                logging.error(
                    f"Telegram search error: "
                    f"{type(e).__name__}: {e}"
                )

                # Don't immediately fail.
                # Fallback scan will run.
                continue

    except Exception as e:

        logging.error(
            f"Search phase error: "
            f"{type(e).__name__}: {e}"
        )


    # ========================================================
    # PHASE 2 - RECENT POST SCAN
    # ========================================================

    if best_score < 0.82:

        try:

            async for msg in bot.iter_messages(
                channel_id,
                limit=3000
            ):

                scanned += 1

                if not msg:
                    continue

                post_text = (
                    msg.raw_text or ""
                )

                if not post_text:
                    continue

                score = score_post(
                    post_text,
                    candidates
                )

                if score > best_score:

                    best_score = score
                    best_message = msg

                if best_score >= 0.99:
                    break

        except Exception as e:

            return {
                "success": False,
                "message": None,
                "score": best_score,
                "scanned": scanned,
                "error":
                    f"{type(e).__name__}: {e}"
            }


    # ========================================================
    # FINAL RESULT
    # ========================================================

    if (
        best_message
        and best_score >= 0.82
    ):

        logging.info(
            f"✅ MATCH FOUND | "
            f"score={best_score:.2f} | "
            f"post={best_message.id}"
        )

        return {
            "success": True,
            "message": best_message,
            "score": best_score,
            "scanned": scanned,
            "error": None
        }


    return {
        "success": False,
        "message": None,
        "score": best_score,
        "scanned": scanned,
        "error":
            "Reliable matching post nahi mila."
    }


# ============================================================
# 📢 CHANNEL ACCESS DIAGNOSTIC
# ============================================================

async def check_channel_access(
    channel_id
):

    try:

        entity = await bot.get_entity(
            channel_id
        )

        title = getattr(
            entity,
            "title",
            "Unknown Channel"
        )

        # Try reading latest post
        messages = await bot.get_messages(
            entity,
            limit=1
        )

        if messages is None:

            return {
                "success": False,
                "title": title,
                "error":
                    "Channel mila, lekin messages read nahi hue."
            }

        return {
            "success": True,
            "title": title,
            "error": None
        }

    except Exception as e:

        return {
            "success": False,
            "title": "Unknown",
            "error":
                f"{type(e).__name__}: {e}"
        }


# ============================================================
# 🔗 ORIGINAL POST LINK
# ============================================================

async def get_post_link(
    channel_id,
    message
):

    try:

        channel = await bot.get_entity(
            channel_id
        )

        username = getattr(
            channel,
            "username",
            None
        )

        # Public channel
        if username:

            return (
                f"https://t.me/"
                f"{username}/"
                f"{message.id}"
            )

    except Exception:
        pass

    # Private channel
    clean_id = str(
        channel_id
    ).replace(
        "-100",
        ""
    )

    return (
        f"https://t.me/c/"
        f"{clean_id}/"
        f"{message.id}"
    )


# ============================================================
# 📤 TELEGRAM SHARE LINK
# ============================================================

def make_share_url(
    post_link
):

    return (
        "https://t.me/share/url"
        "?url="
        + post_link
    )


# ============================================================
# 👥 GROUP LIVE SEARCH
# ============================================================

@bot.on(events.NewMessage(
    incoming=True
))
async def handle_group_search(event):

    # Only groups
    if not event.is_group:
        return

    # Ignore bot's own messages
    if event.out:
        return

    text = (
        event.raw_text or ""
    ).strip()

    if not text:
        return

    # Commands handled separately
    if text.startswith("/"):
        return

    group_id = event.chat_id

    if not group_id:
        return


    # ========================================================
    # 1️⃣ GROUP -> OWNER MAPPING
    # ========================================================

    try:

        owner_id = await firebase_get_async(
            f"groups/{group_id}"
        )

    except Exception as e:

        await event.reply(
            "⚠️ **BOT DIAGNOSTIC**\n\n"
            "👥 Group Mapping: ❌\n"
            "🔥 Firebase: ❌\n"
            "📢 Channel: ❌\n"
            "🔎 Search: ❌\n\n"
            "📝 Error:\n"
            f"`{type(e).__name__}: {e}`"
        )

        return


    if not owner_id:

        await event.reply(
            "⚠️ **BOT DIAGNOSTIC**\n\n"
            "👥 Group Mapping: ❌\n"
            "🔥 Firebase: ✅\n"
            "📢 Channel: ❌\n"
            "🔎 Search: ❌\n\n"
            "📝 Problem:\n"
            f"`groups/{group_id}` "
            "Firebase mein nahi mila.\n\n"
            "💡 Is Group ka `/setup` dobara karo."
        )

        return


    # ========================================================
    # 2️⃣ USER CONFIG
    # ========================================================

    try:

        owner_id = int(
            owner_id
        )

        config = await get_user_config(
            owner_id
        )

    except Exception as e:

        await event.reply(
            "⚠️ **BOT DIAGNOSTIC**\n\n"
            "👥 Group Mapping: ✅\n"
            "🔥 Firebase: ❌\n"
            "📢 Channel: ❌\n"
            "🔎 Search: ❌\n\n"
            "📝 Error:\n"
            f"`{type(e).__name__}: {e}`"
        )

        return


    if not config:

        await event.reply(
            "⚠️ **BOT DIAGNOSTIC**\n\n"
            "👥 Group Mapping: ✅\n"
            "🔥 Firebase: ⚠️\n"
            "📢 Channel: ❌\n"
            "🔎 Search: ❌\n\n"
            "📝 Problem:\n"
            f"`users/{owner_id}/config` "
            "nahi mila.\n\n"
            "💡 `/setup` dobara karo."
        )

        return


    # ========================================================
    # 3️⃣ ACTIVE CHECK
    # ========================================================

    if not config.get("active"):

        await event.reply(
            "⚠️ **BOT DIAGNOSTIC**\n\n"
            "👥 Group Mapping: ✅\n"
            "🔥 Firebase: ✅\n"
            "📢 Channel: ❌\n"
            "🔎 Search: ❌\n\n"
            "📝 Problem:\n"
            "`active` Firebase mein false hai.\n\n"
            "💡 `/setup` dobara karo."
        )

        return


    # ========================================================
    # 4️⃣ GROUP ID CHECK
    # ========================================================

    saved_group_id = config.get(
        "group_id"
    )

    if str(saved_group_id) != str(group_id):

        await event.reply(
            "⚠️ **BOT DIAGNOSTIC**\n\n"
            "👥 Group Mapping: ❌\n"
            "🔥 Firebase: ✅\n"
            "📢 Channel: ❌\n"
            "🔎 Search: ❌\n\n"
            "📝 Problem:\n"
            f"Current Group ID:\n"
            f"`{group_id}`\n\n"
            f"Saved Group ID:\n"
            f"`{saved_group_id}`"
        )

        return


    # ========================================================
    # 5️⃣ CHANNEL ID
    # ========================================================

    channel_id = config.get(
        "channel_id"
    )

    if not channel_id:

        await event.reply(
            "⚠️ **BOT DIAGNOSTIC**\n\n"
            "👥 Group Mapping: ✅\n"
            "🔥 Firebase: ✅\n"
            "📢 Channel ID: ❌\n"
            "🔎 Search: ❌\n\n"
            "📝 Problem:\n"
            "`channel_id` Firebase config mein missing hai."
        )

        return


    # ========================================================
    # 6️⃣ CHANNEL ACCESS
    # ========================================================

    channel_status = await check_channel_access(
        channel_id
    )

    if not channel_status["success"]:

        await event.reply(
            "⚠️ **BOT DIAGNOSTIC**\n\n"
            "👥 Group Mapping: ✅\n"
            "🔥 Firebase: ✅\n"
            "📢 Channel Access: ❌\n"
            "🔎 Search: ❌\n\n"
            f"📝 Channel:\n"
            f"`{config.get('channel_link', '-')}`\n\n"
            "❌ Error:\n"
            f"`{channel_status['error']}`\n\n"
            "💡 Bot ko Channel mein add/admin "
            "karke dobara test karo."
        )

        return


    channel_title = channel_status[
        "title"
    ]


    # ========================================================
    # 7️⃣ SEARCH
    # ========================================================

    logging.info(
        "================================================"
    )

    logging.info(
        f"🔎 USER REQUEST: {text}"
    )

    logging.info(
        f"👥 GROUP: {group_id}"
    )

    logging.info(
        f"📢 CHANNEL: {channel_id}"
    )

    result = await search_channel(
        channel_id,
        text
    )


    # ========================================================
    # 8️⃣ SEARCH FAILED
    # ========================================================

    if not result["success"]:

        await event.reply(
            "🔎 **SEARCH DIAGNOSTIC**\n\n"
            "👥 Group Mapping: ✅\n"
            "🔥 Firebase: ✅\n"
            f"📢 Channel: ✅ {channel_title}\n"
            "🔐 Channel Access: ✅\n"
            "🧠 Fuzzy Search: ✅\n\n"
            f"📝 Request:\n"
            f"`{text}`\n\n"
            f"📚 Posts Checked:\n"
            f"`{result['scanned']}`\n\n"
            f"🎯 Best Match Score:\n"
            f"`{result['score']:.2f}`\n\n"
            "❌ **Reason:**\n"
            f"`{str(result['error'])[:800]}`\n\n"
            "💡 Agar post Channel mein hai, "
            "to uske caption/text mein app name hona chahiye."
        )

        return


    # ========================================================
    # 9️⃣ POST FOUND
    # ========================================================

    found_message = result[
        "message"
    ]


    # ========================================================
    # 🔗 CREATE POST LINK
    # ========================================================

    try:

        post_link = await get_post_link(
            channel_id,
            found_message
        )

    except Exception as e:

        await event.reply(
            "⚠️ **BOT DIAGNOSTIC**\n\n"
            "👥 Group Mapping: ✅\n"
            "🔥 Firebase: ✅\n"
            "📢 Channel Access: ✅\n"
            "🔎 Search: ✅\n"
            "🔗 Post Link: ❌\n\n"
            "📝 Error:\n"
            f"`{type(e).__name__}: {e}`"
        )

        return


    # ========================================================
    # 🔤 DISPLAY NAME
    # ========================================================

    candidates = extract_candidates(
        text
    )

    if candidates:

        display_name = (
            candidates[0].title()
        )

    else:

        display_name = text.title()


    # ========================================================
    # 📤 SUCCESS REPLY
    # ========================================================

    reply_text = (
        "👋 **Hello!**\n\n"
        f"📥 **{display_name}** "
        "channel par available hai.\n\n"
        f"📢 Channel: **{channel_title}**\n"
        f"🎯 Match: `{result['score']:.2f}`\n\n"
        "👇 **Original Post:**\n"
        f"{post_link}\n\n"
        "📤 Neeche Share Post button se "
        "post share kar sakte ho."
    )


    buttons = [

        [
            Button.url(
                "📤 Share Post",
                make_share_url(
                    post_link
                )
            )
        ],

        [
            Button.url(
                "🔗 Open Original Post",
                post_link
            )
        ]

    ]


    try:

        await event.reply(
            reply_text,
            buttons=buttons,
            link_preview=False
        )

        logging.info(
            f"✅ REPLY SENT | "
            f"{display_name} | "
            f"{post_link}"
        )

    except Exception as e:

        await event.reply(
            "⚠️ **BOT DIAGNOSTIC**\n\n"
            "👥 Group Mapping: ✅\n"
            "🔥 Firebase: ✅\n"
            "📢 Channel Access: ✅\n"
            "🔎 Search: ✅\n"
            "🔗 Post Link: ✅\n"
            "💬 Group Reply: ❌\n\n"
            "📝 Error:\n"
            f"`{type(e).__name__}: {e}`"
        )


# ============================================================
# ❤️ PING
# ============================================================

@bot.on(events.NewMessage(
    pattern=r"^/ping$"
))
async def ping_handler(event):

    elapsed = (
        datetime.now()
        - START_TIME
    )

    total_seconds = int(
        elapsed.total_seconds()
    )

    hours = (
        total_seconds // 3600
    )

    minutes = (
        total_seconds % 3600
    ) // 60

    await event.reply(
        "🟢 **BOT ONLINE**\n\n"
        f"⏱ Uptime: `{hours}h {minutes}m`\n\n"
        "👥 Public Multi-User: **ON**\n"
        "🔎 Live Search: **ON**\n"
        "🧠 Fuzzy Search: **ON**\n"
        "🔥 Firebase: **ON**\n"
        "📤 Share Button: **ON**\n"
        "🧪 Diagnostic System: **ON**"
    )


# ============================================================
# 📖 HELP
# ============================================================

@bot.on(events.NewMessage(
    pattern=r"^/help$"
))
async def help_handler(event):

    await event.reply(
        "🤖 **PUBLIC LIVE SEARCH BOT**\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🚀 `/start`\n"
        "⚙️ `/setup`\n"
        "📋 `/mysetup`\n"
        "🗑️ `/reset`\n"
        "❌ `/cancel`\n"
        "❤️ `/ping`\n"
        "📖 `/help`\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🔎 **SEARCH EXAMPLES**\n\n"
        "`Kuku TV do`\n"
        "`Kuku TV link`\n"
        "`KukuTV chahiye`\n"
        "`bhai Kuku TV dedo`\n"
        "`BulletShorts do`\n"
        "`BulletShort link`\n"
        "`bulletshrt chahiye`\n\n"
        "Bot uppercase/lowercase, "
        "space difference aur chhoti "
        "spelling mistakes ko tolerate karega.\n\n"
        "Post na mile to diagnostic "
        "message ke saath reason batayega."
    )


# ============================================================
# 🚀 MAIN
# ============================================================

async def main():

    print("")
    print("⏳ Starting Telegram Client...")
    print("")

    await bot.start(
        bot_token=BOT_TOKEN
    )

    me = await bot.get_me()

    print("==========================================")
    print(f"✅ BOT: @{me.username}")
    print(f"👑 OWNER ID: {OWNER_ID}")
    print("🟢 PUBLIC MULTI-USER: ON")
    print("🔎 LIVE SEARCH: ON")
    print("🧠 FUZZY SEARCH: ON")
    print("🔥 FIREBASE: ON")
    print("📤 SHARE BUTTON: ON")
    print("🧪 DIAGNOSTIC: ON")
    print("==========================================")
    print("")

    await bot.run_until_disconnected()


# ============================================================
# 🏁 RUN
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
            f"❌ FATAL ERROR: "
            f"{type(e).__name__}: {e}"
        )

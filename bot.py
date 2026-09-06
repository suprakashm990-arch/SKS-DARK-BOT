import os
import sys
import re
import asyncio
import logging
from datetime import datetime
from difflib import SequenceMatcher

import requests
from telethon import TelegramClient, events, Button


# =========================================================
# 🚀 PUBLIC MULTI-USER LIVE SEARCH BOT
# =========================================================

print("🚀 Public Live Search Bot Starting...")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# =========================================================
# 🔐 TELEGRAM SECRETS
# =========================================================

API_ID = os.environ.get("TG_API_ID")
API_HASH = os.environ.get("TG_API_HASH")
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")


# =========================================================
# 👑 OWNER
# =========================================================

OWNER_ID = 8587571289


# =========================================================
# 🔥 FIREBASE
# =========================================================

FIREBASE_URL = "https://sks-9865a-default-rtdb.firebaseio.com/"


if not API_ID or not API_HASH or not BOT_TOKEN:
    print("\n❌ ERROR: GitHub Secrets missing!")
    print("TG_API_ID")
    print("TG_API_HASH")
    print("TG_BOT_TOKEN")
    sys.exit(1)


API_ID = int(API_ID)

bot = TelegramClient(
    "public_live_search_bot",
    API_ID,
    API_HASH
)

START_TIME = datetime.now()


# =========================================================
# ⚙️ USER SETUP SESSIONS
# =========================================================

setup_sessions = {}


# =========================================================
# 🔥 FIREBASE FUNCTIONS
# =========================================================

def firebase_get(path):

    try:

        url = (
            f"{FIREBASE_URL.rstrip('/')}/"
            f"{path}.json"
        )

        response = requests.get(
            url,
            timeout=15
        )

        if response.status_code == 200:
            return response.json()

    except Exception as e:

        logging.error(
            f"Firebase GET Error: {e}"
        )

    return None


def firebase_put(path, data):

    try:

        url = (
            f"{FIREBASE_URL.rstrip('/')}/"
            f"{path}.json"
        )

        response = requests.put(
            url,
            json=data,
            timeout=15
        )

        return response.status_code in (200, 201)

    except Exception as e:

        logging.error(
            f"Firebase PUT Error: {e}"
        )

    return False


def firebase_delete(path):

    try:

        url = (
            f"{FIREBASE_URL.rstrip('/')}/"
            f"{path}.json"
        )

        response = requests.delete(
            url,
            timeout=15
        )

        return response.status_code in (200, 204)

    except Exception as e:

        logging.error(
            f"Firebase DELETE Error: {e}"
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


# =========================================================
# 🔗 TELEGRAM LINK / ENTITY RESOLVER
# =========================================================

def extract_private_chat_id(link):

    match = re.search(
        r"t\.me/c/(\d+)(?:/\d+)?",
        link,
        re.IGNORECASE
    )

    if match:

        internal_id = match.group(1)

        return int(
            "-100" + internal_id
        )

    return None


async def resolve_chat(value):

    value = value.strip()

    # Telegram numeric ID
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

    # Private channel/group link
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


# =========================================================
# 👤 USER CONFIG
# =========================================================

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


# =========================================================
# 🚀 START
# =========================================================

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

    owner_text = ""

    if user_id == OWNER_ID:

        owner_text = (
            "👑 **Owner detected!**\n\n"
        )

    if config and config.get("active"):

        await event.reply(
            owner_text +
            "🤖 **PUBLIC LIVE SEARCH BOT**\n\n"
            "✅ Aapka setup already active hai.\n\n"
            "📢 Channel:\n"
            f"`{config.get('channel_link', '-')}`\n\n"
            "👥 Group:\n"
            f"`{config.get('group_link', '-')}`\n\n"
            "🟢 Live Search: **ACTIVE**\n\n"
            "⚙️ Setup change:\n"
            "`/setup`\n\n"
            "📋 Setup dekhein:\n"
            "`/mysetup`\n\n"
            "🗑️ Setup remove:\n"
            "`/reset`\n\n"
            "❤️ Status:\n"
            "`/ping`"
        )

        return

    setup_sessions[user_id] = {
        "step": "channel"
    }

    await event.reply(
        owner_text +
        "👋 **Welcome!**\n\n"
        "Ye Public Live Search Bot hai.\n\n"
        "Sabse pehle apne **Telegram Channel ka link** bhejo.\n\n"
        "Example:\n"
        "`https://t.me/YourChannel`\n\n"
        "Ya:\n"
        "`@YourChannel`\n\n"
        "⚠️ Bot ko Channel ka access hona chahiye.\n\n"
        "❌ Cancel:\n"
        "`/cancel`"
    )


# =========================================================
# ⚙️ SETUP
# =========================================================

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
        "Step 1/2\n\n"
        "📢 Apne **Channel ka link** bhejo.\n\n"
        "Example:\n"
        "`https://t.me/YourChannel`\n\n"
        "Ya:\n"
        "`@YourChannel`\n\n"
        "❌ Cancel: `/cancel`"
    )


# =========================================================
# ❌ CANCEL
# =========================================================

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
        "❌ **Setup cancelled.**\n\n"
        "Dobara setup ke liye:\n"
        "`/setup`"
    )


# =========================================================
# 📋 MYSETUP
# =========================================================

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
            "Setup start karein:\n"
            "`/setup`"
        )

        return

    await event.reply(
        "📋 **YOUR SETUP**\n\n"
        f"📢 Channel:\n"
        f"`{config.get('channel_link', '-')}`\n\n"
        f"👥 Group:\n"
        f"`{config.get('group_link', '-')}`\n\n"
        f"🆔 Channel ID:\n"
        f"`{config.get('channel_id', '-')}`\n\n"
        f"🆔 Group ID:\n"
        f"`{config.get('group_id', '-')}`\n\n"
        "🟢 Status: **ACTIVE**"
    )


# =========================================================
# 🗑️ RESET
# =========================================================

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
            "❌ Aapka koi active setup nahi hai."
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
        "Aapka Channel + Group mapping "
        "Firebase se remove ho gaya.\n\n"
        "Naya setup:\n"
        "`/setup`"
    )


# =========================================================
# 🧩 PRIVATE SETUP PROCESSOR
# =========================================================

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

    # =====================================================
    # STEP 1 - CHANNEL
    # =====================================================

    if session["step"] == "channel":

        status = await event.reply(
            "⏳ **Channel verify kar raha hoon...**"
        )

        channel = await resolve_chat(
            text
        )

        if not channel:

            await status.edit(
                "❌ **Channel nahi mila.**\n\n"
                "Link/username check karo aur "
                "dobara bhejo."
            )

            return

        # Must be broadcast channel
        if not getattr(
            channel,
            "broadcast",
            False
        ):

            await status.edit(
                "❌ Ye Telegram Channel nahi lag raha.\n\n"
                "Please actual Channel ka link bhejo."
            )

            return

        channel_id = channel.id

        session["step"] = "group"
        session["channel_id"] = channel_id
        session["channel_link"] = text

        await status.edit(
            "✅ **CHANNEL CONNECTED!**\n\n"
            f"📢 {getattr(channel, 'title', 'Channel')}\n\n"
            "Step 2/2\n\n"
            "👥 Ab **Group ka link** bhejo.\n\n"
            "Example:\n"
            "`https://t.me/YourGroup`\n\n"
            "Ya:\n"
            "`@YourGroup`\n\n"
            "⚠️ Bot ko Group mein add hona chahiye."
        )

        return

    # =====================================================
    # STEP 2 - GROUP
    # =====================================================

    if session["step"] == "group":

        status = await event.reply(
            "⏳ **Group verify kar raha hoon...**"
        )

        group = await resolve_chat(
            text
        )

        if not group:

            await status.edit(
                "❌ **Group nahi mila.**\n\n"
                "Bot ko Group mein add karo aur "
                "dobara Group link bhejo."
            )

            return

        # Reject channel
        if getattr(
            group,
            "broadcast",
            False
        ):

            await status.edit(
                "❌ Ye Channel hai.\n\n"
                "Please Group ka link bhejo."
            )

            return

        group_id = group.id
        channel_id = session["channel_id"]

        # =================================================
        # GROUP ALREADY USED?
        # =================================================

        existing_owner = await firebase_get_async(
            f"groups/{group_id}"
        )

        if (
            existing_owner is not None
            and str(existing_owner)
            != str(user_id)
        ):

            await status.edit(
                "❌ **Ye Group already configured hai.**\n\n"
                "Please apna doosra Group use karo."
            )

            return

        # =================================================
        # SAVE USER CONFIG
        # =================================================

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
                "❌ Firebase mein save nahi hua.\n\n"
                "Dobara try karo."
            )

            return

        # Group ownership mapping
        await firebase_put_async(
            f"groups/{group_id}",
            str(user_id)
        )

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
            "🟢 **LIVE SEARCH: ACTIVE**\n\n"
            "Ab bot:\n"
            "🔎 Group request detect karega\n"
            "📢 Configured Channel search karega\n"
            "📝 Post text + caption check karega\n"
            "🔗 Original post link dega\n"
            "📤 Share Post button dega\n\n"
            "📋 `/mysetup`\n"
            "⚙️ `/setup`\n"
            "🗑️ `/reset`"
        )


# =========================================================
# 🧹 TEXT NORMALIZATION
# =========================================================

def normalize_text(text):

    if not text:
        return ""

    text = text.lower()

    # Common separators -> space
    text = re.sub(
        r"[_\-./|]+",
        " ",
        text
    )

    # Remove emojis / special symbols
    text = re.sub(
        r"[^\w\s+]",
        " ",
        text,
        flags=re.UNICODE
    )

    # Remove extra spaces
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


# =========================================================
# 🧠 REQUEST CLEANING
# =========================================================

STOP_WORDS = {
    "do",
    "de",
    "dedo",
    "link",
    "links",
    "bhejo",
    "bhej",
    "send",
    "share",
    "chahiye",
    "chaahiye",
    "mujhe",
    "please",
    "plz",
    "bhai",
    "bro",
    "sir",
    "hai",
    "he",
    "ho",
    "kya",
    "ka",
    "ki",
    "ke",
    "ko",
    "mera",
    "meri",
    "apna",
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
    "dena",
    "dijiye",
    "chahiye",
    "milega",
    "milega",
}


def extract_candidates(text):

    normalized = normalize_text(
        text
    )

    if not normalized:
        return []

    words = normalized.split()

    # Remove common request words
    useful_words = [
        word
        for word in words
        if word not in STOP_WORDS
        and len(word) >= 2
    ]

    candidates = []

    # Full cleaned phrase
    if useful_words:

        candidates.append(
            " ".join(useful_words)
        )

    # Try all 1-5 word windows
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

    # Compact versions
    compact_candidates = []

    for candidate in candidates:

        compact = compact_text(
            candidate
        )

        if compact and compact not in compact_candidates:

            compact_candidates.append(
                compact
            )

    return candidates + compact_candidates


# =========================================================
# 🔍 FUZZY SIMILARITY
# =========================================================

def similarity(a, b):

    a_norm = compact_text(a)
    b_norm = compact_text(b)

    if not a_norm or not b_norm:
        return 0.0

    # Exact
    if a_norm == b_norm:
        return 1.0

    # One contains another
    if (
        a_norm in b_norm
        or b_norm in a_norm
    ):

        shorter = min(
            len(a_norm),
            len(b_norm)
        )

        longer = max(
            len(a_norm),
            len(b_norm)
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
        a_norm,
        b_norm
    ).ratio()


# =========================================================
# 🧠 EXTRACT POSSIBLE APP TERMS FROM POST
# =========================================================

def post_search_terms(text):

    normalized = normalize_text(
        text
    )

    if not normalized:
        return []

    words = normalized.split()

    terms = []

    # Whole post
    terms.append(
        normalized
    )

    # Word groups
    max_window = min(
        6,
        len(words)
    )

    for size in range(
        max_window,
        0,
        -1
    ):

        for i in range(
            0,
            len(words) - size + 1
        ):

            phrase = " ".join(
                words[
                    i:i + size
                ]
            )

            if len(
                compact_text(phrase)
            ) >= 3:

                terms.append(
                    phrase
                )

    return terms


# =========================================================
# 🏆 SCORE A POST
# =========================================================

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

    # -----------------------------------------------------
    # Exact phrase / compact phrase
    # -----------------------------------------------------

    for candidate in candidates:

        candidate_norm = normalize_text(
            candidate
        )

        candidate_compact = compact_text(
            candidate
        )

        if not candidate_compact:
            continue

        if candidate_norm in normalized_post:

            # Strong exact match
            score = 0.98

            if score > best:
                best = score

        elif (
            candidate_compact in compact_post
        ):

            score = 0.96

            if score > best:
                best = score

    # -----------------------------------------------------
    # Fuzzy word matching
    # -----------------------------------------------------

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

            if best_word > 0:
                word_scores.append(
                    best_word
                )

        if word_scores:

            avg_score = (
                sum(word_scores)
                / len(word_scores)
            )

            # Strong fuzzy match
            if avg_score >= 0.82:

                score = (
                    0.70
                    + (
                        avg_score * 0.25
                    )
                )

                if score > best:
                    best = score

    return best


# =========================================================
# 🔎 CHANNEL SEARCH
# =========================================================

async def search_channel(
    channel_id,
    user_text
):

    candidates = extract_candidates(
        user_text
    )

    if not candidates:
        return None

    logging.info(
        f"🔎 Candidates: {candidates}"
    )

    best_message = None
    best_score = 0.0

    # =====================================================
    # PHASE 1
    # Telegram server-side search
    # =====================================================

    try:

        # Search each useful candidate
        server_queries = []

        for candidate in candidates:

            if len(candidate) < 3:
                continue

            # Don't search compact garbage
            if " " not in candidate and len(candidate) < 4:
                continue

            if candidate not in server_queries:

                server_queries.append(
                    candidate
                )

        # Limit queries for performance
        server_queries = server_queries[:8]

        for query in server_queries:

            try:

                async for msg in bot.iter_messages(
                    channel_id,
                    search=query,
                    limit=30
                ):

                    if not msg:
                        continue

                    message_text = (
                        msg.raw_text or ""
                    )

                    if not message_text:
                        continue

                    score = score_post(
                        message_text,
                        candidates
                    )

                    if score > best_score:

                        best_score = score
                        best_message = msg

                        if best_score >= 0.98:
                            break

                if best_score >= 0.98:
                    break

            except Exception as e:

                logging.warning(
                    f"Server search failed "
                    f"for '{query}': {e}"
                )

    except Exception as e:

        logging.error(
            f"Server search error: {e}"
        )

    # =====================================================
    # PHASE 2
    # Recent channel posts fallback
    # =====================================================

    # If server search didn't find a strong result,
    # scan recent posts for typo tolerance.
    if best_score < 0.90:

        try:

            scanned = 0

            async for msg in bot.iter_messages(
                channel_id,
                limit=3000
            ):

                if not msg:
                    continue

                message_text = (
                    msg.raw_text or ""
                )

                if not message_text:
                    continue

                scanned += 1

                score = score_post(
                    message_text,
                    candidates
                )

                if score > best_score:

                    best_score = score
                    best_message = msg

                # Excellent result
                if best_score >= 0.98:
                    break

            logging.info(
                f"📚 Scanned: {scanned} posts | "
                f"Best score: {best_score:.2f}"
            )

        except Exception as e:

            logging.error(
                f"Fallback search error: {e}"
            )

    # =====================================================
    # MINIMUM MATCH THRESHOLD
    # =====================================================

    if best_message and best_score >= 0.82:

        logging.info(
            f"✅ Match found | "
            f"Score: {best_score:.2f} | "
            f"Message ID: {best_message.id}"
        )

        return best_message

    logging.info(
        f"❌ No reliable match | "
        f"Best score: {best_score:.2f}"
    )

    return None


# =========================================================
# 🔗 ORIGINAL POST LINK
# =========================================================

async def get_post_link(
    channel_id,
    message
):

    try:

        chat = await bot.get_entity(
            channel_id
        )

        username = getattr(
            chat,
            "username",
            None
        )

        if username:

            return (
                f"https://t.me/"
                f"{username}/"
                f"{message.id}"
            )

    except Exception:
        pass

    # Private channel
    channel_id_str = str(
        channel_id
    ).replace(
        "-100",
        ""
    )

    return (
        f"https://t.me/c/"
        f"{channel_id_str}/"
        f"{message.id}"
    )


# =========================================================
# 📤 SHARE URL
# =========================================================

def make_share_url(post_link):

    return (
        "https://t.me/share/url"
        f"?url={post_link}"
    )


# =========================================================
# 👥 GROUP MESSAGE HANDLER
# =========================================================

@bot.on(events.NewMessage(
    incoming=True
))
async def handle_group_search(event):

    # Only groups
    if not event.is_group:
        return

    # Ignore our own messages
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

    # =====================================================
    # FIND GROUP OWNER
    # =====================================================

    owner_id = await firebase_get_async(
        f"groups/{group_id}"
    )

    if not owner_id:
        return

    try:

        owner_id = int(
            owner_id
        )

    except Exception:

        return

    # =====================================================
    # GET CONFIG
    # =====================================================

    config = await get_user_config(
        owner_id
    )

    if not config:
        return

    if not config.get("active"):
        return

    # Exact group protection
    if str(
        config.get("group_id")
    ) != str(group_id):

        return

    channel_id = config.get(
        "channel_id"
    )

    if not channel_id:
        return

    # =====================================================
    # SEARCH
    # =====================================================

    logging.info(
        f"🔎 Group request: "
        f"'{text}' | "
        f"Group: {group_id} | "
        f"Channel: {channel_id}"
    )

    found_message = await search_channel(
        channel_id,
        text
    )

    # Not found -> SILENT
    if not found_message:

        logging.info(
            f"❌ No result for: {text}"
        )

        return

    # =====================================================
    # CREATE ORIGINAL POST LINK
    # =====================================================

    post_link = await get_post_link(
        channel_id,
        found_message
    )

    # =====================================================
    # DETECT APP NAME FROM REQUEST
    # =====================================================

    candidates = extract_candidates(
        text
    )

    display_name = (
        candidates[0].title()
        if candidates
        else text.title()
    )

    # =====================================================
    # REPLY
    # =====================================================

    reply_text = (
        "👋 **Hello!**\n\n"
        f"📥 **{display_name}** "
        "channel par available hai.\n\n"
        "👇 **Original Post:**\n"
        f"{post_link}\n\n"
        "📤 Neeche **Share Post** button "
        "se post share kar sakte ho."
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
            f"✅ Reply sent | "
            f"{display_name} | "
            f"{post_link}"
        )

    except Exception as e:

        logging.error(
            f"❌ Reply error: {e}"
        )


# =========================================================
# ❤️ PING
# =========================================================

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
        "🔎 Live Search: **ON**\n"
        "🔥 Firebase: **ON**\n"
        "🧠 Fuzzy Search: **ON**\n"
        "📤 Share Button: **ON**"
    )


# =========================================================
# 📖 HELP
# =========================================================

@bot.on(events.NewMessage(
    pattern=r"^/help$"
))
async def help_handler(event):

    await event.reply(
        "🤖 **PUBLIC LIVE SEARCH BOT**\n\n"
        "Commands:\n\n"
        "🚀 `/start`\n"
        "⚙️ `/setup`\n"
        "📋 `/mysetup`\n"
        "🗑️ `/reset`\n"
        "❌ `/cancel`\n"
        "❤️ `/ping`\n"
        "📖 `/help`\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🔎 **Search Examples**\n\n"
        "`Kuku TV do`\n"
        "`Kuku TV link`\n"
        "`KukuTV chahiye`\n"
        "`bhai Kuku TV dedo`\n"
        "`BulletShort do`\n"
        "`Bulletshorts link`\n"
        "`bulletshrt chahiye`\n\n"
        "Bot Channel ke post ke "
        "text/caption ko fuzzy-match karega.\n\n"
        "Post na mile to bot reply nahi karega."
    )


# =========================================================
# 🚀 MAIN
# =========================================================

async def main():

    print(
        "⏳ Starting Telegram Client..."
    )

    await bot.start(
        bot_token=BOT_TOKEN
    )

    me = await bot.get_me()

    print(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    print(
        f"✅ Bot: @{me.username}"
    )

    print(
        f"👑 Owner ID: {OWNER_ID}"
    )

    print(
        "🟢 Public Multi-User: ON"
    )

    print(
        "🔎 Fuzzy Live Search: ON"
    )

    print(
        "🔥 Firebase: ON"
    )

    print(
        "📤 Share Button: ON"
    )

    print(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    await bot.run_until_disconnected()


# =========================================================
# 🏁 START
# =========================================================

if __name__ == "__main__":

    try:

        bot.loop.run_until_complete(
            main()
        )

    except KeyboardInterrupt:

        print(
            "\n🛑 Bot stopped."
        )

    except Exception as e:

        print(
            f"\n❌ Fatal Error: {e}"
        )

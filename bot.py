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
# Dependencies: Telethon + requests only
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

print("🚀 PREMIUM MOD BOT BOOTING...")

API_ID = os.environ.get("TG_API_ID")
API_HASH = os.environ.get("TG_API_HASH")
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")

FIREBASE_URL = "https://sks-9865a-default-rtdb.firebaseio.com/"
OWNER_ID = 8587571289

# Recent-post scan. Increase only if your channel is very large.
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
    API_HASH
)

START_TIME = datetime.now()
SETUP = {}
CHANNEL_CACHE = {}
SEARCH_LOCKS = {}


# ============================================================
# FIREBASE
# ============================================================

def firebase_get(path):
    try:
        url = FIREBASE_URL.rstrip("/") + "/" + path.lstrip("/")
        r = requests.get(url, timeout=12)
        if r.status_code == 200:
            return r.json()
        logging.error("Firebase GET %s -> HTTP %s", path, r.status_code)
    except Exception as e:
        logging.error("Firebase GET error: %s", e)
    return None


def firebase_put(path, data):
    try:
        url = FIREBASE_URL.rstrip("/") + "/" + path.lstrip("/")
        r = requests.put(url, json=data, timeout=12)
        if r.status_code in (200, 201):
            return True
        logging.error("Firebase PUT %s -> HTTP %s", path, r.status_code)
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
# GROUP -> CHANNEL MAPPING
# Stored by GROUP ID, not by requesting user.
# This fixes the old public-mode mapping problem.
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
        "owner_id": OWNER_ID,
    }
    return firebase_put(mapping_path(group_id), data)


# ============================================================
# OPTIONAL MANUAL FILTER LINKS
# ============================================================

def safe_key(value):
    value = str(value).strip().lower()
    for c in ".#$[]/":
        value = value.replace(c, "_")
    return value[:100]


def get_filter_links():
    data = firebase_get("links")
    return data if isinstance(data, dict) else {}


# ============================================================
# TEXT NORMALIZATION / FUZZY MATCH
# No rapidfuzz dependency required.
# ============================================================

REQUEST_WORDS = {
    "do", "de", "dedo", "bhejo", "bhej", "send",
    "link", "links", "download", "downloadlink",
    "please", "plz", "pls", "bhai", "bro",
    "mujhe", "mera", "meri", "chahiye", "chaiye",
    "hai", "kya", "ka", "ki", "ke", "ko",
    "me", "mein", "par", "pe", "se", "wala", "wali",
    "version", "latest", "new", "mod", "apk", "app",
}


def normalize(text):
    if not text:
        return ""

    text = unicodedata.normalize("NFKC", str(text)).lower()

    # URLs / punctuation / separators are not useful for app-name matching.
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[_\-/.,:;|+*=~`'\"()\[\]{}<>!?]+", " ", text)

    text = "".join(
        c if c.isalnum() or c.isspace() else " "
        for c in text
    )

    return re.sub(r"\s+", " ", text).strip()


def compact(text):
    return normalize(text).replace(" ", "")


def extract_app_query(text):
    words = normalize(text).split()
    cleaned = [w for w in words if w not in REQUEST_WORDS]
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

    direct = SequenceMatcher(None, a_n, b_n).ratio() * 100
    compact_score = SequenceMatcher(None, a_c, b_c).ratio() * 100

    # Compare individual words too.
    q_words = a_n.split()
    p_words = b_n.split()

    word_best = 0
    for qw in q_words:
        if len(qw) < 2:
            continue
        for pw in p_words:
            s = SequenceMatcher(None, qw, pw).ratio() * 100
            if s > word_best:
                word_best = s

    return max(direct, compact_score, word_best)


def post_score(query, text):
    """
    Give highest priority to the app name appearing in the post.
    This avoids matching a random word in a long caption.
    """
    q = normalize(query)
    t = normalize(text)

    if not q or not t:
        return 0

    if q in t:
        return 100

    q_compact = compact(q)
    t_compact = compact(t)

    if q_compact and q_compact in t_compact:
        return 98

    # Check every short window around post words.
    q_words = q.split()
    t_words = t.split()

    best = similarity(q, t)

    if len(q_words) > 1:
        n = len(q_words)
        for i in range(max(1, len(t_words) - 20)):
            window = " ".join(t_words[i:i+n])
            if window:
                best = max(best, similarity(q, window))

    return best


# ============================================================
# TELEGRAM ENTITY RESOLUTION
# ============================================================

def extract_username(value):
    value = (value or "").strip()

    if value.startswith("@"):
        return value[1:]

    m = re.match(
        r"^(?:https?://)?(?:www\.)?t\.me/([A-Za-z0-9_]+)(?:/.*)?$",
        value
    )

    if m:
        username = m.group(1)
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
        logging.error("Resolve entity %r: %s", value, e)
        return None


async def validate_channel(channel):
    try:
        msgs = await bot.get_messages(channel, limit=3)
        return True, msgs
    except ChatAdminRequiredError:
        return False, "Bot ko channel read/admin permission nahi hai."
    except ChannelPrivateError:
        return False, "Channel private hai ya bot member nahi hai."
    except FloodWaitError as e:
        return False, f"Telegram FloodWait: {e.seconds}s."
    except Exception as e:
        return False, str(e)


# ============================================================
# CHANNEL SEARCH
# Telegram server search + recent-history fallback.
# ============================================================

async def search_channel(channel, query):
    if not query:
        return None, 0

    best = None
    best_score = 0
    seen = set()

    # First ask Telegram's own channel search.
    terms = [normalize(query)]
    for word in normalize(query).split():
        if len(word) >= 3:
            terms.append(word)

    for term in terms[:5]:
        try:
            async for msg in bot.iter_messages(
                channel,
                search=term,
                limit=100
            ):
                if not msg or msg.id in seen:
                    continue
                seen.add(msg.id)

                text = msg.raw_text or ""
                if not text:
                    continue

                score = post_score(query, text)

                if score > best_score:
                    best_score = score
                    best = msg

                if score >= 98:
                    return best, best_score

        except FloodWaitError as e:
            logging.warning("Search FloodWait: %ss", e.seconds)
            await asyncio.sleep(e.seconds)
        except Exception as e:
            logging.warning("Telegram search failed: %s", e)

    # Fallback: inspect recent channel posts directly.
    try:
        scanned = 0

        async for msg in bot.iter_messages(
            channel,
            limit=SCAN_LIMIT
        ):
            if not msg:
                continue

            text = msg.raw_text or ""
            if not text:
                continue

            scanned += 1
            score = post_score(query, text)

            if score > best_score:
                best_score = score
                best = msg

            if score >= 98:
                return best, best_score

            if scanned >= SCAN_LIMIT:
                break

    except FloodWaitError as e:
        logging.warning("History scan FloodWait: %ss", e.seconds)
    except Exception as e:
        logging.error("History scan error: %s", e)

    # 60 is enough for small spelling differences without
    # making random posts match too easily.
    if best and best_score >= 60:
        return best, best_score

    return None, best_score


# ============================================================
# POST LINK / SHARE LINK
# ============================================================

def post_link(channel, message):
    username = getattr(channel, "username", None)

    if username:
        return f"https://t.me/{username}/{message.id}"

    cid = getattr(channel, "id", None)
    if cid:
        return f"https://t.me/c/{cid}/{message.id}"

    return None


def share_link(url, text):
    return (
        "https://t.me/share/url"
        "?url=" + quote(url, safe="")
        "&text=" + quote(text, safe="")
    )


# ============================================================
# ADMIN CHECK
# ============================================================

async def is_group_admin(event):
    if not event.is_group:
        return False

    try:
        p = await bot.get_permissions(
            event.chat_id,
            event.sender_id
        )
        return bool(p.is_admin)
    except Exception:
        return False


# ============================================================
# /START
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/start$"))
async def start_handler(event):
    await event.reply(
        "👋 **PREMIUM MOD SEARCH BOT**\n\n"
        "🔎 Smart Channel Search\n"
        "🧠 Fuzzy App Matching\n"
        "🔥 Firebase Group Mapping\n"
        "🔗 Open + Share Post\n\n"
        "Group admin setup:\n"
        "`/setup`\n\n"
        "Check bot:\n"
        "`/ping`"
    )


# ============================================================
# /SETUP
# Run inside the target group.
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/setup$"))
async def setup_start(event):
    if not event.is_group:
        await event.reply(
            "⚠️ `/setup` target group ke andar run karo."
        )
        return

    if not await is_group_admin(event):
        await event.reply(
            "❌ Sirf group admin `/setup` kar sakta hai."
        )
        return

    SETUP[event.sender_id] = {
        "group_id": int(event.chat_id),
        "step": "channel"
    }

    await event.reply(
        "⚙️ **SETUP STARTED**\n\n"
        "📢 Ab jis channel se search karna hai uska:\n"
        "• `@username` ya\n"
        "• `https://t.me/username`\n"
        "bhejo.\n\n"
        "⚠️ Bot ko target channel mein add/admin karna zaroori hai."
    )


@bot.on(events.NewMessage(incoming=True))
async def setup_input(event):
    user_id = event.sender_id
    session = SETUP.get(user_id)

    if not session:
        return

    text = (event.raw_text or "").strip()

    if not text or text.startswith("/"):
        return

    if session.get("step") != "channel":
        return

    if not await is_group_admin(event):
        return

    channel = await resolve_entity(text)

    if not channel:
        await event.reply(
            "❌ **Channel identify nahi hua.**\n\n"
            "Public channel ka exact @username/link bhejo.\n"
            "Agar private channel hai to bot ko pehle channel mein add karo."
        )
        return

    ok, info = await validate_channel(channel)

    if not ok:
        await event.reply(
            "❌ **Channel access problem**\n\n"
            f"{info}"
        )
        return

    session["channel_id"] = int(channel.id)
    session["channel_title"] = getattr(
        channel, "title", "Unknown"
    )
    session["step"] = "confirm"

    await event.reply(
        "📢 **CHANNEL FOUND ✅**\n\n"
        f"Name: **{session['channel_title']}**\n"
        f"ID: `{session['channel_id']}`\n\n"
        f"👥 Group ID: `{session['group_id']}`\n\n"
        "Save karne ke liye `/save` bhejo.\n"
        "Cancel ke liye `/cancel`."
    )


@bot.on(events.NewMessage(pattern=r"^/save$"))
async def setup_save(event):
    user_id = event.sender_id
    session = SETUP.get(user_id)

    if not session:
        await event.reply(
            "❌ Active setup nahi hai. Group mein `/setup` run karo."
        )
        return

    if not await is_group_admin(event):
        return

    if session.get("step") != "confirm":
        await event.reply("❌ Setup incomplete hai.")
        return

    channel = await resolve_entity(
        str(session["channel_id"])
    )

    if not channel:
        await event.reply(
            "❌ Channel dobara resolve nahi hua. `/setup` phir se karo."
        )
        return

    if save_mapping(session["group_id"], channel):
        SETUP.pop(user_id, None)

        await event.reply(
            "✅ **SETUP COMPLETE**\n\n"
            f"👥 Group: `{session['group_id']}`\n"
            f"📢 Channel: **{session['channel_title']}**\n"
            f"🆔 `{session['channel_id']}`\n\n"
            "🔎 Search: ✅\n"
            "🧠 Fuzzy Match: ✅\n"
            "🔥 Firebase: ✅\n"
            "🔗 Share Button: ✅\n\n"
            "Ab user likh sakta hai:\n"
            "`Kuku TV do`\n"
            "`KukuTvv link`\n"
            "`Bullet Shorts dedo`"
        )
    else:
        await event.reply("❌ Firebase mein mapping save nahi hui.")


@bot.on(events.NewMessage(pattern=r"^/cancel$"))
async def setup_cancel(event):
    SETUP.pop(event.sender_id, None)
    await event.reply("❌ Setup cancelled.")


# ============================================================
# /DIAGNOSTIC
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/(diagnostic|diag)$"))
async def diagnostic_handler(event):
    if event.is_group and not await is_group_admin(event):
        return

    group_id = event.chat_id if event.is_group else None

    if not group_id:
        await event.reply(
            "⚠️ `/diagnostic` target group mein run karo."
        )
        return

    mapping = get_mapping(group_id)

    lines = [
        "🧪 **BOT DIAGNOSTIC**",
        "",
        f"👥 Group ID: `{group_id}`",
    ]

    if not mapping:
        lines.append("🔥 Firebase Mapping: ❌")
        lines.append("➡️ Group mein `/setup` run karo.")
        await event.reply("\n".join(lines))
        return

    lines.append("🔥 Firebase Mapping: ✅")

    channel_id = mapping.get("channel_id")

    if not channel_id:
        lines.append("📢 Channel ID: ❌")
        await event.reply("\n".join(lines))
        return

    try:
        channel = await bot.get_entity(int(channel_id))
        lines.append(
            f"📢 Channel: **{getattr(channel, 'title', 'Unknown')}**"
        )
        lines.append("📢 Channel Resolve: ✅")

        ok, info = await validate_channel(channel)

        if ok:
            lines.append("📖 Channel Read Access: ✅")
            lines.append("🔎 Search Engine: ✅")
        else:
            lines.append("📖 Channel Read Access: ❌")
            lines.append(f"Reason: `{str(info)[:300]}`")

    except Exception as e:
        lines.append("📢 Channel Resolve: ❌")
        lines.append(f"Reason: `{str(e)[:300]}`")

    await event.reply("\n".join(lines))


# ============================================================
# /PING
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/ping$"))
async def ping_handler(event):
    seconds = int((datetime.now() - START_TIME).total_seconds())
    h = seconds // 3600
    m = (seconds % 3600) // 60

    await event.reply(
        "🟢 **BOT ONLINE**\n\n"
        f"⏱️ Uptime: `{h}h {m}m`\n"
        "👥 Public Multi-User: ✅\n"
        "🔎 Channel Search: ✅\n"
        "🧠 Fuzzy Match: ✅\n"
        "🔥 Firebase: ✅"
    )


# ============================================================
# /FILTER
# Owner-only manual Firebase links
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/filter\s+(.+?)\s+(https?://\S+)$"))
async def filter_handler(event):
    if event.sender_id != OWNER_ID:
        return

    app_name = event.pattern_match.group(1).strip().lower()
    link = event.pattern_match.group(2).strip()

    if firebase_put(f"links/{safe_key(app_name)}", link):
        await event.reply(
            "✅ **FILTER SAVED**\n\n"
            f"📱 `{app_name.upper()}`\n"
            f"🔗 {link}"
        )
    else:
        await event.reply("❌ Firebase save failed.")


# ============================================================
# /KILLPOST
# Owner-only reply-to-delete
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/killpost$"))
async def killpost_handler(event):
    if event.sender_id != OWNER_ID:
        return

    if not event.is_reply:
        await event.reply(
            "⚠️ Delete karne wale post ko reply karke `/killpost` bhejo."
        )
        return

    try:
        reply = await event.get_reply_message()
        await reply.delete()
        await event.delete()
    except Exception as e:
        logging.error("killpost: %s", e)


# ============================================================
# MAIN GROUP SEARCH
# IMPORTANT: mapping is based on GROUP ID, so every user in
# the same configured group gets the same channel.
# ============================================================

@bot.on(events.NewMessage(incoming=True))
async def group_search_handler(event):
    if not event.is_group:
        return

    if event.sender_id == bot.uid:
        return

    text = (event.raw_text or "").strip()

    if not text or text.startswith("/"):
        return

    # Setup messages are handled separately.
    if event.sender_id in SETUP:
        return

    group_id = int(event.chat_id)
    mapping = get_mapping(group_id)

    if not mapping:
        # Only inform admins. Normal users see no spam.
        if await is_group_admin(event):
            await event.reply(
                "⚠️ Is group ka channel configured nahi hai.\n"
                "Admin `/setup` run kare."
            )
        return

    channel_id = mapping.get("channel_id")

    if not channel_id:
        return

    query = extract_app_query(text)

    if len(query) < 2:
        return

    logging.info(
        "SEARCH group=%s user=%s query=%r",
        group_id,
        event.sender_id,
        query
    )

    # Avoid multiple expensive searches at exactly the same time
    # in one group.
    lock = SEARCH_LOCKS.setdefault(group_id, asyncio.Lock())

    async with lock:
        try:
            channel = CHANNEL_CACHE.get(int(channel_id))

            if channel is None:
                channel = await bot.get_entity(int(channel_id))
                CHANNEL_CACHE[int(channel_id)] = channel

            found, score = await search_channel(
                channel,
                query
            )

        except FloodWaitError as e:
            logging.warning("FloodWait %ss", e.seconds)
            return

        except Exception as e:
            logging.error("Main search error: %s", e)

            if await is_group_admin(event):
                await event.reply(
                    "❌ **Search Error**\n\n"
                    f"`{str(e)[:400]}`"
                )
            return

    # --------------------------------------------------------
    # Manual Firebase link fallback
    # --------------------------------------------------------

    if not found:
        links = get_filter_links()
        best_name = None
        best_link = None
        best = 0

        for name, link in links.items():
            s = similarity(query, str(name))
            if s > best:
                best = s
                best_name = name
                best_link = link

        if best_link and best >= 75:
            await event.reply(
                "👋 **Hello!**\n\n"
                f"📥 **{str(best_name).upper()}** available hai.\n\n"
                f"👉 {best_link}",
                link_preview=False
            )
        return

    url = post_link(channel, found)

    if not url:
        return

    title = getattr(channel, "title", "Channel")

    share = share_link(
        url,
        f"{query.upper()} Download"
    )

    buttons = [
        [
            Button.url("📥 OPEN POST", url),
            Button.url("↗️ SHARE", share),
        ]
    ]

    reply = (
        "👋 **Hello!**\n\n"
        f"📥 **{query.upper()}** mil gaya.\n\n"
        f"📢 Source: **{title}**\n"
        f"🎯 Match: **{int(score)}%**\n\n"
        "👇 Post open/share karo:"
    )

    try:
        await event.reply(
            reply,
            buttons=buttons,
            link_preview=False
        )
        logging.info(
            "REPLIED query=%r post=%s score=%s",
            query,
            found.id,
            int(score)
        )
    except Exception as e:
        logging.error("Reply error: %s", e)


# ============================================================
# ROSE / JOIN MESSAGE CLEANER
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

        if not sender or not getattr(sender, "bot", False):
            return

        if sender.id == bot.uid:
            return

        text = (event.raw_text or "").lower()

        words = (
            "welcome",
            "joined",
            "made it",
            "hey",
        )

        if any(w in text for w in words):
            asyncio.create_task(delete_later(event, 300))

    except Exception:
        pass


# ============================================================
# GITHUB SAFE RESTART
# ============================================================

async def github_keep_alive():
    while True:
        try:
            elapsed = datetime.now() - START_TIME

            if elapsed >= timedelta(hours=5, minutes=45):
                token = os.environ.get("MY_GITHUB_TOKEN")
                repo = os.environ.get("GITHUB_REPOSITORY")

                if token and repo:
                    url = (
                        f"https://api.github.com/repos/{repo}/"
                        "actions/workflows/run-bot.yml/dispatches"
                    )

                    headers = {
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {token}",
                    }

                    try:
                        r = requests.post(
                            url,
                            headers=headers,
                            json={"ref": "main"},
                            timeout=15
                        )
                        logging.info(
                            "GitHub restart dispatch: HTTP %s",
                            r.status_code
                        )
                    except Exception as e:
                        logging.error(
                            "GitHub restart request: %s",
                            e
                        )

                os._exit(0)

        except Exception as e:
            logging.error("Keep-alive error: %s", e)

        await asyncio.sleep(600)


# ============================================================
# START
# ============================================================

async def main():
    print("⏳ Starting Telegram client...")

    await bot.start(bot_token=BOT_TOKEN)

    me = await bot.get_me()

    print(
        f"✅ Bot started: @{getattr(me, 'username', 'unknown')}"
    )
    print("🟢 PUBLIC MULTI-USER MODE: ON")
    print("🔎 SMART SEARCH: ON")
    print("🧠 FUZZY MATCH: ON")
    print("🔥 FIREBASE: ON")
    print("🔗 SHARE BUTTON: ON")

    bot.loop.create_task(github_keep_alive())

    await bot.run_until_disconnected()


if __name__ == "__main__":
    try:
        bot.loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("🛑 Bot stopped.")
    except Exception as e:
        print(f"❌ FATAL ERROR: {e}")

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
    base = "https://t.me/share/url"
    return base + "?url=" + quote(url, safe="") + "&text=" + quote(text, safe="")


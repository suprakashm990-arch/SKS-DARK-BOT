import os
import sys
import re
import asyncio
import logging
from datetime import datetime

import requests
from telethon import TelegramClient, events
from telethon.errors import RPCError


# =========================================================
# 🚀 PUBLIC LIVE SEARCH BOT
# =========================================================

print("🚀 Public Live Search Bot Starting...")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# =========================================================
# 🔐 TELEGRAM CONFIG
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
# 🧠 SETUP SESSIONS
# =========================================================
#
# user_id:
# {
#     "step": "channel"
# }
#
# ya
#
# {
#     "step": "group",
#     "channel_id": -100xxxxxxxxxx,
#     "channel_link": "..."
# }
#
# =========================================================

setup_sessions = {}


# =========================================================
# 🔥 FIREBASE HELPERS
# =========================================================

def firebase_get(path):
    try:
        url = f"{FIREBASE_URL.rstrip('/')}/{path}.json"

        response = requests.get(
            url,
            timeout=15
        )

        if response.status_code == 200:
            return response.json()

    except Exception as e:
        logging.error(f"Firebase GET Error: {e}")

    return None


def firebase_put(path, data):
    try:
        url = f"{FIREBASE_URL.rstrip('/')}/{path}.json"

        response = requests.put(
            url,
            json=data,
            timeout=15
        )

        return response.status_code in (200, 201)

    except Exception as e:
        logging.error(f"Firebase PUT Error: {e}")

    return False


def firebase_delete(path):
    try:
        url = f"{FIREBASE_URL.rstrip('/')}/{path}.json"

        response = requests.delete(
            url,
            timeout=15
        )

        return response.status_code in (200, 204)

    except Exception as e:
        logging.error(f"Firebase DELETE Error: {e}")

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
# 🔗 TELEGRAM ID PARSER
# =========================================================

def extract_private_chat_id(link):
    """
    Example:

    https://t.me/c/123456789/100
    -> -100123456789

    Only works when the internal Telegram ID
    is visible from the message link.
    """

    match = re.search(
        r"t\.me/c/(\d+)(?:/\d+)?",
        link
    )

    if match:
        internal_id = match.group(1)
        return int("-100" + internal_id)

    return None


async def resolve_chat(value):
    """
    Supports:

    @username
    https://t.me/username
    https://t.me/c/123456789/100
    -100xxxxxxxxxx
    username
    """

    value = value.strip()

    # Numeric Telegram ID
    if re.fullmatch(r"-100\d+", value):
        try:
            entity = await bot.get_entity(int(value))
            return entity
        except Exception:
            return None

    # Private t.me/c link
    private_id = extract_private_chat_id(value)

    if private_id:
        try:
            entity = await bot.get_entity(private_id)
            return entity
        except Exception:
            return None

    # Normal public username/link
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
        entity = await bot.get_entity(username)
        return entity

    except Exception:
        return None


# =========================================================
# 👤 USER CONFIG
# =========================================================

async def get_user_config(user_id):
    return await firebase_get_async(
        f"users/{user_id}/config"
    )


async def save_user_config(user_id, config):
    return await firebase_put_async(
        f"users/{user_id}/config",
        config
    )


# =========================================================
# 🚀 /START
# =========================================================

@bot.on(events.NewMessage(
    pattern=r"^/start$"
))
async def start_handler(event):

    user_id = event.sender_id

    if not user_id:
        return

    config = await get_user_config(user_id)

    # 👑 Owner recognition
    if user_id == OWNER_ID:
        owner_text = "👑 **Owner detected.**\n\n"
    else:
        owner_text = ""

    if config and config.get("active"):

        await event.reply(
            owner_text +
            "✅ **Aapka Live Search Bot already configured hai.**\n\n"
            "📢 Channel:\n"
            f"`{config.get('channel_link', 'Saved')}`\n\n"
            "👥 Group:\n"
            f"`{config.get('group_link', 'Saved')}`\n\n"
            "Bot ab isi Group mein request dekhega "
            "aur isi Channel mein live search karega.\n\n"
            "⚙️ Configuration badalne ke liye:\n"
            "`/setup`\n\n"
            "📋 Current setup dekhne ke liye:\n"
            "`/mysetup`\n\n"
            "🗑️ Configuration remove karne ke liye:\n"
            "`/reset`\n\n"
            "❌ Setup cancel:\n"
            "`/cancel`"
        )

        return

    # New user
    setup_sessions[user_id] = {
        "step": "channel"
    }

    await event.reply(
        owner_text +
        "👋 **Welcome!**\n\n"
        "Ye Public Live Search Bot hai.\n\n"
        "Sabse pehle mujhe apne **Telegram Channel ka link** bhejo.\n\n"
        "📢 Example:\n"
        "`https://t.me/YourChannel`\n\n"
        "Ya:\n"
        "`@YourChannel`\n\n"
        "⚠️ Channel mein bot ko access hona chahiye.\n\n"
        "❌ Cancel karna ho:\n"
        "`/cancel`"
    )


# =========================================================
# ⚙️ /SETUP
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
        "⚙️ **New Setup Started**\n\n"
        "Step 1/2\n\n"
        "📢 Apne **Channel ka link** bhejo.\n\n"
        "Example:\n"
        "`https://t.me/YourChannel`\n\n"
        "Ya:\n"
        "`@YourChannel`\n\n"
        "❌ Cancel: `/cancel`"
    )


# =========================================================
# ❌ /CANCEL
# =========================================================

@bot.on(events.NewMessage(
    pattern=r"^/cancel$"
))
async def cancel_handler(event):

    user_id = event.sender_id

    if user_id in setup_sessions:
        del setup_sessions[user_id]

    await event.reply(
        "❌ **Setup cancelled.**\n\n"
        "Jab dobara setup karna ho:\n"
        "`/setup`"
    )


# =========================================================
# 📋 /MYSETUP
# =========================================================

@bot.on(events.NewMessage(
    pattern=r"^/mysetup$"
))
async def mysetup_handler(event):

    user_id = event.sender_id

    config = await get_user_config(user_id)

    if not config or not config.get("active"):
        await event.reply(
            "❌ Aapka koi setup nahi hai.\n\n"
            "Setup start karne ke liye:\n"
            "`/setup`"
        )
        return

    await event.reply(
        "📋 **Your Configuration**\n\n"
        f"📢 Channel:\n`{config.get('channel_link')}`\n\n"
        f"👥 Group:\n`{config.get('group_link')}`\n\n"
        f"🆔 Channel ID:\n`{config.get('channel_id')}`\n\n"
        f"🆔 Group ID:\n`{config.get('group_id')}`\n\n"
        "🟢 Status: **ACTIVE**"
    )


# =========================================================
# 🗑️ /RESET
# =========================================================

@bot.on(events.NewMessage(
    pattern=r"^/reset$"
))
async def reset_handler(event):

    user_id = event.sender_id

    config = await get_user_config(user_id)

    if not config:
        await event.reply(
            "❌ Aapka setup already empty hai."
        )
        return

    group_id = config.get("group_id")

    # Remove group mapping
    if group_id:
        await firebase_delete_async(
            f"groups/{group_id}"
        )

    # Remove user configuration
    await firebase_delete_async(
        f"users/{user_id}/config"
    )

    setup_sessions.pop(user_id, None)

    await event.reply(
        "🗑️ **Configuration Removed Successfully.**\n\n"
        "Ab bot aapke purane Channel/Group ko monitor nahi karega.\n\n"
        "Naya setup:\n"
        "`/setup`"
    )


# =========================================================
# 🧩 SETUP MESSAGE PROCESSOR
# =========================================================

@bot.on(events.NewMessage(incoming=True))
async def setup_message_processor(event):

    if not event.is_private:
        return

    user_id = event.sender_id

    if not user_id:
        return

    # Commands ko ignore
    if event.raw_text.startswith("/"):
        return

    if user_id not in setup_sessions:
        return

    session = setup_sessions[user_id]

    text = event.raw_text.strip()

    if not text:
        return

    # =====================================================
    # STEP 1: CHANNEL
    # =====================================================

    if session["step"] == "channel":

        await event.reply(
            "⏳ **Channel check kar raha hoon...**"
        )

        channel = await resolve_chat(text)

        if not channel:

            await event.reply(
                "❌ **Channel nahi mil raha.**\n\n"
                "Check karo:\n"
                "• Link sahi hai?\n"
                "• Bot ko Channel mein add kiya hai?\n"
                "• Private Channel hai to bot ko access diya hai?\n\n"
                "Dobara Channel link bhejo."
            )

            return

        # Check channel-like entity
        if not getattr(channel, "broadcast", False):

            await event.reply(
                "❌ Ye Telegram Channel nahi lag raha.\n\n"
                "Please actual **Channel link** bhejo."
            )

            return

        channel_id = channel.id

        session["step"] = "group"
        session["channel_id"] = channel_id
        session["channel_link"] = text

        await event.reply(
            "✅ **Channel successfully connected!**\n\n"
            f"📢 `{getattr(channel, 'title', 'Channel')}`\n\n"
            "Step 2/2\n\n"
            "👥 Ab mujhe **Group ka link** bhejo.\n\n"
            "Example:\n"
            "`https://t.me/YourGroup`\n\n"
            "Ya:\n"
            "`@YourGroup`\n\n"
            "⚠️ Bot ko us Group mein add hona chahiye.\n\n"
            "❌ Cancel: `/cancel`"
        )

        return

    # =====================================================
    # STEP 2: GROUP
    # =====================================================

    if session["step"] == "group":

        await event.reply(
            "⏳ **Group check kar raha hoon...**"
        )

        group = await resolve_chat(text)

        if not group:

            await event.reply(
                "❌ **Group nahi mil raha.**\n\n"
                "Pehle bot ko Group mein add karo, "
                "phir Group ka link dobara bhejo."
            )

            return

        # Channel ko group ke roop mein accept nahi karna
        if getattr(group, "broadcast", False):

            await event.reply(
                "❌ Ye Channel hai.\n\n"
                "Please **Group ka link** bhejo."
            )

            return

        group_id = group.id
        channel_id = session["channel_id"]

        # =================================================
        # CHECK GROUP ALREADY CLAIMED
        # =================================================

        existing_owner = await firebase_get_async(
            f"groups/{group_id}"
        )

        if existing_owner and str(existing_owner) != str(user_id):

            await event.reply(
                "❌ **Ye Group already kisi aur user ke setup mein hai.**\n\n"
                "Please apna doosra Group use karo."
            )

            return

        # =================================================
        # SAVE CONFIG
        # =================================================

        config = {
            "active": True,

            "user_id": user_id,

            "channel_id": channel_id,
            "channel_link": session["channel_link"],

            "group_id": group_id,
            "group_link": text,

            "created_at": datetime.utcnow().isoformat()
        }

        saved = await save_user_config(
            user_id,
            config
        )

        if not saved:

            await event.reply(
                "❌ Firebase mein configuration save nahi ho paya.\n\n"
                "Thodi der baad dobara try karo."
            )

            return

        # Group -> Owner mapping
        await firebase_put_async(
            f"groups/{group_id}",
            str(user_id)
        )

        # Session remove
        setup_sessions.pop(user_id, None)

        await event.reply(
            "🎉 **SETUP COMPLETE!**\n\n"
            f"📢 Channel:\n`{session['channel_link']}`\n\n"
            f"👥 Group:\n`{text}`\n\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🟢 **Live Search: ACTIVE**\n\n"
            "Ab bot:\n"
            "• Isi Group mein messages check karega\n"
            "• Isi Channel mein app search karega\n"
            "• App milne par isi Group mein reply karega\n\n"
            "📋 Setup dekhne ke liye:\n"
            "`/mysetup`\n\n"
            "⚙️ Setup change karne ke liye:\n"
            "`/setup`\n\n"
            "🗑️ Setup remove karne ke liye:\n"
            "`/reset`"
        )


# =========================================================
# 🔎 APP REQUEST DETECTION
# =========================================================

INTENT_KEYWORDS = {
    "do",
    "de",
    "link",
    "app",
    "apk",
    "mod",
    "chahiye",
    "dedo",
    "bhejo",
    "send",
    "download",
    "tv",
    "movie",
    "series",
    "ott",
    "premium",
    "share"
}


STOP_WORDS = {
    "do",
    "de",
    "link",
    "app",
    "apk",
    "mod",
    "please",
    "plz",
    "bhai",
    "bro",
    "hai",
    "kya",
    "chahiye",
    "dedo",
    "bhejo",
    "send",
    "mujhe",
    "ko",
    "mera",
    "meri",
    "yaar",
    "download",
    "share",
    "please",
    "sir"
}


def extract_app_name(text):

    text = text.lower().strip()

    # URL etc remove
    text = re.sub(
        r"https?://\S+",
        "",
        text
    )

    words = text.split()

    if not words:
        return ""

    # Intent check
    if not any(
        word in INTENT_KEYWORDS
        for word in words
    ):
        return ""

    cleaned = []

    for word in words:

        word = re.sub(
            r"[^\w.+-]",
            "",
            word
        )

        if not word:
            continue

        if word in STOP_WORDS:
            continue

        cleaned.append(word)

    app_name = " ".join(cleaned).strip()

    if len(app_name) < 2:
        return ""

    return app_name


# =========================================================
# 🔎 LIVE SEARCH IN CONFIGURED CHANNEL
# =========================================================

async def search_channel(channel_id, app_name):

    try:

        found = None

        # Primary server-side Telegram search
        async for message in bot.iter_messages(
            channel_id,
            search=app_name,
            limit=20
        ):

            if not message:
                continue

            message_text = message.raw_text or ""

            if not message_text:
                continue

            if app_name.lower() in message_text.lower():

                found = message
                break

        return found

    except Exception as e:

        logging.error(
            f"Channel search error: {e}"
        )

        return None


# =========================================================
# 👥 GROUP LIVE SEARCH
# =========================================================

@bot.on(events.NewMessage(incoming=True))
async def handle_group_replies(event):

    # Sirf groups
    if not event.is_group:
        return

    # Bot ke apne messages ignore
    if event.out:
        return

    # Text nahi hai
    text = event.raw_text

    if not text:
        return

    text = text.strip()

    # Commands ignore
    if text.startswith("/"):
        return

    group_id = event.chat_id

    if not group_id:
        return

    # =====================================================
    # FIND WHICH USER OWNS THIS GROUP
    # =====================================================

    owner_id = await firebase_get_async(
        f"groups/{group_id}"
    )

    if not owner_id:
        # Ye group kisi user ne configure nahi kiya
        return

    try:
        owner_id = int(owner_id)
    except Exception:
        return

    # =====================================================
    # GET OWNER CONFIG
    # =====================================================

    config = await get_user_config(
        owner_id
    )

    if not config:
        return

    if not config.get("active"):
        return

    # Safety: exact group check
    if str(config.get("group_id")) != str(group_id):
        return

    channel_id = config.get("channel_id")

    if not channel_id:
        return

    # =====================================================
    # EXTRACT APP NAME
    # =====================================================

    app_name = extract_app_name(text)

    if not app_name:
        return

    display_name = app_name.upper()

    logging.info(
        f"🔎 Search request: {display_name} | "
        f"Group: {group_id} | "
        f"Channel: {channel_id}"
    )

    # =====================================================
    # LIVE SEARCH
    # =====================================================

    found_msg = await search_channel(
        channel_id,
        app_name
    )

    # =====================================================
    # NOT FOUND = SILENT
    # =====================================================

    if not found_msg:
        logging.info(
            f"❌ Not found: {app_name}"
        )
        return

    # =====================================================
    # CREATE CHANNEL POST LINK
    # =====================================================

    channel_username = getattr(
        found_msg.chat,
        "username",
        None
    )

    if channel_username:

        post_link = (
            f"https://t.me/"
            f"{channel_username}/"
            f"{found_msg.id}"
        )

    else:

        # Private channel
        channel_id_str = str(
            channel_id
        ).replace("-100", "")

        post_link = (
            f"https://t.me/c/"
            f"{channel_id_str}/"
            f"{found_msg.id}"
        )

    # =====================================================
    # REPLY
    # =====================================================

    reply_text = (
        "👋 **Hello!**\n\n"
        f"📥 **{display_name}** "
        "channel par available hai.\n\n"
        f"👉 {post_link}"
    )

    try:

        await event.reply(
            reply_text,
            link_preview=False
        )

        logging.info(
            f"✅ Replied: {display_name}"
        )

    except Exception as e:

        logging.error(
            f"Reply error: {e}"
        )


# =========================================================
# ❤️ HEALTH CHECK
# =========================================================

@bot.on(events.NewMessage(
    pattern=r"^/ping$"
))
async def ping_handler(event):

    elapsed = datetime.now() - START_TIME

    total_seconds = int(
        elapsed.total_seconds()
    )

    hours = total_seconds // 3600
    minutes = (
        total_seconds % 3600
    ) // 60

    await event.reply(
        "🟢 **BOT ONLINE**\n\n"
        f"⏱ Uptime: `{hours}h {minutes}m`\n"
        "🔎 Live Search: **ON**\n"
        "🔥 Firebase: **ON**"
    )


# =========================================================
# 📖 HELP
# =========================================================

@bot.on(events.NewMessage(
    pattern=r"^/help$"
))
async def help_handler(event):

    await event.reply(
        "🤖 **Public Live Search Bot**\n\n"
        "Commands:\n\n"
        "🚀 `/start` — Start bot\n"
        "⚙️ `/setup` — Channel + Group setup\n"
        "📋 `/mysetup` — Current configuration\n"
        "🗑️ `/reset` — Remove configuration\n"
        "❌ `/cancel` — Cancel setup\n"
        "❤️ `/ping` — Bot status\n"
        "📖 `/help` — Help\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "📢 Bot sirf aapke configured Channel "
        "se search karega.\n\n"
        "👥 Bot sirf aapke configured Group mein "
        "reply karega."
    )


# =========================================================
# 🚀 MAIN
# =========================================================

async def main():

    print("⏳ Starting Telegram Client...")

    await bot.start(
        bot_token=BOT_TOKEN
    )

    me = await bot.get_me()

    print(
        f"✅ Bot Started: "
        f"@{me.username}"
    )

    print(
        f"👑 Owner ID: {OWNER_ID}"
    )

    print(
        "🔎 Public Multi-User Live Search: ON"
    )

    print(
        "🔥 Firebase Configuration Database: ON"
    )

    print(
        "🟢 Bot is ready!"
    )

    await bot.run_until_disconnected()


# =========================================================
# 🏁 RUN
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

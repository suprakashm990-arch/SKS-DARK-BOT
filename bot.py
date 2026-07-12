import os
import sys
import time
import logging
import requests
import asyncio
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient, events

logging.basicConfig(level=logging.INFO)

# 🔐 GitHub Secrets se variables uthana
API_ID = os.environ.get("TG_API_ID")
API_HASH = os.environ.get("TG_API_HASH")
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")

# 🌐 FIREBASE SETTING
FIREBASE_URL = "https://sks-9865a-default-rtdb.firebaseio.com/"

if not API_ID or not API_HASH or not BOT_TOKEN:
    print("\n❌ ERROR: GitHub Secrets sahi se set nahi hain!\n")
    exit(1)

API_ID = int(API_ID)
bot = TelegramClient('dynamic_filter_bot', API_ID, API_HASH)

# 👑 OWNER KI ASLI USER ID
OWNER_ID = 8587571289

# ⏰ SERVER START TIME TRACKER
START_TIME = datetime.now()

# Global Variable to hold dynamic channel ID
TARGET_CHANNEL_ID = None


# --- 📂 CLOUD FIREBASE DATABASE LOGIC ---

def save_post_to_cloud(chat_id, message_id, custom_time=None):
    try:
        post_time = custom_time if custom_time else datetime.now().isoformat()
        data = {
            "chat_id": chat_id,
            "message_id": message_id,
            "post_time": post_time
        }
        requests.put(f"{FIREBASE_URL}auto_posts/{message_id}.json", json=data)
        return True
    except Exception as e:
        logging.error(f"Firebase post save error: {e}")
        return False

def load_all_cloud_posts():
    try:
        response = requests.get(f"{FIREBASE_URL}auto_posts.json")
        if response.status_code == 200 and response.json():
            return response.json()
    except Exception as e:
        logging.error(f"Firebase post load error: {e}")
    return {}

def delete_post_from_cloud(message_id):
    try:
        requests.delete(f"{FIREBASE_URL}auto_posts/{message_id}.json")
    except Exception as e:
        logging.error(f"Firebase delete error: {e}")

def get_rotate_time_minutes():
    try:
        response = requests.get(f"{FIREBASE_URL}rotate_config/minutes.json")
        if response.status_code == 200 and response.json():
            return int(response.json())
    except Exception:
        pass
    return 4320  # Default 3 Din (4320 Minutes)


# 🛠️ 1. AUTOMATIC HISTORICAL DATA SYNC ENGINE
async def sync_historical_channel_posts(target_channel_id):
    logging.info(f"🔄 Starting historical channel post sync for ID: {target_channel_id}...")
    try:
        cloud_posts = load_all_cloud_posts()
        existing_msg_ids = {int(k) for k in cloud_posts.keys()} if cloud_posts else set()
        
        async for message in bot.iter_messages(target_channel_id, limit=300):
            if message.text and not message.text.startswith('/'):
                if message.id not in existing_msg_ids:
                    asli_time = message.date.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
                    save_post_to_cloud(target_channel_id, message.id, custom_time=asli_time)
        logging.info("✅ Historical post sync completed successfully!")
    except Exception as e:
        logging.error(f"Error during historical sync: {e}")


# ⚙️ 2. DYNAMIC FILTER INFO COMMAND
@bot.on(events.NewMessage(pattern=r'/filter (.+?) (https?://\S+)'))
async def set_filter(event):
    if event.sender_id != OWNER_ID:
        await event.reply("❌ Aap is bot ke admin nahi hain!")
        return
    await event.reply("ℹ️ Filter ki zaroorat nahi hai. Bot automatic live search kar leta hai.")
    raise events.StopPropagation


# ⏱️ 3. TELEGRAM SE TIME CONTROL SET KARNA
@bot.on(events.NewMessage(pattern=r'/rotate_time (\d+)'))
async def set_rotate_time(event):
    if event.sender_id != OWNER_ID:
        await event.reply("❌ Aap is bot ke admin nahi hain!")
        return
    
    minutes = int(event.pattern_match.group(1))
    msg_info = f"{minutes} minutes"
    if minutes == 1: msg_info = "1 Minute (Testing Only)"
    elif minutes == 720: msg_info = "12 Ghante"
    elif minutes == 1440: msg_info = "1 Din"
    elif minutes == 4320: msg_info = "3 Din"

    try:
        requests.put(f"{FIREBASE_URL}rotate_config/minutes.json", json=minutes)
        await event.reply(f"⏰ **Rotation Time Updated!**\nAb har **{msg_info}** baad posts automatic rotate honge.")
    except Exception as e:
        await event.reply("❌ Firebase mein time update karne mein error aaya!")
    raise events.StopPropagation


# 💀 4. LIFETIME POST DELETE FROM BOT LOOP
@bot.on(events.NewMessage(pattern=r'/killpost'))
async def kill_post_handler(event):
    if not event.is_reply:
        await event.reply("❌ Kisi aise post par **Reply** karke `/killpost` likhein.")
        return
        
    reply_msg = await event.get_reply_message()
    target_msg_id = reply_msg.id
    target_chat_id = event.chat_id
    
    if reply_msg.fwd_from:
        if reply_msg.fwd_from.saved_from_msg_id:
            target_msg_id = reply_msg.fwd_from.saved_from_msg_id
        if reply_msg.fwd_from.saved_from_peer and hasattr(reply_msg.fwd_from.saved_from_peer, 'channel_id'):
            c_id = reply_msg.fwd_from.saved_from_peer.channel_id
            target_chat_id = int(f"-100{c_id}") if not str(c_id).startswith("-100") else c_id

    delete_post_from_cloud(target_msg_id)
    delete_post_from_cloud(reply_msg.id)
    
    try: await bot.delete_messages(target_chat_id, target_msg_id)
    except Exception: pass
    try: await bot.delete_messages(event.chat_id, reply_msg.id)
    except Exception: pass
    try: await event.delete()
    except Exception: pass
        
    await bot.send_message(event.chat_id, "🗑️ **Lifetime Deleted!** Post permanent clean ho gayi hai.")
    raise events.StopPropagation


# 🚀 5. CHANNEL POST TRACKING LAYER
@bot.on(events.NewMessage)
async def track_channel_posts(event):
    global TARGET_CHANNEL_ID
    if event.is_channel and not event.is_group:
        if event.text and event.text.startswith('/'):
            return
        TARGET_CHANNEL_ID = event.chat_id
        try:
            requests.put(f"{FIREBASE_URL}config/target_channel.json", json=TARGET_CHANNEL_ID)
        except Exception:
            pass
        save_post_to_cloud(event.chat_id, event.id)


# 👥 6. 🔥 MASTER DETECTOR SEARCH ENGINE
@bot.on(events.NewMessage(incoming=True))
async def handle_group_replies(event):
    global TARGET_CHANNEL_ID
    if not event.is_group:
        return
        
    message_text = event.raw_text.lower() if event.raw_text else ""
    if message_text.startswith('/'):
        return

    clean_query = message_text
    for word in ["do", "chahiye", "link", "app", "tv", "kisi ke paas", "hai", "kya", "bhai", "please", "plz", "de do", "dena"]:
        clean_query = clean_query.replace(word, "")
    
    clean_query = clean_query.strip()
    if not clean_query or len(clean_query) < 2:
        return

    try:
        # 1️⃣ Backup Layer 1: Database configuration check
        if not TARGET_CHANNEL_ID:
            try:
                res = requests.get(f"{FIREBASE_URL}config/target_channel.json")
                if res.status_code == 200 and res.json():
                    TARGET_CHANNEL_ID = int(res.json())
            except Exception:
                pass

        # 2️⃣ Backup Layer 2: Load from active cloud rotation logs
        if not TARGET_CHANNEL_ID:
            cloud_posts = load_all_cloud_posts()
            if cloud_posts:
                first_key = list(cloud_posts.keys())[0]
                TARGET_CHANNEL_ID = int(cloud_posts[first_key].get("chat_id"))

        # 3️⃣ Backup Layer 3: Safe Dialog Scanning (Wrapped under try-except block to prevent crash)
        if not TARGET_CHANNEL_ID:
            try:
                async for dialog in bot.iter_dialogs(limit=50):
                    if dialog.is_channel and not dialog.is_group:
                        TARGET_CHANNEL_ID = dialog.id
                        break
            except Exception as e:
                logging.error(f"Dialog scanning bypass: {e}")

        if not TARGET_CHANNEL_ID:
            logging.error("❌ CRITICAL: Target channel could not be resolved.")
            return

        found_msg = None
        async for message in bot.iter_messages(TARGET_CHANNEL_ID, search=clean_query, limit=25):
            if message.text and clean_query in message.text.lower():
                found_msg = message
                break

        if found_msg:
            try:
                channel_entity = await bot.get_entity(TARGET_CHANNEL_ID)
                username = channel_entity.username
                if username:
                    post_link = f"https://t.me/{username}/{found_msg.id}"
                else:
                    encoded_id = str(abs(TARGET_CHANNEL_ID)).replace("100", "", 1)
                    post_link = f"https://t.me/c/{encoded_id}/{found_msg.id}"
            except Exception:
                encoded_id = str(abs(TARGET_CHANNEL_ID)).replace("100", "", 1)
                post_link = f"https://t.me/c/{encoded_id}/{found_msg.id}"

            reply_text = (
                f"👋 Hello,\n\n"
                f"📥 **{clean_query.upper()}** aapke liye Telegram Channel par pehle se hi upload hai!\n\n"
                f"👉 **Yahan se direct download karein:** {post_link}"
            )
            await event.reply(reply_text, link_preview=False)
        else:
            await event.reply(f"⏳ **{clean_query.upper()} Coming Soon...**\nBhai ye app abhi channel par upload nahi hai, jald hi aa jayega!")

    except Exception as e:
        logging.error(f"Live search error: {e}")


# 🔄 7. CORE ENGINE: ADVANCED ROTATION & AUTO-PURGE LOOP
async def check_and_rotate_posts():
    while True:
        elapsed_time = datetime.now() - START_TIME
        if elapsed_time >= timedelta(hours=4, minutes=45):
            os.execv(sys.executable, ['python'] + sys.argv)

        try:
            interval_minutes = get_rotate_time_minutes()
            cloud_posts = load_all_cloud_posts()
            
            for key_id, post_data in list(cloud_posts.items()):
                chat_id = post_data["chat_id"]
                msg_id = int(post_data["message_id"])
                post_time_str = post_data["post_time"]
                
                post_time = datetime.fromisoformat(post_time_str)
                time_threshold = datetime.now() - timedelta(minutes=interval_minutes)
                
                if post_time <= time_threshold:
                    original_msg = None
                    try:
                        original_msg = await bot.get_messages(chat_id, ids=msg_id)
                    except Exception:
                        pass

                    try:
                        await bot.delete_messages(chat_id, msg_id)
                        delete_post_from_cloud(msg_id)
                    except Exception:
                        pass

                    if original_msg and original_msg.text:
                        try:
                            new_msg = await bot.send_message(chat_id, original_msg)
                            if new_msg:
                                save_post_to_cloud(chat_id, new_msg.id)
                        except Exception:
                            pass
                    else:
                        delete_post_from_cloud(msg_id)
                            
        except Exception as e:
            logging.error(f"Cloud Rotation Engine error: {e}")
            
        await asyncio.sleep(20)


# 🚀 CLIENT RUNNER
async def main():
    global TARGET_CHANNEL_ID
    await bot.start(bot_token=BOT_TOKEN)
    
    # 🌟 Multi-Layer Target Resolution on boot
    try:
        res = requests.get(f"{FIREBASE_URL}config/target_channel.json")
        if res.status_code == 200 and res.json():
            TARGET_CHANNEL_ID = int(res.json())
    except Exception:
        pass

    if not TARGET_CHANNEL_ID:
        try:
            async for dialog in bot.iter_dialogs(limit=30):
                if dialog.is_channel and not dialog.is_group:
                    TARGET_CHANNEL_ID = dialog.id
                    requests.put(f"{FIREBASE_URL}config/target_channel.json", json=TARGET_CHANNEL_ID)
                    break
        except Exception as e:
            logging.error(f"Initial boot dialog search bypassed: {e}")
            
    if TARGET_CHANNEL_ID:
        bot.loop.create_task(sync_historical_channel_posts(TARGET_CHANNEL_ID))
        
    bot.loop.create_task(check_and_rotate_posts())
    await bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())

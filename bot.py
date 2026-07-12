import os
import sys
import time
import logging
import requests
import asyncio
from datetime import datetime, timedelta
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

# 🚨 TARGET CHANNEL ID (Apne main channel ki numeric ID yahan daalna zaroor, jaise: -100xxxxxx)
TARGET_CHANNEL_ID = -1002231267890 

# ⏰ SERVER START TIME TRACKER (Auto-Reboot matrix ke liye)
START_TIME = datetime.now()


# --- 📂 CLOUD FIREBASE DATABASE LOGIC ---

def save_post_to_cloud(chat_id, message_id, app_name=""):
    try:
        data = {
            "chat_id": chat_id,
            "message_id": message_id,
            "app_name": app_name.lower().strip(), # App ka naam track karne ke liye
            "post_time": datetime.now().isoformat()
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
    return 720  # Default 12 Ghante


# 1. ⚙️ LINK SET/UPDATE COMMAND (Purana filter code choda hai taaki error na aaye)
@bot.on(events.NewMessage(pattern=r'/filter (.+?) (https?://\S+)'))
async def set_filter(event):
    if event.sender_id != OWNER_ID:
        await event.reply("❌ Aap is bot ke admin nahi hain!")
        return
    await event.reply("ℹ️ Ab aapko filter lagane ki zaroorat nahi hai bhai! Bot direct channel se khoj leta hai.")
    raise events.StopPropagation


# 2. ⏱️ TELEGRAM SE TIME CONTROL SET KARNA
@bot.on(events.NewMessage(pattern=r'/rotate_time (\d+)'))
async def set_rotate_time(event):
    if event.sender_id != OWNER_ID:
        await event.reply("❌ Aap is bot ke admin nahi hain!")
        return
    
    minutes = int(event.pattern_match.group(1))
    
    msg_info = f"{minutes} minutes"
    if minutes == 1: msg_info = "1 Minute (Testing Only)"
    elif minutes == 300: msg_info = "5 Ghante"
    elif minutes == 720: msg_info = "12 Ghante"
    elif minutes == 1440: msg_info = "1 Din"
    elif minutes == 4320: msg_info = "3 Din"
    elif minutes == 10080: msg_info = "7 Din"

    try:
        requests.put(f"{FIREBASE_URL}rotate_config/minutes.json", json=minutes)
        await event.reply(f"⏰ **Rotation Time Updated!**\nAb har **{msg_info}** baad posts automatic rotate honge.")
    except Exception as e:
        await event.reply("❌ Firebase mein time update karne mein error aaya!")
    raise events.StopPropagation


# 3. 💀 LIFETIME POST DELETE FROM BOT LOOP
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

    if reply_msg.reply_to and reply_msg.reply_to.reply_to_top_id:
        target_msg_id = reply_msg.reply_to.reply_to_top_id

    delete_post_from_cloud(target_msg_id)
    delete_post_from_cloud(reply_msg.id)
    
    try: await bot.delete_messages(target_chat_id, target_msg_id)
    except Exception: pass
    try: await bot.delete_messages(event.chat_id, reply_msg.id)
    except Exception: pass
    try: await event.delete()
    except Exception: pass
        
    await bot.send_message(event.chat_id, "🗑️ **Lifetime Deleted!** Post system se permanent clean ho gayi hai.")
    raise events.StopPropagation


# 4. 🚀 CHANNEL POST TRACKING LAYER (Ab Text Content se App Name bhi nikalega)
@bot.on(events.NewMessage)
async def track_channel_posts(event):
    if event.is_channel and not event.is_group:
        if event.text and event.text.startswith('/'):
            return

        chat_id = event.chat_id
        msg_id = event.id
        
        # Post ke pehle line se ya text se app name nikalne ki koshish karna
        app_name_extracted = ""
        if event.text:
            first_line = event.text.split('\n')[0]
            # Agar text me emojis hain toh clean karke app name extract karne ke liye
            app_name_extracted = first_line.replace('🔥', '').replace('🎁', '').replace('⭐', '').strip()
            
        save_post_to_cloud(chat_id, msg_id, app_name_extracted)


# 👥 5. UPGRADED AUTOMATIC SMART REPLY ENGINE (NO FILTERS NEEDED!)
@bot.on(events.NewMessage(incoming=True))
async def handle_group_replies(event):
    if not event.is_group:
        return
        
    message_text = event.raw_text.lower() if event.raw_text else ""
    if message_text.startswith('/'):
        return

    # Trigger words check karna jab user kuch maange (jaise: 'do', 'link', 'app', 'chahiye')
    keywords = ["do", "chahiye", "link", "app", "tv"]
    
    # Agar message me koi bhi app maangne ka ishara ho ya direct app ka naam ho
    if any(word in message_text for word in keywords) or len(message_text.strip().split()) <= 3:
        # Context cleaning ( फालतू words hata kar asli app name nikalna )
        clean_query = message_text
        for word in ["do", "chahiye", "link", "app", "tv", "kisi ke paas", "hai", "kya", "bhai", "please", "plz"]:
            clean_query = clean_query.replace(word, "")
        
        clean_query = clean_query.strip()
        if not clean_query:
            return

        # Firebase me chal rahe active rotations scan karna
        cloud_posts = load_all_cloud_posts()
        found_post = None
        matched_app_name = ""

        for key_id, post_data in cloud_posts.items():
            db_app_name = post_data.get("app_name", "")
            # Match condition: Agar user ka query database ke app name se match ho jaye
            if db_app_name and (db_app_name in clean_query or clean_query in db_app_name):
                found_post = post_data
                matched_app_name = db_app_name
                break

        # Response handling matrix
        if found_post:
            # Channel username fetch karne ki koshish (Public links ke liye)
            try:
                channel_entity = await bot.get_entity(found_post["chat_id"])
                username = channel_entity.username
                if username:
                    post_link = f"https://t.me/{username}/{found_post['message_id']}"
                else:
                    # Private channel format fallback
                    encoded_id = str(abs(found_post["chat_id"])).replace("100", "", 1)
                    post_link = f"https://t.me/c/{encoded_id}/{found_post['message_id']}"
            except Exception:
                post_link = f"https://t.me/c/{str(abs(found_post['chat_id']))}/{found_post['message_id']}"

            reply_text = (
                f"👋 Hello,\n\n"
                f"📥 **{matched_app_name.upper()}** aapke liye Telegram Channel par pehle se hi live hai!\n\n"
                f"👉 **Yahan se direct download karein:** {post_link}"
            )
            await event.reply(reply_text, link_preview=False)
        else:
            # Agar app pure channel database me nahi mila
            # Pure text se target keyword clean karke capital name banana
            display_name = clean_query.upper() if clean_query else "Requested App"
            await event.reply(f"⏳ **{display_name} Coming Soon...**\nBhai ye app abhi channel par nahi hai, jald hi upload kiya jayega!")


# 🔄 6. BACKGROUND ENGINE (Rotation Management + 4h 45m Safe Auto-Reboot)
async def check_and_rotate_posts():
    while True:
        elapsed_time = datetime.now() - START_TIME
        if elapsed_time >= timedelta(hours=4, minutes=45):
            print("🔄 [SAFE REBOOT] restarting to prevent force-kill...")
            os.execv(sys.executable, ['python'] + sys.argv)

        try:
            interval_minutes = get_rotate_time_minutes()
            cloud_posts = load_all_cloud_posts()
            
            for key_id, post_data in cloud_posts.items():
                chat_id = post_data["chat_id"]
                msg_id = post_data["message_id"]
                app_name = post_data.get("app_name", "")
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
                    except Exception:
                        pass

                    if original_msg:
                        try:
                            new_msg = await bot.send_message(chat_id, original_msg)
                            if new_msg:
                                delete_post_from_cloud(msg_id)
                                save_post_to_cloud(chat_id, new_msg.id, app_name)
                        except Exception:
                            pass
                    else:
                        delete_post_from_cloud(msg_id)
                        
        except Exception as e:
            logging.error(f"Cloud Rotation Engine error: {e}")
            
        await asyncio.sleep(15)


# 🚀 CLIENT RUNNER
async def main():
    await bot.start(bot_token=BOT_TOKEN)
    bot.loop.create_task(check_and_rotate_posts())
    await bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())

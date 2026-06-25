import os
import time
import logging
import requests
import sqlite3
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

# 📂 SQLite Local Database Setup (Post Tracking Ke Liye)
def init_db():
    conn = sqlite3.connect('posts.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS auto_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            message_id INTEGER,
            text TEXT,
            media_file_id TEXT,
            post_time TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- FIREBASE DATABASE LOGIC ---
def load_links_from_firebase():
    try:
        response = requests.get(f"{FIREBASE_URL}links.json")
        if response.status_code == 200 and response.json():
            return response.json()
    except Exception as e:
        logging.error(f"Firebase load error: {e}")
    return {}

def save_link_to_firebase(app_name, download_link):
    try:
        requests.put(f"{FIREBASE_URL}links/{app_name}.json", json=download_link)
        return True
    except Exception as e:
        logging.error(f"Firebase save error: {e}")
        return False

def get_rotate_time_minutes():
    """Firebase se rotate karne ka interval nikalna (Default: 720 minutes = 12 hours)"""
    try:
        response = requests.get(f"{FIREBASE_URL}rotate_config/minutes.json")
        if response.status_code == 200 and response.json():
            return int(response.json())
    except Exception:
        pass
    return 720

def save_rotate_time_to_firebase(minutes):
    try:
        requests.put(f"{FIREBASE_URL}rotate_config/minutes.json", json=minutes)
        return True
    except Exception as e:
        logging.error(f"Firebase save time error: {e}")
        return False


# 1. ⚙️ LINK SET/UPDATE COMMAND
@bot.on(events.NewMessage(pattern=r'/filter (.+?) (https?://\S+)'))
async def set_filter(event):
    if event.sender_id != OWNER_ID:
        await event.reply("❌ Aap is bot ke admin nahi hain!")
        return
        
    app_name = event.pattern_match.group(1).lower().strip()
    download_link = event.pattern_match.group(2).strip()
    
    if save_link_to_firebase(app_name, download_link):
        await event.reply(f"✅ Success! App **{app_name.upper()}** ka link Cloud Firebase mein permanent save ho gaya.\n🔗 Link: {download_link}")
    else:
        await event.reply("❌ Firebase Database mein save karne mein koi galti hui!")
    raise events.StopPropagation


# 2. ⏱️ TELEGRAM SE TIME CONTROL SET KARNA
@bot.on(events.NewMessage(pattern=r'/rotate_time (\d+)'))
async def set_rotate_time(event):
    if event.sender_id != OWNER_ID:
        await event.reply("❌ Aap is bot ke admin nahi hain!")
        return
    
    minutes = int(event.pattern_match.group(1))
    if save_rotate_time_to_firebase(minutes):
        await event.reply(f"⏰ **Rotation Time Updated!**\nAb har **{minutes} minutes** baad posts rotate (delete aur repost) honge.")
    else:
        await event.reply("❌ Firebase mein time update karne mein error aaya!")
    raise events.StopPropagation


# 3. 💀 LIFETIME POST DELETE FROM BOT LOOP
@bot.on(events.NewMessage(pattern=r'/killpost'))
async def kill_post_handler(event):
    if event.sender_id != OWNER_ID:
        await event.reply("❌ Aap is bot ke admin nahi hain!")
        return
        
    if not event.is_reply:
        await event.reply("❌ Kisi aise post par **Reply** karke `/killpost` likhein jise lifetime rotate loop se hatana hai.")
        return
        
    reply_msg = await event.get_reply_message()
    target_msg_id = reply_msg.id
    target_chat_id = event.chat_id
    
    # SQLite Database se use permanently uda dena taaki repost na ho
    conn = sqlite3.connect('posts.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM auto_posts WHERE chat_id = ? AND message_id = ?', (target_chat_id, target_msg_id))
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    
    # Channel se bhi manual message delete kar dena
    try:
        await bot.delete_messages(target_chat_id, target_msg_id)
    except Exception:
        pass
        
    if rows_affected > 0:
        await event.reply("🗑️ **Lifetime Deleted!** Yeh post ab rotation system se hamesha ke liye hat gaya hai aur dobara repost nahi hoga.")
    else:
        await event.reply("⚠️ Yeh post bot tracking database mein nahi tha, par channel se delete kar diya gaya hai.")
    raise events.StopPropagation


# 4. 👥 GROUP AUTOMATIC REPLY + NEW MESSAGE TRACKING
@bot.on(events.NewMessage(incoming=True))
async def handle_messages(event):
    message_text = event.raw_text.lower() if event.raw_text else ""
    
    # Agar admin ya koi bhi channel mein post karta hai, toh bot rotation database mein save karega
    if (event.is_channel or event.is_group) and not message_text.startswith('/'):
        chat_id = event.chat_id
        msg_id = event.id
        text = event.text or ""
        
        # Safe structural check for media references
        media_file_id = None
        if event.media:
            media_file_id = event.message.media

        conn = sqlite3.connect('posts.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO auto_posts (chat_id, message_id, text, media_file_id, post_time)
            VALUES (?, ?, ?, ?, ?)
        ''', (chat_id, msg_id, text, str(media_file_id) if media_file_id else None, datetime.now()))
        conn.commit()
        conn.close()

    if message_text.startswith('/filter'):
        return
        
    # Online database se reply match logic execution
    current_links = load_links_from_firebase()
    
    for app_name, download_link in current_links.items():
        if app_name in message_text:
            reply_text = (
                f"👋 Hello,\n\n"
                f"📥 **{app_name.upper()}** ka naya download link ye raha:\n"
                f"👉 {download_link}"
            )
            await event.reply(reply_text, link_preview=False)
            break


# 🔄 5. BACKGROUND ROTATE LAYER (EXACT TIME BASED REPOST)
async def check_and_rotate_posts():
    while True:
        try:
            # Live custom time pull karna (Firebase)
            interval_minutes = get_rotate_time_minutes()
            time_threshold = datetime.now() - timedelta(minutes=interval_minutes)
            
            conn = sqlite3.connect('posts.db')
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM auto_posts WHERE post_time <= ?', (time_threshold,))
            old_posts = cursor.fetchall()
            
            for post in old_posts:
                db_id, chat_id, msg_id, text, media_file_id, post_time = post
                
                # A. Pehle Purana Post Delete Karo
                try:
                    await bot.delete_messages(chat_id, msg_id)
                except Exception as e:
                    logging.info(f"Post already deleted or missing: {e}")

                # B. Same content ko instantly repost karna
                try:
                    new_msg = None
                    if media_file_id:
                        # Re-binding reference check
                        file_payload = eval(media_file_id) if 'MessageMedia' in media_file_id else media_file_id
                        new_msg = await bot.send_message(chat_id, text, file=file_payload)
                    else:
                        new_msg = await bot.send_message(chat_id, text)
                        
                    if new_msg:
                        # C. Base key details ko update karna
                        cursor.execute('DELETE FROM auto_posts WHERE id = ?', (db_id,))
                        cursor.execute('''
                            INSERT INTO auto_posts (chat_id, message_id, text, media_file_id, post_time)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (chat_id, new_msg.id, text, media_file_id, datetime.now()))
                        conn.commit()
                except Exception as e:
                    logging.error(f"Repost failed: {e}")
                    
            conn.close()
        except Exception as e:
            logging.error(f"Rotation engine error: {e}")
            
        # Testing loop support ke liye har 10 second mein evaluation runner trigger chalu rahega
        await asyncio.sleep(10)


# 🚀 CLIENT START OVERRIDE RUNNER
async def main():
    print("🤖 Bot is starting with Firebase Database...")
    await bot.start(bot_token=BOT_TOKEN)
    print("✅ Bot is successfully running 24/7 with Cloud Database & Auto-Rotate Logic!")
    
    # Background thread execution matrix activate karna
    bot.loop.create_task(check_and_rotate_posts())
    await bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())

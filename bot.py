import os
import logging
import requests
from telethon import TelegramClient, events

logging.basicConfig(level=logging.INFO)

# 🔐 GitHub Secrets se variables uthana
API_ID = os.environ.get("TG_API_ID")
API_HASH = os.environ.get("TG_API_HASH")
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")

# 🌐 FIREBASE SETTING
# Apna Firebase URL yahan daalein (Aakhir mein / zaroor lagayein)
FIREBASE_URL = "https://sks-9865a-default-rtdb.firebaseio.com/"

if not API_ID or not API_HASH or not BOT_TOKEN:
    print("\n❌ ERROR: GitHub Secrets sahi se set nahi hain!\n")
    exit(1)

API_ID = int(API_ID)
bot = TelegramClient('dynamic_filter_bot', API_ID, API_HASH)

# 👑 OWNER KI ASLI USER ID
OWNER_ID = 8587571289

# --- FIREBASE DATABASE LOGIC ---
def load_links_from_firebase():
    """Firebase se saare links fetch karne ke liye"""
    try:
        response = requests.get(f"{FIREBASE_URL}links.json")
        if response.status_code == 200 and response.json():
            return response.json()
    except Exception as e:
        logging.error(f"Firebase load error: {e}")
    return {}

def save_link_to_firebase(app_name, download_link):
    """Firebase mein link permanent save karne ke liye"""
    try:
        # App name ko lower case mein hi save karenge uniformly
        requests.put(f"{FIREBASE_URL}links/{app_name}.json", json=download_link)
        return True
    except Exception as e:
        logging.error(f"Firebase save error: {e}")
        return False

# 1. ⚙️ LINK SET/UPDATE COMMAND
@bot.on(events.NewMessage(pattern=r'/filter (.+?) (https?://\S+)'))
async def set_filter(event):
    if event.sender_id != OWNER_ID:
        await event.reply("❌ Aap is bot ke admin nahi hain!")
        return
        
    app_name = event.pattern_match.group(1).lower().strip()
    download_link = event.pattern_match.group(2).strip()
    
    # Firebase mein permanently save karo
    if save_link_to_firebase(app_name, download_link):
        await event.reply(f"✅ Success! App **{app_name.upper()}** ka link Cloud Firebase mein permanent save ho gaya.\n🔗 Link: {download_link}")
    else:
        await event.reply("❌ Firebase Database mein save karne mein koi galti hui!")
    raise events.StopPropagation

# 2. 👥 GROUP AUTOMATIC REPLY
@bot.on(events.NewMessage(incoming=True))
async def handle_messages(event):
    message_text = event.raw_text.lower()
    
    if message_text.startswith('/filter'):
        return
        
    # Har message par online database se fresh links load karo
    # Isse server restart hone par bhi data hamesha live rahega!
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

print("🤖 Bot is starting with Firebase Database...")
bot.start(bot_token=BOT_TOKEN)
print("✅ Bot is successfully running 24/7 with Cloud Database!")
bot.run_until_disconnected()

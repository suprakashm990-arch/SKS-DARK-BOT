import os
import json
import logging
from telethon import TelegramClient, events

logging.basicConfig(level=logging.INFO)

# 🔐 GitHub Secrets se variables uthana
API_ID = os.environ.get("TG_API_ID")
API_HASH = os.environ.get("TG_API_HASH")
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")

if not API_ID or not API_HASH or not BOT_TOKEN:
    print("\n❌ ERROR: GitHub Secrets sahi se set nahi hain!\n")
    exit(1)

API_ID = int(API_ID)
bot = TelegramClient('dynamic_filter_bot', API_ID, API_HASH)

# 👑 OWNER KI ASLI USER ID
OWNER_ID = 8587571289

# 📂 DATABASE FILE NAME
DB_FILE = "links_database.json"

# --- DATABASE LOGIC (File se links load aur save karna) ---
def load_links():
    """File se saare links load karne ke liye"""
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error loading JSON: {e}")
            return {}
    return {}

def save_links(data):
    """File mein links ko permanent save karne ke liye"""
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Error saving JSON: {e}")

# Bot chalu hote hi memory mein purane saved links load karo
APP_LINKS = load_links()
print(f"📦 Loaded {len(APP_LINKS)} links from database file.")

# 1. ⚙️ LINK SET/UPDATE COMMAND
@bot.on(events.NewMessage(pattern=r'/filter (.+?) (https?://\S+)'))
async def set_filter(event):
    global APP_LINKS
    if event.sender_id != OWNER_ID:
        await event.reply("❌ Aap is bot ke admin nahi hain!")
        return
        
    app_name = event.pattern_match.group(1).lower().strip()
    download_link = event.pattern_match.group(2).strip()
    
    # Naya link memory mein daalo aur instantly file mein save kar do
    APP_LINKS[app_name] = download_link
    save_links(APP_LINKS)
    
    await event.reply(f"✅ Success! App **{app_name.upper()}** ka link permanent database mein save ho gaya hai.\n🔗 Link: {download_link}")
    raise events.StopPropagation

# 2. 👥 GROUP AUTOMATIC REPLY
@bot.on(events.NewMessage(incoming=True))
async def handle_messages(event):
    message_text = event.raw_text.lower()
    
    if message_text.startswith('/filter'):
        return
        
    for app_name, download_link in APP_LINKS.items():
        if app_name in message_text:
            reply_text = (
                f"👋 Hello,\n\n"
                f"📥 **{app_name.upper()}** ka naya download link ye raha:\n"
                f"👉 {download_link}"
            )
            await event.reply(reply_text, link_preview=False)
            break

print("🤖 Bot is starting...")
bot.start(bot_token=BOT_TOKEN)
print("✅ Bot is successfully running 24/7 with JSON Database!")
bot.run_until_disconnected()

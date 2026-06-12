import os
import logging
from telethon import TelegramClient, events

logging.basicConfig(level=logging.INFO)

# 🔐 GitHub Secrets se variables uthana
API_ID = os.environ.get("TG_API_ID")
API_HASH = os.environ.get("TG_API_HASH")
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")

# Ekdum saaf check ki kya secrets sahi se load huye hain
if not API_ID or not API_HASH or not BOT_TOKEN:
    print("\n❌ ERROR: GitHub Secrets (TG_API_ID, TG_API_HASH, TG_BOT_TOKEN) sahi se set nahi hain!")
    print("Kripya GitHub Repository Settings -> Secrets mein check karein.\n")
    exit(1)

# API_ID ko integer mein badalna
API_ID = int(API_ID)

# 🤖 Bot client ko chalu karna (Yahan token direct pass ho raha hai bina confirmation ke)
bot = TelegramClient('dynamic_filter_bot', API_ID, API_HASH)

# Dynamic memory space filters ke liye
APP_LINKS = {}

# 👑 OWNER KA USERNAME (Apna original username yahan @ ke sath likhein)
OWNER_USERNAME = "@promodsks_bot"

# 1. ⚙️ LINK SET/UPDATE COMMAND
@bot.on(events.NewMessage(pattern=r'/filter (.+?) (https?://\S+)'))
async def set_filter(event):
    sender = await event.get_sender()
    username = f"@{sender.username}" if sender and sender.username else ""
    
    if username != OWNER_USERNAME:
        await event.reply("❌ Aap is bot ke admin nahi hain!")
        return
        
    app_name = event.pattern_match.group(1).lower().strip()
    download_link = event.pattern_match.group(2).strip()
    
    APP_LINKS[app_name] = download_link
    await event.reply(f"✅ Success! App **{app_name.upper()}** ka link set ho gaya hai.\n🔗 Link: {download_link}")

# 2. 👥 GROUP AUTOMATIC REPLY
@bot.on(events.NewMessage(incoming=True))
async def handle_messages(event):
    message_text = event.raw_text.lower()
    
    if message_text.startswith('/'):
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
print("✅ Bot is successfully running 24/7!")
bot.run_until_disconnected()

import os
import logging
from telethon import TelegramClient, events

logging.basicConfig(level=logging.INFO)

API_ID = int(os.environ.get("TG_API_ID", 123456))
API_HASH = os.environ.get("TG_API_HASH", "YOUR_API_HASH")
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "YOUR_BOT_TOKEN")

bot = TelegramClient('dynamic_filter_bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# 📝 Yahan saare links temporary memory mein save honge
# Note: Agar GitHub workflow restart hoga, toh purane link ud sakte hain. Permanent database ke bina abhi yahi rasta hai.
APP_LINKS = {}

# 👑 OWNER/ADMIN KA TELEGRAM USERNAME (Apna original username yahan @ ke sath likhein)
# Taaki koi dusra banda aapke bot mein link na badal sake!
OWNER_USERNAME = "@YAHAN_APNA_TELEGRAM_USERNAME"

print("🤖 Dynamic Filter Bot Successfully Live...")

# 1. ⚙️ LINK SET/UPDATE KARNE KA COMMAND (Sirf aapke liye)
# Usage on Telegram: /filter story tv https://t.me/your_link
@bot.on(events.NewMessage(pattern=r'/filter (.+?) (https?://\S+)'))
async def set_filter(event):
    sender = await event.get_sender()
    username = f"@{sender.username}" if sender and sender.username else ""
    
    # Security check: Sirf aap hi link badal sakte hain
    if username != OWNER_USERNAME:
        await event.reply("❌ Aap is bot ke admin nahi hain!")
        return
        
    app_name = event.pattern_match.group(1).lower().strip()
    download_link = event.pattern_match.group(2).strip()
    
    # Link save ya update ho jayega
    APP_LINKS[app_name] = download_link
    await event.reply(f"✅ Success! App **{app_name.upper()}** ka link set ho gaya hai.\n🔗 Link: {download_link}")

# 2. 👥 GROUP MEIN AUTOMATIC REPLY DENA
@bot.on(events.NewMessage(incoming=True))
async def handle_messages(event):
    message_text = event.raw_text.lower()
    
    # Agar message command hai (/filter) toh reply mat do
    if message_text.startswith('/'):
        return
        
    # Check karna ki kya user ne saved app ka naam pucha hai
    for app_name, download_link in APP_LINKS.items():
        if app_name in message_text:
            reply_text = (
                f"👋 Hello,\n\n"
                f"📥 **{app_name.upper()}** ka naya download link ye raha:\n"
                f"👉 {download_link}"
            )
            await event.reply(reply_text, link_preview=False)
            break

bot.run_until_disconnected()

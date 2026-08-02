import os
import sys
import time
import logging
import requests
import asyncio
from datetime import datetime, timedelta
from telethon import TelegramClient, events

print("🚀 System Booting Up (Live Search + Cleaner Version)...")
logging.basicConfig(level=logging.INFO)

# 🔐 GitHub Secrets
API_ID = os.environ.get("TG_API_ID")
API_HASH = os.environ.get("TG_API_HASH")
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")

# 🌐 FIREBASE SETTING (Sirf manual Filter links ke liye)
FIREBASE_URL = "https://sks-9865a-default-rtdb.firebaseio.com/"

if not API_ID or not API_HASH or not BOT_TOKEN:
    print("\n❌ ERROR: GitHub Secrets sahi se set nahi hain!\n")
    sys.exit(1)

API_ID = int(API_ID)
bot = TelegramClient('dynamic_filter_bot', API_ID, API_HASH)

# 👑 OWNER KI ASLI USER ID & CHANNEL ID
OWNER_ID = 8587571289
TARGET_CHANNEL_ID = -1003987208966 # Aapka Premium Mod Channel
TARGET_CHANNEL_USER = "PRMMOD"

START_TIME = datetime.now()

# --- 📂 FIREBASE FILTER DATABASE ---
def load_links_from_firebase():
    try:
        response = requests.get(f"{FIREBASE_URL}links.json")
        if response.status_code == 200 and response.json(): return response.json()
    except: pass
    return {}

def save_link_to_firebase(app_name, download_link):
    try:
        requests.put(f"{FIREBASE_URL}links/{app_name}.json", json=download_link)
        return True
    except: return False


# 1. ⚙️ LINK SET/UPDATE COMMAND (/filter)
@bot.on(events.NewMessage(pattern=r'/filter (.+?) (https?://\S+)'))
async def set_filter(event):
    if event.sender_id != OWNER_ID: return
    app_name = event.pattern_match.group(1).lower().strip()
    download_link = event.pattern_match.group(2).strip()
    if save_link_to_firebase(app_name, download_link):
        await event.reply(f"✅ Success! App **{app_name.upper()}** saved.\n🔗 Link: {download_link}")


# 2. 💀 MANUAL POST DELETE COMMAND (/killpost)
@bot.on(events.NewMessage(pattern=r'/killpost'))
async def kill_post_handler(event):
    if not event.is_reply: return
    reply_msg = await event.get_reply_message()
    target_msg_id = reply_msg.id
    target_chat = event.chat_id 
    
    is_channel_post = False
    if event.chat_id == TARGET_CHANNEL_ID:
        target_chat = TARGET_CHANNEL_USER
        is_channel_post = True
    elif reply_msg.fwd_from and reply_msg.fwd_from.channel_post:
        target_msg_id = reply_msg.fwd_from.channel_post
        target_chat = TARGET_CHANNEL_USER
        is_channel_post = True
        
    try: await bot.delete_messages(target_chat, target_msg_id)
    except: pass
        
    if is_channel_post and event.chat_id != TARGET_CHANNEL_ID:
        try: await bot.delete_messages(event.chat_id, reply_msg.id)
        except: pass
        
    try: await event.delete()
    except: pass
    msg = await bot.send_message(event.chat_id, "🗑️ **Post Deleted!**")
    await asyncio.sleep(5)
    try: await msg.delete()
    except: pass


# 3. 🧹 ROSE BOT WELCOME CLEANER (5 Min Auto-Delete)
async def delete_msg_later(event, delay_seconds):
    await asyncio.sleep(delay_seconds)
    try: await event.delete()
    except: pass

@bot.on(events.NewMessage(incoming=True))
async def clean_rose_welcome(event):
    if event.is_group:
        sender = await event.get_sender()
        # Agar message kisi Bot (Jaise Rose) ne bheja hai aur usme welcome likha hai
        if sender and sender.bot and sender.id != bot.uid:
            text = event.raw_text.lower()
            if "welcome" in text or "hey" in text or "made it" in text:
                bot.loop.create_task(delete_msg_later(event, 300)) # 300 sec = 5 minute

@bot.on(events.ChatAction)
async def clean_join_service_msg(event):
    # Telegram ka default "User joined the group" wala kachra message bhi 5 min me uda dega
    if event.is_group and (event.user_joined or event.user_added):
        bot.loop.create_task(delete_msg_later(event, 300))


# 4. 👥 GROUP AUTOMATIC REPLY (Live Search - No Auto Posting)
@bot.on(events.NewMessage(incoming=True))
async def handle_group_replies(event):
    if not event.is_group: return
        
    text = event.raw_text.lower() if event.raw_text else ""
    if not text or text.startswith('/'): return
        
    intent_keywords = {"do", "de", "link", "app", "apk", "mod", "chahiye", "dedo", "bhejo", "tv", "movie", "series", "ott", "premium"}
    message_words = text.split()
    if not any(word in intent_keywords for word in message_words):
        return # Random chat ko ignore karega
    
    stop_words = {"do", "de", "link", "app", "please", "plz", "bhai", "hai", "kya", "chahiye", "dedo", "bhejo", "mujhe", "ko", "mera", "yaar"}
    cleaned_words = [w for w in message_words if w not in stop_words]
    app_name = " ".join(cleaned_words).strip()
    
    if not app_name or len(app_name) < 2: return
    display_name = app_name.upper()

    # Pehle Filter Data check karega
    firebase_links = load_links_from_firebase()
    for saved_app, saved_link in firebase_links.items():
        if saved_app.lower() in app_name or app_name in saved_app.lower():
            await event.reply(f"👋 Hello,\n\n📥 **{saved_app.upper()}** yahan available hai:\n👉 {saved_link}", link_preview=False)
            return

    # Filter me nahi hai, toh Channel me LIVE Search karega
    found_msg = None
    try:
        test_ids = [20000, 15000, 10000, 8000, 5000, 3000, 1000, 500, 100]
        max_id = 500
        try:
            milestones = await event.client.get_messages(TARGET_CHANNEL_ID, ids=test_ids)
            for i, m in enumerate(milestones):
                if m is not None:
                    max_id = test_ids[i] + 500 
                    break
        except: pass
            
        min_id = max(0, max_id - 1000)
        search_ids = list(range(max_id, min_id, -1))
        
        for i in range(0, len(search_ids), 200):
            chunk = search_ids[i:i + 200]
            msgs = await event.client.get_messages(TARGET_CHANNEL_ID, ids=chunk)
            
            for msg in msgs:
                if msg and msg.text and app_name in msg.text.lower():
                    found_msg = msg
                    break
            if found_msg: break
    except: pass
            
    # Agar App mil gayi toh link dega, nahi mili toh CHUP rahega!
    if found_msg:
        c_id_str = str(TARGET_CHANNEL_ID).replace("-100", "")
        post_link = f"https://t.me/c/{c_id_str}/{found_msg.id}"
        reply_text = f"👋 Hello,\n\n📥 **{display_name}** channel par available hai.\n\n👉 {post_link}"
        await event.reply(reply_text, link_preview=False)


# 5. 🔄 GITHUB AUTO-RUNNER (Bot ko 24/7 zinda rakhne ke liye)
async def github_keep_alive():
    while True:
        elapsed_time = datetime.now() - START_TIME
        if elapsed_time >= timedelta(hours=5, minutes=45):
            print("🔄 [GITHUB SAFE REBOOT] Triggering new server...")
            github_token = os.environ.get("MY_GITHUB_TOKEN")
            repo_name = os.environ.get("GITHUB_REPOSITORY")
            if github_token and repo_name:
                try:
                    url = f"https://api.github.com/repos/{repo_name}/actions/workflows/run-bot.yml/dispatches"
                    headers = {"Accept": "application/vnd.github.v3+json", "Authorization": f"token {github_token}"}
                    requests.post(url, headers=headers, json={"ref": "main"})
                except: pass
            os._exit(0)
            
        await asyncio.sleep(600) # Har 10 minute me time check karega


# 🚀 CLIENT RUNNER
async def main():
    print("⏳ Starting Telegram Client...")
    await bot.start(bot_token=BOT_TOKEN)
    print("✅ Client Started!")
    
    bot.loop.create_task(github_keep_alive())
    print("🛡️ Bot is Online 24/7! (No-Post / Pure Live Search Mode)")
    
    await bot.run_until_disconnected()

if __name__ == '__main__':
    try:
        bot.loop.run_until_complete(main())
    except Exception as e:
        print(f"❌ Fatal Loop Error: {e}")

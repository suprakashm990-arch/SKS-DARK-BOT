import os
import sys
import time
import logging
import requests
import asyncio
import re
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.tl.functions.channels import GetFullChannelRequest, LeaveChannelRequest

print("🚀 System Booting Up (Ultimate Public Version)...")
logging.basicConfig(level=logging.INFO)

# 🔐 GitHub Secrets
API_ID = os.environ.get("TG_API_ID")
API_HASH = os.environ.get("TG_API_HASH")
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")

# 🌐 FIREBASE SETTING (Sirf Blacklist/Blocked Chats ke liye)
FIREBASE_URL = "https://sks-9865a-default-rtdb.firebaseio.com/"

if not API_ID or not API_HASH or not BOT_TOKEN:
    print("\n❌ ERROR: GitHub Secrets sahi se set nahi hain!\n")
    sys.exit(1)

API_ID = int(API_ID)
bot = TelegramClient('dynamic_filter_bot', API_ID, API_HASH)

# 👑 OWNER KI ASLI USER ID
OWNER_ID = 8587571289
START_TIME = datetime.now()


# --- 📂 FIREBASE DATABASE LOGIC (Only for Chat Control) ---
def load_blocked_chats():
    try:
        response = requests.get(f"{FIREBASE_URL}blocked_chats.json")
        if response.status_code == 200 and response.json(): 
            return response.json()
    except: pass
    return {}

def block_chat_in_db(chat_id):
    try:
        requests.put(f"{FIREBASE_URL}blocked_chats/{chat_id}.json", json=True)
    except: pass


# 1. 🚪 BOT CONTROL COMMAND (Bot ko kisi chat se nikalna)
@bot.on(events.NewMessage(pattern=r'/leave(?: ([-0-9]+))?'))
async def leave_chat_handler(event):
    if event.sender_id != OWNER_ID: return
    chat_id_arg = event.pattern_match.group(1)
    
    target_chat = int(chat_id_arg) if chat_id_arg else event.chat_id
    
    # Agar direct group me command diya hai
    if target_chat == event.chat_id and not event.is_private:
        await event.reply("👋 Owner ka order! Main is Group/Channel se jaa raha hu. Alvida!")
        
    try:
        # Firebase me ID save kar li (Taaki dubara koi add kare toh ignore kare)
        block_chat_in_db(target_chat)
        
        # Chat se exit hona
        await bot(LeaveChannelRequest(target_chat))
        
        if target_chat != event.chat_id:
            await event.reply(f"✅ Bot successfully Left & Blocked chat ID: `{target_chat}`")
    except Exception as e:
        await event.reply(f"❌ Error: {str(e)}")


# 2. 💀 MANUAL KILL POST COMMAND
@bot.on(events.NewMessage(pattern=r'/killpost'))
async def kill_post_handler(event):
    if not event.is_reply or event.sender_id != OWNER_ID: return
    reply_msg = await event.get_reply_message()
    
    try: await bot.delete_messages(event.chat_id, reply_msg.id)
    except: pass
    
    if reply_msg.fwd_from and reply_msg.fwd_from.saved_from_msg_id:
        target_msg_id = reply_msg.fwd_from.saved_from_msg_id
        if hasattr(reply_msg.fwd_from.saved_from_peer, 'channel_id'):
            c_id = reply_msg.fwd_from.saved_from_peer.channel_id
            target_chat_id = int(f"-100{c_id}") if not str(c_id).startswith("-100") else c_id
            try: await bot.delete_messages(target_chat_id, target_msg_id)
            except: pass

    try: await event.delete()
    except: pass
    msg = await bot.send_message(event.chat_id, "🗑️ **Post hamesha ke liye Delete ho gayi!**")
    await asyncio.sleep(3)
    try: await msg.delete()
    except: pass


# 3. 📢 GLOBAL BROADCAST COMMAND
@bot.on(events.NewMessage(pattern=r'/broadcast'))
async def broadcast_message(event):
    if event.sender_id != OWNER_ID: return
    if not event.is_private:
        await event.reply("❌ Ye command sirf Bot ke Private Chat (DM) me kaam karega.")
        return

    reply_msg = await event.get_reply_message()
    text = event.raw_text.replace('/broadcast', '').strip()

    if not reply_msg and not text:
        await event.reply("❌ Broadcast ke liye: `/broadcast hello` likhein ya kisi post par reply karein.")
        return

    msg = await event.reply("⏳ **Broadcasting started...**")
    success, failed = 0, 0
    blocked_chats = load_blocked_chats()

    async for dialog in bot.iter_dialogs():
        if dialog.is_channel or dialog.is_group:
            if dialog.id == event.chat_id or str(dialog.id) in blocked_chats: 
                continue 
            
            try:
                if reply_msg:
                    await bot.forward_messages(dialog.id, reply_msg)
                else:
                    await bot.send_message(dialog.id, text)
                success += 1
                await asyncio.sleep(1) # Ban se bachne ke liye delay
            except:
                failed += 1

    await msg.edit(f"✅ **Broadcast Complete!**\n🚀 Sent: **{success} chats**\n❌ Failed: **{failed} chats**")


# 4. 👥 PUBLIC GROUP AUTOMATIC REPLY (Smart Engine)
linked_channels_cache = {}

@bot.on(events.NewMessage(incoming=True))
async def handle_group_replies(event):
    if not event.is_group: return
        
    text = event.raw_text.lower() if event.raw_text else ""
    if not text or text.startswith('/'): return
    
    # Check if chat is Blocked by Owner
    blocked_chats = load_blocked_chats()
    if str(event.chat_id) in blocked_chats:
        return # Blocked group me chup rahega

    # Intent Detection
    intent_keywords = {"do", "de", "link", "app", "apk", "mod", "chahiye", "dedo", "bhejo", "tv", "movie", "series", "ott", "premium"}
    message_words = text.split()
    if not any(word in intent_keywords for word in message_words):
        return 
    
    stop_words = {"do", "de", "link", "app", "please", "plz", "bhai", "hai", "kya", "chahiye", "dedo", "bhejo", "mujhe", "ko", "mera", "yaar"}
    cleaned_words = [w for w in message_words if w not in stop_words]
    app_name = " ".join(cleaned_words).strip()
    
    if not app_name or len(app_name) < 2: return
    display_name = app_name.upper()

    # Find Linked Channel Automatically
    chat_id = event.chat_id
    if chat_id not in linked_channels_cache:
        try:
            full_chat = await event.client(GetFullChannelRequest(chat_id))
            if full_chat.full_chat.linked_chat_id:
                raw_id = str(full_chat.full_chat.linked_chat_id)
                linked_channels_cache[chat_id] = int(f"-100{raw_id}") if not raw_id.startswith("-100") else int(raw_id)
            else:
                linked_channels_cache[chat_id] = None 
        except:
            linked_channels_cache[chat_id] = None
            
    channel_id = linked_channels_cache.get(chat_id)
    if not channel_id: return 

    # Search in Channel
    found_msg = None
    try:
        async for msg in event.client.iter_messages(channel_id, limit=200):
            if msg.text and app_name in msg.text.lower():
                found_msg = msg
                break
    except: pass
            
    if found_msg:
        c_id_str = str(channel_id).replace("-100", "")
        post_link = f"https://t.me/c/{c_id_str}/{found_msg.id}"
        reply_text = f"👋 Hello,\n\n📥 **{display_name}** channel par available hai.\n\n👉 {post_link}"
        await event.reply(reply_text, link_preview=False)
    # Agar nahi mila toh CHUP RAHEGA (No coming soon)


# 5. 🗑️ EXPIRE DATE SCANNER & GITHUB AUTO-RESTART
def extract_expire_date(text):
    match = re.search(r'(?i)expir[a-z]*\s*(?:date)?\s*[:-]?\s*(\d{2}[-/.]\d{2}[-/.]\d{4}|\d{4}[-/.]\d{2}[-/.]\d{2})', text)
    if match:
        date_str = match.group(1).replace('.', '-').replace('/', '-')
        try:
            if len(date_str.split('-')[0]) == 2: return datetime.strptime(date_str, "%d-%m-%Y")
            else: return datetime.strptime(date_str, "%Y-%m-%d")
        except: pass
    return None

async def expiry_scanner_and_github_runner():
    while True:
        # ⏰ GITHUB AUTO-REBOOT
        elapsed_time = datetime.now() - START_TIME
        if elapsed_time >= timedelta(hours=5, minutes=45):
            print("🔄 Triggering new GitHub Server...")
            github_token = os.environ.get("MY_GITHUB_TOKEN")
            repo_name = os.environ.get("GITHUB_REPOSITORY")
            if github_token and repo_name:
                try:
                    url = f"https://api.github.com/repos/{repo_name}/actions/workflows/run-bot.yml/dispatches"
                    requests.post(url, headers={"Accept": "application/vnd.github.v3+json", "Authorization": f"token {github_token}"}, json={"ref": "main"})
                except: pass
            os._exit(0)

        # 🗑️ EXPIRE POST SCAN
        print("🔍 Scanning channels for Expired Posts...")
        blocked_chats = load_blocked_chats()
        try:
            async for dialog in bot.iter_dialogs():
                if dialog.is_channel and not dialog.is_group:
                    if str(dialog.id) in blocked_chats: continue
                    try:
                        async for msg in bot.iter_messages(dialog.entity, limit=100):
                            if msg.text:
                                exp_date = extract_expire_date(msg.text)
                                if exp_date and datetime.now() >= exp_date:
                                    try:
                                        await bot.delete_messages(dialog.entity, msg.id)
                                        print(f"🗑️ Deleted Expired Post in {dialog.name}")
                                    except: pass
                    except: pass
        except: pass
            
        await asyncio.sleep(3600) # Har 1 Ghante me scan


# 🚀 CLIENT RUNNER
async def main():
    print("⏳ Starting Client...")
    await bot.start(bot_token=BOT_TOKEN)
    print("✅ Public Bot Online 24/7!")
    bot.loop.create_task(expiry_scanner_and_github_runner())
    await bot.run_until_disconnected()

if __name__ == '__main__':
    try: bot.loop.run_until_complete(main())
    except Exception as e: print(f"❌ Error: {e}")

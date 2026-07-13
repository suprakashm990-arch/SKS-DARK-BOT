import os
import sys
import time
import logging
import requests
import asyncio
from datetime import datetime, timedelta
from telethon import TelegramClient, events

print("ðŸš€ System Booting Up...")
logging.basicConfig(level=logging.INFO)

# ðŸ” GitHub Secrets
API_ID = os.environ.get("TG_API_ID")
API_HASH = os.environ.get("TG_API_HASH")
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")

# ðŸŒ FIREBASE SETTING
FIREBASE_URL = "https://sks-9865a-default-rtdb.firebaseio.com/"

if not API_ID or not API_HASH or not BOT_TOKEN:
    print("\nâŒ ERROR: GitHub Secrets sahi se set nahi hain!\n")
    sys.exit(1)

API_ID = int(API_ID)
bot = TelegramClient('dynamic_filter_bot', API_ID, API_HASH)

# ðŸ‘‘ OWNER KI ASLI USER ID
OWNER_ID = 8587571289
TARGET_CHANNEL_ID = -1003987208966 # Aapka Premium Mod Channel

# â° SERVER START TIME TRACKER 
START_TIME = datetime.now()


# --- ðŸ“‚ CLOUD FIREBASE DATABASE LOGIC ---
def save_post_to_cloud(chat_id, message_id):
    try:
        data = {"chat_id": chat_id, "message_id": message_id, "post_time": datetime.now().isoformat()}
        requests.put(f"{FIREBASE_URL}auto_posts/{message_id}.json", json=data)
        return True
    except: return False

def load_all_cloud_posts():
    try:
        response = requests.get(f"{FIREBASE_URL}auto_posts.json")
        if response.status_code == 200 and response.json(): return response.json()
    except: pass
    return {}

def delete_post_from_cloud(message_id):
    try: requests.delete(f"{FIREBASE_URL}auto_posts/{message_id}.json")
    except: pass

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

def get_rotate_time_minutes():
    try:
        response = requests.get(f"{FIREBASE_URL}rotate_config/minutes.json")
        if response.status_code == 200 and response.json(): return int(response.json())
    except: pass
    return 720  


# 1. âš™ï¸ LINK SET/UPDATE COMMAND
@bot.on(events.NewMessage(pattern=r'/filter (.+?) (https?://\S+)'))
async def set_filter(event):
    if event.sender_id != OWNER_ID: return
    app_name = event.pattern_match.group(1).lower().strip()
    download_link = event.pattern_match.group(2).strip()
    if save_link_to_firebase(app_name, download_link):
        await event.reply(f"âœ… Success! App **{app_name.upper()}** saved.\nðŸ”— Link: {download_link}")


# 2. â±ï¸ TELEGRAM SE TIME CONTROL SET KARNA
@bot.on(events.NewMessage(pattern=r'/rotate_time (\d+)'))
async def set_rotate_time(event):
    if event.sender_id != OWNER_ID: return
    minutes = int(event.pattern_match.group(1))
    try:
        requests.put(f"{FIREBASE_URL}rotate_config/minutes.json", json=minutes)
        await event.reply(f"â° **Rotation Time Updated to {minutes} minutes!**")
    except:
        await event.reply("âŒ Error in updating time!")


# 3. ðŸ’€ LIFETIME POST DELETE FROM BOT
@bot.on(events.NewMessage(pattern=r'/killpost'))
async def kill_post_handler(event):
    if not event.is_reply: return
    reply_msg = await event.get_reply_message()
    target_msg_id = reply_msg.id
    target_chat_id = event.chat_id
    
    if reply_msg.fwd_from and reply_msg.fwd_from.saved_from_msg_id:
        target_msg_id = reply_msg.fwd_from.saved_from_msg_id
        if hasattr(reply_msg.fwd_from.saved_from_peer, 'channel_id'):
            c_id = reply_msg.fwd_from.saved_from_peer.channel_id
            target_chat_id = int(f"-100{c_id}") if not str(c_id).startswith("-100") else c_id

    delete_post_from_cloud(target_msg_id)
    delete_post_from_cloud(reply_msg.id)
    try: await bot.delete_messages(target_chat_id, target_msg_id)
    except: pass
    try: await bot.delete_messages(event.chat_id, reply_msg.id)
    except: pass
    try: await event.delete()
    except: pass
    await bot.send_message(event.chat_id, "ðŸ—‘ï¸ **Lifetime Deleted!**")


# 4. ðŸš€ CHANNEL POST TRACKING LAYER
@bot.on(events.NewMessage)
async def track_channel_posts(event):
    if event.is_channel and not event.is_group:
        if event.text and event.text.startswith('/'): return
        save_post_to_cloud(event.chat_id, event.id)


# 5. ðŸ‘¥ GROUP AUTOMATIC REPLY (Smart Intent + History Bypass)
@bot.on(events.NewMessage(incoming=True))
async def handle_group_replies(event):
    if not event.is_group: return
        
    message_text = event.raw_text.lower() if event.raw_text else ""
    if not message_text or message_text.startswith('/'): return
        
    intent_keywords = {"do", "de", "link", "app", "apk", "mod", "chahiye", "dedo", "bhejo", "tv", "movie", "series", "ott", "premium"}
    message_words = message_text.split()
    has_intent = any(word in intent_keywords for word in message_words)
    
    stop_words = {"do", "de", "link", "app", "please", "plz", "bhai", "hai", "kya", "chahiye", "dedo", "bhejo", "mujhe", "ko", "mera", "yaar"}
    cleaned_words = [w for w in message_words if w not in stop_words]
    app_name = " ".join(cleaned_words).strip()
    
    if not app_name or len(app_name) < 2: return
        
    found_msg = None
    display_name = app_name.upper()
    
    try:
        test_ids = [20000, 15000, 10000, 8000, 5000, 3000, 1000, 500, 200, 100, 50]
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
        chunk_size = 200
        
        for i in range(0, len(search_ids), chunk_size):
            chunk = search_ids[i:i + chunk_size]
            msgs = await event.client.get_messages(TARGET_CHANNEL_ID, ids=chunk)
            
            for msg in msgs:
                if msg and msg.text and app_name in msg.text.lower():
                    found_msg = msg
                    break
            if found_msg: break
    except: pass
            
    if found_msg:
        c_id_str = str(TARGET_CHANNEL_ID).replace("-100", "")
        post_link = f"https://t.me/c/{c_id_str}/{found_msg.id}"
        reply_text = f"ðŸ‘‹ Hello,\n\nðŸ“¥ **{display_name}** channel par available hai.\n\nðŸ‘‰ {post_link}"
        await event.reply(reply_text, link_preview=False)
    else:
        if has_intent:
            reply_text = f"â³ **{display_name}** Coming Soon...\n\nYe app abhi channel par upload nahi hai."
            await event.reply(reply_text, link_preview=False)


# 6. ðŸš€ PURANI POSTS KO EK SATH DATABASE MEIN DAALNE WALA COMMAND (BYPASS TRICK KE SATH)
@bot.on(events.NewMessage(pattern=r'/sync_posts(?: (\d+))?'))
async def sync_old_posts(event):
    valid_admins = [OWNER_ID, TARGET_CHANNEL_ID, 1087968824]
    if event.sender_id not in valid_admins:
        await event.reply(f"âŒ Aap is bot ke admin nahi hain! Tip: Ye command DM me dein.")
        return
        
    limit = event.pattern_match.group(1)
    limit = int(limit) if limit else 50
    msg = await event.reply(f"â³ **Scanning...**\nPichli {limit} posts add ho rahi hain...")
    
    count = 0
    try:
        existing_posts = load_all_cloud_posts()
        existing_ids = [str(v['message_id']) for v in existing_posts.values()] if existing_posts else []
        
        max_id = 500
        test_ids = [50000, 30000, 20000, 10000, 5000, 3000, 1000, 500, 100]
        try:
            milestones = await event.client.get_messages(TARGET_CHANNEL_ID, ids=test_ids)
            for i, m in enumerate(milestones):
                if m is not None:
                    max_id = test_ids[i] + 500
                    break
        except: pass
            
        valid_msgs = []
        search_ids = list(range(max_id, 0, -1))
        
        for i in range(0, len(search_ids), 100):
            if len(valid_msgs) >= limit: break
            chunk = search_ids[i:i + 100]
            msgs = await event.client.get_messages(TARGET_CHANNEL_ID, ids=chunk)
            
            for c_msg in msgs:
                if c_msg and c_msg.text and c_msg.id > 1:
                    valid_msgs.append(c_msg)
                    if len(valid_msgs) >= limit: break
                        
        for c_msg in valid_msgs:
            msg_id_str = str(c_msg.id)
            if msg_id_str not in existing_ids:
                staggered_time = datetime.now() - timedelta(minutes=(count * 5))
                data = {"chat_id": TARGET_CHANNEL_ID, "message_id": c_msg.id, "post_time": staggered_time.isoformat()}
                requests.put(f"{FIREBASE_URL}auto_posts/{c_msg.id}.json", json=data)
                count += 1
                
        await msg.edit(f"âœ… **SUCCESS!**\nTotal **{count} purani posts** system me add ho gayi hain.")
    except Exception as e:
        await msg.edit(f"âŒ **Error:** {str(e)}")
    raise events.StopPropagation


# 7. ðŸ”„ BACKGROUND ENGINE (Rotation + 24/7 GitHub Auto-Runner)
async def check_and_rotate_posts():
    while True:
        elapsed_time = datetime.now() - START_TIME
        if elapsed_time >= timedelta(hours=5, minutes=45):
            print("ðŸ”„ [GITHUB SAFE REBOOT] Triggering new server...")
            github_token = os.environ.get("MY_GITHUB_TOKEN")
            repo_name = os.environ.get("GITHUB_REPOSITORY")
            if github_token and repo_name:
                try:
                    url = f"https://api.github.com/repos/{repo_name}/actions/workflows/run-bot.yml/dispatches"
                    headers = {"Accept": "application/vnd.github.v3+json", "Authorization": f"token {github_token}"}
                    requests.post(url, headers=headers, json={"ref": "main"})
                except: pass
            os._exit(0)

        try:
            interval_minutes = get_rotate_time_minutes()
            cloud_posts = load_all_cloud_posts()
            
            for key_id, post_data in cloud_posts.items():
                chat_id = post_data["chat_id"]
                msg_id = post_data["message_id"]
                post_time_str = post_data["post_time"]
                
                if datetime.fromisoformat(post_time_str) <= (datetime.now() - timedelta(minutes=interval_minutes)):
                    original_msg = None
                    try:
                        target_chat = await bot.get_entity(chat_id)
                    except: target_chat = chat_id

                    try: original_msg = await bot.get_messages(target_chat, ids=msg_id)
                    except: pass

                    try: await bot.delete_messages(target_chat, msg_id)
                    except: pass

                    if original_msg:
                        try:
                            new_msg = await bot.send_message(target_chat, original_msg)
                            if new_msg:
                                delete_post_from_cloud(msg_id)
                                save_post_to_cloud(chat_id, new_msg.id)
                        except: pass
                    else:
                        delete_post_from_cloud(msg_id)
        except: pass
            
        await asyncio.sleep(15)


# ðŸš€ CLIENT RUNNER
async def main():
    print("â³ Starting Telegram Client...")
    await bot.start(bot_token=BOT_TOKEN)
    print("âœ… Client Started! Booting background engine...")
    bot.loop.create_task(check_and_rotate_posts())
    print("ðŸ›¡ï¸ Bot is Online 24/7! Listening for messages...")
    await bot.run_until_disconnected()

if __name__ == '__main__':
    try:
        bot.loop.run_until_complete(main())
    except Exception as e:
        print(f"âŒ Fatal Loop Error: {e}")

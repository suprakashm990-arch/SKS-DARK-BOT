import os
import sys
import time
import logging
import requests
import asyncio
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.tl.functions.channels import GetFullChannelRequest

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

# ⏰ SERVER START TIME TRACKER (Auto-Reboot matrix ke liye)
START_TIME = datetime.now()


# --- 📂 CLOUD FIREBASE DATABASE LOGIC ---

def save_post_to_cloud(chat_id, message_id):
    try:
        data = {
            "chat_id": chat_id,
            "message_id": message_id,
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
    try:
        response = requests.get(f"{FIREBASE_URL}rotate_config/minutes.json")
        if response.status_code == 200 and response.json():
            return int(response.json())
    except Exception:
        pass
    return 720  # Default 12 Ghante


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
    
    # Validation info array UI message ke liye
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
    
    try:
        await bot.delete_messages(target_chat_id, target_msg_id)
    except Exception:
        pass
    try:
        await bot.delete_messages(event.chat_id, reply_msg.id)
    except Exception:
        pass
    try:
        await event.delete()
    except Exception:
        pass
        
    await bot.send_message(event.chat_id, "🗑️ **Lifetime Deleted!** Post system se permanent clean ho gayi hai.")
    raise events.StopPropagation


# 4. 🚀 CHANNEL POST TRACKING LAYER (Hidden Link Friendly Object Saver)
@bot.on(events.NewMessage)
async def track_channel_posts(event):
    if event.is_channel and not event.is_group:
        if event.text and event.text.startswith('/'):
            return

        chat_id = event.chat_id
        msg_id = event.id
        save_post_to_cloud(chat_id, msg_id)

# 5. 👥 GROUP AUTOMATIC REPLY (SMART INTENT DETECTION + HACKER TRICK)
@bot.on(events.NewMessage(incoming=True))
async def handle_group_replies(event):
    if not event.is_group:
        return
        
    message_text = event.raw_text.lower() if event.raw_text else ""
    if not message_text or message_text.startswith('/'):
        return
        
    # --- 🧠 SMART INTENT DETECTION ---
    # Sirf in words ke hone par hi bot 'Coming Soon' bolega (Random chat ko ignore karega)
    intent_keywords = {"do", "de", "link", "app", "apk", "mod", "chahiye", "dedo", "bhejo", "tv", "movie", "series", "ott", "premium"}
    message_words = message_text.split()
    
    # Kya user ne sach me koi App/Link manga hai?
    has_intent = any(word in intent_keywords for word in message_words)
    
    # Message ko saaf karna (faltu words hatana)
    stop_words = {"do", "de", "link", "app", "please", "plz", "bhai", "hai", "kya", "chahiye", "dedo", "bhejo", "mujhe", "ko", "mera", "yaar"}
    cleaned_words = [w for w in message_words if w not in stop_words]
    app_name = " ".join(cleaned_words).strip()
    
    # Agar message me bacha hi kuch nahi (eg: "bhai kya hai") to ignore karo
    if not app_name or len(app_name) < 2:
        return
        
    TARGET_CHANNEL = 'PRMMOD'
    found_msg = None
    display_name = app_name.upper()
    
    try:
        # 🚀 FAST CHUNK SEARCH (Bypassing History Ban)
        test_ids = [20000, 15000, 10000, 8000, 5000, 3000, 1000, 500, 200, 100, 50]
        max_id = 500
        
        try:
            milestones = await event.client.get_messages(TARGET_CHANNEL, ids=test_ids)
            for i, m in enumerate(milestones):
                if m is not None:
                    max_id = test_ids[i] + 500 
                    break
        except Exception:
            pass
            
        # Sirf aakhiri 1000 posts scan karenge speed ke liye
        min_id = max(0, max_id - 1000)
        search_ids = list(range(max_id, min_id, -1))
        chunk_size = 200
        
        for i in range(0, len(search_ids), chunk_size):
            chunk = search_ids[i:i + chunk_size]
            msgs = await event.client.get_messages(TARGET_CHANNEL, ids=chunk)
            
            for msg in msgs:
                if msg and msg.text:
                    # Agar user ne 'kuku' likha, aur post me 'Kuku TV' hai -> Perfect Match ho jayega!
                    if app_name in msg.text.lower():
                        found_msg = msg
                        break
            if found_msg:
                break
                    
    except Exception:
        pass
            
    if found_msg:
        try:
            post_link = f"https://t.me/{TARGET_CHANNEL}/{found_msg.id}"
                
            reply_text = (
                f"👋 Hello,\n\n"
                f"📥 **{display_name}** channel par available hai.\n\n"
                f"👉 {post_link}"
            )
            await event.reply(reply_text, link_preview=False)
        except Exception:
            pass
    else:
        # 🛑 FIX: Agar App nahi mili aur user ne 'do/link' manga hai, tabhi reply karega
        if has_intent:
            reply_text = (
                f"⏳ **{display_name}** Coming Soon...\n\n"
                f"Ye app abhi channel par upload nahi hai."
            )
            await event.reply(reply_text, link_preview=False)


# ðŸ”„ 6. BACKGROUND ENGINE (Rotation + 24/7 GitHub Auto-Runner + 3 Day Fix)
async def check_and_rotate_posts():
    while True:
        # â° 24/7 GITHUB AUTO-REBOOT HACK
        elapsed_time = datetime.now() - START_TIME
        
        # Theek 5 ghante 45 minute baad naya server trigger hoga
        if elapsed_time >= timedelta(hours=5, minutes=45):
            print("ðŸ”„ [GITHUB SAFE REBOOT] 5 Ghante 45 Min pure hue! Naya server start kar raha hu...")
            
            # Aapka GitHub Token aur Repo Name automatically fetch hoga
            github_token = os.environ.get("MY_GITHUB_TOKEN")
            repo_name = os.environ.get("GITHUB_REPOSITORY")
            
            if github_token and repo_name:
                try:
                    url = f"https://api.github.com/repos/{repo_name}/actions/workflows/run-bot.yml/dispatches"
                    headers = {
                        "Accept": "application/vnd.github.v3+json",
                        "Authorization": f"token {github_token}"
                    }
                    # GitHub ko request bhej di ki naya Action chalu karo
                    requests.post(url, headers=headers, json={"ref": "main"})
                    print("âœ… Naya GitHub Action Server trigger ho gaya!")
                except Exception as e:
                    print(f"âŒ API Error: {e}")
                    
            # Request bhejte hi purana script turant band ho jayega
            os._exit(0)

        # --- Purana Rotation Logic (3-Day Fix Ke Sath) ---
        try:
            interval_minutes = get_rotate_time_minutes()
            cloud_posts = load_all_cloud_posts()
            
            for key_id, post_data in cloud_posts.items():
                chat_id = post_data["chat_id"]
                msg_id = post_data["message_id"]
                post_time_str = post_data["post_time"]
                
                post_time = datetime.fromisoformat(post_time_str)
                time_threshold = datetime.now() - timedelta(minutes=interval_minutes)
                
                if post_time <= time_threshold:
                    original_msg = None
                    try:
                        target_chat = await bot.get_entity(chat_id)
                    except Exception:
                        target_chat = chat_id

                    try:
                        original_msg = await bot.get_messages(target_chat, ids=msg_id)
                    except Exception:
                        pass

                    try:
                        await bot.delete_messages(target_chat, msg_id)
                    except Exception as e:
                        logging.info(f"Post already gone: {e}")

                    if original_msg:
                        try:
                            new_msg = await bot.send_message(target_chat, original_msg)
                            if new_msg:
                                delete_post_from_cloud(msg_id)
                                save_post_to_cloud(chat_id, new_msg.id)
                        except Exception as e:
                            logging.error(f"Repost failed: {e}")
                    else:
                        delete_post_from_cloud(msg_id)
                        
        except Exception as e:
            logging.error(f"Cloud Rotation Engine error: {e}")
            
        await asyncio.sleep(15)


# 7. ðŸš€ PURANI POSTS KO EK SATH DATABASE MEIN DAALNE WALA COMMAND (BYPASS TRICK KE SATH)
@bot.on(events.NewMessage(pattern=r'/sync_posts(?: (\d+))?'))
async def sync_old_posts(event):
    valid_admins = [OWNER_ID, -1003987208966, 1087968824]
    
    if event.sender_id not in valid_admins:
        await event.reply(f"âŒ Aap is bot ke admin nahi hain!\n(Aapki system ID `{event.sender_id}` hai)\n\nðŸ‘‰ **Tip:** Ye command seedha Bot ke Private Message (DM) me dein.")
        return
        
    limit = event.pattern_match.group(1)
    limit = int(limit) if limit else 50
    
    TARGET_CHANNEL = -1003987208966 # Aapka Channel ID
    
    msg = await event.reply(f"â³ **Scanning...**\nChannel ki pichli {limit} posts ko database me add kiya jaa raha hai. Kripya wait karein...")
    
    count = 0
    try:
        existing_posts = load_all_cloud_posts()
        existing_ids = [str(v['message_id']) for v in existing_posts.values()] if existing_posts else []
        
        # --- ðŸš€ HACKER TRICK: Bypassing History Ban ---
        max_id = 500
        test_ids = [50000, 30000, 20000, 10000, 5000, 3000, 1000, 500, 100]
        try:
            milestones = await event.client.get_messages(TARGET_CHANNEL, ids=test_ids)
            for i, m in enumerate(milestones):
                if m is not None:
                    max_id = test_ids[i] + 500
                    break
        except Exception:
            pass
            
        valid_msgs = []
        search_ids = list(range(max_id, 0, -1))
        chunk_size = 100
        
        # Reverse me ID check karega bina history mange
        for i in range(0, len(search_ids), chunk_size):
            if len(valid_msgs) >= limit:
                break
            chunk = search_ids[i:i + chunk_size]
            
            # Fetch specific IDs (Bots allowed)
            msgs = await event.client.get_messages(TARGET_CHANNEL, ids=chunk)
            
            for channel_msg in msgs:
                if channel_msg and channel_msg.text and channel_msg.id > 1:
                    valid_msgs.append(channel_msg)
                    if len(valid_msgs) >= limit:
                        break
                        
        # ðŸš€ Ab pakdi gayi posts ko Firebase me save karna
        for channel_msg in valid_msgs:
            msg_id_str = str(channel_msg.id)
            if msg_id_str not in existing_ids:
                # Har post me 5 min ka gap (Spam se bachne ke liye)
                staggered_time = datetime.now() - timedelta(minutes=(count * 5))
                
                data = {
                    "chat_id": TARGET_CHANNEL,
                    "message_id": channel_msg.id,
                    "post_time": staggered_time.isoformat()
                }
                
                requests.put(f"{FIREBASE_URL}auto_posts/{channel_msg.id}.json", json=data)
                count += 1
                
        await msg.edit(f"âœ… **SUCCESS!**\n\nTotal **{count} purani posts** system me add ho gayi hain.\nAb ye saari posts automatic rotate hoti rahengi!")
        
    except Exception as e:
        await msg.edit(f"âŒ **Error Aaya:**\n`{str(e)}`")
    raise events.StopPropagation
    

import os
import sys
import time
import logging
import requests
import asyncio
from datetime import datetime, timedelta
from telethon import TelegramClient, events, Button
from telethon.tl.functions.channels import EditBannedRequest
from telethon.tl.types import ChatBannedRights

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

# 👑 OWNER KI ASLI USER ID (Sirf aapke liye secure access)
OWNER_ID = 8587571289

# ⏰ SERVER START TIME TRACKER
START_TIME = datetime.now()

# 🛠️ STATE CONTEXT ENGINE (Interactive Chat Input Store)
user_states = {}

# --- 📂 CLOUD FIREBASE DATABASE LOGIC ---

def save_post_to_cloud(chat_id, message_id, app_name="generic"):
    try:
        data = {
            "chat_id": chat_id,
            "message_id": message_id,
            "app_name": app_name,
            "post_time": datetime.now().isoformat()
        }
        requests.put(f"{FIREBASE_URL}auto_posts/{message_id}.json", json=data)
        return True
    except Exception as e:
        logging.error(f"Firebase save error: {e}"); return False

def load_all_cloud_posts():
    try:
        response = requests.get(f"{FIREBASE_URL}auto_posts.json")
        if response.status_code == 200 and response.json(): return response.json()
    except Exception as e: logging.error(f"Firebase load error: {e}")
    return {}

def delete_post_from_cloud(message_id):
    try: requests.delete(f"{FIREBASE_URL}auto_posts/{message_id}.json")
    except Exception as e: logging.error(f"Firebase delete error: {e}")

def get_rotate_time_minutes():
    try:
        response = requests.get(f"{FIREBASE_URL}rotate_config/minutes.json")
        if response.status_code == 200 and response.json(): return int(response.json())
    except Exception: pass
    return 720

# 🆕 Dynamic Text Template Engine Methods
def get_firebase_data(path):
    try:
        res = requests.get(f"{FIREBASE_URL}{path}.json")
        if res.status_code == 200: return res.json()
    except Exception: pass
    return None

def save_firebase_data(path, data):
    try: requests.put(f"{FIREBASE_URL}{path}.json", json=data); return True
    except Exception: return False


# ====================================================================
# 🎛️ NATIVE TELEGRAM SIDE-MENU SETTINGS GENERATOR (ON STARTUP)
# ====================================================================
async def setup_bot_menu():
    from telethon.tl.functions.bots import SetBotCommandsRequest
    from telethon.tl.types import BotCommand, BotCommandScopeDefault
    commands = [
        BotCommand(command="start", description="Check Bot Is Alive (Status)"),
        BotCommand(command="upload_post", description="Post Engine (App Name + Download Link)"),
        BotCommand(command="set_text", description="Set/Update Custom Post Text Layout"),
        BotCommand(command="add_image", description="Add Permanent App Image (Name + Link)"),
        BotCommand(command="delete_image", description="Delete Saved App Image Link"),
        BotCommand(command="setup_welcome", description="Set Welcome Banner Image & Text (1-Min Delete)"),
        BotCommand(command="setup_antilink", description="Set Custom Anti-Link Messages & Warnings"),
        BotCommand(command="group_lock", description="Lock Group (All users message lock)"),
        BotCommand(command="group_unlock", description="Unlock Group (All users message open)"),
        BotCommand(command="user_panel", description="Master Controls (Ban/Unban/Mute/Unmute)"),
        BotCommand(command="cancel", description="Cancel Any Ongoing Setup Mode")
    ]
    await bot(SetBotCommandsRequest(scope=BotCommandScopeDefault(), lang_code="", commands=commands))


# ====================================================================
# 🚀 CORE ROUTING ENGINE & INTERACTIVE INPUT CONTROL MATCH
# ====================================================================

@bot.on(events.NewMessage)
async def master_input_router(event):
    if event.text and event.text.startswith('/cancel'):
        if event.sender_id == OWNER_ID:
            user_states.pop(OWNER_ID, None)
            await event.reply("❌ Ongoing Setup Mode ko cancel kar diya gaya hai bhai.")
        return

    # Check if admin is currently in a text configuration input stage
    if event.sender_id == OWNER_ID and OWNER_ID in user_states:
        state = user_states[OWNER_ID]
        current_step = state["step"]
        
        if current_step == "set_text_layout":
            if save_firebase_data("templates/post_layout", event.text):
                await event.reply("✅ **Post Text Format Updated Successfully!** Ab bot isi format me templates banaega.")
            else:
                await event.reply("❌ Database sync issue! Dubara koshish karein.")
            user_states.pop(OWNER_ID, None)
            return

        elif current_step == "welcome_image":
            state["welcome_img"] = event.text.strip()
            state["step"] = "welcome_text"
            await event.reply("📝 Ab **Welcome Text Message** type karke bhejiye jisme user ka naam add karna ho:")
            return

        elif current_step == "welcome_text":
            welcome_data = {"image": state["welcome_img"], "text": event.text}
            if save_firebase_data("config/welcome", welcome_data):
                await event.reply("👋 **Welcome Banner & Text Setup Configured!** Naye users ko 1-min auto-delete system ke sath dikhega.")
            user_states.pop(OWNER_ID, None)
            return

        elif current_step == "antilink_text":
            if save_firebase_data("config/antilink_msg", event.text):
                await event.reply("🛡️ **Anti-Link Warning Text Successfully Configured!**")
            user_states.pop(OWNER_ID, None)
            return


# ====================================================================
# 🎛️ SIDE-MENU COMMAND FUNCTIONAL INTERFACES
# ====================================================================

@bot.on(events.NewMessage(pattern=r'/start'))
async def alive_checker(event):
    uptime = str(datetime.now() - START_TIME).split('.')[0]
    await event.reply(
        f"🟢 **SKS HYBRID CORE IS ALIVE V3.0**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👑 **Owner ID:** `{OWNER_ID}` (Personal Secure Mode)\n"
        f"⏰ **Bot Uptime:** `{uptime}`\n"
        f"🛡️ **System Check:** Database Fully Integrated!\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👉 Side-menu ka upyog karke saare features live chalaein bhai!"
    )

@bot.on(events.NewMessage(pattern=r'/set_text'))
async def trigger_set_text(event):
    if event.sender_id != OWNER_ID: return
    user_states[OWNER_ID] = {"step": "set_text_layout"}
    await event.reply(
        "📝 **POST FORMAT CONFIGURATOR**\n\n"
        "Bhai, apna naya design kiya hua text layout bhejiye.\n"
        "Layout ke andar jahan app ka naam aana hai wahan `{app_name}` aur jahan download link aana hai wahan `{download_link}` placeholder ka hi use karein!"
    )

@bot.on(events.NewMessage(pattern=r'/setup_welcome'))
async def trigger_setup_welcome(event):
    if event.sender_id != OWNER_ID: return
    user_states[OWNER_ID] = {"step": "welcome_image"}
    await event.reply("🖼️ **WELCOME MODULE SETUP**\n\nBhai, pehle Welcome Image Banner ka **Link (URL)** bhejiye:")

@bot.on(events.NewMessage(pattern=r'/setup_antilink'))
async def trigger_setup_antilink(event):
    if event.sender_id != OWNER_ID: return
    user_states[OWNER_ID] = {"step": "antilink_text"}
    await event.reply(
        "🛡️ **ANTI-LINK MESSAGE CONFIGURATOR**\n\n"
        "Bhai, jab koi user group me link bhejega toh use kya warning message dena hai wo type karke bhejiye.\n"
        "*(Note: Text me user ke naam ke liye `{user_name}` aur warning number ke liye `{warn_count}` ka use karein)*"
    )

# 🖼️ Add App Image Link Permanent
@bot.on(events.NewMessage(pattern=r'/add_image (.+?) (https?://\S+)'))
async def add_app_image(event):
    if event.sender_id != OWNER_ID: return
    app_name = event.pattern_match.group(1).lower().strip()
    img_link = event.pattern_match.group(2).strip()
    if save_firebase_data(f"app_images/{app_name}", img_link):
        await event.reply(f"✅ Success! App **{app_name.upper()}** ka image link database me lock ho gaya.\n🖼️ URL: {img_link}")

# 🗑️ Delete Saved App Image Link via Target App Name Only
@bot.on(events.NewMessage(pattern=r'/delete_image (.+)'))
async def delete_app_image(event):
    if event.sender_id != OWNER_ID: return
    app_name = event.pattern_match.group(1).lower().strip()
    try:
        requests.delete(f"{FIREBASE_URL}app_images/{app_name}.json")
        await event.reply(f"🗑️ **Image Cleaned!** App **{app_name.upper()}** ka image link database se delete ho gaya.")
    except Exception:
        await event.reply("❌ Error while clearing from database!")


# ====================================================================
# 📦 POST & AUTO-PURGE PRODUCTION ENGINE
# ====================================================================
@bot.on(events.NewMessage(pattern=r'/upload_post (.+?) (https?://\S+)'))
async def production_post_engine(event):
    if event.sender_id != OWNER_ID: return
    app_name = event.pattern_match.group(1).lower().strip()
    download_link = event.pattern_match.group(2).strip()

    # Database validation lookups
    layout_template = get_firebase_data("templates/post_layout")
    app_image_url = get_firebase_data(f"app_images/{app_name}")

    if not layout_template:
        await event.reply("❌ Bhai, pehle `/set_text` command use karke post text template layout set kijiye!"); return
    if not app_image_url:
        await event.reply(f"❌ Error: **{app_name.upper()}** ki image database me nahi hai. Pehle `/add_image {app_name} link` karke permanent save karein."); return

    # 🔄 Auto-Purge Policy Evaluation (Check and permanent clean old post matching app_name)
    all_active_posts = load_all_cloud_posts()
    for msg_id, p_data in list(all_active_posts.items()):
        if p_data.get("app_name") == app_name:
            try:
                await bot.delete_messages(p_data["chat_id"], int(msg_id))
                delete_post_from_cloud(int(msg_id))
                logging.info(f"Auto-Purge executed for old post: {msg_id}")
            except Exception: pass

    # Dynamic format reconstruction without using un-escaped hyper-constructs
    formatted_caption = layout_template.replace("{app_name}", app_name.upper()).replace("{download_link}", download_link)

    # Compile rotation post targeting active workspace channel destination dynamically
    target_channel_id = get_firebase_data("config/target_channel")
    if not target_channel_id:
        target_channel_id = event.chat_id # Default fallback to chat if console channel unmapped

    try:
        new_post = await bot.send_message(target_channel_id, formatted_caption, file=app_image_url, link_preview=False)
        save_post_to_cloud(target_channel_id, new_post.id, app_name)
        await event.reply(f"🚀 **New Post Uploaded & Old Post Purged Successfully!** App: {app_name.upper()}")
    except Exception as e:
        await event.reply(f"❌ Post Upload Failed! Logic stack trace: {e}")


# ====================================================================
# 🔒 LOCK & UNLOCK GROUP PERMISSIONS MANAGEMENT MATRIX
# ====================================================================
async def toggle_group_lock(event, lock_status):
    if event.sender_id != OWNER_ID: return
    rights = ChatBannedRights(until_date=None, send_messages=lock_status, send_media=lock_status, send_stickers=lock_status, send_gifs=lock_status)
    try:
        await bot(EditBannedRequest(channel=event.chat_id, participant=event.chat_id, banned_rights=rights))
        msg = "🔒 **GROUP ALL LOCKED!** Ab mere owner ke alawa koi bhi member message nahi kar payega." if lock_status else "🔓 **GROUP ALL UNLOCKED!** Saare users ab chat kar sakte hain."
        await event.reply(msg)
    except Exception as e:
        await event.reply(f"❌ Permission update system issue: {e}")

@bot.on(events.NewMessage(pattern=r'/group_lock'))
async def lock_engine(event): await toggle_group_lock(event, True)

@bot.on(events.NewMessage(pattern=r'/group_unlock'))
async def unlock_engine(event): await toggle_group_lock(event, False)


# ====================================================================
# 🛡️ HARDCORE ANTI-LINK & 3-WARNING ENFORCEMENT ENGINE
# ====================================================================
user_warn_matrix = {}

@bot.on(events.NewMessage(incoming=True))
async def anti_link_protection(event):
    if not event.is_group or event.sender_id == OWNER_ID: return
    
    # 📝 Auto Error/Problem keyword interceptor logic
    msg_text = event.raw_text.lower() if event.raw_text else ""
    if any(kw in msg_text for kw in ["problem", "not working", "kaam nahi kar raha"]):
        await event.reply("⚠️ Aapka message check kiya ja raha hai... Team jald hi aapki problem solve karegi!")
        return

    # Check for link markers in incoming streams
    has_link = False
    if event.entities:
        for entity in event.entities:
            from telethon.tl.types import MessageEntityUrl, MessageEntityTextUrl
            if isinstance(entity, (MessageEntityUrl, MessageEntityTextUrl)): has_link = True; break
    if not has_link and any(marker in msg_text for marker in ["t.me/", "http://", "https://", "www."]):
        has_link = True

    if has_link:
        user = await event.get_sender()
        user_id = event.sender_id
        user_name = getattr(user, 'first_name', 'User')

        try: await event.delete()
        except Exception: pass

        # Warning counting matrix map
        current_warns = user_warn_matrix.get(user_id, 0) + 1
        user_warn_matrix[user_id] = current_warns

        if current_warns < 3:
            custom_warn_layout = get_firebase_data("config/antilink_msg")
            if not custom_warn_layout:
                custom_warn_layout = "⚠️ Hello {user_name}, Links are strictly blocked in this workspace! [Warning: {warn_count}/3]"
            warn_reply = custom_warn_layout.replace("{user_name}", user_name).replace("{warn_count}", str(current_warns))
            await event.respond(warn_reply)
        else:
            # 🚨 3rd Strike Reached - Execute immediate mute lockdown and trigger Owner Action Center Matrix
            user_warn_matrix[user_id] = 0 # reset tracking
            mute_rights = ChatBannedRights(until_date=None, send_messages=True)
            try: await bot(EditBannedRequest(channel=event.chat_id, participant=user_id, banned_rights=mute_rights))
            except Exception: pass

            action_text = (
                f"🚨 **STRIKE 3 OUT: SPAM LIMIT REACHED!** 🚨\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 **User:** {user_name} (ID: `{user_id}`)\n"
                f"🛑 **Reason:** Group me link spamming ki limits break ki hain.\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Owner Bhai, faisla kijiye is user ke sath kya karna hai:"
            )
            buttons = [
                [Button.inline("🔨 Permanent Ban", data=f"act_ban_{user_id}_{event.chat_id}"),
                 Button.inline("🔊 Unmute Member", data=f"act_unmute_{user_id}_{event.chat_id}")],
                [Button.inline("🕊️ Forgive (Keep Mute)", data="act_dismiss")]
            ]
            await bot.send_message(OWNER_ID, action_text, buttons=buttons)


# Callback interface parsing admin processing button events
@bot.on(events.CallbackQuery)
async def process_owner_actions(event):
    if event.sender_id != OWNER_ID: return
    data = event.data.decode('utf-8')
    
    if data.startswith("act_"):
        tokens = data.split("_")
        action = tokens[1]
        
        if action == "dismiss":
            await event.edit("🔒 User ko locked-mute status pe maintain rakha gaya hai.")
            return
            
        target_uid = int(tokens[2])
        target_cid = int(tokens[3])
        
        if action == "ban":
            ban_rights = ChatBannedRights(until_date=None, view_messages=True, send_messages=True, send_media=True)
            try:
                await bot(EditBannedRequest(channel=target_cid, participant=target_uid, banned_rights=ban_rights))
                await event.edit("🔨 **User Successfully Banned Everywhere!** Base cleared.")
            except Exception as e: await event.edit(f"❌ Ban System Error: {e}")
            
        elif action == "unmute":
            open_rights = ChatBannedRights(until_date=None, send_messages=False, send_media=False)
            try:
                await bot(EditBannedRequest(channel=target_cid, participant=target_uid, banned_rights=open_rights))
                await event.edit("🔊 **User Unmuted!** Dubara group me chat kar payega.")
            except Exception as e: await event.edit(f"❌ Unmute System Error: {e}")


# ====================================================================
# 👋 SMART USER WELCOME WITH 1-MINUTE AUTO-DELETE TIMEOUT LOGIC
# ====================================================================
@bot.on(events.ChatAction)
async def smart_welcome_handler(event):
    if event.user_joined or event.user_added:
        welcome_config = get_firebase_data("config/welcome")
        if not welcome_config: return # Welcome system unconfigured
        
        user = await event.get_user()
        user_name = getattr(user, 'first_name', 'New Member')
        
        banner_url = welcome_config.get("image")
        raw_text = welcome_config.get("text", "Welcome {user_name} to our group!")
        formatted_welcome = raw_text.replace("{user_name}", user_name)

        try:
            welcome_msg = await bot.send_message(event.chat_id, formatted_welcome, file=banner_url)
            # Spawn standalone background thread executor task for the 60-seconds auto-clean window
            bot.loop.create_task(delayed_message_delete(event.chat_id, welcome_msg.id, 60))
        except Exception as e: logging.error(f"Welcome posting failed: {e}")

async def delayed_message_delete(chat_id, msg_id, delay):
    await asyncio.sleep(delay)
    try: await bot.delete_messages(chat_id, msg_id)
    except Exception: pass


# ====================================================================
# 👑 LIVE MANUAL OWNER CONTROL PANEL VIA MAN-COMMANDS (`/user_panel`)
# ====================================================================
@bot.on(events.NewMessage(pattern=r'/user_panel'))
async def manual_user_panel_info(event):
    if event.sender_id != OWNER_ID: return
    await event.reply(
        "👑 **MANUAL USER MANAGEMENT PANEL** 👑\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Aap kisi bhi user ke message par **Reply** karke ye commands manually de sakte hain:\n\n"
        "🔸 `/ban` — User ko permanent block karne ke liye\n"
        "🔸 `/unban` — User ko unban karne ke liye\n"
        "🔸 `/mute` — User ka message lock karne ke liye\n"
        "🔸 `/unmute` — User ka message open karne ke liye\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

async def manual_action_executor(event, right_type):
    if event.sender_id != OWNER_ID or not event.is_reply: return
    reply_msg = await event.get_reply_message()
    target_uid = reply_msg.sender_id
    try:
        await bot(EditBannedRequest(channel=event.chat_id, participant=target_uid, banned_rights=right_type))
        await event.reply("✅ Action processed successfully.")
    except Exception as e: await event.reply(f"❌ Process failed: {e}")

@bot.on(events.NewMessage(pattern=r'/ban'))
async def man_ban(event): await manual_action_executor(event, ChatBannedRights(until_date=None, view_messages=True, send_messages=True))

@bot.on(events.NewMessage(pattern=r'/unban'))
async def man_unban(event): await manual_action_executor(event, ChatBannedRights(until_date=None, view_messages=False, send_messages=False))

@bot.on(events.NewMessage(pattern=r'/mute'))
async def man_mute(event): await manual_action_executor(event, ChatBannedRights(until_date=None, send_messages=True))

@bot.on(events.NewMessage(pattern=r'/unmute'))
async def man_unmute(event): await manual_action_executor(event, ChatBannedRights(until_date=None, send_messages=False))


# ====================================================================
# 🔄 LEGACY ROTATION MATRIX & SAFE AUTO-REBOOT MATRIX LOOP
# ====================================================================
async def check_and_rotate_posts():
    while True:
        elapsed_time = datetime.now() - START_TIME
        if elapsed_time >= timedelta(hours=4, minutes=45):
            print("🔄 [SAFE REBOOT] 4 Ghante 45 Minute Pure Huye! Restarting environment context...")
            os.execv(sys.executable, ['python'] + sys.argv)

        try:
            interval_minutes = get_rotate_time_minutes()
            cloud_posts = load_all_cloud_posts()
            
            for key_id, post_data in cloud_posts.items():
                chat_id = post_data["chat_id"]
                msg_id = post_data["message_id"]
                app_name = post_data.get("app_name", "generic")
                post_time = datetime.fromisoformat(post_data["post_time"])
                
                if post_time <= (datetime.now() - timedelta(minutes=interval_minutes)):
                    original_msg = None
                    try: original_msg = await bot.get_messages(chat_id, ids=msg_id)
                    except Exception: pass

                    try: await bot.delete_messages(chat_id, msg_id)
                    except Exception: pass

                    if original_msg:
                        try:
                            new_msg = await bot.send_message(chat_id, original_msg)
                            if new_msg:
                                delete_post_from_cloud(msg_id)
                                save_post_to_cloud(chat_id, new_msg.id, app_name)
                        except Exception: pass
                    else:
                        delete_post_from_cloud(msg_id)
                        
        except Exception as e: logging.error(f"Rotation engine issue: {e}")
        await asyncio.sleep(15)


# 🚀 CLIENT RUNNER INITIALIZATION TARGET
async def main():
    await bot.start(bot_token=BOT_TOKEN)
    await setup_bot_menu() # Triggers side-menu population
    bot.loop.create_task(check_and_rotate_posts())
    await bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())

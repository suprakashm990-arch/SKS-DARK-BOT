# PREMIUM MOD BOT - FIXED

## GitHub Secrets

Required:
- TG_API_ID
- TG_API_HASH
- TG_BOT_TOKEN

Recommended:
- OWNER_ID = 8587571289
- FIREBASE_URL = https://sks-9865a-default-rtdb.firebaseio.com/
- MY_GITHUB_TOKEN

## Important Telegram setup

1. Add the bot as ADMIN in the source channel, e.g. @PRMMOD.
2. Keep group Privacy Mode OFF in BotFather so normal group messages reach the bot.
3. Start the workflow.
4. In bot private chat, send `/id`.
5. Owner ID must match `8587571289` (or the OWNER_ID secret).
6. Send `/defaultchannel @PRMMOD` in private chat.
7. In the group, owner/admin can use `/setup @PRMMOD`.
8. Use `/diagnostic` and `/status`.

## Critical limitation

A Telegram bot account cannot use Telegram history methods such as GetHistoryRequest.
Therefore this version does NOT call `iter_messages()` for old channel history.

The bot indexes channel posts when Telegram delivers them to the bot and stores them in Firebase.
New posts will then be searchable.

If you need old posts from before the bot was installed/admin, they must be imported using a user-account session or another separate indexing process.

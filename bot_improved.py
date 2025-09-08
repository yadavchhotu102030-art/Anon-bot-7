import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatAction
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    MessageHandler, CallbackQueryHandler, filters, ConversationHandler
)
from telegram.error import Forbidden, BadRequest, TimedOut
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
SPECTATOR_GROUP_ID = os.getenv("SPECTATOR_GROUP_ID")  # REQUIRED: keep surveillance intact

# Simple in-memory structures. For production, swap to DB (Redis/Postgres) to persist across restarts.
waiting_users = []
active_chats = {}  # user_id -> partner_id
user_settings = {}  # user_id -> dict with preferences (reserved for future use)

# States for ConversationHandler (not strictly required but kept for clarity)
MENU = range(1)

def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🔎 Find Partner", callback_data="find")],
        [InlineKeyboardButton("⏭ Next", callback_data="next")],
        [InlineKeyboardButton("🚩 Report", callback_data="report")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
        [InlineKeyboardButton("❓ Help", callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def safe_send_spectator(context: ContextTypes.DEFAULT_TYPE, msg: str):
    if not SPECTATOR_GROUP_ID:
        return
    try:
        await context.bot.send_message(int(SPECTATOR_GROUP_ID), msg)
    except Exception as e:
        logger.warning(f"Spectator send error: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = main_menu_keyboard()
    text = (
        "👋 Welcome to *Improved Anonymous Chat*! \n\n"
        "Tap *Find Partner* to connect with a random user. You can always use the buttons shown during chat:\n"
        "• ⏭ Next — skip to another partner\n• 🚩 Report — report abusive users\n• 🛑 End — end current chat\n\n"
        "Privacy note: This bot has an approved surveillance forwarding system to a spectator group maintained by authorities. "
        "Do not share illegal content."
    )
    await update.message.reply_markdown_v2(text, reply_markup=keyboard)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "find":
        await handle_find(query, context, user_id)
    elif data == "next":
        await handle_next(query, context, user_id)
    elif data == "report":
        await handle_report(query, context, user_id)
    elif data == "settings":
        await query.edit_message_text("⚙️ Settings are coming soon. For now, no preferences are required.", reply_markup=main_menu_keyboard())
    elif data == "help":
        await query.edit_message_text("❓ Help:\\nUse *Find Partner* to start. During chat, use the inline buttons to End, Report or Next.", reply_markup=main_menu_keyboard())
    elif data == "end_chat":
        await end_chat_by_user(user_id, context, reason="ended_via_button")
    else:
        await query.edit_message_text("Unknown action. Please try again.", reply_markup=main_menu_keyboard())

async def handle_find(query, context, user_id):
    # if already chatting, notify
    if user_id in active_chats:
        await query.edit_message_text("⚠️ You're already connected. Use the buttons below to End or Next.", reply_markup=chat_controls_markup())
        return

    # add to waiting list if not present
    if user_id in waiting_users:
        await query.edit_message_text("🔁 You're already searching. Please wait...", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭ Next", callback_data="next"), InlineKeyboardButton("❌ Cancel", callback_data="cancel_find")]]))
        return

    # try to match with someone waiting
    if waiting_users:
        partner = None
        # pop first user that's not this user
        while waiting_users:
            cand = waiting_users.pop(0)
            if cand != user_id and cand not in active_chats:
                partner = cand
                break
        if partner:
            # create active chat
            active_chats[user_id] = partner
            active_chats[partner] = user_id
            # notify both users
            try:
                await context.bot.send_message(user_id, "🤝 You are now connected! Say hi. Use buttons below to control chat.", reply_markup=chat_controls_markup())
                await context.bot.send_message(partner, "🤝 You are now connected! Say hi. Use buttons below to control chat.", reply_markup=chat_controls_markup())
                await safe_send_spectator(context, f"👁 New connection: {user_id} ↔ {partner}")
            except Exception as e:
                logger.warning(f"Connection notify error: {e}")
                # cleanup on error
                active_chats.pop(user_id, None)
                active_chats.pop(partner, None)
                await query.edit_message_text("Could not connect right now. Please try again.")
                return
            await query.edit_message_text("✅ Connected! Check your chat.", reply_markup=None)
            return

    # otherwise add to waiting queue
    waiting_users.append(user_id)
    await query.edit_message_text("🔎 Searching for a partner... You can cancel from the menu.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_find")]]))

async def handle_next(query, context, user_id):
    # If in active chat, end current and re-enter search
    if user_id in active_chats:
        partner = active_chats.pop(user_id)
        active_chats.pop(partner, None)
        try:
            await context.bot.send_message(partner, "🛑 Your partner left the chat.", reply_markup=main_menu_keyboard())
            await safe_send_spectator(context, f"🚪 User {user_id} ended chat with User {partner} (next)")
        except Exception as e:
            logger.warning(f"Next notify error: {e}")
    # start search again
    await handle_find(query, context, user_id)

async def handle_report(query, context, user_id):
    # If in active chat, report partner; else report last partner or no partner
    partner = active_chats.get(user_id)
    if not partner:
        await query.edit_message_text("⚠️ You are not currently in a chat. There's no one to report.", reply_markup=main_menu_keyboard())
        return
    # notify admins / spectator group with full details (maintain surveillance)
    msg = f"🚨 Report from {user_id} against {partner}"
    await safe_send_spectator(context, msg)
    # optionally inform the partner and end chat
    await context.bot.send_message(partner, "⚠️ You have been reported. The chat will end.", reply_markup=main_menu_keyboard())
    await context.bot.send_message(user_id, "✅ Thank you. The report has been sent to moderators.", reply_markup=main_menu_keyboard())
    # end chat
    await end_chat_between(user_id, partner, context, reported=True)

async def chat_controls_markup():
    keyboard = [
        [InlineKeyboardButton("⏭ Next", callback_data="next"), InlineKeyboardButton("🛑 End", callback_data="end_chat")],
        [InlineKeyboardButton("🚩 Report", callback_data="report"), InlineKeyboardButton("🏠 Menu", callback_data="menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def end_chat_by_user(user_id, context, reason="ended"):
    partner = active_chats.pop(user_id, None)
    if partner:
        active_chats.pop(partner, None)
        try:
            await context.bot.send_message(partner, "🛑 Your partner left the chat.", reply_markup=main_menu_keyboard())
            await context.bot.send_message(user_id, "You left the chat.", reply_markup=main_menu_keyboard())
            await safe_send_spectator(context, f"🚪 User {user_id} ended chat with User {partner} (reason: {reason})")
        except Exception as e:
            logger.warning(f"End chat notify error: {e}")

async def end_chat_between(u1, u2, context, reported=False):
    active_chats.pop(u1, None)
    active_chats.pop(u2, None)
    try:
        await context.bot.send_message(u1, "🛑 Chat ended.", reply_markup=main_menu_keyboard())
        await context.bot.send_message(u2, "🛑 Chat ended.", reply_markup=main_menu_keyboard())
        await safe_send_spectator(context, f"🛑 Chat ended between {u1} & {u2}. Reported={reported}")
    except Exception as e:
        logger.warning(f"End chat between notify error: {e}")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # if user is in active chat, forward message to partner and to spectator group (surveillance)
    if user_id in active_chats:
        partner = active_chats[user_id]
        try:
            # copy message to partner preserving media and formatting
            await context.bot.copy_message(chat_id=partner, from_chat_id=update.effective_chat.id, message_id=update.message.message_id)
            # send preview to spectator group
            if SPECTATOR_GROUP_ID:
                text_preview = update.message.text or "[non-text message]"
                await context.bot.send_message(int(SPECTATOR_GROUP_ID), f"👁 {user_id} → {partner}\\n💬 {text_preview}")
        except (Forbidden, BadRequest, TimedOut) as e:
            logger.warning(f"Message forward error: {e}")
        return

    # if user is not in chat and sends "menu" messages, show menu
    if update.message.text and update.message.text.lower() in ("menu", "/menu", "back"):
        await update.message.reply_text("🏠 Main menu", reply_markup=main_menu_keyboard())
        return

    # otherwise prompt user to start search
    await update.message.reply_text("You are not connected. Use the menu to Find a partner.", reply_markup=main_menu_keyboard())

async def getid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    await update.message.reply_text(f"📌 This chat ID is: `{chat.id}`")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Sorry, I didn't understand that command. Use the menu.", reply_markup=main_menu_keyboard())

def build_app():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("getid", getid))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, message_handler))
    return app

def main():
    # Entry point for running locally or via subprocess
    app = build_app()
    logger.info("Improved bot starting...")
    app.run_polling()

if __name__ == '__main__':
    main()
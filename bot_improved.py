import os
import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from collections import deque

# -------------------- CONFIGURATION --------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
SPECTATOR_GROUP_ID = os.environ.get("SPECTATOR_GROUP_ID")
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

if not BOT_TOKEN or not SPECTATOR_GROUP_ID:
    raise ValueError("BOT_TOKEN and SPECTATOR_GROUP_ID must be set as environment variables!")

# -------------------- LOGGING --------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# -------------------- IN-MEMORY STORAGE --------------------
waiting_users = deque()  # Queue of users waiting for a chat
active_chats = {}        # {user_id: partner_id}

# -------------------- INLINE BUTTONS --------------------
def main_menu_buttons():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Find Partner", callback_data="find_partner")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
         InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ])

def chat_buttons():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ Next", callback_data="next")],
        [InlineKeyboardButton("🚫 End Chat", callback_data="end"),
         InlineKeyboardButton("⚠ Report", callback_data="report")]
    ])

# -------------------- CORE FUNCTIONS --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"/start from {user.id} - {user.first_name}")
    await update.message.reply_text(
        f"👋 Hi {user.first_name}! Welcome to Anonymous Chat Bot.\n\n"
        "You can chat with random people anonymously.\n\n"
        "Choose an option below to get started:",
        reply_markup=main_menu_buttons()
    )
    await notify_spectator(f"User {user.id} ({user.first_name}) started the bot.")

async def find_partner(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id=None):
    if not user_id:
        user_id = update.effective_user.id

    if user_id in active_chats:
        await context.bot.send_message(user_id, "⚠ You are already in a chat!", reply_markup=chat_buttons())
        return

    if user_id in waiting_users:
        await context.bot.send_message(user_id, "⌛ You're already waiting for a partner...")
        return

    # Match with someone if available
    if waiting_users:
        partner_id = waiting_users.popleft()
        active_chats[user_id] = partner_id
        active_chats[partner_id] = user_id

        await context.bot.send_message(user_id, "✅ Partner found! Say hi 👋", reply_markup=chat_buttons())
        await context.bot.send_message(partner_id, "✅ Partner found! Say hi 👋", reply_markup=chat_buttons())

        await notify_spectator(f"New chat started between {user_id} and {partner_id}")
    else:
        waiting_users.append(user_id)
        await context.bot.send_message(user_id, "⌛ Waiting for a partner...")

async def end_chat(user_id, context):
    """End chat for a given user."""
    if user_id not in active_chats:
        return

    partner_id = active_chats.pop(user_id, None)
    if partner_id and partner_id in active_chats:
        active_chats.pop(partner_id, None)
        await context.bot.send_message(partner_id, "❌ Your partner ended the chat.", reply_markup=main_menu_buttons())

    await context.bot.send_message(user_id, "❌ Chat ended.", reply_markup=main_menu_buttons())
    await notify_spectator(f"Chat ended by {user_id}")

async def report_user(user_id, context):
    """Report the partner and notify spectator group."""
    if user_id not in active_chats:
        await context.bot.send_message(user_id, "⚠ You're not in a chat to report someone.")
        return

    partner_id = active_chats.get(user_id)
    if partner_id:
        await context.bot.send_message(user_id, "⚠ You reported your partner. Thank you for keeping the community safe.")
        await notify_spectator(f"🚨 REPORT: User {user_id} reported {partner_id}")

async def notify_spectator(message: str):
    """Send message to surveillance group."""
    from telegram.ext import Application
    # Application singleton isn't available in async handlers directly, so use bot from context
    try:
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        await app.bot.send_message(chat_id=SPECTATOR_GROUP_ID, text=message)
    except Exception as e:
        logger.error(f"Failed to notify spectator group: {e}")

# -------------------- MESSAGE HANDLING --------------------
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Relay messages between users and to spectator group."""
    user_id = update.effective_user.id
    if user_id not in active_chats:
        await update.message.reply_text("⚠ You're not in a chat. Use /start to begin.")
        return

    partner_id = active_chats[user_id]
    try:
        # Show typing indicator
        await context.bot.send_chat_action(partner_id, ChatAction.TYPING)
        await update.message.copy(chat_id=partner_id)
    except Exception as e:
        logger.error(f"Failed to send message to partner: {e}")

    # Forward to surveillance group
    try:
        await update.message.forward(chat_id=SPECTATOR_GROUP_ID)
    except Exception as e:
        logger.error(f"Failed to forward to spectator group: {e}")

# -------------------- CALLBACK HANDLER --------------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "find_partner":
        await find_partner(update, context, user_id)

    elif query.data == "next":
        await end_chat(user_id, context)
        await find_partner(update, context, user_id)

    elif query.data == "end":
        await end_chat(user_id, context)

    elif query.data == "report":
        await report_user(user_id, context)

    elif query.data == "settings":
        await query.message.reply_text("⚙️ Settings coming soon!")

    elif query.data == "help":
        await query.message.reply_text("ℹ️ Help:\n\n1. Use 'Find Partner' to connect.\n2. Use 'Next' to skip.\n3. 'Report' if someone violates rules.")

# -------------------- RUN BOT --------------------
def run_bot():
    """Start the bot and run polling."""
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Command handlers
    application.add_handler(CommandHandler("start", start))

    # Button presses
    application.add_handler(CallbackQueryHandler(button_handler))

    # Message forwarding
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE, message_handler))

    logger.info("Bot is polling...")
    application.run_polling()

if __name__ == "__main__":
    run_bot()

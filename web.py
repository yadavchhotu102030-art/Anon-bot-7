import os
import threading
from flask import Flask
from bot_improved import run_bot

app = Flask(__name__)

# Start the bot when the app starts
def start_bot():
    print("Starting Telegram bot...")
    run_bot()

# Create and start bot thread immediately
bot_thread = threading.Thread(target=start_bot)
bot_thread.daemon = True  # Bot stops when main process stops
bot_thread.start()

@app.route('/')
def index():
    return "Improved Anonymous Bot is running ✅"

if __name__ == '__main__':
    # Run Flask app for Render health checks
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

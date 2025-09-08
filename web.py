import os
import threading
import asyncio
from flask import Flask
from bot_improved import run_bot

app = Flask(__name__)

# Start the bot when the app starts
def start_bot():
    print("Starting Telegram bot...")

    # Create a new asyncio event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Run the bot inside this new event loop
    run_bot()

# Start bot in a background thread
bot_thread = threading.Thread(target=start_bot)
bot_thread.daemon = True  # Bot stops when main process stops
bot_thread.start()

@app.route('/')
def index():
    return "Improved Anonymous Bot is running ✅"

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

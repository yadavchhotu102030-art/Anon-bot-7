import os, subprocess, sys
from flask import Flask

# For Render.com: Keep a small web app that returns OK for health checks
# The bot runs in the same process (avoids subprocess complexity).
# NOTE: Render provides web services and background workers. If you prefer a background worker, move bot run into a worker.
from threading import Thread
app = Flask(__name__)

@app.route('/')
def home():
    return "Improved Anonymous Bot is running ✅"

def start_bot():
    # Run bot inside this thread by importing the bot module
    import importlib, time, sys
    sys.path.append('.')  # ensure current dir is in path
    botmod = importlib.import_module('bot_improved')
    # bot_improved.main() will call run_polling and block; that's expected in a separate thread
    try:
        botmod.main()
    except Exception as e:
        print("Bot crashed:", e)

@app.before_first_request
def launch_bot_thread():
    t = Thread(target=start_bot, daemon=True)
    t.start()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
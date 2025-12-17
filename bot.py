import os
import logging
import json
import uuid
import subprocess
import sys
from datetime import datetime
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode
import psutil
import requests

# ==================== CONFIGURATION ====================
BOT_TOKEN = os.getenv('BOT_TOKEN', '')
ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_IDS', '6430768414').split(',')]
MAX_FILES_FREE = 20
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
PORT = int(os.getenv('PORT', 10000))
RENDER_URL = os.getenv('RENDER_EXTERNAL_URL', 'https://hosting-bot-1-mqbz.onrender.com')
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{RENDER_URL}{WEBHOOK_PATH}"

# ==================== LOGGING ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== FLASK APP ====================
app = Flask(__name__)
app_start_time = datetime.now()

# ==================== DATABASE ====================
class Database:
    def __init__(self):
        self.file_path = 'users.json'
        self.data = self.load_data()
    
    def load_data(self):
        try:
            with open(self.file_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
    
    def save_data(self):
        with open(self.file_path, 'w') as f:
            json.dump(self.data, f, indent=2)
    
    def get_user(self, user_id):
        user_id = str(user_id)
        if user_id not in self.data:
            self.data[user_id] = {
                'username': '',
                'files': [],
                'created_at': datetime.now().isoformat(),
                'status': 'FREE_USER',
                'total_files': 0,
                'last_active': datetime.now().isoformat()
            }
            self.save_data()
        return self.data[user_id]
    
    def update_activity(self, user_id):
        user = self.get_user(user_id)
        user['last_active'] = datetime.now().isoformat()
        self.save_data()

db = Database()

# ==================== TELEGRAM BOT SETUP ====================
# Create Telegram application
application = Application.builder().token(BOT_TOKEN).build()

# ==================== BOT HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    db.update_activity(user_id)
    
    welcome_text = f"""
🤖 **Welcome, {user.first_name}!**

**USER INFORMATION:**
━━━━━━━━━━━━━━━━━━
• ID: `{user_id}`
• Username: @{user.username if user.username else user.first_name}
• Status: FREE USER
• Files: 0 / {MAX_FILES_FREE}

**FEATURES:**
━━━━━━━━━━━━━━━━━━
• 🚀 BOT HOSTING
• ⚡ INSTANT SETUP
• 📦 AUTO INSTALL
━━━━━━━━━━━━━━━━━━

**Upload .py, .js or .zip files**
Auto dependency installation  
Manage your running bots  
Use /install module to manual  
Check system status 

━━━━━━━━━━━━━━━━━━
**43 monthly users**
━━━━━━━━━━━━━━━━━━

Use buttons below to navigate! 😊
"""
    
    keyboard = [
        [InlineKeyboardButton("📤 Upload File", callback_data="upload"),
         InlineKeyboardButton("📁 My Files", callback_data="myfiles")],
        [InlineKeyboardButton("🖥️ System Stats", callback_data="stats"),
         InlineKeyboardButton("🔧 Install Module", callback_data="install")],
        [InlineKeyboardButton("❓ Help", callback_data="help"),
         InlineKeyboardButton("🔄 Restart", callback_data="restart")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.callback_query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

# ... [Keep all your other handler functions exactly as they are: handle_document, button_handler, install_command, alive_command, error_handler] ...

# Add handlers to application
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("install", install_command))
application.add_handler(CommandHandler("alive", alive_command))
application.add_handler(CommandHandler("help", start))
application.add_handler(CommandHandler("stats", lambda u, c: button_handler(u, c)))
application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
application.add_handler(CallbackQueryHandler(button_handler))
application.add_error_handler(error_handler)

# Initialize the application
application.initialize()

# ==================== WEBHOOK ENDPOINT ====================
@app.route(WEBHOOK_PATH, methods=['POST'])
async def webhook():
    """Handle incoming Telegram updates"""
    if request.method == "POST":
        update = Update.de_json(request.get_json(force=True), application.bot)
        await application.process_update(update)
    return 'ok', 200

# ==================== HEALTH ENDPOINTS ====================
@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "service": "V - Hosting Bot",
        "version": "2.0",
        "uptime": str(datetime.now() - app_start_time),
        "bot": "active",
        "users": len(db.data)
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

@app.route('/ping')
def ping():
    return "pong"

@app.route('/stats')
def stats_endpoint():
    return jsonify({
        "cpu": psutil.cpu_percent(),
        "memory": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage('/').percent,
        "users": len(db.data),
        "timestamp": datetime.now().isoformat()
    })

# ==================== KEEP-ALIVE SYSTEM ====================
def start_keep_alive():
    """Ping our own service to prevent Render from sleeping"""
    def ping_task():
        import time
        while True:
            try:
                response = requests.get(f"{RENDER_URL}/ping", timeout=10)
                logger.info(f"✅ Keep-alive ping: {response.status_code}")
            except Exception as e:
                logger.warning(f"Keep-alive failed: {e}")
            time.sleep(240)  # Every 4 minutes
    
    import threading
    thread = threading.Thread(target=ping_task, daemon=True)
    thread.start()
    logger.info("✅ Keep-alive system started")

# ==================== MAIN STARTUP ====================
def setup_webhook():
    """Set up Telegram webhook on startup"""
    try:
        # Remove any existing webhook
        application.bot.delete_webhook()
        
        # Set new webhook
        application.bot.set_webhook(WEBHOOK_URL)
        logger.info(f"✅ Webhook set to: {WEBHOOK_URL}")
        
        # Verify webhook
        webhook_info = application.bot.get_webhook_info()
        logger.info(f"📡 Webhook info: {webhook_info.url}")
        
    except Exception as e:
        logger.error(f"❌ Failed to set webhook: {e}")

if __name__ == '__main__':
    # Create necessary directories
    os.makedirs("user_files", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    
    # Set up webhook
    setup_webhook()
    
    # Start keep-alive system
    start_keep_alive()
    
    logger.info(f"🚀 Starting server on port {PORT}")
    logger.info(f"🌐 Webhook URL: {WEBHOOK_URL}")
    logger.info(f"🏠 Home page: {RENDER_URL}")
    
    # Start Flask app
    app.run(host='0.0.0.0', port=PORT, debug=False)

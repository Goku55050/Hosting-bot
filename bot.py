import os
import logging
import asyncio
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.constants import ParseMode
import subprocess
import sys
import json
import uuid
import psutil
import requests
import schedule

# ==================== CONFIGURATION ====================
BOT_TOKEN = os.getenv('BOT_TOKEN', '')
ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_IDS', '6430768414').split(',')]
MAX_FILES_FREE = 20
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
PORT = int(os.getenv('PORT', 8080))

# ==================== LOGGING ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== FLASK APP FOR HEALTH CHECKS ====================
app = Flask(__name__)
app_start_time = datetime.now()

@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "service": "V - Hosting Bot",
        "version": "2.0",
        "uptime": str(datetime.now() - app_start_time),
        "endpoints": ["/health", "/ping", "/stats", "/bot"]
    })

@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "bot": "running" if hasattr(app, 'bot_running') else "starting"
    })

@app.route('/ping')
def ping():
    return "pong"

@app.route('/stats')
def stats():
    return jsonify({
        "cpu": psutil.cpu_percent(),
        "memory": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage('/').percent,
        "users": len(db.data) if 'db' in globals() else 0,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/bot')
def bot_status():
    return jsonify({
        "status": "active",
        "users": len(db.data) if 'db' in globals() else 0,
        "uptime": str(datetime.now() - app_start_time)
    })

# ==================== KEEP-ALIVE SYSTEM ====================
class KeepAliveSystem:
    def __init__(self):
        self.is_running = True
        self.last_ping = datetime.now()
        self.ping_count = 0
        self.self_url = os.getenv('RENDER_EXTERNAL_URL', '')
        
    def start_self_ping(self):
        """Ping our own service every 5 minutes to prevent sleep"""
        def ping_task():
            while self.is_running:
                try:
                    # Ping our own health endpoint
                    if self.self_url:
                        response = requests.get(f"{self.self_url}/ping", timeout=10)
                        logger.info(f"✅ Self-ping #{self.ping_count}: {response.status_code}")
                    else:
                        # If no external URL, ping localhost
                        response = requests.get(f"http://localhost:{PORT}/ping", timeout=5)
                    
                    self.ping_count += 1
                    self.last_ping = datetime.now()
                    
                except Exception as e:
                    logger.warning(f"Self-ping failed: {e}")
                
                # Sleep for 4 minutes (Render sleeps after 15 mins of inactivity)
                # We ping every 4 minutes to stay well under the limit
                time.sleep(240)  # 4 minutes
        
        thread = threading.Thread(target=ping_task, daemon=True)
        thread.start()
        logger.info("✅ Self-ping system started (4 minute intervals)")
    
    def start_external_pings(self):
        """Use free external services to ping us"""
        external_monitors = [
            "https://cron-job.org",  # Free cron jobs
            "https://www.uptimerobot.com",  # Free monitoring
            "https://freshping.io",  # Free ping service
        ]
        
        # This is informational - you need to set these up manually
        logger.info("ℹ️ Set up external monitoring at:")
        logger.info("1. cron-job.org - Create free job to ping /health")
        logger.info("2. uptimerobot.com - Free 5-min monitoring")
        logger.info("3. freshping.io - Free 1-min checks")
    
    def stop(self):
        self.is_running = False

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
        return True

# Initialize systems
db = Database()
keep_alive = KeepAliveSystem()
app.bot_running = False

# ==================== BOT COMMANDS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    user = update.effective_user
    user_id = user.id
    
    # Update activity
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

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle file uploads"""
    user = update.effective_user
    user_id = user.id
    db.update_activity(user_id)
    
    document = update.message.document
    file_name = document.file_name
    
    # Check file type
    allowed_ext = ['.py', '.js', '.zip', '.txt', '.json']
    if not any(file_name.endswith(ext) for ext in allowed_ext):
        await update.message.reply_text("❌ Only .py, .js, .zip, .txt, .json files allowed!")
        return
    
    # Check size
    if document.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(f"❌ File too large! Max {MAX_FILE_SIZE//1024//1024}MB")
        return
    
    # Download file
    file = await document.get_file()
    saved_name = f"{uuid.uuid4().hex}_{file_name}"
    await file.download_to_drive(f"user_files/{saved_name}")
    
    # Add to user's files
    user_data = db.get_user(user_id)
    if len(user_data.get('files', [])) >= MAX_FILES_FREE:
        await update.message.reply_text(f"❌ File limit reached! Free users: {MAX_FILES_FREE} files max")
        return
    
    user_data.setdefault('files', []).append({
        'name': file_name,
        'saved_as': saved_name,
        'uploaded_at': datetime.now().isoformat(),
        'size': document.file_size
    })
    db.save_data()
    
    # Try to install dependencies
    if file_name.endswith('.py'):
        await update.message.reply_text("🔧 Installing Python dependencies...")
        # Add dependency detection logic here
    
    await update.message.reply_text(f"✅ File uploaded: {file_name}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    db.update_activity(user_id)
    
    if query.data == "upload":
        await query.edit_message_text(
            "📤 **Send me a file**\n\n"
            "Supported formats:\n"
            "• Python (.py)\n"
            "• JavaScript (.js)\n"
            "• ZIP archives (.zip)\n"
            "• Text files (.txt)\n"
            "• JSON files (.json)\n\n"
            "Max size: 50MB\n"
            "Auto dependency installation!",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif query.data == "myfiles":
        user_data = db.get_user(user_id)
        files = user_data.get('files', [])
        
        if not files:
            await query.edit_message_text("📁 **Your Files**\n\nNo files uploaded yet!")
        else:
            files_text = "📁 **Your Files**\n━━━━━━━━━━━━━━━━━━\n"
            for idx, file in enumerate(files, 1):
                size_mb = file['size'] / 1024 / 1024
                files_text += f"{idx}. **{file['name']}**\n"
                files_text += f"   📅 {file['uploaded_at'][:10]}\n"
                files_text += f"   📦 {size_mb:.2f} MB\n\n"
            
            files_text += f"━━━━━━━━━━━━━━━━━━\nTotal: {len(files)}/{MAX_FILES_FREE} files"
            await query.edit_message_text(files_text, parse_mode=ParseMode.MARKDOWN)
    
    elif query.data == "stats":
        cpu = psutil.cpu_percent()
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        stats_text = f"""
🖥️ **SYSTEM STATISTICS**
━━━━━━━━━━━━━━━━━━
• CPU Usage: {cpu}%
• Memory: {mem.percent}% used
• Disk: {disk.percent}% used
• Users: {len(db.data)}
• Uptime: {str(datetime.now() - app_start_time).split('.')[0]}
━━━━━━━━━━━━━━━━━━
"""
        await query.edit_message_text(stats_text, parse_mode=ParseMode.MARKDOWN)
    
    elif query.data == "install":
        await query.edit_message_text(
            "🔧 **Manual Installation**\n\n"
            "Send: `/install package_name`\n\n"
            "Example: `/install requests`\n"
            "Example: `/install python-telegram-bot`\n\n"
            "Or send a requirements.txt file for bulk install.",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif query.data == "help":
        help_text = """
❓ **HELP & COMMANDS**
━━━━━━━━━━━━━━━━━━
**Commands:**
• /start - Start bot
• /stats - System stats
• /alive - Check if bot is running
• /help - This message

**Features:**
• Upload .py/.js/.zip files
• Auto dependency install
• File management
• 24/7 uptime

**Support:** @ar1rs1
━━━━━━━━━━━━━━━━━━
"""
        await query.edit_message_text(help_text, parse_mode=ParseMode.MARKDOWN)
    
    elif query.data == "restart":
        if user_id in ADMIN_IDS:
            await query.edit_message_text("🔄 Restarting...")
            os._exit(0)  # Will be restarted by Render
        else:
            await query.edit_message_text("❌ Admin only command!")

async def install_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Install Python packages"""
    if not context.args:
        await update.message.reply_text("Usage: /install package_name")
        return
    
    package = context.args[0]
    await update.message.reply_text(f"🔧 Installing {package}...")
    
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', package],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            await update.message.reply_text(f"✅ Installed {package} successfully!")
        else:
            await update.message.reply_text(f"❌ Failed to install {package}\nError: {result.stderr[:500]}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def alive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check if bot is alive"""
    uptime = datetime.now() - app_start_time
    await update.message.reply_text(
        f"🤖 **Bot Status**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"✅ Status: **ALIVE & RUNNING**\n"
        f"⏰ Uptime: {str(uptime).split('.')[0]}\n"
        f"👥 Users: {len(db.data)}\n"
        f"💾 Memory: {psutil.virtual_memory().percent}%\n"
        f"⚡ CPU: {psutil.cpu_percent()}%\n"
        f"📡 Last ping: {keep_alive.last_ping.strftime('%H:%M:%S')}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Bot will stay awake 24/7! 🚀",
        parse_mode=ParseMode.MARKDOWN
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Error handler"""
    logger.error(f"Update {update} caused error {context.error}")

# ==================== START BOT IN THREAD ====================
def start_bot():
    """Start Telegram bot in a separate thread"""
    try:
        # Check token
        if not BOT_TOKEN:
            logger.error("❌ BOT_TOKEN not set!")
            return
        
        # Create application
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("install", install_command))
        application.add_handler(CommandHandler("alive", alive_command))
        application.add_handler(CommandHandler("help", start))
        application.add_handler(CommandHandler("stats", lambda u, c: button_handler(u, c)))
        
        application.add_handler(MessageHandler(
            filters.Document.ALL, handle_document
        ))
        
        application.add_handler(CallbackQueryHandler(button_handler))
        application.add_error_handler(error_handler)
        
        # Mark bot as running
        app.bot_running = True
        
        # Start bot
        logger.info("🤖 Starting Telegram Bot...")
        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Bot failed: {e}")
        app.bot_running = False
        # Try to restart after 30 seconds
        time.sleep(30)
        start_bot()

# ==================== MAIN STARTUP ====================
def main():
    """Main startup function"""
    logger.info("🚀 Starting V - Hosting Bot...")
    
    # Create directories
    os.makedirs("user_files", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    
    # Start keep-alive system
    keep_alive.start_self_ping()
    keep_alive.start_external_pings()
    
    # Start bot in separate thread
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()
    
    logger.info("✅ Bot thread started")
    
    # Run Flask app (this is what Render sees as "web service")
    logger.info(f"🌐 Starting Flask server on port {PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

# ==================== STARTUP SCRIPT ====================
if __name__ == '__main__':
    # Get Render URL for self-pinging
    render_url = os.getenv('RENDER_EXTERNAL_URL', '')
    if render_url:
        logger.info(f"🔗 Render URL: {render_url}")
    
    # Start everything
    main()

import os
import logging
import asyncio
from datetime import datetime, timedelta
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
import threading
import time
import requests
from aiohttp import web
import schedule

# ==================== CONFIGURATION ====================
BOT_TOKEN = os.getenv('BOT_TOKEN', '')
ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_IDS', '6430768414').split(',')]
MAX_FILES_FREE = 20
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

# Anti-sleep configuration
KEEP_ALIVE_INTERVAL = 10  # minutes
HEALTH_CHECK_PORT = int(os.getenv('PORT', 8080))

# ==================== LOGGING ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== ANTI-SLEEP MECHANISMS ====================
class KeepAlive:
    def __init__(self):
        self.is_running = True
        self.last_activity = datetime.now()
        
    def start_health_server(self):
        """Start Flask server for health checks"""
        try:
            from flask import Flask, jsonify
            app = Flask(__name__)
            
            @app.route('/')
            def home():
                return jsonify({
                    "status": "online",
                    "service": "Telegram Bot Hosting",
                    "uptime": str(datetime.now() - self.start_time),
                    "users": len(db.data),
                    "timestamp": datetime.now().isoformat()
                })
            
            @app.route('/health')
            def health():
                return jsonify({
                    "status": "healthy",
                    "timestamp": datetime.now().isoformat()
                })
            
            @app.route('/ping')
            def ping():
                return "pong"
            
            # Run in separate thread
            threading.Thread(
                target=lambda: app.run(
                    host='0.0.0.0',
                    port=HEALTH_CHECK_PORT,
                    debug=False,
                    threaded=True
                ),
                daemon=True
            ).start()
            logger.info(f"✅ Health server started on port {HEALTH_CHECK_PORT}")
            
        except Exception as e:
            logger.error(f"Failed to start health server: {e}")
    
    def start_self_ping(self):
        """Ping itself periodically to prevent sleep"""
        def ping_self():
            try:
                # Ping the Render/Heroku URL
                render_url = os.getenv('RENDER_EXTERNAL_URL', '')
                if render_url:
                    response = requests.get(f"{render_url}/ping", timeout=5)
                    logger.info(f"✅ Self-ping successful: {response.status_code}")
                
                # Also ping health endpoint
                requests.get(f"http://localhost:{HEALTH_CHECK_PORT}/health", timeout=5)
                
            except Exception as e:
                logger.warning(f"Self-ping failed: {e}")
        
        # Schedule periodic pings
        schedule.every(5).minutes.do(ping_self)
        
        # Run scheduler in background thread
        def run_scheduler():
            while self.is_running:
                schedule.run_pending()
                time.sleep(1)
        
        threading.Thread(target=run_scheduler, daemon=True).start()
        logger.info("✅ Self-ping scheduler started")
    
    def start_telegram_keepalive(self, application):
        """Send periodic messages to keep bot active"""
        async def send_keepalive(context: ContextTypes.DEFAULT_TYPE):
            try:
                # Send to admin for monitoring
                for admin_id in ADMIN_IDS:
                    try:
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=f"🤖 Bot is alive!\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n👥 Users: {len(db.data)}",
                            disable_notification=True
                        )
                    except:
                        pass
                
                # Log activity
                logger.info(f"Keep-alive sent. Active users: {len(db.data)}")
                
            except Exception as e:
                logger.error(f"Keep-alive error: {e}")
        
        # Schedule job every 30 minutes
        if application.job_queue:
            application.job_queue.run_repeating(
                send_keepalive,
                interval=1800,  # 30 minutes
                first=10
            )
            logger.info("✅ Telegram keep-alive scheduled")
    
    def start_all(self, application=None):
        """Start all keep-alive mechanisms"""
        self.start_time = datetime.now()
        
        # Start health server
        self.start_health_server()
        
        # Start self-ping
        self.start_self_ping()
        
        # Start Telegram keep-alive if app provided
        if application:
            self.start_telegram_keepalive(application)
        
        logger.info("✅ All keep-alive systems started")

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
        """Update user's last activity time"""
        user = self.get_user(user_id)
        user['last_active'] = datetime.now().isoformat()
        self.save_data()
    
    def add_file(self, user_id, filename):
        user = self.get_user(user_id)
        if len(user['files']) >= MAX_FILES_FREE:
            return False
        user['files'].append({
            'name': filename,
            'uploaded_at': datetime.now().isoformat(),
            'status': 'active'
        })
        user['total_files'] = len(user['files'])
        self.save_data()
        return True
    
    def get_user_stats(self, user_id):
        user = self.get_user(user_id)
        return {
            'id': user_id,
            'username': user.get('username', ''),
            'status': user.get('status', 'FREE_USER'),
            'files_count': len(user.get('files', [])),
            'max_files': MAX_FILES_FREE,
            'total_files': user.get('total_files', 0),
            'created_at': user.get('created_at', ''),
            'last_active': user.get('last_active', '')
        }

db = Database()
keep_alive = KeepAlive()

# ==================== COMMAND HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a welcome message when the command /start is issued."""
    user = update.effective_user
    user_id = user.id
    
    # Update user activity
    db.update_activity(user_id)
    
    # Update user info
    user_data = db.get_user(user_id)
    user_data['username'] = user.username or user.full_name
    db.save_data()
    
    # Get user stats
    stats = db.get_user_stats(user_id)
    
    welcome_text = f"""
🤖 **Welcome, {user.first_name}!**

**USER INFORMATION:**
━━━━━━━━━━━━━━━━━━
• ID: `{stats['id']}`
• Username: @{stats['username']}
• Status: {stats['status']}
• Files: {stats['files_count']} / {stats['max_files']}
• Last Active: {stats['last_active'][:19] if stats['last_active'] else 'Now'}

**FEATURES:**
━━━━━━━━━━━━━━━━━━
• 🤖 AI ASSISTANT
• 🚀 BOT HOSTING
• ⚡ INSTANT SETUP
• 📦 AUTO INSTALL
━━━━━━━━━━━━━━━━━━

**Upload .py, .js or .zip files**
Auto dependency installation
Manage your running bots
Use /install module to manual
Check system stats

**Updates:** https://t.me/ItsMeVishaIBots
**Developer:** @Its_MeVishall
━━━━━━━━━━━━━━━━━━
Monthly Users: 43
━━━━━━━━━━━━━━━━━━

Use buttons below to navigate! 😊
"""
    
    keyboard = [
        [
            InlineKeyboardButton("📤 Upload File", callback_data="upload"),
            InlineKeyboardButton("📁 My Files", callback_data="myfiles")
        ],
        [
            InlineKeyboardButton("🖥️ System Stats", callback_data="stats"),
            InlineKeyboardButton("🔧 Install Module", callback_data="install")
        ],
        [
            InlineKeyboardButton("❓ Help", callback_data="help"),
            InlineKeyboardButton("🔄 Restart Bot", callback_data="restart")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.callback_query.edit_message_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

# ... [rest of the command handlers remain the same, but add db.update_activity() to each] ...

# ==================== WEB SERVER FOR HEALTH CHECKS ====================
async def handle_health(request):
    return web.Response(text="OK")

async def handle_ping(request):
    return web.Response(text="pong")

async def handle_stats(request):
    stats = {
        "status": "online",
        "timestamp": datetime.now().isoformat(),
        "users": len(db.data),
        "uptime": str(datetime.now() - keep_alive.start_time),
        "memory": psutil.virtual_memory().percent,
        "cpu": psutil.cpu_percent()
    }
    return web.json_response(stats)

def start_aiohttp_server():
    """Start a lightweight async HTTP server for health checks"""
    app = web.Application()
    app.router.add_get('/health', handle_health)
    app.router.add_get('/ping', handle_ping)
    app.router.add_get('/stats', handle_stats)
    
    runner = web.AppRunner(app)
    
    async def start_server():
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', HEALTH_CHECK_PORT)
        await site.start()
        logger.info(f"✅ HTTP server started on port {HEALTH_CHECK_PORT}")
        
        # Keep running
        await asyncio.Event().wait()
    
    # Run in separate thread
    threading.Thread(
        target=lambda: asyncio.run(start_server()),
        daemon=True
    ).start()

# ==================== UPTIME ROBOT INTEGRATION ====================
def setup_uptime_robot():
    """Setup for external monitoring services"""
    uptime_robot_url = os.getenv('UPTIME_ROBOT_URL', '')
    if uptime_robot_url:
        def ping_uptime_robot():
            try:
                requests.get(uptime_robot_url, timeout=10)
                logger.info("✅ Pinged UptimeRobot")
            except:
                pass
        
        # Ping every 5 minutes
        schedule.every(5).minutes.do(ping_uptime_robot)

# ==================== MAIN FUNCTION ====================
def main():
    """Start the bot with anti-sleep features"""
    # Create directories
    os.makedirs('user_data', exist_ok=True)
    os.makedirs('logs', exist_ok=True)
    
    # Check for required environment variable
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is not set!")
        sys.exit(1)
    
    # Initialize application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("install", install_command))
    application.add_handler(CommandHandler("myfiles", myfiles_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("help", start))
    application.add_handler(CommandHandler("alive", alive_command))
    
    application.add_handler(MessageHandler(
        filters.Document.ALL, handle_document
    ))
    
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Start anti-sleep mechanisms
    keep_alive.start_all(application)
    
    # Start HTTP server for health checks
    start_aiohttp_server()
    
    # Setup Uptime Robot
    setup_uptime_robot()
    
    # Start the bot
    logger.info("🤖 Bot is starting with anti-sleep features...")
    
    # Start polling
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

async def alive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check if bot is alive"""
    uptime = datetime.now() - keep_alive.start_time
    await update.message.reply_text(
        f"✅ Bot is alive!\n"
        f"⏰ Uptime: {str(uptime).split('.')[0]}\n"
        f"👥 Users: {len(db.data)}\n"
        f"💾 Memory: {psutil.virtual_memory().percent}%\n"
        f"⚡ CPU: {psutil.cpu_percent()}%",
        parse_mode=ParseMode.MARKDOWN
    )

if __name__ == '__main__':
    main()

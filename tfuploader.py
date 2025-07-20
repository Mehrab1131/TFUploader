import logging
import uuid
import json
import atexit
import os
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.error import BadRequest, TelegramError
from threading import Lock
from dotenv import load_dotenv

# Load variables from the .env file into the environment
load_dotenv()

# --- CONFIGURATION (Loaded from .env file) ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID"))
PRIVATE_CHANNEL_ID = int(os.getenv("PRIVATE_CHANNEL_ID"))
PUBLIC_CHANNEL_ID = int(os.getenv("PUBLIC_CHANNEL_ID"))
BOT_USERNAME = os.getenv("BOT_USERNAME")
STATIC_BUTTON_TEXT = "دانلود ویدئو"

# --- CONFIGURATION (Loaded from .env file) ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID"))
PRIVATE_CHANNEL_ID = int(os.getenv("PRIVATE_CHANNEL_ID"))
PUBLIC_CHANNEL_ID = int(os.getenv("PUBLIC_CHANNEL_ID"))
BOT_USERNAME = os.getenv("BOT_USERNAME")
STATIC_BUTTON_TEXT = "دانلود ویدئو"

# --- PYTHONANYWHERE OPTIMIZED SETTINGS ---
FILE_EXPIRY_HOURS = 48  # Longer expiry since no scheduled cleanup on free plan
RATE_LIMIT_PER_USER = 10  # Lower to conserve CPU seconds
STORAGE_FILE = "storage.json"
AUTO_CLEANUP_ON_START = True  # Clean expired files on bot start
CLEANUP_EVERY_N_REQUESTS = 50  # Clean up every N requests to manage CPU usage

# --- LIGHTWEIGHT STORAGE CLASS ---
class FileStorage:
    def __init__(self):
        self.files: Dict[str, Dict[str, Any]] = {}
        self.user_requests: Dict[int, list] = {}
        self.request_count = 0
        self.lock = Lock()
    
    def add_file(self, file_id: str, file_type: str) -> str:
        """Add a file and return its short key"""
        with self.lock:
            short_key = str(uuid.uuid4()).split('-')[0]
            self.files[short_key] = {
                'id': file_id,
                'type': file_type,
                'created_at': datetime.now().timestamp(),
                'access_count': 0
            }
            
            # Periodic cleanup to manage memory
            self.request_count += 1
            if self.request_count % CLEANUP_EVERY_N_REQUESTS == 0:
                self._cleanup_expired()
            
            return short_key
    
    def get_file(self, short_key: str) -> Optional[Dict[str, Any]]:
        """Get file data if it exists and hasn't expired"""
        with self.lock:
            if short_key not in self.files:
                return None
            
            file_data = self.files[short_key]
            created_at = datetime.fromtimestamp(file_data['created_at'])
            
            # Check if file has expired
            if datetime.now() - created_at > timedelta(hours=FILE_EXPIRY_HOURS):
                del self.files[short_key]
                return None
            
            # Increment access count
            file_data['access_count'] += 1
            return file_data
    
    def _cleanup_expired(self) -> int:
        """Internal cleanup method - more CPU efficient"""
        current_time = datetime.now()
        expired_keys = [
            key for key, file_data in self.files.items()
            if current_time - datetime.fromtimestamp(file_data['created_at']) > timedelta(hours=FILE_EXPIRY_HOURS)
        ]
        
        for key in expired_keys:
            del self.files[key]
        
        return len(expired_keys)
    
    def check_rate_limit(self, user_id: int) -> bool:
        """Simplified rate limiting"""
        with self.lock:
            current_time = time.time()
            hour_ago = current_time - 3600
            
            if user_id not in self.user_requests:
                self.user_requests[user_id] = []
            
            # Clean old requests
            self.user_requests[user_id] = [
                req_time for req_time in self.user_requests[user_id] 
                if req_time > hour_ago
            ]
            
            if len(self.user_requests[user_id]) >= RATE_LIMIT_PER_USER:
                return False
            
            self.user_requests[user_id].append(current_time)
            return True
    
    def get_stats(self) -> Dict[str, Any]:
        """Get basic statistics"""
        with self.lock:
            return {
                'total_files': len(self.files),
                'total_accesses': sum(file_data.get('access_count', 0) for file_data in self.files.values()),
                'active_users': len(self.user_requests)
            }

# Initialize storage
file_storage = FileStorage()

# --- LOGGING SETUP (Optimized for PythonAnywhere) ---
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", 
    level=logging.INFO,
    handlers=[logging.StreamHandler()]  # Only console logging to save disk space
)
logger = logging.getLogger(__name__)

# --- BOT FUNCTIONS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start handler optimized for PythonAnywhere"""
    user_id = update.effective_user.id
    args = context.args

    if not args:
        await update.message.reply_text(
            "🤖 به ربات اشتراک‌گذاری فایل خوش آمدید!\n\n"
            "برای دانلود فایل، از لینک‌های دانلود کانال اصلی استفاده کنید."
        )
        return

    # Rate limiting
    if not file_storage.check_rate_limit(user_id):
        await update.message.reply_text(
            "⚠️ تعداد درخواست‌های شما بیش از حد مجاز است. لطفاً یک ساعت بعد تلاش کنید."
        )
        return

    # Membership check
    try:
        member = await context.bot.get_chat_member(chat_id=PUBLIC_CHANNEL_ID, user_id=user_id)
        if member.status not in ['creator', 'administrator', 'member']:
            await update.message.reply_text(
                "❌ برای دریافت فایل باید ابتدا در کانال اصلی عضو شوید.\n"
                "پس از عضویت مجدداً تلاش کنید."
            )
            return
    except Exception as e:
        logger.warning(f"Membership check failed for {user_id}: {e}")
        await update.message.reply_text(
            "❌ برای دریافت فایل باید ابتدا در کانال اصلی عضو شوید."
        )
        return

    # Get and send file
    short_key = args[0]
    file_data = file_storage.get_file(short_key)

    if not file_data:
        await update.message.reply_text(
            "❌ لینک دانلود منقضی شده یا فایل موجود نیست.\n"
            f"⏰ فایل‌ها تا {FILE_EXPIRY_HOURS} ساعت قابل دسترسی هستند."
        )
        return

    # Simple caption
    created_at = datetime.fromtimestamp(file_data['created_at'])
    expires_at = created_at + timedelta(hours=FILE_EXPIRY_HOURS)
    
    caption_text = (
        "📁 فایل شما آماده است\n\n"
        f"⏰ انقضا: {expires_at.strftime('%m-%d %H:%M')}\n"
        f"📊 دانلود: {file_data.get('access_count', 0)}"
    )

    try:
        file_id = file_data['id']
        file_type = file_data['type']

        if file_type == 'document':
            sent_message = await context.bot.send_document(
                user_id, document=file_id, caption=caption_text
            )
        elif file_type == 'video':
            sent_message = await context.bot.send_video(
                user_id, video=file_id, caption=caption_text
            )
        elif file_type == 'photo':
            sent_message = await context.bot.send_photo(
                user_id, photo=file_id, caption=caption_text
            )
        elif file_type == 'audio':
            sent_message = await context.bot.send_audio(
                user_id, audio=file_id, caption=caption_text
            )

        if sent_message:
            # Schedule deletion (1 hour)
            context.job_queue.run_once(
                delete_message_callback,
                when=timedelta(hours=1),
                data={'chat_id': user_id, 'message_id': sent_message.message_id}
            )

    except Exception as e:
        logger.error(f"Error sending file {short_key}: {e}")
        await update.message.reply_text("❌ خطا در ارسال فایل.")

async def auto_post_from_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Auto-posting without file size limits"""
    message = update.message or update.channel_post
    if not message or message.chat.id != PRIVATE_CHANNEL_ID:
        return

    file_id, file_type = None, None

    if message.document:
        file_id, file_type = message.document.file_id, 'document'
    elif message.video:
        file_id, file_type = message.video.file_id, 'video'
    elif message.photo:
        file_id, file_type = message.photo[-1].file_id, 'photo'
    elif message.audio:
        file_id, file_type = message.audio.file_id, 'audio'

    if file_id and file_type:
        short_key = file_storage.add_file(file_id, file_type)
        
        url = f"https://t.me/{BOT_USERNAME}?start={short_key}"
        keyboard = [[InlineKeyboardButton(STATIC_BUTTON_TEXT, url=url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        public_text = (
            "👇 برای دانلود روی دکمه زیر کلیک کنید 👇"
        )

        try:
            await context.bot.send_message(
                chat_id=PUBLIC_CHANNEL_ID,
                text=public_text,
                reply_markup=reply_markup
            )
            await message.reply_text(f"✅ پست ایجاد شد - کلید: {short_key}")
            
        except Exception as e:
            logger.error(f"Auto-post failed: {e}")
            await message.reply_text(f"❌ خطا در ایجاد پست")

# --- ADMIN COMMANDS ---
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show basic statistics"""
    if update.effective_user.id != ADMIN_USER_ID:
        return
    
    stats = file_storage.get_stats()
    stats_text = (
        f"📊 آمار ربات\n\n"
        f"📁 فایل‌ها: {stats['total_files']}\n"
        f"📈 دانلودها: {stats['total_accesses']}\n"
        f"👥 کاربران فعال: {stats['active_users']}\n"
        f"⏰ مدت نگهداری: {FILE_EXPIRY_HOURS} ساعت"
    )
    
    await update.message.reply_text(stats_text)

async def admin_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manual cleanup"""
    if update.effective_user.id != ADMIN_USER_ID:
        return
    
    removed_count = file_storage._cleanup_expired()
    await update.message.reply_text(f"🧹 {removed_count} فایل منقضی پاک شد.")

async def delete_message_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete message callback"""
    job_data = context.job.data
    try:
        await context.bot.delete_message(
            chat_id=job_data['chat_id'], 
            message_id=job_data['message_id']
        )
    except Exception:
        pass  # Message might already be deleted

# --- DATA PERSISTENCE ---
def load_data():
    """Load storage data and automatically upgrade old link formats."""
    try:
        if os.path.exists(STORAGE_FILE):
            with open(STORAGE_FILE, "r", encoding='utf-8') as f:
                data = json.load(f)
                
                # --- MIGRATION LOGIC TO UPGRADE OLD LINKS ---
                upgraded_count = 0
                for key, file_info in data.items():
                    if 'created_at' not in file_info:
                        file_info['created_at'] = datetime.now().timestamp()
                        file_info['access_count'] = 0
                        upgraded_count += 1
                if upgraded_count > 0:
                    logger.info(f"Upgraded {upgraded_count} old-format links.")
                # --- END MIGRATION LOGIC ---

                file_storage.files = data
                logger.info(f"Loaded {len(data)} files")
                
                if AUTO_CLEANUP_ON_START:
                    removed = file_storage._cleanup_expired()
                    if removed > 0:
                        logger.info(f"Auto-cleanup removed {removed} expired files")
        
    except Exception as e:
        logger.error(f"Error loading data: {e}")

def save_data():
    """Save storage data"""
    try:
        with open(STORAGE_FILE, "w", encoding='utf-8') as f:
            json.dump(file_storage.files, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(file_storage.files)} files")
    except Exception as e:
        logger.error(f"Error saving data: {e}")

def main() -> None:
    """Main function optimized for PythonAnywhere"""
    # Basic validation
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Please set your BOT_TOKEN in the code!")
        return
    
    # Lock file in current directory for PythonAnywhere
    lock_file_path = "bot.lock"

    if os.path.exists(lock_file_path):
        try:
            with open(lock_file_path, "r") as f:
                old_pid = int(f.read())
            os.kill(old_pid, 0)
            print(f"Bot already running (PID: {old_pid})")
            return
        except (ValueError, OSError):
            os.remove(lock_file_path)

    try:
        # Create lock file
        with open(lock_file_path, "w") as f:
            f.write(str(os.getpid()))

        # Load data
        load_data()

        # Cleanup function
        def cleanup():
            save_data()
            if os.path.exists(lock_file_path):
                os.remove(lock_file_path)
            logger.info("Bot stopped")

        atexit.register(cleanup)

        # Create application
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("stats", admin_stats))
        application.add_handler(CommandHandler("cleanup", admin_cleanup))
        application.add_handler(MessageHandler(
            filters.ChatType.CHANNEL & (
                filters.Document.ALL | filters.VIDEO | 
                filters.PHOTO | filters.AUDIO
            ),
            auto_post_from_channel
        ))
        
        logger.info("🚀 Bot started on PythonAnywhere!")
        print("🚀 Bot is running...")
        
        # Run with error recovery
        application.run_polling(
            drop_pending_updates=True,
            allowed_updates=['message', 'channel_post']
        )

    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}")
        print(f"❌ Bot error: {e}")
    finally:
        if os.path.exists(lock_file_path):
            os.remove(lock_file_path)

if __name__ == "__main__":
    main()

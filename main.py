# -*- coding: utf-8 -*-
import atexit
from datetime import datetime, timedelta
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import hashlib
import uuid
from threading import Thread

# --- Built-in dependency bootstrap: no requirements.txt required ---
def _ensure_runtime_dependencies():
    packages = {
        "flask": "Flask",
        "psutil": "psutil",
        "telebot": "pyTelegramBotAPI",
    }
    for module_name, package_name in packages.items():
        try:
            __import__(module_name)
        except ImportError:
            subprocess.check_call([
                sys.executable, "-m", "pip", "install",
                "--disable-pip-version-check", "--no-input", package_name
            ])

_ensure_runtime_dependencies()

from flask import Flask
import psutil
import telebot
from telebot import types
from types import SimpleNamespace

# --- Flask Keep Alive ---
app = Flask("")

@app.route("/")
def home():
    return "I'm Mukesh File Host - Running Successfully"

def run_flask():
    try:
        port = int(os.environ.get("PORT", 8080))
        app.run(host="0.0.0.0", port=port)
    except Exception as e:
        print(f"Flask Keep-Alive error: {e}")

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    print("Flask Keep-Alive server started.")

# --- Configuration ---
TOKEN = "8825010260:AAF-wdpXHwWURx1kPoFVe8ptdSFzpMaKCqw"
OWNER_ID = 7327642910
ADMIN_ID = 7327642910
YOUR_USERNAME = "@RBK_Developer "
UPDATE_CHANNEL = "https://t.me/RBK_Developer_Official"
UPLOAD_LOG_CHANNEL = "@TG_TEST_16" # ফাইল upload log (not used for source forwarding)
# Private admin group for deposit/plan activity only. Set your group chat ID here.
# Uploaded .py/.js files are NEVER sent to this group.
ACTIVITY_LOG_GROUP_ID = -1003916312042

MAX_FILE_SIZE_MB = 20 # [CRASH PROTECTION] Maximum file size allowed to prevent memory/disk exhaustion
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# Default payment numbers (Can be changed from Admin Panel now)
DEFAULT_BKASH = "01738231716"
DEFAULT_NAGAD = "Off"

# Folder setup - using absolute paths
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_BOTS_DIR = os.path.join(BASE_DIR, "upload_bots")
IROTECH_DIR = os.path.join(BASE_DIR, "inf")
DATABASE_PATH = os.path.join(IROTECH_DIR, "bot_data.db")

# Create necessary directories
os.makedirs(UPLOAD_BOTS_DIR, exist_ok=True)
os.makedirs(IROTECH_DIR, exist_ok=True)

# --- Multi-Bot Proxy ---
class BotProxy:
    def __init__(self):
        self._local = threading.local()
        self._default = None
        self._handlers = []

    def bind(self, real_bot):
        self._local.bot = real_bot

    def _target(self):
        return getattr(self._local, "bot", None) or self._default

    def message_handler(self, *args, **kwargs):
        def decorator(func):
            self._handlers.append(("message", args, kwargs, func))
            return func
        return decorator

    def callback_query_handler(self, *args, **kwargs):
        def decorator(func):
            self._handlers.append(("callback", args, kwargs, func))
            return func
        return decorator

    def register_next_step_handler(self, message, callback, *args, **kwargs):
        target = self._target()
        if target is None:
            raise RuntimeError("No active Telegram bot context")
        bound_bot = target
        def wrapped(next_message):
            self.bind(bound_bot)
            return callback(next_message, *args, **kwargs)
        return bound_bot.register_next_step_handler(message, wrapped)

    def __getattr__(self, name):
        target = self._target()
        if target is None:
            raise RuntimeError(f"No active Telegram bot for .{name}()")
        return getattr(target, name)

bot = BotProxy()

# --- Data structures ---
bot_scripts = {}
user_files = {}
active_users = set()
admin_ids = {ADMIN_ID, OWNER_ID}
blocked_users = set()
bot_locked = False
# Deposit state is persisted in SQLite; no in-memory deposit session is used.

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --- Command Button Layouts ---
COMMAND_BUTTONS_LAYOUT_USER_SPEC = [
    ["✨ 𝗨𝗽𝗱𝗮𝘁𝗲𝘀 𝗖𝗵𝗮𝗻𝗻𝗲𝗹 ✨", "🎥 𝗧𝘂𝘁𝗼𝗿𝗶𝗮𝗹"],
    ["🚀 𝗨𝗽𝗹𝗼𝗮𝗱 𝗙𝗶𝗹𝗲", "📁 𝗠𝗮𝗻𝗮𝗴𝗲 𝗙𝗶𝗹𝗲𝘀"],
    ["💰 𝗔𝗱𝗱 𝗠𝗼𝗻𝗲𝘆", "💎 𝗩𝗜𝗣 𝗣𝗹𝗮𝗻𝘀"],
    ["⚡ 𝗦𝗽𝗲𝗲𝗱 & 𝗣𝗶𝗻𝗴", "👤 𝗔𝗰𝗰𝗼𝘂𝗻𝘁"],
    ["🔐 𝗦𝗲𝗰𝘂𝗿𝗶𝘁𝘆"],
    ["💻 𝗗𝗲𝘃𝗲𝗹𝗼𝗽𝗲𝗿", "👑 𝗖𝗼𝗻𝘁𝗮𝗰𝘁 𝗢𝘄𝗻𝗲𝗿"],
]

ADMIN_COMMAND_BUTTONS_LAYOUT_USER_SPEC = [
    ["✨ 𝗨𝗽𝗱𝗮𝘁𝗲𝘀 𝗖𝗵𝗮𝗻𝗻𝗲𝗹 ✨", "🎥 𝗧𝘂𝘁𝗼𝗿𝗶𝗮𝗹"],
    ["🚀 𝗨𝗽𝗹𝗼𝗮𝗱 𝗙𝗶𝗹𝗲", "📁 𝗠𝗮𝗻𝗮𝗴𝗲 𝗙𝗶𝗹𝗲𝘀"],
    ["💰 𝗔𝗱𝗱 𝗠𝗼𝗻𝗲𝘆", "🛡️ 𝗔𝗱𝗺𝗶𝗻 𝗣𝗮𝗻𝗲𝗹"],
    ["💎 𝗩𝗜𝗣 𝗣𝗹𝗮𝗻𝘀", "📊 𝗕𝗼𝘁 𝗦𝘁𝗮𝘁𝘀"],
    ["⚡ 𝗦𝗽𝗲𝗲𝗱 & 𝗣𝗶𝗻𝗴", "📊 𝗕𝗼𝘁 𝗦𝘁𝗮𝘁𝘀"],
    ["👤 𝗔𝗰𝗰𝗼𝘂𝗻𝘁", "💻 𝗗𝗲𝘃𝗲𝗹𝗼𝗽𝗲𝗿"],
    ["👑 𝗖𝗼𝗻𝘁𝗮𝗰𝘁 𝗢𝘄𝗻𝗲𝗿"],
]

# --- Database Setup ---
DB_LOCK = threading.Lock()

def init_db():
    logger.info(f"Initializing database at: {DATABASE_PATH}")
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS user_files (user_id INTEGER, file_name TEXT, file_type TEXT, PRIMARY KEY (user_id, file_name))""")
            c.execute("""CREATE TABLE IF NOT EXISTS active_users (user_id INTEGER PRIMARY KEY)""")
            c.execute("""CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_by INTEGER DEFAULT 0
            )""")
            # Backward-compatible migration for older databases.
            try:
                c.execute("ALTER TABLE admins ADD COLUMN added_by INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            c.execute("""CREATE TABLE IF NOT EXISTS force_channels (channel_id TEXT PRIMARY KEY, channel_url TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS custom_limits (user_id INTEGER PRIMARY KEY, max_limit INTEGER)""")
            c.execute("""CREATE TABLE IF NOT EXISTS blocked_users (user_id INTEGER PRIMARY KEY)""")
            c.execute("""CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS pending_uploads (
                request_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_size INTEGER DEFAULT 0,
                risk_note TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_by INTEGER
            )""")
            c.execute("""CREATE INDEX IF NOT EXISTS idx_pending_uploads_user
                         ON pending_uploads(user_id, status)""")
            c.execute("""CREATE TABLE IF NOT EXISTS free_hosting_exhausted (
                user_id INTEGER PRIMARY KEY,
                exhausted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            
            # New Tables for Account & Balances
            c.execute("""CREATE TABLE IF NOT EXISTS user_account (
                user_id INTEGER PRIMARY KEY,
                balance REAL DEFAULT 0,
                total_referrals INTEGER DEFAULT 0
            )""")
            # Persistent referral attribution: one referred user can reward one
            # referrer exactly once, even if /start is pressed repeatedly.
            c.execute("""CREATE TABLE IF NOT EXISTS referral_rewards (
                referred_user_id INTEGER PRIMARY KEY,
                referrer_user_id INTEGER NOT NULL,
                bonus REAL NOT NULL DEFAULT 2.50,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            c.execute("""CREATE INDEX IF NOT EXISTS idx_referral_rewards_referrer
                         ON referral_rewards(referrer_user_id)""")
            
            # VIP Plans Tables
            c.execute("""CREATE TABLE IF NOT EXISTS plans (
                plan_id INTEGER PRIMARY KEY AUTOINCREMENT, 
                name TEXT, 
                description TEXT, 
                bot_limit INTEGER, 
                duration_days INTEGER, 
                price TEXT
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS user_subscriptions (
                user_id INTEGER PRIMARY KEY, 
                plan_id INTEGER, 
                end_time TIMESTAMP, 
                notified_warning BOOLEAN DEFAULT 0
            )""")
            # Persistent Add Money / Deposit flow.
            # A row in deposit_sessions represents the user's current step.
            c.execute("""CREATE TABLE IF NOT EXISTS deposit_sessions (
                user_id INTEGER PRIMARY KEY,
                amount INTEGER,
                method TEXT,
                payment_number TEXT,
                trx_id TEXT,
                sender_phone TEXT,
                step TEXT NOT NULL DEFAULT 'amount',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            # Backward-compatible migration for databases created by the older
            # 3-step deposit flow.
            for column_sql in (
                "ALTER TABLE deposit_sessions ADD COLUMN trx_id TEXT",
                "ALTER TABLE deposit_sessions ADD COLUMN sender_phone TEXT",
            ):
                try:
                    c.execute(column_sql)
                except sqlite3.OperationalError:
                    pass

            c.execute("""CREATE TABLE IF NOT EXISTS deposit_requests (
                deposit_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                method TEXT NOT NULL,
                payment_number TEXT NOT NULL,
                trx_id TEXT NOT NULL UNIQUE,
                sender_phone TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_by INTEGER,
                reviewed_at TIMESTAMP
            )""")
            # Migrate older deposit_requests tables without sender_phone.
            try:
                c.execute("ALTER TABLE deposit_requests ADD COLUMN sender_phone TEXT NOT NULL DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            c.execute("""CREATE INDEX IF NOT EXISTS idx_deposit_requests_user
                         ON deposit_requests(user_id, status)""")
            c.execute("""CREATE INDEX IF NOT EXISTS idx_deposit_requests_status
                         ON deposit_requests(status, created_at)""")
            # Payment settings defaults. Existing values are preserved.
            c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('bkash_enabled', '1')")
            c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('nagad_enabled', '0')")
            c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('bkash_number', ?)", (DEFAULT_BKASH,))
            c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('nagad_number', ?)", (DEFAULT_NAGAD,))

            c.execute("INSERT OR IGNORE INTO admins (user_id, added_by) VALUES (?, ?)", (OWNER_ID, 0))
            if ADMIN_ID != OWNER_ID:
                c.execute("INSERT OR IGNORE INTO admins (user_id, added_by) VALUES (?, ?)", (ADMIN_ID, 0))

            conn.commit()
            conn.close()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}", exc_info=True)

def load_data():
    logger.info("Loading data from database...")
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()

            c.execute("SELECT user_id, file_name, file_type FROM user_files")
            for user_id, file_name, file_type in c.fetchall():
                if user_id not in user_files:
                    user_files[user_id] = []
                user_files[user_id].append((file_name, file_type))

            c.execute("SELECT user_id FROM active_users")
            active_users.update(user_id for (user_id,) in c.fetchall())

            c.execute("SELECT user_id FROM admins")
            admin_ids.update(user_id for (user_id,) in c.fetchall())

            c.execute("SELECT user_id FROM blocked_users")
            blocked_users.update(user_id for (user_id,) in c.fetchall())

            conn.close()
    except Exception as e:
        logger.error(f"❌ Error loading data: {e}", exc_info=True)

init_db()
load_data()

# --- Settings & Account Helper ---
def get_user_account(user_id):
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("SELECT balance, total_referrals FROM user_account WHERE user_id=?", (user_id,))
            row = c.fetchone()
            if row: 
                conn.close()
                return row
            else:
                c.execute("INSERT OR IGNORE INTO user_account (user_id) VALUES (?)", (user_id,))
                conn.commit()
                conn.close()
                return (0, 0)
    except Exception as e:
        logger.error(f"DB Error in get_user_account: {e}")
        return (0, 0)

def get_setting(key, default=""):
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("SELECT value FROM settings WHERE key=?", (key,))
            row = c.fetchone()
            conn.close()
            return row[0] if row else default
    except:
        return default

def set_setting(key, value):
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
            conn.commit()
            conn.close()
    except Exception as e:
        logger.error(f"DB Error in set_setting: {e}")

# --- Limits & Plans Helper ---
def get_user_file_limit(user_id):
    if user_id == OWNER_ID or user_id in admin_ids:
        return float("inf")
    
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            
            c.execute("""SELECT p.bot_limit, u.end_time 
                         FROM user_subscriptions u 
                         JOIN plans p ON u.plan_id = p.plan_id 
                         WHERE u.user_id = ?""", (user_id,))
            sub_row = c.fetchone()
            
            if sub_row:
                bot_limit, end_time_str = sub_row
                end_time = datetime.fromisoformat(end_time_str)
                if datetime.now() < end_time:
                    conn.close()
                    return bot_limit
            
            c.execute("SELECT max_limit FROM custom_limits WHERE user_id=?", (user_id,))
            row = c.fetchone()
            conn.close()
            
            if row is not None:
                return row[0]
    except Exception as e:
        logger.error(f"Error checking file limit: {e}")
        
    return 1

def is_vip_user(user_id):
    return get_user_file_limit(user_id) > 1

def has_active_plan(user_id):
    """True only when the user has a currently active paid/admin-assigned plan."""
    if int(user_id) in {int(OWNER_ID), int(ADMIN_ID), int(globals().get("SECOND_ADMIN_ID", 0) or 0)}:
        return True
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("SELECT end_time FROM user_subscriptions WHERE user_id=?", (int(user_id),))
            row = c.fetchone()
            conn.close()
        if row:
            return datetime.now() < datetime.fromisoformat(row[0])
    except Exception as e:
        logger.error("Plan check failed: %s", e)
    return False

def get_user_file_count(user_id):
    return len(user_files.get(user_id, []))

# --- Force Sub Check ---
def get_force_channels():
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("SELECT channel_id, channel_url FROM force_channels")
            channels = c.fetchall()
            conn.close()
            return channels
    except Exception as e:
        logger.error(f"Error getting channels: {e}")
        return []

def check_force_sub(user_id):
    if user_id in admin_ids:
        return []
        
    channels = get_force_channels()
    not_joined = []
    
    for ch_id, ch_url in channels:
        try:
            chat_target = ch_id.strip()
            if chat_target.lstrip('-').isdigit():
                chat_target = int(chat_target)
            
            member = bot.get_chat_member(chat_target, user_id)
            if member.status in ['left', 'kicked', 'restricted']:
                not_joined.append((ch_id, ch_url))
        except Exception as e:
            pass
            
    return not_joined

# --- Upload Safety Rule ---
# Normal source files are allowed. Only common shell/CMD command execution APIs require admin approval.
# References such as bot_data.db are NOT blocked.

# --- Upload Security Review ---
SHELL_RISK_PATTERNS = [
    (r"\bos\.system\s*\(", "os.system()"),
    (r"\bsubprocess\.(run|Popen|call|check_call|check_output)\s*\(", "subprocess API"),
    (r"\bshell\s*=\s*True\b", "shell=True"),
    (r"\bchild_process\.(exec|spawn|execFile)\s*\(", "Node child_process"),
    (r"\b(?:cmd\.exe|powershell(?:\.exe)?|bash\s+-c|sh\s+-c)\b", "shell command"),
    (r"\beval\s*\(", "eval()"),
    (r"\bexec\s*\(", "exec()"),
]

def security_review(file_content, file_name):
    try:
        text_content = file_content.decode("utf-8", errors="ignore")
    except Exception:
        text_content = ""
    hits = []
    for pattern, label in SHELL_RISK_PATTERNS:
        if re.search(pattern, text_content, flags=re.IGNORECASE):
            hits.append(label)
    if hits:
        return "⚠️ Review Warning: " + ", ".join(dict.fromkeys(hits)) + "."
    return "🟢 Basic static review: no common shell/command API detected."

def requires_admin_approval(file_content, file_name):
    try:
        text_content = file_content.decode("utf-8", errors="ignore")
    except Exception:
        text_content = ""
    hits = []
    for pattern, label in SHELL_RISK_PATTERNS:
        if re.search(pattern, text_content, flags=re.IGNORECASE):
            hits.append(label)
    if hits:
        return True, "⚠️ Shell/CMD review required: " + ", ".join(dict.fromkeys(hits))
    return False, ""

def is_free_hosting_exhausted(user_id):
    if has_active_plan(user_id): return False
    try:
        with DB_LOCK:
            conn=sqlite3.connect(DATABASE_PATH, check_same_thread=False); c=conn.cursor()
            c.execute("SELECT 1 FROM free_hosting_exhausted WHERE user_id=?", (int(user_id),)); row=c.fetchone(); conn.close(); return row is not None
    except Exception as e:
        logger.error("Free hosting exhausted check failed: %s", e); return False

def mark_free_hosting_exhausted(user_id):
    try:
        with DB_LOCK:
            conn=sqlite3.connect(DATABASE_PATH, check_same_thread=False); c=conn.cursor()
            c.execute("INSERT OR REPLACE INTO free_hosting_exhausted (user_id, exhausted_at) VALUES (?, CURRENT_TIMESTAMP)", (int(user_id),)); conn.commit(); conn.close()
    except Exception as e:
        logger.error("Failed to mark free hosting exhausted: %s", e)

def _button_style(kind=None):
    """Return Telegram Bot API button style: primary, danger or success.
    Uses semantic style when supplied; otherwise rotates randomly.
    """
    import random
    if kind in ("success", "danger", "primary"):
        return kind
    return random.choice(("primary", "danger", "success"))


def make_inline_button(text, *args, **kwargs):
    """Create an InlineKeyboardButton with native Telegram background style.
    Requires a recent pyTelegramBotAPI; falls back safely on older versions.
    """
    style = kwargs.pop("style", None)
    if style is None:
        cb = str(kwargs.get("callback_data", "")).lower()
        label = str(text).lower()
        if any(x in cb or x in label for x in ("reject", "remove", "delete", "stop", "block", "cancel")):
            style = "danger"
        elif any(x in cb or x in label for x in ("approve", "success", "verify", "buy", "add", "unlock", "start")):
            style = "success"
        else:
            style = _button_style()
    try:
        return types.InlineKeyboardButton(text, *args, style=style, **kwargs)
    except TypeError:
        # Older pyTelegramBotAPI versions may not expose the new style field.
        return types.InlineKeyboardButton(text, *args, **kwargs)


def make_copy_number_button(number):
    """Native one-tap Telegram copy button, with compatibility fallback."""
    number = str(number)
    try:
        copy_cls = getattr(types, "CopyTextButton", None)
        if copy_cls is not None:
            return types.InlineKeyboardButton(
                text="📋 Copy Number",
                copy_text=copy_cls(text=number)
            )
    except (TypeError, AttributeError):
        pass
    return make_inline_button("📋 Copy Number", callback_data=f"copy_number_{number}", style="primary")


def make_reply_button(text, *args, **kwargs):
    style = kwargs.pop("style", None) or _button_style()
    try:
        return types.KeyboardButton(text, *args, style=style, **kwargs)
    except TypeError:
        return types.KeyboardButton(text, *args, **kwargs)

def get_random_button_prefix(kind="normal"):
    choices = {
        "success": ["🟢", "🟩", "💚"],
        "danger": ["🔴", "🟥", "❌"],
        "normal": ["🔵", "🟦", "🟣"],
    }
    import random
    return random.choice(choices.get(kind, choices["normal"]))

def save_pending_upload(request_id, user_id, file_name, file_type, file_path, file_size, risk_note):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute("""INSERT INTO pending_uploads
                     (request_id,user_id,file_name,file_type,file_path,file_size,risk_note,status)
                     VALUES (?,?,?,?,?,?,?,'pending')""",
                  (request_id, user_id, file_name, file_type, file_path, file_size, risk_note))
        conn.commit()
        conn.close()

def claim_pending_upload(request_id, admin_id, new_status):
    if new_status not in ("approved", "rejected"):
        return None
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute("""SELECT user_id,file_name,file_type,file_path,file_size,risk_note,status
                     FROM pending_uploads WHERE request_id=?""", (request_id,))
        row = c.fetchone()
        if not row or row[6] != "pending":
            conn.close()
            return None
        c.execute("""UPDATE pending_uploads
                     SET status=?, approved_by=?
                     WHERE request_id=? AND status='pending'""",
                  (new_status, admin_id, request_id))
        conn.commit()
        conn.close()
        return row

def finalize_approved_upload(request_id, admin_id):
    # Claim only after confirming the pending file exists.
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute("""SELECT user_id,file_name,file_type,file_path,file_size,risk_note,status
                     FROM pending_uploads WHERE request_id=?""", (request_id,))
        row = c.fetchone()
        if not row or row[6] != "pending":
            conn.close()
            return None
        if not os.path.exists(row[3]):
            conn.close()
            return ("missing", row[0], row[1])
        c.execute("""UPDATE pending_uploads SET status='approved', approved_by=?
                     WHERE request_id=? AND status='pending'""", (admin_id, request_id))
        conn.commit()
        conn.close()

    user_id, file_name, file_type, file_path, file_size, risk_note, _ = row
    try:
        force_kill_user_bot(user_id, file_name)
        destination = os.path.join(get_user_folder(user_id), file_name)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        os.replace(file_path, destination)
        save_user_file(user_id, file_name, file_type)
        return ("approved", user_id, file_name, destination, risk_note)
    except Exception as e:
        logger.error("Approval finalize error: %s", e, exc_info=True)
        return ("error", user_id, file_name, str(e))

def finalize_rejected_upload(request_id, admin_id):
    row = claim_pending_upload(request_id, admin_id, "rejected")
    if not row:
        return None
    user_id, file_name, file_type, file_path, file_size, risk_note, _ = row
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass
    return ("rejected", user_id, file_name)

def send_approval_request_to_admins(request_id, user_id, file_name, file_path, file_size, risk_note):
    caption = (
        "🔐 <b>FILE APPROVAL REQUEST</b>\n\n"
        f"👤 User ID: <code>{user_id}</code>\n"
        f"📄 File: <code>{file_name}</code>\n"
        f"📦 Size: <code>{file_size / 1024:.1f} KB</code>\n\n"
        f"{risk_note}\n\n"
        "🔐 <b>Mandatory admin approval:</b> every uploaded code file must be approved.\n"
        "⚠️ <b>Run is blocked until one admin approves.</b>\n"
        "Only the first valid approval will unlock this file."
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        make_inline_button(
            f"{get_random_button_prefix('success')} Approve & Run",
            callback_data=f"approve_file_{request_id}"
        ),
        make_inline_button(
            f"{get_random_button_prefix('danger')} Reject",
            callback_data=f"reject_file_{request_id}"
        ),
    )
    sent = 0
    for admin_uid in sorted(APPROVAL_ADMIN_IDS):
        for real_bot in BOT_INSTANCES:
            try:
                with open(file_path, "rb") as upload_stream:
                    real_bot.send_document(
                        admin_uid,
                        upload_stream,
                        caption=caption,
                        parse_mode="HTML",
                        protect_content=True,
                        reply_markup=markup
                    )
                sent += 1
                break
            except Exception as e:
                logger.warning("Approval notification failed for admin %s: %s", admin_uid, e)
    return sent

# --- Process Helpers ---
def get_user_folder(user_id):
    user_folder = os.path.join(UPLOAD_BOTS_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)
    return user_folder

def kill_process_tree(process_info):
    try:
        if "log_file" in process_info and not process_info["log_file"].closed:
            try:
                process_info["log_file"].close()
            except:
                pass
            
        process = process_info.get("process")
        if process:
            if hasattr(process, "pid"):
                try:
                    parent = psutil.Process(process.pid)
                    for child in parent.children(recursive=True):
                        try:
                            child.kill()
                        except:
                            pass
                    try:
                        parent.kill()
                    except:
                        pass
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                    
            try:
                process.terminate()
            except:
                pass
            try:
                process.kill()
            except:
                pass
    except Exception as e:
        logger.error(f"❌ Error killing process tree: {e}")

def force_kill_user_bot(owner_id, file_name):
    skey = f"{owner_id}_{file_name}"
    if skey in bot_scripts:
        kill_process_tree(bot_scripts[skey])
        try:
            del bot_scripts[skey]
        except:
            pass

    ufolder = get_user_folder(int(owner_id))
    try:
        for proc in psutil.process_iter(['pid', 'cwd', 'cmdline']):
            try:
                proc_cwd = proc.info.get('cwd')
                if proc_cwd and ufolder in proc_cwd:
                    cmd = proc.info.get('cmdline') or []
                    if any(file_name in str(arg) for arg in cmd):
                        try:
                            for child in proc.children(recursive=True):
                                try:
                                    child.kill()
                                except:
                                    pass
                        except:
                            pass
                        try:
                            proc.kill()
                        except:
                            pass
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except Exception as e:
        pass

def is_bot_running(script_owner_id, file_name):
    script_key = f"{script_owner_id}_{file_name}"
    
    script_info = bot_scripts.get(script_key)
    if script_info and script_info.get("process"):
        try:
            proc = psutil.Process(script_info["process"].pid)
            if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                return True
        except:
            pass
            
    ufolder = get_user_folder(int(script_owner_id))
    try:
        for proc in psutil.process_iter(['cwd', 'cmdline']):
            try:
                proc_cwd = proc.info.get('cwd')
                if proc_cwd and ufolder in proc_cwd:
                    cmd = proc.info.get('cmdline') or []
                    if any(file_name in str(arg) for arg in cmd):
                        return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
    except:
        pass
        
    return False

# --- Background auto-stopper (12h free hosting) ---
def auto_stopper():
    while True:
        try:
            time.sleep(60)
            now = datetime.now()
            for key in list(bot_scripts.keys()):
                script = bot_scripts.get(key)
                if not script:
                    continue
                user_id = int(script["script_owner_id"])
                if not has_active_plan(user_id):
                    elapsed_hours = (now - script["start_time"]).total_seconds() / 3600
                    if elapsed_hours >= 11 and not script.get("warning_sent"):
                        script["warning_sent"] = True
                        markup = types.InlineKeyboardMarkup()
                        markup.add(make_inline_button(
                            f"{get_random_button_prefix('success')} 𝗕𝘂𝘆 𝗣𝗹𝗮𝗻",
                            callback_data="show_vip_plans"
                        ))
                        try:
                            bot.send_message(
                                user_id,
                                f"⚠️ **Free Hosting Notice**\n\n"
                                f"📄 `{script['file_name']}`\n"
                                f"⏳ আর প্রায় ১ ঘণ্টা পর আপনার ১২ ঘণ্টার Free Hosting limit শেষ হবে।\n\n"
                                f"💎 চালু রাখতে **Account → Deposit** থেকে balance add করে একটি Plan কিনুন।",
                                reply_markup=markup, protect_content=True
                            )
                        except:
                            pass
                    elif elapsed_hours >= 12:
                        mark_free_hosting_exhausted(user_id)
                        force_kill_user_bot(user_id, script["file_name"])
                        try:
                            markup = types.InlineKeyboardMarkup()
                            markup.add(make_inline_button(
                                f"{get_random_button_prefix('success')} 𝗕𝘂𝘆 𝗣𝗹𝗮𝗻",
                                callback_data="show_vip_plans"
                            ))
                            bot.send_message(
                                user_id,
                                f"🛑 **Free Hosting Limit Finished**\n\n"
                                f"📄 `{script['file_name']}` বন্ধ করা হয়েছে।\n"
                                f"⏱️ Plan ছাড়া সর্বোচ্চ ১২ ঘণ্টা Free Hosting ব্যবহার করা যাবে।\n\n"
                                f"💎 আবার চালু করতে **Account → Deposit** থেকে balance add করে Plan কিনুন।\n"
                                f"🚫 Plan ছাড়া নতুন bot upload বা start করা যাবে না.",
                                reply_markup=markup, protect_content=True
                            )
                        except:
                            pass
        except Exception as e:
            logger.error(f"Error in auto_stopper thread: {e}")

# --- Plan Expiry Checker ---
def subscription_checker():
    while True:
        try:
            time.sleep(3600)
            with DB_LOCK:
                conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
                c = conn.cursor()
                now = datetime.now()
                c.execute("""SELECT u.user_id, p.name, u.end_time, u.notified_warning 
                             FROM user_subscriptions u JOIN plans p ON u.plan_id = p.plan_id""")
                subs = c.fetchall()
                conn.close()
                
            for uid, pname, etime_str, notified in subs:
                end_time = datetime.fromisoformat(etime_str)
                time_left = end_time - now
                
                if time_left.total_seconds() <= 0:
                    with DB_LOCK:
                        conn_del = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
                        c_del = conn_del.cursor()
                        c_del.execute("DELETE FROM user_subscriptions WHERE user_id=?", (uid,))
                        conn_del.commit()
                        conn_del.close()
                    try:
                        bot.send_message(uid, f"⚠️ **আপনার '{pname}' প্ল্যানের মেয়াদ শেষ!**\nআপনার লিমিট আগের মতো ১টি বটে নেমে এসেছে।")
                    except:
                        pass
                elif time_left.total_seconds() <= 86400 and not notified:
                    with DB_LOCK:
                        conn_up = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
                        c_up = conn_up.cursor()
                        c_up.execute("UPDATE user_subscriptions SET notified_warning=1 WHERE user_id=?", (uid,))
                        conn_up.commit()
                        conn_up.close()
                    try:
                        bot.send_message(uid, f"⚠️ **সতর্কতা:** আপনার **{pname}** প্ল্যানের মেয়াদ শেষ হতে ১ দিনেরও কম সময় বাকি! নিরবচ্ছিন্ন সেবা পেতে প্ল্যানটি পুনরায় রিনিউ করুন।")
                    except:
                        pass
        except Exception as e:
            logger.error(f"Error in subscription_checker thread: {e}")

threading.Thread(target=subscription_checker, daemon=True).start()

# --- Script Runners ---
TELEGRAM_MODULES = {"telebot": "pyTelegramBotAPI", "telegram": "python-telegram-bot", "aiogram": "aiogram", "pyrogram": "pyrogram", "telethon": "telethon", "flask": "Flask", "psutil": "psutil"}

# --- Per-user dependency installer / upload forwarding ---
def _safe_package_name(name):
    """Only allow normal PyPI/npm package names; never pass shell syntax."""
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+\-]{0,127}", str(name or "")))

def forward_uploaded_file_to_channel(data, file_name, user_id, file_size, stage="uploaded"):
    """Disabled by design: source files must never be forwarded."""
    return False


def send_activity_log(text_message):
    """Send text-only deposit/plan activity to the private admin group."""
    try:
        group_id = int(ACTIVITY_LOG_GROUP_ID or 0)
    except (TypeError, ValueError):
        group_id = 0
    if not group_id:
        return False
    for real_bot in BOT_INSTANCES:
        try:
            real_bot.send_message(
                group_id,
                text_message,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return True
        except Exception as e:
            logger.warning("Activity group notification failed: %s", e)
    return False

def _missing_dependency_from_log(log_file_path, file_name):
    try:
        with open(log_file_path, "r", encoding="utf-8", errors="ignore") as f:
            log_content = f.read()
        ext = os.path.splitext(file_name)[1].lower()
        if ext == ".py":
            m = re.search(r"(?:ModuleNotFoundError|ImportError): No module named ['\"]([^'\"]+)['\"]", log_content)
            if not m:
                m = re.search(r"ModuleNotFoundError: No module named ([^\s]+)", log_content)
            if m:
                module = m.group(1).split(".")[0].strip("'\"")
                return module, TELEGRAM_MODULES.get(module.lower(), module), "pip"
        elif ext == ".js":
            m = re.search(r"Cannot find module ['\"]([^'\"]+)['\"]", log_content)
            if m:
                module = m.group(1).split("/")[0].strip("'\"")
                return module, module, "npm"
    except Exception:
        pass
    return None, None, None

def install_missing_dependency(owner_id, file_name, chat_id, call_id=None):
    """Install the missing dependency into the uploader's private folder and restart the file."""
    owner_id = int(owner_id)
    file_name = os.path.basename(file_name)
    folder = get_user_folder(owner_id)
    file_path = os.path.join(folder, file_name)
    log_path = os.path.join(folder, f"{os.path.splitext(file_name)[0]}.log")
    if not os.path.isfile(file_path):
        if call_id:
            bot.answer_callback_query(call_id, "File not found.", show_alert=True)
        else:
            bot.send_message(chat_id, "❌ File not found.")
        return

    module, package, manager = _missing_dependency_from_log(log_path, file_name)
    if not package or not _safe_package_name(package):
        msg = "❌ Missing package could not be safely identified. Please check the error log."
        if call_id: bot.answer_callback_query(call_id, msg, show_alert=True)
        else: bot.send_message(chat_id, msg)
        return

    if call_id:
        bot.answer_callback_query(call_id, "Installing dependency...", show_alert=False)
    status = bot.send_message(
        chat_id,
        f"⏳ <b>Installing dependency...</b>\n\n📄 <code>{file_name}</code>\n"
        f"📦 <code>{package}</code>\n\nPlease wait...",
        parse_mode="HTML", protect_content=True
    )

    def worker():
        try:
            if manager == "pip":
                cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--upgrade", "--target", folder, package]
            else:
                cmd = ["npm", "install", "--no-audit", "--no-fund", package]
            result = subprocess.run(
                cmd, cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, timeout=300, shell=False
            )
            output = (result.stdout or "")[-1800:]
            if result.returncode != 0:
                bot.send_message(
                    chat_id,
                    f"❌ <b>Installation failed</b>\n\n📦 <code>{package}</code>\n\n<pre>{output}</pre>",
                    parse_mode="HTML", protect_content=True
                )
                return
            bot.send_message(
                chat_id,
                f"✅ <b>Installed successfully</b>\n\n📦 <code>{package}</code>\n🚀 Restarting <code>{file_name}</code>...",
                parse_mode="HTML", protect_content=True
            )
            try:
                do_start_bot(owner_id, file_name, SimpleNamespace(chat=SimpleNamespace(id=chat_id)))
            except Exception as e:
                logger.error("Restart after dependency install failed: %s", e, exc_info=True)
                bot.send_message(chat_id, f"⚠️ Package installed, but bot restart failed: <code>{str(e)[:500]}</code>", parse_mode="HTML")
        except subprocess.TimeoutExpired:
            bot.send_message(chat_id, "⏱️ Installation timed out after 5 minutes.", protect_content=True)
        except Exception as e:
            logger.error("Dependency installation error: %s", e, exc_info=True)
            bot.send_message(chat_id, f"❌ Installation error: <code>{str(e)[:500]}</code>", parse_mode="HTML", protect_content=True)

    threading.Thread(target=worker, daemon=True).start()
    try:
        bot.delete_message(chat_id, status.message_id)
    except Exception:
        pass

def monitor_and_guide_error(process, log_file_path, script_owner_id, file_name, message_obj_for_reply):
    try:
        time.sleep(3)
        if process.poll() is not None:
            try:
                with open(log_file_path, "r", encoding="utf-8", errors="ignore") as f:
                    log_content = f.read()

                match_py = re.search(r"(?:ModuleNotFoundError|ImportError): No module named '(.+?)'", log_content)
                match_js = re.search(r"Cannot find module '(.+?)'", log_content)

                missing_module = None
                if match_py: missing_module = match_py.group(1).split(".")[0].strip("'\"")
                elif match_js: missing_module = match_js.group(1).split("/")[0].strip("'\"")

                if missing_module:
                    pkg_name = TELEGRAM_MODULES.get(missing_module.lower(), missing_module)
                    ext = os.path.splitext(file_name)[1].lower()
                    cmd_text = f"npm install {pkg_name}" if ext == ".js" else f"pip install {pkg_name}"
                    error_msg = f"⚠️ **ফাইল রান হতে সমস্যা হয়েছে!**\n\n📄 **File:** `{file_name}`\n❌ **সমস্যা:** আপনার কোডে `{missing_module}` মডিউলটি মিসিং আছে।\n💻 **প্রয়োজনীয় কমান্ড:** `{cmd_text}`"
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    markup.add(
                        make_inline_button(f"📦 Install {pkg_name}", callback_data=f"instmod_{script_owner_id}_{file_name}"),
                        make_inline_button("📄 View Error Logs", callback_data=f"viewlog_{script_owner_id}_{file_name}")
                    )
                    error_msg += "\n\n📦 নিচের <b>Install</b> বাটনে ক্লিক করলে শুধু আপনার এই ফাইলের জন্য dependency install হবে এবং install শেষে bot আবার automatically run হবে."
                    bot.send_message(message_obj_for_reply.chat.id, error_msg, reply_markup=markup, parse_mode="HTML", protect_content=True)
                else:
                    markup = types.InlineKeyboardMarkup()
                    markup.add(make_inline_button("📄 View Error Logs", callback_data=f"viewlog_{script_owner_id}_{file_name}"))
                    bot.send_message(message_obj_for_reply.chat.id, f"⚠️ **আপনার কোডে ভুল (Syntax/Runtime Error) পাওয়া গেছে!**\n📄 **File:** `{file_name}`", reply_markup=markup, parse_mode="Markdown", protect_content=True)
            except: pass
    except Exception as e:
        logger.error(f"Error in monitor_and_guide_error: {e}")

def run_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply):
    script_key = f"{script_owner_id}_{file_name}"
    try:
        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = open(log_file_path, "w", encoding="utf-8", errors="ignore")
        
        unique_port = 8000 + (int(hashlib.md5(script_key.encode()).hexdigest(), 16) % 50000)
        
        custom_env = os.environ.copy()
        custom_env["PORT"] = str(unique_port)
        custom_env["PYTHONDONTWRITEBYTECODE"] = "1"
        custom_env["PYTHONPATH"] = user_folder
        custom_env["HOME"] = user_folder        
        custom_env["TEMP"] = user_folder        
        custom_env["TMP"] = user_folder         
        custom_env["TMPDIR"] = user_folder      
        
        process = subprocess.Popen([sys.executable, "-u", script_path], cwd=user_folder, stdout=log_file, stderr=log_file, stdin=subprocess.DEVNULL, env=custom_env, shell=False, start_new_session=True)
        
        bot_scripts[script_key] = {"process": process, "log_file": log_file, "file_name": file_name, "script_owner_id": script_owner_id, "start_time": datetime.now(), "warning_sent": False, "user_folder": user_folder, "type": "py"}
        bot.send_message(message_obj_for_reply.chat.id, f"🚀 **Python Bot Started!**\n📄 File: `{file_name}`\n🆔 PID: `{process.pid}`", parse_mode="Markdown", protect_content=True)
        threading.Thread(target=monitor_and_guide_error, args=(process, log_file_path, script_owner_id, file_name, message_obj_for_reply), daemon=True).start()
    except Exception as e:
        bot.send_message(message_obj_for_reply.chat.id, f"❌ Error starting script: {str(e)}", protect_content=True)

def run_js_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply):
    script_key = f"{script_owner_id}_{file_name}"
    try:
        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = open(log_file_path, "w", encoding="utf-8", errors="ignore")
        
        unique_port = 8000 + (int(hashlib.md5(script_key.encode()).hexdigest(), 16) % 50000)
        
        custom_env = os.environ.copy()
        custom_env["PORT"] = str(unique_port)
        custom_env["NODE_PATH"] = user_folder
        custom_env["HOME"] = user_folder
        custom_env["TEMP"] = user_folder
        custom_env["TMP"] = user_folder
        custom_env["TMPDIR"] = user_folder
        
        process = subprocess.Popen(["node", script_path], cwd=user_folder, stdout=log_file, stderr=log_file, stdin=subprocess.DEVNULL, env=custom_env, shell=False, start_new_session=True)
        
        bot_scripts[script_key] = {"process": process, "log_file": log_file, "file_name": file_name, "script_owner_id": script_owner_id, "start_time": datetime.now(), "warning_sent": False, "user_folder": user_folder, "type": "js"}
        bot.send_message(message_obj_for_reply.chat.id, f"🚀 **JS Bot Started!**\n📄 File: `{file_name}`\n🆔 PID: `{process.pid}`", parse_mode="Markdown", protect_content=True)
        threading.Thread(target=monitor_and_guide_error, args=(process, log_file_path, script_owner_id, file_name, message_obj_for_reply), daemon=True).start()
    except Exception as e:
        bot.send_message(message_obj_for_reply.chat.id, f"❌ Error starting JS script: {str(e)}", protect_content=True)

def do_start_bot(owner_id, fname, message_obj, call_id=None):
    owner_id = int(owner_id)
    ufolder = get_user_folder(owner_id)
    fpath = os.path.join(ufolder, fname)
    ext = os.path.splitext(fname)[1].lower()

    if is_free_hosting_exhausted(owner_id):
        text = "⏱️ Free 12-hour hosting has ended. Buy a plan from Account → Deposit to continue."
        if call_id: bot.answer_callback_query(call_id, text, show_alert=True)
        else: bot.send_message(message_obj.chat.id, "🛑 **Free Hosting Limit Finished**\n\n💎 Account → Deposit থেকে balance add করে একটি Plan কিনুন।", parse_mode="Markdown")
        return

    # A file must exist in the approved user_files table before it can run.
    if not any(str(n) == str(fname) for n, _ in user_files.get(owner_id, [])):
        if call_id:
            bot.answer_callback_query(call_id, "🔐 File is not approved yet.", show_alert=True)
        else:
            bot.send_message(message_obj.chat.id, "🔐 **File locked:** admin approval is required before it can run.")
        return

    # Free users can host for at most 12 hours per running process.
    if not has_active_plan(owner_id):
        # Existing free run can be continued only while its 12h timer is active.
        existing = bot_scripts.get(f"{owner_id}_{fname}")
        if existing:
            elapsed = (datetime.now() - existing["start_time"]).total_seconds() / 3600
            if elapsed >= 12:
                force_kill_user_bot(owner_id, fname)
                if call_id:
                    bot.answer_callback_query(call_id, "⏱️ Free 12-hour limit reached. Buy a plan.", show_alert=True)
                return

    if is_bot_running(owner_id, fname):
        if call_id: bot.answer_callback_query(call_id, "এই বোটটি অলরেডি রানিং আছে!", show_alert=True)
        return

    if call_id: bot.answer_callback_query(call_id, "Starting...")
    if ext == ".js":
        run_js_script(fpath, int(owner_id), ufolder, fname, message_obj)
    else:
        run_script(fpath, int(owner_id), ufolder, fname, message_obj)

# --- DB Files Operations ---
def save_user_file(user_id, file_name, file_type="py"):
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO user_files (user_id, file_name, file_type) VALUES (?, ?, ?)", (user_id, file_name, file_type))
            conn.commit()
            conn.close()
            if user_id not in user_files: user_files[user_id] = []
            user_files[user_id] = [(fn, ft) for fn, ft in user_files[user_id] if fn != file_name]
            user_files[user_id].append((file_name, file_type))
    except Exception as e:
        logger.error(f"Error saving file to DB: {e}")

def remove_user_file_db(user_id, file_name):
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("DELETE FROM user_files WHERE user_id = ? AND file_name = ?", (user_id, file_name))
            conn.commit()
            conn.close()
            if user_id in user_files:
                user_files[user_id] = [f for f in user_files[user_id] if f[0] != file_name]
    except Exception as e:
        logger.error(f"Error removing file from DB: {e}")

def add_active_user(user_id):
    active_users.add(user_id)
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("INSERT OR IGNORE INTO active_users (user_id) VALUES (?)", (user_id,))
            conn.commit()
            conn.close()
    except Exception as e:
        logger.error(f"Error adding active user: {e}")

# --- UI Methods ---
def create_reply_keyboard_main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    layout_to_use = ADMIN_COMMAND_BUTTONS_LAYOUT_USER_SPEC if user_id in admin_ids else COMMAND_BUTTONS_LAYOUT_USER_SPEC
    for row in layout_to_use:
        markup.add(*[make_reply_button(text) for text in row])
    return markup

def _payment_enabled(method):
    return get_setting(f"{method}_enabled", "0") == "1"


def create_admin_panel_inline(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    bkash_state = "🟢 ON" if _payment_enabled("bkash") else "🔴 OFF"
    nagad_state = "🟢 ON" if _payment_enabled("nagad") else "🔴 OFF"

    markup.add(
        make_inline_button(f"🟣 bKash {bkash_state}", callback_data="toggle_bkash"),
        make_inline_button(f"🟠 Nagad {nagad_state}", callback_data="toggle_nagad")
    )
    markup.add(
        make_inline_button("⚙️ 𝗦𝗲𝘁 bKash Number", callback_data="set_bkash"),
        make_inline_button("⚙️ 𝗦𝗲𝘁 Nagad Number", callback_data="set_nagad")
    )
    markup.add(
        make_inline_button("💰 𝗣𝗲𝗻𝗱𝗶𝗻𝗴 𝗗𝗲𝗽𝗼𝘀𝗶𝘁𝘀", callback_data="pending_deposits"),
    )
    markup.add(
        make_inline_button(f"{get_random_button_prefix('success')} 𝗔𝗱𝗱 𝗣𝗹𝗮𝗻", callback_data="add_plan"),
        make_inline_button(f"{get_random_button_prefix('danger')} 𝗥𝗲𝗺𝗼𝘃𝗲 𝗣𝗹𝗮𝗻", callback_data="remove_plan")
    )
    markup.add(
        make_inline_button("✅ 𝗔𝗽𝗽𝗿𝗼𝘃𝗲 𝗣𝗹𝗮𝗻 (Give VIP)", callback_data="give_plan")
    )
    markup.add(
        make_inline_button("➕ 𝗔𝗱𝗱 𝗖𝗵𝗮𝗻𝗻𝗲𝗹", callback_data="add_channel"),
        make_inline_button("➖ 𝗥𝗲𝗺𝗼𝘃𝗲 𝗖𝗵𝗮𝗻𝗻𝗲𝗹", callback_data="remove_channel")
    )
    markup.add(
        make_inline_button("📣 𝗕𝗿𝗼𝗮𝗱𝗰𝗮𝘀𝘁", callback_data="broadcast"),
        make_inline_button(f"{get_random_button_prefix('normal')} 𝗟𝗼𝗰𝗸/𝗨𝗻𝗹𝗼𝗰𝗸", callback_data="toggle_lock")
    )
    markup.add(
        make_inline_button("⚙️ 𝗥𝘂𝗻 𝗔𝗹𝗹 𝗦𝗰𝗿𝗶𝗽𝘁𝘀", callback_data="run_all_scripts"),
        make_inline_button("📊 𝗕𝗼𝘁 𝗦𝘁𝗮𝘁𝘀", callback_data="stats")
    )
    markup.add(
        make_inline_button("🎥 𝗦𝗲𝘁 𝗧𝘂𝘁𝗼𝗿𝗶𝗮𝗹", callback_data="set_tutorial")
    )

    core_admins = {int(OWNER_ID), int(globals().get("SECOND_ADMIN_ID", 0) or 0)}
    if int(user_id) in core_admins:
        markup.add(
            make_inline_button("🟩 𝗔𝗱𝗱 𝗔𝗱𝗺𝗶𝗻", callback_data="add_admin"),
            make_inline_button("🟥 𝗥𝗲𝗺𝗼𝘃𝗲 𝗠𝘆 𝗔𝗱𝗺𝗶𝗻", callback_data="remove_admin")
        )
        markup.add(
            make_inline_button("🟦 𝗦𝗲𝘁 𝗕𝗼𝘁 𝗟𝗶𝗺𝗶𝘁", callback_data="set_limit"),
            make_inline_button("🟥 𝗕𝗹𝗼𝗰𝗸 𝗨𝘀𝗲𝗿", callback_data="block_user")
        )
        markup.add(make_inline_button("🟩 𝗨𝗻𝗯𝗹𝗼𝗰𝗸 𝗨𝘀𝗲𝗿", callback_data="unblock_user"))

    if int(user_id) == int(globals().get("SECOND_ADMIN_ID", 0) or 0):
        markup.add(
            make_inline_button("🟦 𝗗𝗕 𝗗𝗼𝘄𝗻𝗹𝗼𝗮𝗱", callback_data="db_download"),
            make_inline_button("🟨 𝗗𝗕 𝗨𝗽𝗹𝗼𝗮𝗱", callback_data="db_upload")
        )
    return markup


# --- Start & Menus ---
@bot.message_handler(commands=["start"])
def start_cmd(message):
    try:
        user_id = message.from_user.id
        if user_id in blocked_users:
            return 
            
        chat_id = message.chat.id
        user_name = message.from_user.first_name
        args = message.text.split()

        if bot_locked and user_id not in admin_ids:
            bot.send_message(chat_id, "⚠️ **Bot is temporarily locked by Admin.**")
            return

        add_active_user(user_id)
        
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("SELECT user_id FROM user_account WHERE user_id=?", (user_id,))
            is_new_user = c.fetchone() is None
            if is_new_user:
                c.execute(
                    "INSERT INTO user_account (user_id, balance, total_referrals) VALUES (?, 0, 0)",
                    (user_id,),
                )

            referral_awarded = False
            referrer_id = None
            if is_new_user and len(args) > 1:
                ref_id = args[1].strip()
                if ref_id.isdigit() and int(ref_id) != user_id:
                    candidate = int(ref_id)
                    c.execute("SELECT user_id FROM user_account WHERE user_id=?", (candidate,))
                    if c.fetchone():
                        try:
                            c.execute(
                                """INSERT INTO referral_rewards
                                   (referred_user_id, referrer_user_id, bonus)
                                   VALUES (?, ?, 2.50)""",
                                (user_id, candidate),
                            )
                            c.execute(
                                "UPDATE user_account SET total_referrals = total_referrals + 1, "
                                "balance = balance + 2.50 WHERE user_id=?",
                                (candidate,),
                            )
                            referral_awarded = True
                            referrer_id = candidate
                        except sqlite3.IntegrityError:
                            # Already rewarded: never credit twice.
                            referral_awarded = False
            conn.commit()
            conn.close()

        if referral_awarded and referrer_id is not None:
            try:
                bot.send_message(
                    referrer_id,
                    "🎉 **Referral Successful!**\n\n"
                    "👤 আপনার ইনভাইট করা নতুন ইউজার বটটিতে জয়েন করেছে।\n"
                    "💰 আপনার ব্যালেন্সে **2.50 BDT** যোগ করা হয়েছে।",
                    parse_mode="Markdown",
                )
            except Exception:
                logger.info("Referral notification could not be delivered to %s", referrer_id)

        limit = get_user_file_limit(user_id)
        is_vip = is_vip_user(user_id)
        vip_status = "💎 VIP Member" if is_vip else "🆓 Free User"

        welcome_msg = (
            f"✨ **𝗪𝗲𝗹𝗰𝗼𝗺𝗲, {user_name}!** ✨\n\n"
            f"🆔 **𝗬𝗼𝘂𝗿 𝗜𝗗:** `{user_id}`\n"
            f"🔰 **𝗦𝘁𝗮𝘁𝘂𝘀:** `{vip_status}`\n"
            f"🔰 **𝗛𝗼𝘀𝘁𝗶𝗻𝗴 𝗟𝗶𝗺𝗶𝘁:** `{get_user_file_count(user_id)}` / `{limit}`\n\n"
            f"🔐 *Secure hosting is active — every upload needs admin approval.*\n"
            f"💡 *Python (.py) & JS (.js) hosting supported.*\n"
            f"👇 *Choose an option below to continue:* "
        )
        bot.send_message(chat_id, welcome_msg, reply_markup=create_reply_keyboard_main_menu(user_id), parse_mode="Markdown", protect_content=True)
    except Exception as e:
        logger.error(f"Error in start command: {e}")

def _logic_upload_file(message):
    user_id = message.from_user.id
    if bot_locked and user_id not in admin_ids:
        bot.send_message(message.chat.id, "⚠️ **Bot is locked by Admin.**")
        return

    if user_id not in admin_ids and not has_active_plan(user_id):
        bot.send_message(
            message.chat.id,
            "🔐 **VIP Plan Required**\n\n"
            "Plan ছাড়া নতুন file upload করা যাবে না।\n"
            "💎 **VIP Plans** থেকে একটি active plan কিনে আবার upload করুন।",
            parse_mode="Markdown"
        )
        return

    current_count = get_user_file_count(user_id)
    max_limit = get_user_file_limit(user_id)

    if current_count >= max_limit:
        bot.send_message(message.chat.id, f"⚠️ **আপনার আপলোড লিমিট শেষ!**\n\n📊 **বর্তমান আপলোড:** `{current_count}` / `{max_limit}`\n"
                              f"নতুন কোনো ফাইল রান করাতে `📁 Manage Files` থেকে যেকোনো একটি বোট ডিলিট করুন অথবা VIP Plan কিনুন।", parse_mode="Markdown")
        return

    bot.send_message(message.chat.id, "🚀 **আপনার Python (.py) অথবা JS (.js) বোট ফাইলটি মেসেজে আপলোড করুন।**\n"
                          "*(ফাইল দেওয়ার পর ফাইলটি সেভ হবে। এরপর Manage Files থেকে বোটটি চালু করতে হবে)*", parse_mode="Markdown")

def _logic_check_files(message):
    user_id = message.from_user.id
    user_files_list = user_files.get(user_id, [])
    if not user_files_list:
        bot.send_message(message.chat.id, "📂 **Your Uploaded Files:**\n\n*(No files uploaded yet)*", parse_mode="Markdown")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for file_name, file_type in sorted(user_files_list):
        is_running = is_bot_running(user_id, file_name)
        status_icon = "🟢 Running" if is_running else "🔴 Stopped"
        btn_text = f"📄 {file_name} ({file_type}) - {status_icon}"
        markup.add(make_inline_button(btn_text, callback_data=f"file_{user_id}_{file_name}"))
    bot.send_message(message.chat.id, f"📁 **𝗠𝗮𝗻𝗮𝗴𝗲 𝗬𝗼𝘂𝗿 𝗙𝗶𝗹𝗲𝘀 ({len(user_files_list)}/{get_user_file_limit(user_id)}):**", reply_markup=markup, parse_mode="Markdown", protect_content=True)

def _logic_vip_plans(message):
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("SELECT plan_id, name, description, bot_limit, duration_days, price FROM plans")
            plans = c.fetchall()
            conn.close()

        if not plans:
            bot.send_message(message.chat.id, "❌ বর্তমানে কোনো VIP Plan নেই। এডমিনের সাথে যোগাযোগ করুন।")
            return

        bot.send_message(message.chat.id, "🌟 **আমাদের ভিআইপি (VIP) প্ল্যানসমূহ:**\nপছন্দমতো প্ল্যান বেছে নিন এবং নিরবচ্ছিন্ন আনলিমিটেড হোস্টিং উপভোগ করুন!", parse_mode="Markdown")
        
        for plan in plans:
            plan_id, name, desc, limit, days, price = plan
            plan_msg = (
                f"**{name}**\n"
                f"📝 **বিস্তারিত:** {desc}\n"
                f"🤖 **বট লিমিট:** `{limit} টি বোট`\n"
                f"⏳ **মেয়াদ:** `{days} দিন`\n"
                f"💰 **মূল্য:** `{price}`"
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(make_inline_button("🛒 Buy Now", callback_data=f"buy_plan_{plan_id}"))
            bot.send_message(message.chat.id, plan_msg, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in VIP plans: {e}")
        bot.send_message(message.chat.id, "❌ Error loading plans.")

def _logic_tutorial(message):
    tut_link = get_setting("tutorial_link", UPDATE_CHANNEL)
    markup = types.InlineKeyboardMarkup()
    markup.add(make_inline_button("🎥 Watch Tutorial Video", url=tut_link))
    msg = (
        "🎥 **𝗛𝗼𝘄 𝗧𝗼 𝗨𝘀𝗲 & 𝗛𝗼𝘀𝘁 𝗕𝗼𝘁:**\n\n"
        "কীভাবে ফাইল আপলোড করতে হয় এবং সহজে আপনার বোট রান করাতে হয় তা শিখতে নিচের বাটনে ক্লিক করে ভিডিওটি দেখুন।"
    )
    bot.send_message(message.chat.id, msg, reply_markup=markup, parse_mode="Markdown", protect_content=True)

def _logic_add_money(message):
    start_deposit_session(message.from_user.id)
    markup = types.InlineKeyboardMarkup()
    markup.add(make_inline_button("❌ Cancel", callback_data="deposit_cancel"))
    bot.send_message(
        message.chat.id,
        "💰 **Add Money**\n\n"
        "💵 কত টাকা যোগ করতে চান?\n"
        "📌 সর্বনিম্ন: **10 BDT**\n"
        "📌 সর্বোচ্চ: **50,000 BDT**\n\n"
        "শুধু টাকার পরিমাণ লিখুন।",
        reply_markup=markup,
        parse_mode="Markdown"
    )


def start_deposit_session(user_id):
    """Create/reset a fully persistent deposit wizard in SQLite."""
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute(
            """INSERT INTO deposit_sessions
               (user_id, amount, method, payment_number, trx_id, sender_phone,
                step, created_at, updated_at)
               VALUES (?, NULL, NULL, NULL, NULL, NULL, 'amount',
                       CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
               ON CONFLICT(user_id) DO UPDATE SET
                   amount=NULL, method=NULL, payment_number=NULL,
                   trx_id=NULL, sender_phone=NULL,
                   step='amount', updated_at=CURRENT_TIMESTAMP""",
            (int(user_id),)
        )
        conn.commit()
        conn.close()


def get_deposit_session(user_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        row = conn.execute(
            """SELECT user_id, amount, method, payment_number, trx_id,
                      sender_phone, step
               FROM deposit_sessions WHERE user_id=?""",
            (int(user_id),)
        ).fetchone()
        conn.close()
    if not row:
        return None
    return {
        "user_id": row[0], "amount": row[1], "method": row[2],
        "payment_number": row[3], "trx_id": row[4],
        "sender_phone": row[5], "step": row[6]
    }


def update_deposit_session(user_id, **fields):
    allowed = {"amount", "method", "payment_number", "trx_id", "sender_phone", "step"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    assignments = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [int(user_id)]
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        conn.execute(
            f"UPDATE deposit_sessions SET {assignments}, updated_at=CURRENT_TIMESTAMP WHERE user_id=?",
            values
        )
        conn.commit()
        conn.close()


def clear_deposit_session(user_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        conn.execute("DELETE FROM deposit_sessions WHERE user_id=?", (int(user_id),))
        conn.commit()
        conn.close()


def get_payment_methods_markup():
    markup = types.InlineKeyboardMarkup(row_width=2)
    added = False
    if _payment_enabled("bkash"):
        markup.add(make_inline_button("🟣 bKash", callback_data="dep_method_bkash"))
        added = True
    if _payment_enabled("nagad"):
        markup.add(make_inline_button("🟠 Nagad", callback_data="dep_method_nagad"))
        added = True
    markup.add(make_inline_button("❌ Cancel", callback_data="deposit_cancel"))
    return markup if added else None


def _show_payment_methods(chat_id):
    markup = get_payment_methods_markup()
    if markup is None:
        bot.send_message(chat_id, "⚠️ বর্তমানে কোনো payment method চালু নেই। Admin-এর সাথে যোগাযোগ করুন।")
        return False
    bot.send_message(
        chat_id,
        "💳 **𝗣𝗮𝘆𝗺𝗲𝗻𝘁 𝗠𝗲𝘁𝗵𝗼𝗱 𝗦𝗲𝗹𝗲𝗰𝘁 করুন:**\n\n"
        "নিচের চালু থাকা method থেকে একটি নির্বাচন করুন।",
        reply_markup=markup,
        parse_mode="Markdown"
    )
    return True


def _show_payment_number(chat_id, user_id, method):
    enabled = _payment_enabled(method)
    number = get_setting(f"{method}_number", DEFAULT_BKASH if method == "bkash" else DEFAULT_NAGAD)
    if not enabled or not number or str(number).strip().lower() == "off":
        bot.send_message(chat_id, "❌ এই payment method বর্তমানে বন্ধ আছে। অন্য method নির্বাচন করুন।")
        update_deposit_session(user_id, method=None, payment_number=None, step="method")
        _show_payment_methods(chat_id)
        return

    session = get_deposit_session(user_id)
    amount = session["amount"] if session else None
    if not amount:
        start_deposit_session(user_id)
        bot.send_message(chat_id, "📝 প্রথমে amount লিখুন।")
        return

    update_deposit_session(user_id, method=method, payment_number=str(number), step="trx")
    method_name = "bKash" if method == "bkash" else "Nagad"
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(make_copy_number_button(number))
    markup.add(make_inline_button("❌ Cancel", callback_data="deposit_cancel"))
    bot.send_message(
        chat_id,
        f"💳 **{method_name} Payment**\n\n"
        f"💵 Amount: `{amount} BDT`\n"
        f"📱 Number: `{number}`\n\n"
        "1️⃣ এই নম্বরে Send Money করুন।\n"
        "2️⃣ পেমেন্ট সফল হলে আপনার TRX ID এবং যে নাম্বার থেকে টাকা পাঠিয়েছেন তা জমা দিন।\n"
        "3️⃣ নিচের Copy Number বাটন ব্যবহার করে payment number কপি করতে পারবেন।\n\n"
        "🔑 এখন আপনার **TRX ID** লিখুন।",
        reply_markup=markup,
        parse_mode="Markdown"
    )


def get_pending_deposits(limit=20):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        rows = conn.execute(
            """SELECT deposit_id, user_id, amount, method, trx_id, created_at
               FROM deposit_requests WHERE status='pending'
               ORDER BY created_at ASC LIMIT ?""",
            (int(limit),)
        ).fetchall()
        conn.close()
    return rows


def claim_deposit(deposit_id, admin_id, new_status):
    if new_status not in ("approved", "rejected"):
        return None
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT deposit_id, user_id, amount, method, payment_number, trx_id,
                      sender_phone, status
               FROM deposit_requests WHERE deposit_id=?""",
            (deposit_id,)
        ).fetchone()
        if not row or row[7] != "pending":
            conn.rollback()
            conn.close()
            return None
        cur = conn.execute(
            """UPDATE deposit_requests
               SET status=?, reviewed_by=?, reviewed_at=CURRENT_TIMESTAMP
               WHERE deposit_id=? AND status='pending'""",
            (new_status, int(admin_id), deposit_id)
        )
        if cur.rowcount != 1:
            conn.rollback()
            conn.close()
            return None
        if new_status == "approved":
            conn.execute(
                "INSERT OR IGNORE INTO user_account (user_id, balance, total_referrals) VALUES (?, 0, 0)",
                (int(row[1]),)
            )
            conn.execute(
                "UPDATE user_account SET balance = balance + ? WHERE user_id=?",
                (int(row[2]), int(row[1]))
            )
        conn.commit()
        conn.close()
    return row


def get_telegram_user_display(user_id):
    """Best-effort Telegram display name and username lookup."""
    uid = int(user_id)
    name = f"User {uid}"
    username = ""
    for real_bot in BOT_INSTANCES:
        try:
            chat = real_bot.get_chat(uid)
            first = (getattr(chat, "first_name", "") or "").strip()
            last = (getattr(chat, "last_name", "") or "").strip()
            username = (getattr(chat, "username", "") or "").strip()
            full_name = " ".join(x for x in (first, last) if x)
            if full_name:
                name = full_name
            break
        except Exception:
            continue
    return name, username


def send_deposit_request_to_admins(deposit_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        row = conn.execute(
            """SELECT user_id, amount, method, payment_number, trx_id,
                      sender_phone, created_at
               FROM deposit_requests WHERE deposit_id=?""",
            (deposit_id,)
        ).fetchone()
        conn.close()
    if not row:
        return 0
    user_id, amount, method, payment_number, trx_id, sender_phone, created_at = row
    display_name, username = get_telegram_user_display(user_id)
    username_line = f" (@{username})" if username else ""
    admin_msg = (
        "💰 **NEW DEPOSIT REQUEST**\n\n"
        f"👤 **Name:** `{display_name}`{username_line}\n"
        f"🆔 **User ID:** `{user_id}`\n"
        f"💵 **Amount:** `{amount} BDT`\n"
        f"🏦 **Method:** `{method.upper()}`\n"
        f"📱 **Payment Number:** `{payment_number}`\n"
        f"📱 **Sender Number:** `{sender_phone}`\n"
        f"🔑 **TRX ID:** `{trx_id}`\n"
        f"🕒 **Time:** `{created_at}`"
    )

    send_activity_log(
        "💰 <b>DEPOSIT REQUEST</b>\n\n"
        f"👤 <b>Name:</b> {display_name}{username_line}\n"
        f"🆔 <b>TG ID:</b> <code>{user_id}</code>\n"
        f"💵 <b>Amount:</b> <code>{amount} BDT</code>\n"
        f"🏦 <b>Method:</b> <code>{method.upper()}</code>\n"
        f"📱 <b>Sender:</b> <code>{sender_phone}</code>\n"
        f"🔑 <b>TRX ID:</b> <code>{trx_id}</code>\n"
        f"🕒 <b>Time:</b> <code>{created_at}</code>"
    )

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        make_inline_button("✅ Approve", callback_data=f"dep_app_{deposit_id}"),
        make_inline_button("❌ Reject", callback_data=f"dep_rej_{deposit_id}")
    )
    sent = 0
    for admin_uid in sorted(APPROVAL_ADMIN_IDS):
        for real_bot in BOT_INSTANCES:
            try:
                real_bot.send_message(admin_uid, admin_msg, reply_markup=markup, parse_mode="Markdown")
                sent += 1
                break
            except Exception as e:
                logger.warning("Deposit notification failed for admin %s: %s", admin_uid, e)
    return sent


def process_deposit_amount(message):
    user_id = int(message.from_user.id)
    text = (message.text or "").strip().replace(",", "")
    if not re.fullmatch(r"\d+", text):
        bot.send_message(message.chat.id, "❌ সঠিক amount লিখুন। শুধু সংখ্যা দিন। (10–50,000)")
        return
    amount = int(text)
    if amount < 10 or amount > 50000:
        bot.send_message(message.chat.id, "❌ Amount অবশ্যই 10 থেকে 50,000 BDT-এর মধ্যে হতে হবে।")
        return

    session = get_deposit_session(user_id)
    if not session:
        start_deposit_session(user_id)
    update_deposit_session(
        user_id,
        amount=amount,
        method=None,
        payment_number=None,
        trx_id=None,
        sender_phone=None,
        step="method",
    )
    _show_payment_methods(message.chat.id)


def process_deposit_trx(message):
    """Persist and validate TRX ID, then move the wizard to sender-phone step."""
    user_id = int(message.from_user.id)
    session = get_deposit_session(user_id)
    if not session or session.get("step") != "trx" or not session.get("amount") or not session.get("method"):
        bot.send_message(
            message.chat.id,
            "❌ এই মুহূর্তে কোনো active deposit নেই। 💰 Add Money চাপুন এবং আবার শুরু করুন।",
        )
        return

    trx_id = (message.text or "").strip()
    if not trx_id or len(trx_id) > 128 or not re.fullmatch(r"[A-Za-z0-9._:-]+", trx_id):
        bot.send_message(message.chat.id, "❌ Valid TRX ID দিন (সর্বোচ্চ 128 characters)।")
        return

    # Keep the session alive in SQLite. Nothing depends on Telegram's
    # volatile register_next_step_handler state.
    update_deposit_session(user_id, trx_id=trx_id, step="sender_phone")

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(make_inline_button("❌ Cancel", callback_data="deposit_cancel"))
    bot.send_message(
        message.chat.id,
        "📱 **Sender Phone Number**\n\n"
        "যে মোবাইল নম্বর থেকে টাকা পাঠিয়েছেন সেই নম্বরটি লিখুন।\n\n"
        "উদাহরণ: `017XXXXXXXX`",
        reply_markup=markup,
        parse_mode="Markdown",
    )


def process_deposit_sender_phone(message):
    """Validate sender phone and atomically create the pending deposit request."""
    user_id = int(message.from_user.id)
    session = get_deposit_session(user_id)
    if (
        not session
        or session.get("step") != "sender_phone"
        or not session.get("amount")
        or not session.get("method")
        or not session.get("payment_number")
        or not session.get("trx_id")
    ):
        bot.send_message(
            message.chat.id,
            "❌ এই মুহূর্তে কোনো active deposit নেই। 💰 Add Money চাপুন এবং আবার শুরু করুন।",
        )
        return

    sender_phone = re.sub(r"[\s-]", "", (message.text or "").strip())
    if sender_phone.startswith("+880"):
        sender_phone = "0" + sender_phone[4:]
    if not re.fullmatch(r"01[3-9]\d{8}", sender_phone):
        bot.send_message(
            message.chat.id,
            "❌ সঠিক বাংলাদেশি sender number দিন। উদাহরণ: `017XXXXXXXX`",
            parse_mode="Markdown",
        )
        return

    amount = int(session["amount"])
    method = str(session["method"])
    payment_number = str(session["payment_number"])
    trx_id = str(session["trx_id"])
    deposit_id = uuid.uuid4().hex

    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT INTO deposit_requests
                   (deposit_id, user_id, amount, method, payment_number, trx_id,
                    sender_phone, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (
                    deposit_id,
                    user_id,
                    amount,
                    method,
                    payment_number,
                    trx_id,
                    sender_phone,
                ),
            )
            conn.execute("DELETE FROM deposit_sessions WHERE user_id=?", (user_id,))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            bot.send_message(
                message.chat.id,
                "❌ এই TRX ID ইতিমধ্যে ব্যবহার করা হয়েছে। সঠিক TRX ID দিন।",
            )
            return
        finally:
            conn.close()

    sent = send_deposit_request_to_admins(deposit_id)
    if sent:
        bot.send_message(
            message.chat.id,
            f"⏳ **Deposit Submitted Successfully**\n\n"
            f"💵 Amount: `{amount} BDT`\n"
            f"🏦 Method: `{method.upper()}`\n"
            f"📱 Sender: `{sender_phone}`\n"
            f"🔑 TRX ID: `{trx_id}`\n\n"
            "👨‍💻 Admin review করার পর approve/reject হবে।",
            parse_mode="Markdown",
        )
    else:
        bot.send_message(
            message.chat.id,
            "⚠️ Deposit database-এ pending হিসেবে save হয়েছে, কিন্তু admin notification পাঠানো যায়নি। "
            "Admin পরে Pending Deposits থেকে review করতে পারবেন।",
        )

def cancel_deposit(user_id):
    clear_deposit_session(user_id)

def _logic_account(message):
    user_id = message.from_user.id
    balance, refs = get_user_account(user_id)
    try:
        bot_username = bot.get_me().username
    except:
        bot_username = "your_bot_username"
        
    ref_link = f"https://t.me/{bot_username}?start={user_id}"
    
    msg = (
        f"👤 **??𝘆 𝗔𝗰𝗰𝗼𝘂𝗻𝘁**\n\n"
        f"💰 **𝗕𝗮𝗹𝗮𝗻𝗰𝗲:** `{balance} BDT`\n"
        f"👥 **𝗧𝗼𝘁𝗮𝗹 𝗥𝗲𝗳𝗲𝗿𝗿𝗮𝗹𝘀:** `{refs}`\n"
        f"🔗 **𝗥𝗲𝗳𝗲𝗿𝗿𝗮𝗹 𝗟𝗶𝗻𝗸:**\n`{ref_link}`\n\n"
        f"*(Referral bonus: প্রতি সফল invite-এ 2.50 BDT)*"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(make_inline_button("💰 𝗔𝗱𝗱 𝗠𝗼𝗻𝗲𝘆", callback_data="deposit_init"))
    bot.send_message(message.chat.id, msg, reply_markup=markup, parse_mode="Markdown")

def process_database_upload(message):
    """Restore SQLite DB only for SECOND_ADMIN_ID."""
    if int(message.from_user.id) != int(globals().get("SECOND_ADMIN_ID", 0) or 0):
        bot.send_message(message.chat.id, "❌ Database restore is restricted to the second bot admin.")
        return
    doc = getattr(message, "document", None)
    if not doc:
        bot.send_message(message.chat.id, "❌ Please send a `.db` or `.sqlite` file.")
        return
    name = os.path.basename(doc.file_name or "")
    if not name.lower().endswith((".db", ".sqlite", ".sqlite3")):
        bot.send_message(message.chat.id, "❌ Only SQLite `.db/.sqlite/.sqlite3` files are accepted.")
        return
    try:
        info = bot.get_file(doc.file_id)
        data = bot.download_file(info.file_path)
        if len(data) > 100 * 1024 * 1024:
            bot.send_message(message.chat.id, "❌ Database backup is too large (max 100 MB).")
            return

        tmp = DATABASE_PATH + ".restore.tmp"
        backup = DATABASE_PATH + ".before_restore.bak"
        with DB_LOCK:
            with open(tmp, "wb") as f:
                f.write(data)
            check = sqlite3.connect(tmp)
            try:
                result = check.execute("PRAGMA integrity_check").fetchone()
            finally:
                check.close()
            if not result or str(result[0]).lower() != "ok":
                os.remove(tmp)
                bot.send_message(message.chat.id, "❌ Database integrity check failed. Current database was not changed.")
                return
            if os.path.exists(DATABASE_PATH):
                shutil.copy2(DATABASE_PATH, backup)
            os.replace(tmp, DATABASE_PATH)

        # Refresh in-memory caches from restored DB.
        user_files.clear()
        active_users.clear()
        blocked_users.clear()
        admin_ids.clear()
        admin_ids.update({int(OWNER_ID), int(ADMIN_ID)})
        if int(globals().get("SECOND_ADMIN_ID", 0) or 0):
            admin_ids.add(int(globals().get("SECOND_ADMIN_ID")))
        load_data()

        bot.send_message(
            message.chat.id,
            "✅ **Database Restored Successfully**\n\n"
            "🛡️ Integrity check: passed\n"
            "💾 Previous DB backup: `.before_restore.bak`\n"
            "🔄 In-memory data: refreshed",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error("Database restore failed: %s", e, exc_info=True)
        try:
            if os.path.exists(DATABASE_PATH + ".restore.tmp"):
                os.remove(DATABASE_PATH + ".restore.tmp")
        except Exception:
            pass
        bot.send_message(message.chat.id, f"❌ **Database restore failed:** `{str(e)[:300]}`", parse_mode="Markdown")

# --- File Upload Handler ---
@bot.message_handler(content_types=["document"])
def handle_file_upload_doc(message):
    user_id = message.from_user.id
    doc_name = os.path.basename(getattr(message.document, "file_name", "") or "")
    if int(user_id) == int(globals().get("SECOND_ADMIN_ID", 0) or 0) and doc_name.lower().endswith((".db", ".sqlite", ".sqlite3")):
        process_database_upload(message); return
    if user_id in blocked_users: return
    if user_id not in admin_ids and not has_active_plan(user_id):
        bot.send_message(
            message.chat.id,
            "🔐 **VIP Plan Required**\n\n"
            "Plan ছাড়া নতুন file upload করা যাবে না।\n"
            "💎 **VIP Plans** থেকে একটি active plan কিনে আবার upload করুন।",
            parse_mode="Markdown"
        )
        return
    if is_free_hosting_exhausted(user_id):
        bot.send_message(message.chat.id, "🛑 **Free Hosting Limit Finished**\n\nPlan ছাড়া আর নতুন bot upload করা যাবে না।\n💎 **Account → Deposit** থেকে balance add করে একটি Plan কিনুন।", parse_mode="Markdown"); return
    doc=message.document
    if getattr(doc,'file_size',0)>MAX_FILE_SIZE_BYTES:
        bot.send_message(message.chat.id, f"❌ **File too large.** Maximum `{MAX_FILE_SIZE_MB} MB`.", parse_mode="Markdown"); return
    current_count=get_user_file_count(user_id); max_limit=get_user_file_limit(user_id)
    file_name=os.path.basename(doc.file_name or 'uploaded_file'); file_name=re.sub(r"[^\w\-.]", "_", file_name)
    file_exists=any(f[0]==file_name for f in user_files.get(user_id,[]))
    if current_count>=max_limit and not file_exists:
        bot.send_message(message.chat.id, "❌ **Upload limit reached.** Delete an existing bot or upgrade your plan.", parse_mode="Markdown"); return
    file_ext=os.path.splitext(file_name)[1].lower()
    if file_ext not in ['.py','.js']:
        bot.send_message(message.chat.id, "⚠️ **Only `.py` and `.js` files are supported.**", parse_mode="Markdown"); return
    wait=None
    try:
        wait=bot.send_message(message.chat.id, f"⏳ **Uploading `{file_name}`...**", parse_mode="Markdown")
        info=bot.get_file(doc.file_id); data=bot.download_file(info.file_path)
        # SECURITY POLICY: every executable code upload requires admin approval.
        # Static scanning is advisory only and can never bypass the approval gate.
        _needs_review, scan_note = requires_admin_approval(data, file_name)
        user_folder = get_user_folder(user_id)
        request_id = uuid.uuid4().hex
        pending_dir = os.path.join(user_folder, ".pending")
        os.makedirs(pending_dir, exist_ok=True)
        pending_path = os.path.join(pending_dir, f"{request_id}_{file_name}")
        with open(pending_path, "wb") as f:
            f.write(data)
        approval_note = (
            "🔐 Admin approval required for every code file. "
            + (scan_note if scan_note else "🟢 Static scan found no common shell/CMD API.")
        )
        save_pending_upload(request_id, user_id, file_name, file_ext[1:], pending_path, len(data), approval_note)
        send_approval_request_to_admins(
            request_id, user_id, file_name, pending_path, len(data), approval_note
        )
        status = (
            "🔐 **Admin Review Required**\n\n"
            f"📄 `{file_name}`\n"
            "⏳ এই code file চালু করার আগে Admin approval বাধ্যতামূলক।\n"
            "🛡️ Static security scan করা হয়েছে।\n"
            "🚀 Admin Approve করলে file unlock হয়ে automatically run হবে।"
        )
        try:
            bot.edit_message_text(status, message.chat.id, wait.message_id, parse_mode="Markdown")
        except Exception:
            bot.send_message(message.chat.id, status, parse_mode="Markdown")
        return
    except Exception as e:
        logger.error('File upload error: %s',e,exc_info=True); bot.send_message(message.chat.id,f"❌ **Upload error:** `{str(e)[:300]}`",parse_mode='Markdown')

# --- Callback Routing ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    try:
        user_id = call.from_user.id
        if user_id in blocked_users:
            return
            
        global bot_locked
        data = call.data

        if data.startswith(("file_", "start_", "verify_", "stop_", "del_", "instmod_", "viewlog_", "extend_")):
            parts = data.split("_")
            owner_id = int(parts[1])
            if user_id != owner_id and user_id not in admin_ids:
                bot.answer_callback_query(call.id, "❌ নিরাপত্তা সতর্কতা: এটি আপনার ফাইল নয়!", show_alert=True)
                return

        if data.startswith("approve_file_") and user_id in APPROVAL_ADMIN_IDS:
            request_id = data[len("approve_file_"):]
            result = finalize_approved_upload(request_id, user_id)
            if not result:
                bot.answer_callback_query(call.id, "Already processed or request not found.", show_alert=True)
                return
            if result[0] in ("missing", "error"):
                bot.answer_callback_query(call.id, "Approval failed.", show_alert=True)
                return

            _, target_uid, fname, file_path, risk_note = result
            bot.answer_callback_query(call.id, f"{get_random_button_prefix('success')} Approved", show_alert=True)
            try:
                bot.edit_message_caption(
                    f"🟢 <b>APPROVED</b>\n\n📄 <code>{fname}</code>\n👤 User: <code>{target_uid}</code>\n{risk_note}",
                    call.message.chat.id, call.message.message_id, parse_mode="HTML"
                )
            except Exception:
                pass
            for admin_uid in sorted(APPROVAL_ADMIN_IDS):
                if admin_uid == user_id:
                    continue
                for real_bot in BOT_INSTANCES:
                    try:
                        real_bot.send_message(admin_uid, f"🟢 **File approved successfully**\n📄 `{fname}`\n👤 User: `{target_uid}`")
                        break
                    except Exception:
                        pass
            try:
                bot.send_message(
                    target_uid,
                    f"🟢 **File Approved & Starting!**\n\n"
                    f"📄 `{fname}`\n"
                    
                    "🚀 Your file has been unlocked and the host is starting it now."
                )
            except Exception:
                pass
            try:
                do_start_bot(target_uid, fname, SimpleNamespace(chat=SimpleNamespace(id=target_uid)))
            except Exception as e:
                logger.error("Auto-start after approval failed: %s", e, exc_info=True)
                try:
                    bot.send_message(target_uid, f"⚠️ File approved, but auto-start failed. Open Manage Files and start `{fname}` manually.")
                except Exception:
                    pass
            return

        elif data.startswith("reject_file_") and user_id in APPROVAL_ADMIN_IDS:
            request_id = data[len("reject_file_"):]
            result = finalize_rejected_upload(request_id, user_id)
            if not result:
                bot.answer_callback_query(call.id, "Already processed or request not found.", show_alert=True)
                return

            _, target_uid, fname = result
            bot.answer_callback_query(call.id, f"{get_random_button_prefix('danger')} Rejected", show_alert=True)
            try:
                bot.edit_message_caption(
                    f"🔴 <b>FILE REJECTED</b>\n\n📄 <code>{fname}</code>\n👤 User: <code>{target_uid}</code>\n\n❌ Rejected successfully.",
                    call.message.chat.id, call.message.message_id, parse_mode="HTML"
                )
            except Exception:
                pass
            for admin_uid in sorted(APPROVAL_ADMIN_IDS):
                if admin_uid == user_id:
                    continue
                for real_bot in BOT_INSTANCES:
                    try:
                        real_bot.send_message(admin_uid, f"🔴 **File rejected successfully**\n📄 `{fname}`\n👤 User: `{target_uid}`")
                        break
                    except Exception:
                        pass
            try:
                bot.send_message(target_uid, f"🔴 **File Rejected**\n\n📄 `{fname}`\n\n❌ Your file was rejected.\n📤 You can upload another file.")
            except Exception:
                pass
            return

        if data.startswith("copy_number_"):
            number = data[len("copy_number_"):]
            bot.answer_callback_query(call.id, "📋 Number sent — tap/hold it to copy.")
            bot.send_message(call.message.chat.id, f"📱 <code>{number}</code>", parse_mode="HTML")
            return

        if data == "show_vip_plans":
            bot.answer_callback_query(call.id)
            _logic_vip_plans(call.message)
            return

        if data == "db_download" and int(user_id) == int(globals().get("SECOND_ADMIN_ID", 0) or 0):
            try:
                with DB_LOCK:
                    if not os.path.exists(DATABASE_PATH):
                        bot.answer_callback_query(call.id, "Database not found.", show_alert=True)
                        return
                    with open(DATABASE_PATH, "rb") as dbf:
                        bot.send_document(
                            call.message.chat.id,
                            dbf,
                            caption="🗄️ **Database Backup**\n\nComplete bot database backup.",
                            parse_mode="Markdown"
                        )
                bot.answer_callback_query(call.id, "Database sent.", show_alert=True)
            except Exception as e:
                logger.error("DB download failed: %s", e, exc_info=True)
                bot.answer_callback_query(call.id, "Database download failed.", show_alert=True)
            return

        if data == "db_upload" and int(user_id) == int(globals().get("SECOND_ADMIN_ID", 0) or 0):
            msg = bot.send_message(
                call.message.chat.id,
                "⬆️ **Database Restore Mode**\n\n"
                "শুধু `.db` / `.sqlite` file পাঠান।\n"
                "⚠️ Current database-এর automatic backup তৈরি হবে, তারপর restore হবে."
            )
            bot.register_next_step_handler(msg, process_database_upload)
            return

        if data.startswith("buy_plan_"):
            plan_id = int(data.split("_")[2])
            
            with DB_LOCK:
                conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
                c = conn.cursor()
                c.execute("SELECT name, duration_days, price FROM plans WHERE plan_id=?", (plan_id,))
                plan_row = c.fetchone()
                conn.close()
            
            if not plan_row:
                bot.answer_callback_query(call.id, "Plan not found!", show_alert=True)
                return
                
            plan_name, duration_days, price_text = plan_row
            
            try:
                price_num = int(''.join(filter(str.isdigit, str(price_text))))
            except ValueError:
                bot.answer_callback_query(call.id, "Error in plan price configuration.", show_alert=True)
                return
                
            balance, _ = get_user_account(user_id)
            
            if balance >= price_num:
                with DB_LOCK:
                    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
                    c = conn.cursor()
                    c.execute("UPDATE user_account SET balance = balance - ? WHERE user_id=?", (price_num, user_id))
                    end_time = datetime.now() + timedelta(days=duration_days)
                    c.execute("INSERT OR REPLACE INTO user_subscriptions (user_id, plan_id, end_time, notified_warning) VALUES (?, ?, ?, 0)", (user_id, plan_id, end_time.isoformat()))
                    conn.commit()
                    conn.close()
                    
                bot.answer_callback_query(call.id, "✅ Plan Purchased Successfully!", show_alert=True)
                buyer_name = (getattr(call.from_user, "first_name", "") or "").strip()
                buyer_last = (getattr(call.from_user, "last_name", "") or "").strip()
                buyer_name = " ".join(x for x in (buyer_name, buyer_last) if x) or f"User {user_id}"
                buyer_username = (getattr(call.from_user, "username", "") or "").strip()
                buyer_username_line = f" (@{buyer_username})" if buyer_username else ""
                send_activity_log(
                    "💎 <b>PLAN PURCHASED</b>\n\n"
                    f"👤 <b>Name:</b> {buyer_name}{buyer_username_line}\n"
                    f"🆔 <b>TG ID:</b> <code>{user_id}</code>\n"
                    f"📦 <b>Plan:</b> <code>{plan_name}</code>\n"
                    f"💵 <b>Price:</b> <code>{price_num} BDT</code>\n"
                    f"⏳ <b>Duration:</b> <code>{duration_days} days</code>"
                )

                bot.send_message(call.message.chat.id, f"🎉 **অভিনন্দন!**\nআপনার **{plan_name}** প্ল্যানটি কেনা সফল হয়েছে।\nমেয়াদ: {duration_days} দিন।\nব্যালেন্স থেকে `{price_num} BDT` কাটা হয়েছে।", parse_mode="Markdown")
            else:
                bot.answer_callback_query(call.id, "❌ অপর্যাপ্ত ব্যালেন্স!", show_alert=True)
                bot.send_message(call.message.chat.id, f"❌ **অপর্যাপ্ত ব্যালেন্স!**\nপ্ল্যানটির দাম `{price_num} BDT`, কিন্তু আপনার একাউন্টে আছে `{balance} BDT`। দয়া করে 👤 Account থেকে ডিপোজিট করুন।", parse_mode="Markdown")

        elif data == "deposit_init":
            start_deposit_session(user_id)
            bot.answer_callback_query(call.id)
            deposit_start_markup = types.InlineKeyboardMarkup(row_width=1)
            deposit_start_markup.add(make_inline_button("❌ Cancel", callback_data="deposit_cancel"))
            bot.send_message(
                call.message.chat.id,
                "💰 **𝗔𝗱𝗱 𝗠𝗼𝗻𝗲𝘆**\n\n"
                "💵 কত টাকা যোগ করতে চান? **10–50,000 BDT**\n"
                "শুধু amount লিখুন।",
                parse_mode="Markdown",
                reply_markup=deposit_start_markup
            )

        elif data == "deposit_cancel":
            cancel_deposit(user_id)
            bot.answer_callback_query(call.id, "Deposit cancelled.")
            bot.send_message(call.message.chat.id, "❌ Deposit flow cancelled। আবার শুরু করতে **💰 Add Money** চাপুন।", parse_mode="Markdown")

        elif data.startswith("dep_method_"):
            method = data[len("dep_method_"):].lower()
            if method not in ("bkash", "nagad"):
                bot.answer_callback_query(call.id, "Invalid payment method.", show_alert=True)
                return
            session = get_deposit_session(user_id)
            if not session or session.get("step") not in ("method", "trx", "sender_phone"):
                start_deposit_session(user_id)
                bot.answer_callback_query(call.id, "প্রথমে amount দিন।", show_alert=True)
                bot.send_message(call.message.chat.id, "💵 Amount লিখুন (10–50,000 BDT):")
                return
            if not session.get("amount"):
                bot.answer_callback_query(call.id, "প্রথমে amount দিন।", show_alert=True)
                return
            bot.answer_callback_query(call.id)
            _show_payment_number(call.message.chat.id, user_id, method)

        elif data.startswith("dep_app_") and user_id in admin_ids:
            deposit_id = data[len("dep_app_"):]
            row = claim_deposit(deposit_id, user_id, "approved")
            if not row:
                bot.answer_callback_query(call.id, "Already processed or request not found.", show_alert=True)
                return
            _, target_uid, amount, method, payment_number, trx_id, sender_phone, _ = row
            bot.answer_callback_query(call.id, "✅ Approved — balance added.", show_alert=True)
            try:
                bot.edit_message_text(
                    call.message.text + f"\n\n✅ **APPROVED by {user_id}**",
                    call.message.chat.id, call.message.message_id, parse_mode="Markdown"
                )
            except Exception:
                pass
            try:
                balance, _ = get_user_account(target_uid)
                bot.send_message(
                    target_uid,
                    f"✅ **Deposit Approved**\n\n"
                    f"💵 Amount: `{amount} BDT`\n"
                    f"🏦 Method: `{method.upper()}`\n"
                    f"🔑 TRX ID: `{trx_id}`\n"
                    f"💰 New Balance: `{balance} BDT`",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            return

        elif data.startswith("dep_rej_") and user_id in admin_ids:
            deposit_id = data[len("dep_rej_"):]
            row = claim_deposit(deposit_id, user_id, "rejected")
            if not row:
                bot.answer_callback_query(call.id, "Already processed or request not found.", show_alert=True)
                return
            _, target_uid, amount, method, payment_number, trx_id, sender_phone, _ = row
            bot.answer_callback_query(call.id, "❌ Deposit rejected.", show_alert=True)
            try:
                bot.edit_message_text(
                    call.message.text + f"\n\n❌ **REJECTED by {user_id}**",
                    call.message.chat.id, call.message.message_id, parse_mode="Markdown"
                )
            except Exception:
                pass
            try:
                bot.send_message(
                    target_uid,
                    f"❌ **Deposit Rejected**\n\n"
                    f"💵 Amount: `{amount} BDT`\n"
                    f"🏦 Method: `{method.upper()}`\n"
                    f"🔑 TRX ID: `{trx_id}`\n\n"
                    "প্রয়োজনে সঠিক transaction তথ্য দিয়ে আবার Add Money করুন।",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            return

        elif data == "pending_deposits" and user_id in admin_ids:
            rows = get_pending_deposits(20)
            if not rows:
                bot.answer_callback_query(call.id, "No pending deposits.", show_alert=True)
                return
            bot.answer_callback_query(call.id)
            bot.send_message(call.message.chat.id, f"💰 **Pending Deposits:** `{len(rows)}`", parse_mode="Markdown")
            for deposit_id, target_uid, amount, method, trx_id, sender_phone, created_at in rows:
                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.add(
                    make_inline_button("✅ Approve", callback_data=f"dep_app_{deposit_id}"),
                    make_inline_button("❌ Reject", callback_data=f"dep_rej_{deposit_id}")
                )
                bot.send_message(
                    call.message.chat.id,
                    f"💰 **Pending Deposit**\n\n"
                    f"👤 User: `{target_uid}`\n"
                    f"💵 Amount: `{amount} BDT`\n"
                    f"🏦 Method: `{method.upper()}`\n"
                    f"📱 Sender: `{sender_phone}`\n"
                    f"🔑 TRX ID: `{trx_id}`\n"
                    f"🕒 `{created_at}`",
                    reply_markup=markup, parse_mode="Markdown"
                )
            return

        elif data.startswith("extend_"):
            bot.answer_callback_query(call.id, "💎 Free limit is 12 hours. Please buy a plan to continue.", show_alert=True)
            _logic_vip_plans(call.message)

        elif data.startswith("file_"):
            _, owner_id, fname = data.split("_", 2)
            is_running = is_bot_running(int(owner_id), fname)
            markup = types.InlineKeyboardMarkup(row_width=2)
            if is_running:
                markup.add(make_inline_button("🛑 Stop Bot", callback_data=f"stop_{owner_id}_{fname}"))
            else:
                markup.add(make_inline_button("▶️ Start Bot", callback_data=f"start_{owner_id}_{fname}"))
            markup.add(make_inline_button("🗑️ Delete Bot File", callback_data=f"del_{owner_id}_{fname}"))
            bot.send_message(call.message.chat.id, f"📄 **File:** `{fname}`\n🚦 Status: `{'🟢 Running' if is_running else '🔴 Stopped'}`", reply_markup=markup, parse_mode="Markdown", protect_content=True)

        elif data.startswith("start_"):
            _, owner_id, fname = data.split("_", 2)
            owner_id = int(owner_id)
            
            not_joined = check_force_sub(owner_id)
            if not_joined and owner_id not in admin_ids:
                markup = types.InlineKeyboardMarkup(row_width=1)
                for ch_id, ch_url in not_joined:
                    markup.add(make_inline_button("📢 Join Channel", url=ch_url))
                markup.add(make_inline_button("✅ Verify", callback_data=f"verify_{owner_id}_{fname}"))
                
                bot.send_message(call.message.chat.id, "⚠️ **আপনার বোট স্টার্ট করতে হলে প্রথমে আমাদের নিচের চ্যানেলগুলোতে জয়েন করুন:**", reply_markup=markup, parse_mode="Markdown")
                return
                
            do_start_bot(owner_id, fname, call.message, call.id)

        elif data.startswith("verify_"):
            _, owner_id, fname = data.split("_", 2)
            owner_id = int(owner_id)
            not_joined = check_force_sub(owner_id)
            
            if not_joined:
                bot.answer_callback_query(call.id, "❌ আপনি এখনো সব চ্যানেলে জয়েন করেননি!", show_alert=True)
            else:
                try: bot.delete_message(call.message.chat.id, call.message.message_id)
                except: pass
                do_start_bot(owner_id, fname, call.message, call.id)

        elif data.startswith("stop_"):
            _, owner_id, fname = data.split("_", 2)
            force_kill_user_bot(owner_id, fname)
            bot.answer_callback_query(call.id, "Stopped!")
            bot.send_message(call.message.chat.id, f"🛑 Script `{fname}` stopped successfully.", parse_mode="Markdown")

        elif data.startswith("del_"):
            _, owner_id, fname = data.split("_", 2)
            force_kill_user_bot(owner_id, fname)
                
            remove_user_file_db(int(owner_id), fname)
            ufolder = get_user_folder(int(owner_id))
            fpath = os.path.join(ufolder, fname)
            log_fpath = os.path.join(ufolder, f"{os.path.splitext(fname)[0]}.log")
            if os.path.exists(fpath): os.remove(fpath)
            if os.path.exists(log_fpath): os.remove(log_fpath)
            pycache_dir = os.path.join(ufolder, "__pycache__")
            if os.path.exists(pycache_dir): shutil.rmtree(pycache_dir, ignore_errors=True)
                
            bot.answer_callback_query(call.id, "Deleted!")
            bot.send_message(call.message.chat.id, f"🗑️ File `{fname}` completely deleted.", parse_mode="Markdown")

        elif data.startswith("instmod_"):
            _, owner_id, fname = data.split("_", 2)
            if int(user_id) != int(owner_id) and user_id not in admin_ids:
                bot.answer_callback_query(call.id, "❌ এটি আপনার ফাইল নয়!", show_alert=True)
                return
            install_missing_dependency(int(owner_id), fname, call.message.chat.id, call.id)
            return

        elif data.startswith("viewlog_"):
            _, owner_id, fname = data.split("_", 2)
            log_fpath = os.path.join(get_user_folder(int(owner_id)), f"{os.path.splitext(fname)[0]}.log")
            if os.path.exists(log_fpath):
                with open(log_fpath, "r", encoding="utf-8", errors="ignore") as f: logs = f.read()[-2000:]
                bot.send_message(call.message.chat.id, f"📜 **Logs:**\n\n```\n{logs if logs else 'No logs'}\n```", parse_mode="Markdown", protect_content=True)
            else:
                bot.answer_callback_query(call.id, "No logs!", show_alert=True)

        elif data == "toggle_bkash" and user_id in admin_ids:
            new_value = "0" if _payment_enabled("bkash") else "1"
            set_setting("bkash_enabled", new_value)
            state = "ON" if new_value == "1" else "OFF"
            bot.answer_callback_query(call.id, f"bKash is now {state}", show_alert=True)
            try:
                bot.edit_message_reply_markup(
                    call.message.chat.id, call.message.message_id,
                    reply_markup=create_admin_panel_inline(user_id)
                )
            except Exception:
                pass
            return

        elif data == "toggle_nagad" and user_id in admin_ids:
            new_value = "0" if _payment_enabled("nagad") else "1"
            set_setting("nagad_enabled", new_value)
            state = "ON" if new_value == "1" else "OFF"
            bot.answer_callback_query(call.id, f"Nagad is now {state}", show_alert=True)
            try:
                bot.edit_message_reply_markup(
                    call.message.chat.id, call.message.message_id,
                    reply_markup=create_admin_panel_inline(user_id)
                )
            except Exception:
                pass
            return

        elif data == "set_bkash" and user_id in admin_ids:
            msg = bot.send_message(call.message.chat.id, "📝 **বিকাশ পেমেন্ট নাম্বার দিন:**")
            bot.register_next_step_handler(msg, process_set_bkash)

        elif data == "set_nagad" and user_id in admin_ids:
            msg = bot.send_message(call.message.chat.id, "📝 **নগদ পেমেন্ট নাম্বার দিন:**")
            bot.register_next_step_handler(msg, process_set_nagad)

        elif data == "add_plan" and user_id in admin_ids:
            msg = bot.send_message(call.message.chat.id, "📝 **প্ল্যানের নাম এবং লোগো/ইমোজি দিন:** (যেমন: 💎 VIP Premium)")
            bot.register_next_step_handler(msg, process_plan_name)
            
        elif data == "remove_plan" and user_id in admin_ids:
            with DB_LOCK:
                conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
                c = conn.cursor()
                c.execute("SELECT plan_id, name FROM plans")
                plans = c.fetchall()
                conn.close()
            
            if not plans:
                bot.answer_callback_query(call.id, "No plans found!", show_alert=True)
                return
                
            markup = types.InlineKeyboardMarkup()
            for p in plans:
                markup.add(make_inline_button(f"🗑️ Delete: {p[1]}", callback_data=f"delplan_{p[0]}"))
            bot.send_message(call.message.chat.id, "Select a plan to delete:", reply_markup=markup)

        elif data.startswith("delplan_") and user_id in admin_ids:
            plan_id = data.split("_")[1]
            with DB_LOCK:
                conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
                c = conn.cursor()
                c.execute("DELETE FROM plans WHERE plan_id=?", (plan_id,))
                conn.commit()
                conn.close()
            bot.answer_callback_query(call.id, "Plan deleted!", show_alert=True)
            bot.send_message(call.message.chat.id, "✅ **প্ল্যান ডিলিট করা হয়েছে!**", parse_mode="Markdown")

        elif data == "give_plan" and user_id in admin_ids:
            msg = bot.send_message(call.message.chat.id, "📝 **যাকে প্ল্যান দিতে চান তার User ID দিন:**")
            bot.register_next_step_handler(msg, process_give_plan_userid)

        elif data.startswith("assign_plan_") and user_id in admin_ids:
            parts = data.split("_")
            target_uid = int(parts[2])
            plan_id = int(parts[3])
            
            with DB_LOCK:
                conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
                c = conn.cursor()
                c.execute("SELECT duration_days, name FROM plans WHERE plan_id=?", (plan_id,))
                row = c.fetchone()
            
            if row:
                duration_days, plan_name = row
                end_time = datetime.now() + timedelta(days=duration_days)
                with DB_LOCK:
                    c.execute("INSERT OR REPLACE INTO user_subscriptions (user_id, plan_id, end_time, notified_warning) VALUES (?, ?, ?, 0)", (target_uid, plan_id, end_time.isoformat()))
                    conn.commit()
                bot.answer_callback_query(call.id, "Plan assigned!", show_alert=True)
                bot.send_message(call.message.chat.id, f"✅ User `{target_uid}` কে সফলভাবে **{plan_name}** দেওয়া হয়েছে!", parse_mode="Markdown")
                target_name, target_username = get_telegram_user_display(target_uid)
                target_username_line = f" (@{target_username})" if target_username else ""
                send_activity_log(
                    "💎 <b>PLAN ASSIGNED BY ADMIN</b>\n\n"
                    f"👤 <b>Name:</b> {target_name}{target_username_line}\n"
                    f"🆔 <b>TG ID:</b> <code>{target_uid}</code>\n"
                    f"📦 <b>Plan:</b> <code>{plan_name}</code>\n"
                    f"⏳ <b>Duration:</b> <code>{duration_days} days</code>\n"
                    f"🛡️ <b>Admin:</b> <code>{user_id}</code>"
                )

                
                try:
                    bot.send_message(target_uid, f"🎉 **অভিনন্দন!**\nআপনাকে **{plan_name}** দেওয়া হয়েছে।\nমেয়াদ: {duration_days} দিন।\nনিরবচ্ছিন্ন হোস্টিং উপভোগ করুন!", parse_mode="Markdown")
                except:
                    pass
            try: conn.close()
            except: pass

        elif data == "set_tutorial" and user_id in admin_ids:
            msg = bot.send_message(call.message.chat.id, "📝 **নতুন টিউটোরিয়াল ভিডিও এর লিংকটি দিন (যেমন: https://youtu.be/...):**")
            bot.register_next_step_handler(msg, process_set_tutorial_link)

        elif data == "add_channel" and user_id in admin_ids:
            msg = bot.send_message(call.message.chat.id, "📝 **চ্যানেল অ্যাড করুন:**\nফরম্যাট: `@channel_id | https://t.me/link`")
            bot.register_next_step_handler(msg, process_add_channel)

        elif data == "remove_channel" and user_id in admin_ids:
            channels = get_force_channels()
            if not channels:
                bot.answer_callback_query(call.id, "No channels added!", show_alert=True)
                return
            markup = types.InlineKeyboardMarkup()
            for ch in channels:
                markup.add(make_inline_button(f"🗑️ Delete {ch[0]}", callback_data=f"del_ch_{ch[0]}"))
            bot.send_message(call.message.chat.id, "Select a channel to remove:", reply_markup=markup)

        elif data.startswith("del_ch_") and user_id in admin_ids:
            ch_id = data[7:]
            with DB_LOCK:
                conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
                c = conn.cursor()
                c.execute("DELETE FROM force_channels WHERE channel_id=?", (ch_id,))
                conn.commit()
                conn.close()
            bot.answer_callback_query(call.id, "Channel removed successfully!", show_alert=True)
            bot.send_message(call.message.chat.id, f"✅ `{ch_id}` removed from Force Sub channels.")

        elif data == "add_admin" and int(user_id) in {int(OWNER_ID), int(globals().get("SECOND_ADMIN_ID", 0) or 0)}:
            msg = bot.send_message(call.message.chat.id, "📝 **যাকে এডমিন বানাতে চান তার User ID দিন:**")
            bot.register_next_step_handler(msg, process_add_admin)

        elif data == "remove_admin" and int(user_id) in {int(OWNER_ID), int(globals().get("SECOND_ADMIN_ID", 0) or 0)}:
            msg = bot.send_message(call.message.chat.id, "📝 **যাকে এডমিন থেকে রিমুভ করতে চান তার User ID দিন:**")
            bot.register_next_step_handler(msg, process_remove_admin)
            
        elif data == "set_limit" and int(user_id) == int(OWNER_ID):
            msg = bot.send_message(call.message.chat.id, "📝 **যাঁর লিমিট পরিবর্তন করতে চান তার User ID দিন (Manual):**")
            bot.register_next_step_handler(msg, process_set_limit_user)
            
        elif data == "block_user" and int(user_id) == int(OWNER_ID):
            msg = bot.send_message(call.message.chat.id, "📝 **যাকে ব্লক করতে চান তার User ID দিন:**")
            bot.register_next_step_handler(msg, process_manual_block)

        elif data == "unblock_user" and int(user_id) == int(OWNER_ID):
            msg = bot.send_message(call.message.chat.id, "📝 **যাকে আনব্লক করতে চান তার User ID দিন:**")
            bot.register_next_step_handler(msg, process_manual_unblock)

        elif data == "broadcast" and user_id in admin_ids:
            msg = bot.send_message(call.message.chat.id, "📝 **ব্রডকাস্ট করার জন্য মেসেজটি দিন:**\n(যেকোনো মেসেজ বা ছবি পাঠাতে পারেন)")
            bot.register_next_step_handler(msg, process_broadcast)

        elif data == "toggle_lock" and user_id in admin_ids:
            bot_locked = not bot_locked
            status = "🔒 Locked" if bot_locked else "🔓 Unlocked"
            bot.answer_callback_query(call.id, f"Bot is now {status}", show_alert=True)
            bot.send_message(call.message.chat.id, f"✅ **Bot Lock Status Changed to:** {status}", parse_mode="Markdown")

        elif data == "stats" and user_id in admin_ids:
            bot.answer_callback_query(call.id)
            msg = (
                f"📊 **𝗕𝗼𝘁 𝗦𝘁𝗮𝘁𝗶𝘀𝘁𝗶𝗰𝘀:**\n\n"
                f"👥 **Total Users:** `{len(active_users)}`\n"
                f"👑 **Total Admins:** `{len(admin_ids)}`\n"
                f"🚀 **Running Bots:** `{len(bot_scripts)}`\n"
                f"🔒 **Bot Locked Status:** `{bot_locked}`\n"
                f"🚫 **Blocked Users:** `{len(blocked_users)}`"
            )
            bot.send_message(call.message.chat.id, msg, parse_mode="Markdown")

        elif data == "run_all_scripts" and user_id in admin_ids:
            bot.answer_callback_query(call.id, "Running all stopped scripts...")
            started_count = 0
            for uid, files in user_files.items():
                for fname, ftype in files:
                    if not is_bot_running(uid, fname):
                        ufolder = get_user_folder(uid)
                        fpath = os.path.join(ufolder, fname)
                        if os.path.exists(fpath) and any(str(n) == str(fname) for n, _ in user_files.get(int(uid), [])):
                            if ftype == "js":
                                run_js_script(fpath, uid, ufolder, fname, call.message)
                            else:
                                run_script(fpath, uid, ufolder, fname, call.message)
                            started_count += 1
                            time.sleep(1)
            bot.send_message(call.message.chat.id, f"✅ **Successfully started {started_count} scripts!**", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error handling callback {call.data}: {e}")

# --- Deposit Input Process Handlers ---\n# Deposit handlers are defined above and use SQLite-backed sessions.\n\n# --- Setting Process Handlers ---
def process_set_bkash(message):
    if int(message.from_user.id) not in admin_ids:
        return
    number = (message.text or "").strip()
    if not re.fullmatch(r"01\d{9}", number):
        bot.send_message(message.chat.id, "❌ সঠিক ১১-ডিজিটের বাংলাদেশি mobile number দিন। উদাহরণ: 017XXXXXXXX")
        return
    set_setting("bkash_number", number)
    bot.send_message(message.chat.id, f"✅ **bKash নাম্বার সেট করা হয়েছে:** `{number}`", parse_mode="Markdown")

def process_set_nagad(message):
    if int(message.from_user.id) not in admin_ids:
        return
    number = (message.text or "").strip()
    if not re.fullmatch(r"01\d{9}", number):
        bot.send_message(message.chat.id, "❌ সঠিক ১১-ডিজিটের বাংলাদেশি mobile number দিন। উদাহরণ: 018XXXXXXXX")
        return
    set_setting("nagad_number", number)
    bot.send_message(message.chat.id, f"✅ **Nagad নাম্বার সেট করা হয়েছে:** `{number}`", parse_mode="Markdown")

# --- Plan Creation Process Handlers ---
admin_plan_temp = {}

def process_plan_name(message):
    name = message.text.strip()
    admin_plan_temp[message.chat.id] = {"name": name}
    msg = bot.send_message(message.chat.id, "📝 **প্ল্যানের বিস্তারিত বিবরণ দিন:**")
    bot.register_next_step_handler(msg, process_plan_desc)

def process_plan_desc(message):
    admin_plan_temp[message.chat.id]["desc"] = message.text.strip()
    msg = bot.send_message(message.chat.id, "📝 **কয়টি বট হোস্ট করা যাবে? (শুধুমাত্র সংখ্যা দিন):**")
    bot.register_next_step_handler(msg, process_plan_limit)

def process_plan_limit(message):
    try:
        limit = int(message.text.strip())
        admin_plan_temp[message.chat.id]["limit"] = limit
        msg = bot.send_message(message.chat.id, "📝 **মেয়াদ কতদিন? (শুধুমাত্র সংখ্যা দিন):**")
        bot.register_next_step_handler(msg, process_plan_days)
    except:
        bot.send_message(message.chat.id, "❌ সংখ্যা দিন। পুনরায় Add Plan এ ক্লিক করুন।")

def process_plan_days(message):
    try:
        days = int(message.text.strip())
        admin_plan_temp[message.chat.id]["days"] = days
        msg = bot.send_message(message.chat.id, "📝 **প্ল্যানের দাম কত? (শুধুমাত্র সংখ্যা দিন, যেমন: 150):**")
        bot.register_next_step_handler(msg, process_plan_price)
    except:
        bot.send_message(message.chat.id, "❌ সংখ্যা দিন। পুনরায় Add Plan এ ক্লিক করুন।")

def process_plan_price(message):
    price = message.text.strip()
    data = admin_plan_temp.get(message.chat.id)
    if not data: return
    
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute("INSERT INTO plans (name, description, bot_limit, duration_days, price) VALUES (?, ?, ?, ?, ?)", 
                 (data["name"], data["desc"], data["limit"], data["days"], price))
        conn.commit()
        conn.close()
        
    bot.send_message(message.chat.id, f"✅ **প্ল্যান সফলভাবে অ্যাড হয়েছে!**\n\nনাম: {data['name']}\nলিমিট: {data['limit']}\nদিন: {data['days']}\nদাম: {price}", parse_mode="Markdown")

def process_give_plan_userid(message):
    try:
        target_uid = int(message.text.strip())
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("SELECT plan_id, name FROM plans")
            plans = c.fetchall()
            conn.close()
        
        if not plans:
            bot.send_message(message.chat.id, "❌ কোনো প্ল্যান তৈরি করা নেই। আগে Add Plan করুন।")
            return
            
        markup = types.InlineKeyboardMarkup()
        for p in plans:
            markup.add(make_inline_button(f"✅ Give: {p[1]}", callback_data=f"assign_plan_{target_uid}_{p[0]}"))
        
        bot.send_message(message.chat.id, f"User `{target_uid}` কে কোন প্ল্যান দিতে চান সিলেক্ট করুন:", reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(message.chat.id, "❌ ভুল User ID!")

# --- Other Admin Process Handlers ---
def process_set_tutorial_link(message):
    try:
        url = message.text.strip()
        if url.startswith("http://") or url.startswith("https://"):
            set_setting("tutorial_link", url)
            bot.send_message(message.chat.id, f"✅ **টিউটোরিয়াল লিংক সফলভাবে আপডেট করা হয়েছে!**\n\n🔗 `{url}`", parse_mode="Markdown")
        else:
            bot.send_message(message.chat.id, "❌ **ভুল লিংক!** সঠিক লিংক দিন (http:// বা https:// দিয়ে শুরু হতে হবে)।")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ **Error:** {str(e)}")

def process_add_channel(message):
    try:
        parts = [p.strip() for p in message.text.split("|")]
        ch_id, ch_url = parts[0], parts[1]
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO force_channels (channel_id, channel_url) VALUES (?, ?)", (ch_id, ch_url))
            conn.commit()
            conn.close()
        bot.send_message(message.chat.id, f"✅ চ্যানেল সফলভাবে যুক্ত করা হয়েছে: {ch_id}")
    except:
        bot.send_message(message.chat.id, "❌ ভুল ফরম্যাট! সঠিক নিয়মে দিন: `@channel_id | https://t.me/link`")

def process_add_admin(message):
    try:
        new_admin = int(message.text.strip())
        actor = int(message.from_user.id)
        protected = {int(OWNER_ID), int(globals().get("SECOND_ADMIN_ID", 0) or 0)}
        if actor not in protected:
            bot.send_message(message.chat.id, "❌ Permission denied.")
            return
        if new_admin in protected:
            bot.send_message(message.chat.id, "🛡️ Core Admin-কে add/remove করা যাবে না.")
            return
        admin_ids.add(new_admin)
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO admins (user_id, added_by) VALUES (?, ?)", (new_admin, actor))
            conn.commit()
            conn.close()
        bot.send_message(message.chat.id, f"✅ `{new_admin}` সফলভাবে আপনার admin list-এ যুক্ত হয়েছে!\n🔐 শুধু আপনিই এই admin-কে remove করতে পারবেন.", parse_mode="Markdown")
    except ValueError:
        bot.send_message(message.chat.id, "❌ ভুল User ID! সঠিক সংখ্যা দিন.")


def process_remove_admin(message):
    try:
        rem_admin = int(message.text.strip())
        actor = int(message.from_user.id)
        protected = {int(OWNER_ID), int(globals().get("SECOND_ADMIN_ID", 0) or 0)}
        # Core accounts are intentionally invisible to the self-admin removal flow.
        # Do not reveal their protected status; report the same result as a missing admin.
        if rem_admin in protected:
            bot.send_message(message.chat.id, "❌ Admin not found.")
            return
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("SELECT added_by FROM admins WHERE user_id=?", (rem_admin,))
            row = c.fetchone()
            if not row:
                conn.close()
                bot.send_message(message.chat.id, "❌ Admin not found.")
                return
            if int(row[0] or 0) != actor:
                conn.close()
                # Do not expose who added the admin or which protected relationship exists.
                bot.send_message(message.chat.id, "❌ Admin not found.")
                return
            c.execute("DELETE FROM admins WHERE user_id=?", (rem_admin,))
            conn.commit()
            conn.close()
        admin_ids.discard(rem_admin)
        bot.send_message(message.chat.id, f"✅ `{rem_admin}` আপনার admin list থেকে remove করা হয়েছে.", parse_mode="Markdown")
    except ValueError:
        bot.send_message(message.chat.id, "❌ ভুল User ID! সঠিক সংখ্যা দিন.")


def process_set_limit_user(message):
    try:
        target_user = int(message.text.strip())
        msg = bot.send_message(message.chat.id, f"📝 **`{target_user}` এর জন্য নতুন লিমিট (কয়টি বোট রান করতে পারবে) দিন:**", parse_mode="Markdown")
        bot.register_next_step_handler(msg, lambda m: process_set_limit_value(m, target_user))
    except ValueError:
        bot.send_message(message.chat.id, "❌ ভুল User ID! সঠিক সংখ্যা দিন।")

def process_set_limit_value(message, target_user):
    try:
        new_limit = int(message.text.strip())
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO custom_limits (user_id, max_limit) VALUES (?, ?)", (target_user, new_limit))
            conn.commit()
            conn.close()
        bot.send_message(message.chat.id, f"✅ **Success!**\n`{target_user}` এর নতুন বোট লিমিট `{new_limit}` সেট করা হয়েছে!", parse_mode="Markdown")
    except ValueError:
        bot.send_message(message.chat.id, "❌ ভুল লিমিট! সঠিক সংখ্যা দিন।")

def process_manual_block(message):
    try:
        target_user = int(message.text.strip())
        if target_user in admin_ids:
            bot.send_message(message.chat.id, "❌ অ্যাডমিনকে ব্লক করা যাবে না!")
            return
        
        blocked_users.add(target_user)
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("INSERT OR IGNORE INTO blocked_users (user_id) VALUES (?)", (target_user,))
            conn.commit()
            conn.close()
            
        bot.send_message(message.chat.id, f"✅ `{target_user}` কে সফলভাবে ব্লক করা হয়েছে।")
        try: bot.send_message(target_user, "🚫 **আপনাকে বট থেকে স্থায়ীভাবে ব্লক করা হয়েছে!**\nকারণ: এডমিন রুলস ভঙ্গের কারণে ব্লক করেছেন।")
        except: pass
    except ValueError:
        bot.send_message(message.chat.id, "❌ ভুল User ID! সঠিক সংখ্যা দিন।")

def process_manual_unblock(message):
    try:
        target_user = int(message.text.strip())
        if target_user in blocked_users:
            blocked_users.remove(target_user)
            
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("DELETE FROM blocked_users WHERE user_id = ?", (target_user,))
            conn.commit()
            conn.close()
            
        bot.send_message(message.chat.id, f"✅ `{target_user}` কে সফলভাবে আনব্লক করা হয়েছে।")
    except ValueError:
        bot.send_message(message.chat.id, "❌ ভুল User ID! সঠিক সংখ্যা দিন।")

def process_broadcast(message):
    success = 0
    failed = 0
    bot.send_message(message.chat.id, "⏳ **ব্রডকাস্ট শুরু হয়েছে...**", parse_mode="Markdown")
    for user in list(active_users):
        try:
            bot.copy_message(user, message.chat.id, message.message_id)
            success += 1
            time.sleep(0.05)
        except Exception:
            failed += 1
    bot.send_message(message.chat.id, f"✅ **ব্রডকাস্ট শেষ!**\n\n🟢 **সফল:** `{success}`\n🔴 **ব্যর্থ:** `{failed}`", parse_mode="Markdown")

# --- Actual Bot Speed ---
def get_actual_bot_speed_ms():
    """Measure real Telegram API round-trip latency instead of showing a fixed value."""
    started = time.perf_counter()
    try:
        bot.get_me()
        elapsed_ms = (time.perf_counter() - started) * 1000
        return max(1, round(elapsed_ms, 1))
    except Exception as e:
        logger.warning("Bot speed check failed: %s", e)
        return None

def send_developer_info(message):
    """Polished Developer card similar to the supplied screenshots."""
    markup = types.InlineKeyboardMarkup(row_width=1)
    try:
        markup.add(make_inline_button(
            "👤 𝗖𝗼𝗻𝘁𝗿𝗮𝗰𝘁 𝗗𝗲𝘃",
            url="https://t.me/RBK_Developer",
            style="success"
        ))
    except TypeError:
        markup.add(types.InlineKeyboardButton(
            "👤 𝗖𝗼𝗻𝘁𝗿𝗮𝗰𝘁 𝗗𝗲𝘃", url="https://t.me/RBK_Developer"
        ))

    text = (
        "📁 <b>〈/〉 𝗗𝗲𝘃𝗲𝗹𝗼𝗽𝗲𝗿</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🤖 <b>যেকোনো ধরনের বট বানাতে এখনই এসএমএস দিন</b>\n\n"
        "👨‍💻 <b>Developer:</b> @RBK_Developer\n"
        "⚡ <b>Fast • Professional • Reliable</b>"
    )
    bot.send_message(
        message.chat.id, text, parse_mode="HTML",
        reply_markup=markup, protect_content=True
    )

def send_actual_speed(message):
    speed_ms = get_actual_bot_speed_ms()
    if speed_ms is None:
        bot.send_message(message.chat.id, "⚡ **Bot Speed:** বর্তমানে speed check করা যাচ্ছে না।", parse_mode="Markdown")
    else:
        bot.send_message(
            message.chat.id,
            f"⚡ **Bot Speed & Ping**\n\n🚀 Telegram API Response: `{speed_ms} ms`\n🟢 Server Active",
            parse_mode="Markdown",
            protect_content=True
        )

# --- Text Handler Mapping ---
BUTTON_MAPPING = {
    "✨ 𝗨𝗽𝗱𝗮𝘁𝗲𝘀 𝗖𝗵𝗮𝗻𝗻𝗲𝗹 ✨": lambda m: bot.send_message(m.chat.id, f"📢 **Join channel:** {UPDATE_CHANNEL}"),
    "🎥 𝗧𝘂𝘁𝗼𝗿𝗶𝗮𝗹": _logic_tutorial,
    "🚀 𝗨𝗽𝗹𝗼𝗮𝗱 𝗙𝗶𝗹𝗲": _logic_upload_file,
    "📁 𝗠𝗮𝗻𝗮𝗴𝗲 𝗙𝗶𝗹𝗲𝘀": _logic_check_files,
    "💎 𝗩𝗜𝗣 𝗣𝗹𝗮𝗻𝘀": _logic_vip_plans,
    "💰 𝗔𝗱𝗱 𝗠𝗼𝗻𝗲𝘆": _logic_add_money,
    "👤 𝗔𝗰𝗰𝗼𝘂𝗻𝘁": _logic_account,
    "⚡ 𝗦𝗽𝗲𝗲𝗱 & 𝗣𝗶𝗻𝗴": send_actual_speed,
    "💻 𝗗𝗲𝘃𝗲𝗹𝗼𝗽𝗲𝗿": send_developer_info,
    "📊 𝗕𝗼𝘁 𝗦𝘁𝗮𝘁𝘀": lambda m: bot.send_message(m.chat.id, f"📊 **Active Users:** `{len(active_users)}`\n🚀 **Running Bots:** `{len(bot_scripts)}`\n🚫 **Blocked Users:** `{len(blocked_users)}`", parse_mode="Markdown"),
    "🔐 𝗦𝗲𝗰𝘂𝗿𝗶𝘁𝘆": lambda m: bot.send_message(
        m.chat.id,
        "🔐 **Premium Security Mode Active**\n\n"
        "• Every `.py` / `.js` upload requires admin approval\n"
        "• Static security scan runs before the approval request\n"
        "• One authorized admin approval unlocks the file\n"
        "• Approved files start automatically\n"
        "• Pending files remain locked",
        parse_mode="Markdown"
    ),
}

@bot.message_handler(func=lambda message: True)
def handle_text_messages(message):
    try:
        user_id = message.from_user.id
        if user_id in blocked_users:
            return
            
        text = message.text or ""
        # Deposit input is state-driven from SQLite, not Telegram's volatile next-step handler.
        # This survives bot restarts and removes the old "session expired" failure mode.
        deposit_session = get_deposit_session(user_id)
        if deposit_session:
            if deposit_session.get("step") == "amount":
                process_deposit_amount(message)
                return
            if deposit_session.get("step") == "trx":
                process_deposit_trx(message)
                return
            if deposit_session.get("step") == "sender_phone":
                process_deposit_sender_phone(message)
                return

        if text == "🛡️ 𝗔𝗱𝗺𝗶𝗻 𝗣𝗮𝗻𝗲𝗹" and user_id in admin_ids:
            bot.send_message(
                message.chat.id,
                "🛡️ **𝗔𝗗𝗠𝗜𝗡 𝗖𝗢𝗡𝗧𝗥𝗢𝗟 𝗖𝗘𝗡𝗧𝗘𝗥**\n\n"
                "🔐 Secure review • Hosting control • User management",
                reply_markup=create_admin_panel_inline(user_id)
            )
            return
            
        if text == "👑 𝗖𝗼𝗻𝘁𝗮𝗰𝘁 𝗢𝘄𝗻𝗲𝗿":
            bot.send_message(message.chat.id, f"👑 **Owner:** {YOUR_USERNAME}")
            return

        action = BUTTON_MAPPING.get(text)
        if action:
            action(message)
    except Exception as e:
        logger.error(f"Error handling message text: {e}")

# =====================================================================
# SECOND BOT CONFIGURATION
# Keep these values after the main code as requested.
# Replace only the two placeholders below.
# =====================================================================
SECOND_BOT_TOKEN = "8825010260:AAF-wdpXHwWURx1kPoFVe8ptdSFzpMaKCqw"
SECOND_ADMIN_ID = 8888777331

APPROVAL_ADMIN_IDS = {int(OWNER_ID), int(ADMIN_ID)}
if SECOND_ADMIN_ID:
    APPROVAL_ADMIN_IDS.add(int(SECOND_ADMIN_ID))
    admin_ids.add(int(SECOND_ADMIN_ID))
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        conn.execute("INSERT OR IGNORE INTO admins (user_id, added_by) VALUES (?, ?)", (int(SECOND_ADMIN_ID), 0))
        conn.commit()
        conn.close()

BOT_INSTANCES = [telebot.TeleBot(TOKEN)]
if SECOND_BOT_TOKEN and SECOND_BOT_TOKEN != "PUT_NEW_BOT_TOKEN_HERE":
    BOT_INSTANCES.append(telebot.TeleBot(SECOND_BOT_TOKEN))

bot._default = BOT_INSTANCES[0]

def _register_proxy_handlers():
    for real_bot in BOT_INSTANCES:
        for kind, args, kwargs, func in bot._handlers:
            def wrapped(update, _func=func, _real_bot=real_bot):
                bot.bind(_real_bot)
                return _func(update)
            if kind == "message":
                real_bot.message_handler(*args, **kwargs)(wrapped)
            else:
                real_bot.callback_query_handler(*args, **kwargs)(wrapped)

_register_proxy_handlers()

# --- App Start ---
def _poll_bot(real_bot, label):
    bot.bind(real_bot)
    logger.info("%s polling started.", label)
    while True:
        try:
            real_bot.polling(none_stop=True, timeout=60, long_polling_timeout=60)
        except telebot.apihelper.ApiException as e:
            logger.error("%s Telegram API error: %s", label, e)
            time.sleep(15)
        except Exception as e:
            logger.error("%s polling error: %s", label, e)
            time.sleep(15)

if __name__ == "__main__":
    keep_alive()
    Thread(target=auto_stopper, daemon=True).start()
    logger.info("🚀 Premium File Host is starting with %d Telegram bot(s)...", len(BOT_INSTANCES))
    for idx, real_bot in enumerate(BOT_INSTANCES, 1):
        Thread(target=_poll_bot, args=(real_bot, f"BOT-{idx}"), daemon=True).start()
    while True:
        time.sleep(3600)
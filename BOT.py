# LOW-RAM PATCH NOTES
# - Main bot token is configured directly in TOKEN below. Keep this file private.
# - No fixed bot-count cap by default; RAM checks still protect the host.
# - Thread pools for common numerical libraries are limited in child processes.
# - CHILD_MEM_LIMIT_MB uses RLIMIT_DATA where supported; this is NOT a security sandbox
#   and cannot guarantee a hard RAM ceiling. Strong isolation requires cgroups/containers
#   or a hosting provider that enforces per-process limits.
# - Rotate the old Telegram bot token because it was embedded in the uploaded source.
# -*- coding: utf-8 -*-
import os as _os0
_os0.environ.setdefault('MALLOC_ARENA_MAX','2')
_os0.environ.setdefault('PYTHONDONTWRITEBYTECODE','1')
import gc
import atexit
import ast
import importlib.util
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
import html
import uuid
import json
from threading import Thread

# --- UTF-8 / Unicode safety ---
# Prevent Bengali/emoji mojibake in hosts that use a non-UTF-8 console locale.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for _stream in (sys.stdout, sys.stderr):
    try:
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# --- Built-in dependency bootstrap ---
# Works on hosts with pip available; requirements.txt is still recommended.
def _ensure_runtime_dependencies():
    """Bootstrap only the packages required by this host bot itself."""
    packages = {
        "flask": "Flask==3.1.3",
        "psutil": "psutil==7.2.2",
        "telebot": "pyTelegramBotAPI==4.29.1",
        "requests": "requests==2.32.5",
    }
    missing = []
    for module_name, package_spec in packages.items():
        try:
            __import__(module_name)
        except ImportError:
            missing.append(package_spec)
    if not missing:
        return True
    commands = [
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", *missing],
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--user", *missing],
    ]
    last_error = None
    for cmd in commands:
        try:
            subprocess.check_call(cmd, timeout=900)
            return True
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Required host packages could not be installed: {last_error}")


_ensure_runtime_dependencies()

from flask import Flask
import psutil
import telebot
from telebot import types
from types import SimpleNamespace

# --- Flask Keep Alive ---
# Robust port selection for hosts that inject PORT or already occupy a port.
import socket as _socket
from flask import Flask
from threading import Thread

app = Flask("rbk_fast_hosting")

# Silence Werkzeug request/startup noise; application logs still use our logger.
try:
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
except Exception:
    pass

@app.route("/")
def home():
    return "I'm TG Bot Hoster"

def _is_port_free(port):
    try:
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as sock:
            sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", int(port)))
            return True
    except OSError:
        return False

def run_flask():
    try:
        base_port = int(os.environ.get("PORT", "5000"))
    except (TypeError, ValueError):
        base_port = 5000
    # Try the platform-provided port first, then safe fallbacks.
    candidates = [base_port] + [p for p in range(8081, 8096) if p != base_port]
    for port in candidates:
        if not _is_port_free(port):
            logger.warning("Flask: port %s is already in use; skipping.", port)
            continue
        try:
            logger.info("Flask Keep-Alive starting on port %s", port)
            app.run(host="0.0.0.0", port=port, use_reloader=False, threaded=False)
            return
        except Exception as exc:
            logger.warning("Flask failed on port %s: %s", port, exc)
    logger.warning("Flask Keep-Alive: no free port found. Telegram bot will continue without web server.")

def keep_alive():
    thread = Thread(target=run_flask, name="flask-keepalive", daemon=True)
    thread.start()
    logger.info("Flask Keep-Alive thread started.")

# --- Configuration ---
TOKEN = os.environ.get("BOT_TOKEN", "8825010260:AAF0NJzRp7lrNTyuHklDNOrL7Di2H9XlY1U").strip()  # Use a NEW token; never reuse the exposed token.
OWNER_ID = 7327642910
ADMIN_ID = 7327642910
YOUR_USERNAME = "@RBK_Developer "
UPDATE_CHANNEL = "https://t.me/RBK_Developer_Official"
UPLOAD_LOG_CHANNEL = "@TG_TEST_16" # ফাইল upload log (not used for source forwarding)
# Private admin group for deposit/plan activity only. Set your group chat ID here.
# Uploaded .py/.js files are NEVER sent to this group.
ACTIVITY_LOG_GROUP_ID = -1003916312042

MAX_FILE_SIZE_MB = 5 # [CRASH PROTECTION] Maximum file size allowed to prevent memory/disk exhaustion
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# Default payment numbers (Can be changed from Admin Panel now)
DEFAULT_BKASH = "01738231716"
DEFAULT_NAGAD = "Off"

# Folder setup - using absolute paths
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_BOTS_DIR = os.path.join(BASE_DIR, "upload_bots")
IROTECH_DIR = os.path.join(BASE_DIR, "inf")
DATABASE_PATH = os.path.join(IROTECH_DIR, "bot_data.db")
# JSON persistence for Admin Gift/Info workflows.
ADMIN_JSON_DIR = os.path.join(IROTECH_DIR, "admin_data")
GIFT_JSON_PATH = os.path.join(ADMIN_JSON_DIR, "gift_codes.json")
INFO_JSON_PATH = os.path.join(ADMIN_JSON_DIR, "info_links.json")
ADMIN_STATE_JSON_PATH = os.path.join(ADMIN_JSON_DIR, "conversation_states.json")
os.makedirs(ADMIN_JSON_DIR, exist_ok=True)

def _json_load(path, default):
    try:
        if not os.path.isfile(path):
            return default
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data
    except Exception as exc:
        logger.warning("JSON load failed for %s: %s", path, exc)
        return default

def _json_save(path, data):
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        return True
    except Exception as exc:
        logger.error("JSON save failed for %s: %s", path, exc, exc_info=True)
        try:
            if os.path.exists(tmp): os.remove(tmp)
        except Exception: pass
        return False

def _json_lock_update(path, updater, default):
    data = _json_load(path, default)
    result = updater(data)
    if not _json_save(path, data):
        return None
    return result


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
        """Persist the next input step instead of using telebot's volatile memory.

        The original pyTelegramBotAPI next-step registry can lose a session after a
        restart and can collide when several flows are opened quickly. This bot
        stores the callback name and simple arguments in SQLite; the main message
        router dispatches the next incoming update and clears the state safely.
        """
        user_id = getattr(getattr(message, "from_user", None), "id", None)
        chat_id = getattr(getattr(message, "chat", None), "id", None)
        # In normal usage `message` is the bot's prompt message, so from_user may
        # be the bot itself. Prefer chat_id as the owner of the workflow.
        if user_id is None or int(user_id) < 0 or int(user_id) not in active_users:
            user_id = chat_id
        if user_id is None:
            raise RuntimeError("Could not determine persistent input owner")
        callback_name = getattr(callback, "__name__", "")
        if not callback_name or callback_name == "<lambda>":
            raise ValueError("Persistent input callback must be a named function")
        if not set_workflow_session(int(user_id), int(chat_id or user_id), callback_name, args, kwargs):
            raise RuntimeError("Could not save persistent input state")
        return True

    def __getattr__(self, name):
        target = self._target()
        if target is None:
            raise RuntimeError(f"No active Telegram bot for .{name}()")
        attr = getattr(target, name)
        # Protect ordinary bot output from forwarding/saving by default.
        # A caller can explicitly pass protect_content=False for Admin-only
        # copyable logs/errors. Telegram still cannot guarantee screenshot blocking.
        protected_methods = {
            "send_message", "send_document", "send_photo", "send_video",
            "send_audio", "send_voice", "send_animation", "send_video_note"
        }
        if name in protected_methods and callable(attr):
            def protected_sender(*args, **kwargs):
                kwargs.setdefault("protect_content", True)
                return attr(*args, **kwargs)
            return protected_sender
        return attr

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

def get_setting(key, default=""):
    """Read a persistent setting safely. Defined early so startup never depends on declaration order."""
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            row = conn.execute("SELECT value FROM settings WHERE key=?", (str(key),)).fetchone()
            conn.close()
        return row[0] if row else default
    except Exception as exc:
        logger.warning("get_setting(%s) failed: %s", key, exc)
        return default

def set_setting(key, value):
    """Persist a setting safely."""
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (str(key), str(value)))
            conn.commit()
            conn.close()
        return True
    except Exception as exc:
        logger.error("set_setting(%s) failed: %s", key, exc, exc_info=True)
        return False

# --- Command Button Layouts ---
COMMAND_BUTTONS_LAYOUT_USER_SPEC = [
    ["✨ 𝗨𝗽𝗱𝗮𝘁𝗲𝘀 𝗖𝗵𝗮𝗻𝗻𝗲𝗹 ✨", "🎥 𝗧𝘂𝘁𝗼𝗿𝗶𝗮𝗹"],
    ["🚀 𝗨𝗽𝗹𝗼𝗮𝗱 𝗙𝗶𝗹𝗲", "📁 𝗠𝗮𝗻𝗮𝗴𝗲 𝗙𝗶𝗹𝗲𝘀"],
    ["💰 𝗔𝗱𝗱 𝗠𝗼𝗻𝗲𝘆", "💎 𝗩𝗜𝗣 𝗣𝗹𝗮𝗻𝘀"],
    ["⚡ 𝗦𝗽𝗲𝗲𝗱 & 𝗣𝗶𝗻𝗴", "👤 𝗔𝗰𝗰𝗼𝘂𝗻𝘁"],
    ["🔐 𝗦𝗲𝗰𝘂𝗿𝗶𝘁𝘆"],
    ["ⓘ 𝗜𝗻𝗳𝗼𝗿𝗺𝗮𝘁𝗶𝗼𝗻", "🎁 𝗚𝗶𝗳𝘁 𝗖𝗼𝗱𝗲"],
    ["💻 𝗗𝗲𝘃𝗲𝗹𝗼𝗽𝗲𝗿", "👑 𝗖𝗼𝗻𝘁𝗮𝗰𝘁 𝗢𝘄𝗻𝗲𝗿"],
]

ADMIN_COMMAND_BUTTONS_LAYOUT_USER_SPEC = [
    ["✨ 𝗨𝗽𝗱𝗮𝘁𝗲𝘀 𝗖𝗵𝗮𝗻𝗻𝗲𝗹 ✨", "🎥 𝗧𝘂𝘁𝗼𝗿𝗶𝗮𝗹"],
    ["🚀 𝗨𝗽𝗹𝗼𝗮𝗱 𝗙𝗶𝗹𝗲", "📁 𝗠𝗮𝗻𝗮𝗴𝗲 𝗙𝗶𝗹𝗲𝘀"],
    ["💰 𝗔𝗱𝗱 𝗠𝗼𝗻𝗲𝘆", "🛡️ 𝗔𝗱𝗺𝗶𝗻 𝗣𝗮𝗻𝗲𝗹"],
    ["💎 𝗩𝗜𝗣 𝗣𝗹𝗮𝗻𝘀", "📊 𝗕𝗼𝘁 𝗦𝘁𝗮𝘁𝘀"],
    ["⚡ 𝗦𝗽𝗲𝗲𝗱 & 𝗣𝗶𝗻𝗴"],
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
            c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('maintenance', '0')")
            c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('notify_activity', '1')")
            c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('welcome_text', '')")
            c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('welcome_image_file_id', '')")

            # Dedicated system_settings table for dynamic public Information links.
            c.execute("""CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            )""")
            info_defaults = {
                'info_dev_url': 'https://t.me/RBK_Developer',
                'info_channel_url': UPDATE_CHANNEL,
                'info_notice_url': UPDATE_CHANNEL,
                'info_support_url': 'https://t.me/RBK_Developer',
            }
            for _k, _v in info_defaults.items():
                c.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)", (_k, _v))

            # Admin-controlled Gift Code system.
            c.execute("""CREATE TABLE IF NOT EXISTS gift_codes (
                code TEXT PRIMARY KEY,
                amount REAL NOT NULL DEFAULT 0,
                max_uses INTEGER NOT NULL DEFAULT 1,
                used_count INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                expires_at TEXT DEFAULT NULL,
                created_by INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS gift_creation_sessions (
                admin_id INTEGER PRIMARY KEY,
                step TEXT NOT NULL DEFAULT 'code',
                code TEXT DEFAULT '',
                amount REAL DEFAULT 0,
                max_uses INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS gift_redemptions (
                code TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                redeemed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(code, user_id)
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS workflow_sessions (
                user_id INTEGER PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                handler TEXT NOT NULL,
                args_json TEXT NOT NULL DEFAULT '[]',
                kwargs_json TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_workflow_sessions_updated ON workflow_sessions(updated_at)")
            c.execute("""CREATE TABLE IF NOT EXISTS admin_activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                details TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS broadcast_sessions (
                admin_id INTEGER PRIMARY KEY,
                source_chat_id INTEGER NOT NULL,
                source_message_id INTEGER NOT NULL,
                button_text TEXT DEFAULT '',
                button_url TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")

            # Editable Developer Information text. Existing custom text is preserved.
            default_dev_info = (
                "📁 <b>ⓘ Developer Info</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
                "🤖 <b>বট সম্পর্কে বিস্তারিত তথ্য:</b>\n"
                "আমাদের এই প্ল্যাটফর্মটি আপনাদের অটোমেশন এবং বিভিন্ন ডিজিটাল সেবা সহজ করার জন্য তৈরি করা হয়েছে। আপনি যদি আপনার বিজনেস বা ব্যক্তিগত কাজের জন্য এই ধরনের কিংবা এর চেয়েও আধুনিক কোনো বট তৈরি করতে চান, তবে আমরা আছি আপনার সহায়তায়!\n\n"
                "💡 <b>আমাদের প্রধান সেবাসমূহ:</b>\n"
                "• কাস্টম টেলিগ্রাম বট ও মিনি অ্যাপ ডেভেলপমেন্ট (Mini Apps)\n"
                "• ওয়েবসাইট ও সার্ভিস ভেরিফিকেশনের জন্য <b>OTP Bot</b> সিস্টেম\n"
                "• অটো পেমেন্ট গেটওয়ে ইন্টিগ্রেশন এবং কাস্টম ডাটাবেস ম্যানেজমেন্ট\n"
                "• যে কোনো ধরনের ওয়েব অ্যাপ্লিকেশন ও অটোমেশন সলিউশন\n\n"
                "💰 আমরা অত্যন্ত সাশ্রয়ী মূল্যে এবং কম সময়ে প্রফেশনাল মানের সার্ভিস প্রদান করে থাকি। দেরি না করে নিচের <b>'Developer'</b> অপশনে ক্লিক করে আজই আমাদের সাথে যোগাযোগ করুন এবং আপনার আইডিয়াটি শেয়ার করুন। ধন্যবাদ! 🚀"
            )
            c.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES ('developer_info_text', ?)", (default_dev_info,))

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
# Restore persisted maintenance state after DB helpers are available.
with DB_LOCK:
    _conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    _row = _conn.execute("SELECT value FROM settings WHERE key=?", ("maintenance",)).fetchone()
    _conn.close()
bot_locked = (_row[0] if _row else "0") == "1"
# Initialize JSON stores and migrate any legacy SQLite Gift Codes once.
if not os.path.isfile(INFO_JSON_PATH):
    _json_save(INFO_JSON_PATH, {"links": []})
if not os.path.isfile(ADMIN_STATE_JSON_PATH):
    _json_save(ADMIN_STATE_JSON_PATH, {"states": {}})
if not os.path.isfile(GIFT_JSON_PATH):
    try:
        with DB_LOCK:
            _conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False)
            _rows=_conn.execute("SELECT code,amount,max_uses,used_count,active,expires_at,created_by,created_at FROM gift_codes").fetchall()
            _conn.close()
        _json_save(GIFT_JSON_PATH,{"codes":[{"code":r[0],"amount":r[1],"max_uses":r[2],"used_count":r[3],"active":r[4],"expires_at":r[5],"created_by":r[6],"created_at":r[7]} for r in _rows]})
    except Exception:
        _json_save(GIFT_JSON_PATH,{"codes":[]})

# =====================================================================
# 💾 PERSISTENT INPUT / WORKFLOW STATE
# =====================================================================
def _json_safe(value):
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        if isinstance(value, (list, tuple)):
            return [_json_safe(v) for v in value]
        if isinstance(value, dict):
            return {str(k): _json_safe(v) for k, v in value.items()}
        return str(value)


def set_workflow_session(user_id, chat_id, handler, args=(), kwargs=None):
    """Persist a next-input handler in SQLite; never rely on telebot memory."""
    try:
        args_json = json.dumps(_json_safe(list(args or ())), ensure_ascii=False)
        kwargs_json = json.dumps(_json_safe(dict(kwargs or {})), ensure_ascii=False)
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            conn.execute(
                """INSERT OR REPLACE INTO workflow_sessions
                   (user_id,chat_id,handler,args_json,kwargs_json,updated_at)
                   VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)""",
                (int(user_id), int(chat_id), str(handler), args_json, kwargs_json),
            )
            conn.commit()
            conn.close()
        return True
    except Exception as exc:
        logger.error("Failed to persist workflow session: %s", exc, exc_info=True)
        return False


def get_workflow_session(user_id):
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            row = conn.execute(
                "SELECT chat_id,handler,args_json,kwargs_json FROM workflow_sessions WHERE user_id=?",
                (int(user_id),),
            ).fetchone()
            conn.close()
        if not row:
            return None
        try:
            args = json.loads(row[2] or "[]")
            kwargs = json.loads(row[3] or "{}")
        except Exception:
            args, kwargs = [], {}
        return {"chat_id": int(row[0]), "handler": row[1], "args": args, "kwargs": kwargs}
    except Exception as exc:
        logger.error("Workflow session read failed: %s", exc, exc_info=True)
        return None


def clear_workflow_session(user_id):
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            conn.execute("DELETE FROM workflow_sessions WHERE user_id=?", (int(user_id),))
            conn.commit()
            conn.close()
        return True
    except Exception as exc:
        logger.error("Workflow session clear failed: %s", exc, exc_info=True)
        return False


def dispatch_workflow_session(message):
    """Run one persisted input step and clear it unless the callback creates another step."""
    user_id = int(_message_actor_id(message))
    session = get_workflow_session(user_id)
    if not session:
        return False
    handler_name = str(session.get("handler") or "")
    callback = globals().get(handler_name)
    if not callable(callback):
        clear_workflow_session(user_id)
        bot.send_message(message.chat.id, "❌ এই input session আর valid নেই। আবার শুরু করুন।", protect_content=True)
        return True
    # Clear before invoking. If the callback asks for another step, the wrapper
    # will create the new persistent row. This prevents stale/deadlocked states.
    clear_workflow_session(user_id)
    try:
        callback(message, *(session.get("args") or []), **(session.get("kwargs") or {}))
    except Exception as exc:
        logger.error("Persistent workflow '%s' failed: %s", handler_name, exc, exc_info=True)
        clear_workflow_session(user_id)
        bot.send_message(
            message.chat.id,
            f"❌ <b>Input processing error</b>\n\n<code>{str(exc)[:500]}</code>\n\nআবার শুরু করুন অথবা /cancel দিন।",
            parse_mode="HTML", protect_content=True,
        )
    return True

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

def get_system_setting(key, default=""):
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            row = conn.execute("SELECT value FROM system_settings WHERE key=?", (key,)).fetchone()
            conn.close()
        return row[0] if row else default
    except Exception:
        return default

def set_system_setting(key, value):
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            conn.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (key, str(value)))
            conn.commit()
            conn.close()
        return True
    except Exception as exc:
        logger.error("system_settings write failed: %s", exc, exc_info=True)
        return False

# =====================================================================
# 🧾 ADMIN ACTIVITY / SECURITY LOG
# =====================================================================
def log_admin_activity(admin_id, action, details=""):
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            conn.execute(
                "INSERT INTO admin_activity_log(admin_id,action,details) VALUES(?,?,?)",
                (int(admin_id), str(action)[:120], str(details)[:1000]),
            )
            conn.commit()
            conn.close()
    except Exception as exc:
        logger.error("Admin activity log failed: %s", exc, exc_info=True)


def get_admin_activity(limit=30):
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            rows = conn.execute(
                "SELECT admin_id,action,details,created_at FROM admin_activity_log ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            conn.close()
        return rows
    except Exception as exc:
        logger.error("Admin activity read failed: %s", exc, exc_info=True)
        return []

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

def get_subscription_status(user_id):
    """Return a user-friendly plan status including precise remaining days/hours."""
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            row = conn.execute(
                "SELECT p.name, p.bot_limit, u.end_time FROM user_subscriptions u "
                "LEFT JOIN plans p ON p.plan_id=u.plan_id WHERE u.user_id=?",
                (int(user_id),),
            ).fetchone()
            conn.close()
        if not row:
            return {"active": False, "name": "No active plan", "limit": get_user_file_limit(int(user_id)), "end": None, "remaining": "No active plan"}
        name, limit, end_text = row
        end = datetime.fromisoformat(str(end_text))
        seconds = max(0, int((end - datetime.now()).total_seconds()))
        if seconds <= 0:
            return {"active": False, "name": str(name or "Expired plan"), "limit": limit or 1, "end": end, "remaining": "Expired"}
        days, rem = divmod(seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes = rem // 60
        remaining = f"{days} দিন {hours} ঘণ্টা {minutes} মিনিট"
        return {"active": True, "name": str(name or "VIP Plan"), "limit": int(limit or 1), "end": end, "remaining": remaining}
    except Exception as exc:
        logger.error("Subscription status failed for %s: %s", user_id, exc)
        return {"active": False, "name": "Status unavailable", "limit": 1, "end": None, "remaining": "Status unavailable"}

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
    # Admins have unlimited free hosting from the normal User Board.
    if int(user_id) in admin_ids or int(user_id) == int(OWNER_ID):
        return False
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
    """Return Telegram Bot API button style.
    Telegram styles are semantic: primary=blue, success=green, danger=red.
    Normal/unclassified buttons stay blue instead of changing randomly.
    """
    if kind in ("success", "danger", "primary"):
        return kind
    return "primary"


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



def make_copy_text_button(text, label="📋 Copy Log / Error"):
    """Native Telegram copy button when supported; safe compatibility fallback."""
    text=str(text or "")[:4096]
    try:
        copy_cls=getattr(types,"CopyTextButton",None)
        if copy_cls is not None:
            return types.InlineKeyboardButton(text=label,copy_text=copy_cls(text=text))
    except (TypeError,AttributeError):
        pass
    return None

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
    """Atomically claim an upload, move it into the approved folder, then mark it approved."""
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        row = conn.execute(
            """SELECT user_id,file_name,file_type,file_path,file_size,risk_note,status
               FROM pending_uploads WHERE request_id=?""",
            (request_id,),
        ).fetchone()
        if not row or row[6] != "pending":
            conn.close()
            return None
        file_path = row[3]
        if not os.path.isfile(file_path):
            conn.close()
            return ("missing", row[0], row[1])
        claimed = conn.execute(
            "UPDATE pending_uploads SET status='approving', approved_by=? WHERE request_id=? AND status='pending'",
            (int(admin_id), request_id),
        )
        if claimed.rowcount != 1:
            conn.rollback()
            conn.close()
            return None
        conn.commit()
        conn.close()

    user_id, file_name, file_type, file_path, file_size, risk_note, _ = row
    destination = os.path.join(get_user_folder(user_id), os.path.basename(file_name))
    try:
        force_kill_user_bot(user_id, file_name)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        if os.path.exists(destination):
            os.remove(destination)
        os.replace(file_path, destination)
        save_user_file(user_id, file_name, file_type)
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            conn.execute(
                "UPDATE pending_uploads SET status='approved', approved_by=? WHERE request_id=? AND status='approving'",
                (int(admin_id), request_id),
            )
            conn.commit()
            conn.close()
        log_admin_activity(int(admin_id), "File approved", f"user={user_id}, file={file_name}")
        return ("approved", user_id, file_name, destination, risk_note)
    except Exception as exc:
        logger.error("Approval finalize error for %s: %s", request_id, exc, exc_info=True)
        # Restore the request to pending when the file could not be finalized.
        try:
            with DB_LOCK:
                conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
                conn.execute(
                    "UPDATE pending_uploads SET status='pending', approved_by=NULL WHERE request_id=? AND status='approving'",
                    (request_id,),
                )
                conn.commit()
                conn.close()
        except Exception:
            pass
        return ("error", user_id, file_name, str(exc))

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
            _reap_dead_scripts()
            gc.collect()
            for key in list(bot_scripts.keys()):
                script = bot_scripts.get(key)
                if not script:
                    continue
                user_id = int(script["script_owner_id"])
                if user_id in admin_ids or user_id == int(OWNER_ID):
                    continue
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
                    # Expiry must stop paid-plan bots; otherwise they could keep running indefinitely.
                    for script_key, script_info in list(bot_scripts.items()):
                        if int(script_info.get("script_owner_id", -1)) == int(uid):
                            try:
                                force_kill_user_bot(uid, script_info.get("file_name", ""))
                            except Exception as stop_exc:
                                logger.warning("Could not stop expired-plan bot %s: %s", script_key, stop_exc)
                    with DB_LOCK:
                        conn_del = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
                        c_del = conn_del.cursor()
                        c_del.execute("DELETE FROM user_subscriptions WHERE user_id=?", (uid,))
                        conn_del.commit()
                        conn_del.close()
                    try:
                        bot.send_message(uid, f"⚠️ আপনার '{pname}' প্ল্যানের মেয়াদ শেষ হয়েছে।\nআপনার হোস্ট করা বটগুলো বন্ধ করা হয়েছে। আবার চালাতে নতুন প্ল্যান কিনুন।")
                    except Exception:
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
TELEGRAM_MODULES = {
    "telebot": "pyTelegramBotAPI",
    "telegram": "python-telegram-bot",
    "telegram.ext": "python-telegram-bot",
    "aiogram": "aiogram",
    "pyrogram": "pyrogram",
    "telethon": "telethon",
    "flask": "Flask",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "quart": "quart",
    "aiohttp": "aiohttp",
    "requests": "requests",
    "httpx": "httpx",
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python-headless",
    "PIL": "Pillow",
    "yaml": "PyYAML",
    "dotenv": "python-dotenv",
    "jwt": "PyJWT",
    "Crypto": "pycryptodome",
    "dateutil": "python-dateutil",
    "discord": "discord.py",
    "discord_webhook": "discord-webhook",
    "selenium": "selenium",
    "playwright": "playwright",
    "numpy": "numpy",
    "pandas": "pandas",
    "matplotlib": "matplotlib",
    "lxml": "lxml",
    "psutil": "psutil",
}

PYTHON_IMPORT_ALIASES = {k.lower(): v for k, v in TELEGRAM_MODULES.items()}

def _module_import_roots(script_path):
    """Return top-level Python imports used by an uploaded script."""
    try:
        source = open(script_path, "r", encoding="utf-8", errors="ignore").read()
        tree = ast.parse(source, filename=script_path)
    except Exception:
        return set()
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots

def _js_import_packages(script_path):
    """Best-effort extraction of npm package names from require/import statements."""
    try:
        source = open(script_path, "r", encoding="utf-8", errors="ignore").read()
    except Exception:
        return set()
    found = set()
    patterns = [
        r"require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
        r"(?:import|export)\s+(?:[^;]*?\s+from\s+)?['\"]([^'\"]+)['\"]",
        r"import\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
    ]
    for pattern in patterns:
        for value in re.findall(pattern, source):
            if value.startswith(".") or value.startswith("/") or value.startswith("node:"):
                continue
            if value.startswith("@"):
                parts = value.split("/")
                pkg = "/".join(parts[:2]) if len(parts) >= 2 else value
            else:
                pkg = value.split("/")[0]
            if _safe_package_name(pkg.replace("/", "-")):
                found.add(pkg)
    return found

def _pip_install_to_folder(user_folder, package_names):
    """Install packages into the user's isolated folder without shell=True."""
    clean = []
    for package in package_names:
        if not _safe_package_name(package):
            continue
        if package not in clean:
            clean.append(package)
    if not clean:
        return (0, "No packages required.")
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--no-cache-dir", "--target", user_folder, *clean]
    try:
        result = subprocess.run(cmd, cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", timeout=900, shell=False)
        return result.returncode, (result.stdout or "")[-3000:]
    except subprocess.TimeoutExpired:
        return 124, "Package installation timed out after 15 minutes."
    except Exception as exc:
        return 1, str(exc)

def _prepare_python_dependencies(user_folder, script_path):
    """Install requirements.txt plus every missing third-party import before launch."""
    results = []
    req = os.path.join(user_folder, "requirements.txt")
    if os.path.isfile(req):
        _marker = req + ".installed"
        _fresh = os.path.isfile(_marker) and os.path.getmtime(_marker) >= os.path.getmtime(req)
        try:
            if _fresh:
                raise subprocess.TimeoutExpired("skip", 0)
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--no-cache-dir", "--target", user_folder, "-r", req],
                cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", timeout=900, shell=False
            )
            results.append(("requirements.txt", result.returncode, (result.stdout or "")[-3000:]))
            if result.returncode == 0:
                open(_marker, "w").close()
        except subprocess.TimeoutExpired:
            if not _fresh:
                results.append(("requirements.txt", 124, "requirements.txt installation timed out after 15 minutes."))
        except Exception as exc:
            results.append(("requirements.txt", 1, str(exc)))

    imports = _module_import_roots(script_path)
    stdlib = set(getattr(sys, "stdlib_module_names", set()))
    candidates = []
    for module in sorted(imports):
        if module in stdlib or module in {"__future__", "typing_extensions"} and os.path.exists(os.path.join(user_folder, module)):
            continue
        local_exists = any(os.path.exists(os.path.join(user_folder, module + suffix)) for suffix in (".py", ".pyc")) or os.path.isdir(os.path.join(user_folder, module))
        if local_exists:
            continue
        try:
            old_path = list(sys.path)
            if user_folder not in sys.path:
                sys.path.insert(0, user_folder)
            available = importlib.util.find_spec(module) is not None
        except Exception:
            available = False
        finally:
            sys.path[:] = old_path
        if not available:
            candidates.append(PYTHON_IMPORT_ALIASES.get(module.lower(), module))

    if candidates:
        code, output = _pip_install_to_folder(user_folder, candidates)
        results.append(("auto-import", code, output))
    return results

def _prepare_node_dependencies(user_folder, script_path):
    """Install package.json dependencies and any detected missing npm imports."""
    results = []
    npm = shutil.which("npm")
    if not npm:
        if os.path.isfile(os.path.join(user_folder, "package.json")):
            return [("npm", 127, "npm is not installed on this hosting environment.")]
        return results
    package_json = os.path.join(user_folder, "package.json")
    if os.path.isfile(package_json):
        try:
            result = subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", timeout=900, shell=False)
            results.append(("package.json", result.returncode, (result.stdout or "")[-3000:]))
        except subprocess.TimeoutExpired:
            results.append(("package.json", 124, "npm install timed out after 15 minutes."))
        except Exception as exc:
            results.append(("package.json", 1, str(exc)))
    candidates = []
    node_modules = os.path.join(user_folder, "node_modules")
    for pkg in sorted(_js_import_packages(script_path)):
        if os.path.exists(os.path.join(node_modules, *pkg.split("/"))):
            continue
        candidates.append(pkg)
    if candidates:
        try:
            result = subprocess.run([npm, "install", "--no-audit", "--no-fund", *candidates], cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", timeout=900, shell=False)
            results.append(("auto-import", result.returncode, (result.stdout or "")[-3000:]))
        except subprocess.TimeoutExpired:
            results.append(("auto-import", 124, "npm package installation timed out after 15 minutes."))
        except Exception as exc:
            results.append(("auto-import", 1, str(exc)))
    return results

def _install_project_dependencies(user_folder, file_name):
    """Install declared and detected dependencies automatically before hosting (one at a time, low RAM)."""
    script_path = os.path.join(user_folder, file_name)
    ext = os.path.splitext(file_name)[1].lower()
    with _PIP_SEM:
        try:
            if ext == ".py":
                return _prepare_python_dependencies(user_folder, script_path)
            if ext == ".js":
                return _prepare_node_dependencies(user_folder, script_path)
            return []
        finally:
            gc.collect()

def _safe_package_name(name):
    """Only allow normal PyPI/npm package names; never pass shell syntax."""
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+\-]{0,127}", str(name or "")))

def forward_uploaded_file_to_channel(data, file_name, user_id, file_size, stage="uploaded"):
    """Disabled by design: source files must never be forwarded."""
    return False


def send_activity_log(text_message):
    """Send text-only activity to the private admin group when notifications are enabled."""
    if get_setting("notify_activity", "1") != "1":
        return False
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
        with open(log_file_path, "r", encoding="utf-8", errors="replace") as f:
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
                cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--no-cache-dir", "--target", folder, package]
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
                with open(log_file_path, "r", encoding="utf-8", errors="replace") as f:
                    log_content = f.read()[-20000:]

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


# ================= LOW-RAM PROTECTION =================
MAX_RUNNING_SCRIPTS = max(0, int(os.environ.get("MAX_RUNNING_SCRIPTS", "0")))  # 0 = no fixed count cap; RAM checks still apply.
CHILD_MEM_LIMIT_MB = max(96, int(os.environ.get("CHILD_MEM_LIMIT_MB", "128")))   # Best-effort Linux process data limit; not a hard RAM sandbox
MIN_FREE_RAM_MB = max(64, int(os.environ.get("MIN_FREE_RAM_MB", "128")))          # Keep headroom for the host bot
_PIP_SEM = threading.Semaphore(1)                                       # একসাথে একটাই pip/npm install

def _apply_child_limits(pid, is_js=False):
    """Hosted bot চালু হওয়ার পর RAM সীমা বসায় (Linux, fork-safe)। Node-এর জন্য --max-old-space-size ব্যবহার হয়।"""
    if is_js:
        return
    try:
        limit = CHILD_MEM_LIMIT_MB * 1024 * 1024
        p = psutil.Process(pid)
        p.rlimit(psutil.RLIMIT_DATA, (limit, limit))
    except Exception:
        pass

def _reap_dead_scripts():
    """মরে যাওয়া process-এর log handle বন্ধ করে dict থেকে সরায়।"""
    for key in list(bot_scripts.keys()):
        info = bot_scripts.get(key)
        try:
            proc = info and info.get("process")
            if proc is not None and proc.poll() is not None:
                try:
                    info["log_file"].close()
                except Exception:
                    pass
                bot_scripts.pop(key, None)
        except Exception:
            pass

def _can_start_new_script(chat_id=None):
    _reap_dead_scripts()
    if MAX_RUNNING_SCRIPTS > 0 and len(bot_scripts) >= MAX_RUNNING_SCRIPTS:
        return False, f"⚠️ সার্ভারের নির্ধারিত সীমা অনুযায়ী একসাথে সর্বোচ্চ {MAX_RUNNING_SCRIPTS}টা bot চলতে পারে। কিছুক্ষণ পর চেষ্টা করুন।"
    try:
        free_mb = psutil.virtual_memory().available / (1024 * 1024)
        if free_mb < MIN_FREE_RAM_MB:
            return False, "⚠️ সার্ভারে RAM কম আছে, কিছুক্ষণ পর আবার চেষ্টা করুন।"
    except Exception:
        pass
    return True, ""

def run_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply):
    script_key = f"{script_owner_id}_{file_name}"
    if is_bot_running(script_owner_id, file_name):
        try: bot.send_message(message_obj_for_reply.chat.id, "ℹ️ এই bot ইতিমধ্যে চলছে। আগে Stop করে আবার Start করুন।")
        except Exception: pass
        return
    _ok, _why = _can_start_new_script()
    if not _ok:
        try: bot.send_message(message_obj_for_reply.chat.id, _why)
        except Exception: pass
        return
    try:
        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = open(log_file_path, "w", encoding="utf-8", errors="ignore")
        
        unique_port = 8000 + (int(hashlib.md5(script_key.encode()).hexdigest(), 16) % 50000)
        
        custom_env = os.environ.copy()
        custom_env["PORT"] = str(unique_port)
        custom_env["PYTHONDONTWRITEBYTECODE"] = "1"
        custom_env["MALLOC_ARENA_MAX"] = "1"
        custom_env["OMP_NUM_THREADS"] = "1"
        custom_env["OPENBLAS_NUM_THREADS"] = "1"
        custom_env["MKL_NUM_THREADS"] = "1"
        custom_env["NUMEXPR_MAX_THREADS"] = "1"
        custom_env["PYTHONUNBUFFERED"] = "1"
        custom_env["PYTHONPATH"] = user_folder
        custom_env["HOME"] = user_folder        
        custom_env["TEMP"] = user_folder        
        custom_env["TMP"] = user_folder         
        custom_env["TMPDIR"] = user_folder

        dependency_results = _install_project_dependencies(user_folder, file_name)
        failed = [r for r in dependency_results if r[1] != 0]
        if failed:
            logger.warning("Project dependency setup reported errors for %s: %s", file_name, failed)

        process = subprocess.Popen([sys.executable, "-u", script_path], cwd=user_folder, stdout=log_file, stderr=log_file, stdin=subprocess.DEVNULL, env=custom_env, shell=False, start_new_session=True)
        
        _apply_child_limits(process.pid)
        bot_scripts[script_key] = {"process": process, "log_file": log_file, "file_name": file_name, "script_owner_id": script_owner_id, "start_time": datetime.now(), "warning_sent": False, "user_folder": user_folder, "type": "py"}
        bot.send_message(message_obj_for_reply.chat.id, f"🚀 **Python Bot Started!**\n📄 File: `{file_name}`\n🆔 PID: `{process.pid}`", parse_mode="Markdown", protect_content=True)
        threading.Thread(target=monitor_and_guide_error, args=(process, log_file_path, script_owner_id, file_name, message_obj_for_reply), daemon=True).start()
    except Exception as e:
        bot.send_message(message_obj_for_reply.chat.id, f"❌ Error starting script: {str(e)}", protect_content=True)

def run_js_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply):
    script_key = f"{script_owner_id}_{file_name}"
    if is_bot_running(script_owner_id, file_name):
        try: bot.send_message(message_obj_for_reply.chat.id, "ℹ️ এই bot ইতিমধ্যে চলছে। আগে Stop করে আবার Start করুন।")
        except Exception: pass
        return
    _ok, _why = _can_start_new_script()
    if not _ok:
        try: bot.send_message(message_obj_for_reply.chat.id, _why)
        except Exception: pass
        return
    try:
        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = open(log_file_path, "w", encoding="utf-8", errors="ignore")
        
        unique_port = 8000 + (int(hashlib.md5(script_key.encode()).hexdigest(), 16) % 50000)
        
        custom_env = os.environ.copy()
        custom_env["PORT"] = str(unique_port)
        custom_env["NODE_PATH"] = user_folder
        custom_env["NODE_OPTIONS"] = f"--max-old-space-size={max(64, CHILD_MEM_LIMIT_MB-30)}"
        custom_env["UV_THREADPOOL_SIZE"] = "1"
        custom_env["HOME"] = user_folder
        custom_env["TEMP"] = user_folder
        custom_env["TMP"] = user_folder
        custom_env["TMPDIR"] = user_folder

        dependency_results = _install_project_dependencies(user_folder, file_name)
        failed = [r for r in dependency_results if r[1] != 0]
        if failed:
            logger.warning("Project dependency setup reported errors for %s: %s", file_name, failed)

        process = subprocess.Popen([shutil.which("node") or "node", script_path], cwd=user_folder, stdout=log_file, stderr=log_file, stdin=subprocess.DEVNULL, env=custom_env, shell=False, start_new_session=True)
        
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

    is_admin_owner = owner_id in admin_ids or owner_id == int(OWNER_ID)
    if not is_admin_owner and is_free_hosting_exhausted(owner_id):
        text = "⏱️ Free 12-hour hosting has ended. Buy a plan from Account → Deposit to continue."
        if call_id:
            bot.answer_callback_query(call_id, text, show_alert=True)
        else:
            bot.send_message(message_obj.chat.id, "🛑 **Free Hosting Limit Finished**\n\n💎 Account → Deposit থেকে balance add করে একটি Plan কিনুন।", parse_mode="Markdown")
        return

    # A file must exist in the approved user_files table before it can run.
    if not any(str(n) == str(fname) for n, _ in user_files.get(owner_id, [])):
        if call_id:
            bot.answer_callback_query(call_id, "🔐 File is not approved yet.", show_alert=True)
        else:
            bot.send_message(message_obj.chat.id, "🔐 **File locked:** admin approval is required before it can run.")
        return

    # Admin/Owner can run unlimited bots for free. Normal users keep the existing 12h rule.
    if not is_admin_owner and not has_active_plan(owner_id):
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

# =====================================================================
# 👥 ADMIN — USER MANAGEMENT
# =====================================================================
def _user_management_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        make_inline_button("👤 User List", callback_data="user_list", style="primary"),
        make_inline_button("🔎 Search User", callback_data="user_search", style="primary"),
    )
    markup.add(
        make_inline_button("💰 Add Balance", callback_data="user_add_balance", style="success"),
        make_inline_button("➖ Deduct Balance", callback_data="user_deduct_balance", style="danger"),
    )
    markup.add(
        make_inline_button("🚫 Ban User", callback_data="user_ban", style="danger"),
        make_inline_button("♻️ Unban User", callback_data="user_unban", style="success"),
    )
    markup.add(
        make_inline_button("👑 Make Admin", callback_data="user_make_admin", style="success"),
        make_inline_button("❌ Remove Admin", callback_data="user_remove_admin", style="danger"),
    )
    markup.add(make_inline_button("📊 User Statistics", callback_data="user_statistics", style="primary"))
    markup.add(make_inline_button("📢 Broadcast", callback_data="broadcast", style="primary"))
    markup.add(make_inline_button("⬅️ Back", callback_data="admin_back", style="danger"))
    return markup


def send_user_management(message):
    if int(_message_actor_id(message)) not in admin_ids:
        return
    bot.send_message(
        message.chat.id,
        "👥 <b>User Management</b>\n\nএকটি action নির্বাচন করুন। সব input <code>SQLite</code>-এ persistent থাকবে।\n❌ যেকোনো সময় <code>/cancel</code> দিতে পারবেন।",
        parse_mode="HTML", reply_markup=_user_management_menu(), protect_content=True,
    )


def _get_user_row(user_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        row = conn.execute("SELECT user_id,balance,total_referrals FROM user_account WHERE user_id=?", (int(user_id),)).fetchone()
        conn.close()
    return row


def _user_card(user_id):
    row = _get_user_row(user_id)
    if not row:
        return f"❌ User <code>{int(user_id)}</code> not found."
    uid, balance, referrals = row
    files = user_files.get(int(uid), [])
    running = sum(1 for fname, _ in files if is_bot_running(uid, fname))
    status = "🚫 Banned" if int(uid) in blocked_users else "🟢 Active"
    role = "👑 Admin" if int(uid) in admin_ids else "👤 User"
    return (
        "👤 <b>User Details</b>\n\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"🎭 Role: <b>{role}</b>\n"
        f"📌 Status: <b>{status}</b>\n"
        f"💰 Balance: <b>{float(balance):g} BDT</b>\n"
        f"👥 Referrals: <b>{referrals}</b>\n"
        f"📁 Hosted Files: <b>{len(files)}</b>\n"
        f"🚀 Running Bots: <b>{running}</b>"
    )


def send_user_list(message):
    if int(_message_actor_id(message)) not in admin_ids:
        return
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        rows = conn.execute("SELECT user_id,balance,total_referrals FROM user_account ORDER BY user_id DESC LIMIT 50").fetchall()
        conn.close()
    if not rows:
        bot.send_message(message.chat.id, "📭 কোনো user পাওয়া যায়নি।", protect_content=True)
        return
    lines = ["👤 <b>User List</b> — latest 50\n"]
    for uid, balance, refs in rows:
        state = "🚫" if int(uid) in blocked_users else "🟢"
        role = "👑" if int(uid) in admin_ids else "👤"
        lines.append(f"{state} {role} <code>{uid}</code> — 💰 {float(balance):g} — 👥 {refs}")
    bot.send_message(message.chat.id, "\n".join(lines), parse_mode="HTML", protect_content=True)


def process_admin_user_search(message):
    if int(_message_actor_id(message)) not in admin_ids:
        return
    raw = (message.text or "").strip().lstrip("@").strip()
    if not raw.isdigit():
        bot.send_message(message.chat.id, "❌ আপাতত numeric Telegram User ID দিন। আবার চেষ্টা করুন অথবা /cancel দিন।", protect_content=True)
        return
    bot.send_message(message.chat.id, _user_card(int(raw)), parse_mode="HTML", protect_content=True)


def _prompt_user_id(message, next_handler, title):
    set_workflow_session(int(_message_actor_id(message)), int(message.chat.id), next_handler)
    bot.send_message(message.chat.id, f"📝 <b>{title}</b>\n\nশুধু User ID দিন:\n❌ বাতিল: <code>/cancel</code>", parse_mode="HTML", protect_content=True)


def process_add_balance_user(message):
    if int(_message_actor_id(message)) not in admin_ids: return
    try:
        uid = int((message.text or "").strip())
        if uid <= 0: raise ValueError
        bot.send_message(message.chat.id, f"💰 User <code>{uid}</code> কে কত BDT add করবেন?", parse_mode="HTML", protect_content=True)
        bot.register_next_step_handler(message, process_add_balance_amount, uid)
    except ValueError:
        bot.send_message(message.chat.id, "❌ Valid numeric User ID দিন।", protect_content=True)


def process_add_balance_amount(message, target_user):
    if int(_message_actor_id(message)) not in admin_ids: return
    try:
        amount = float((message.text or "").strip())
        if amount <= 0 or amount > 100000000: raise ValueError
    except ValueError:
        bot.send_message(message.chat.id, "❌ Valid positive amount দিন।", protect_content=True)
        bot.register_next_step_handler(message, process_add_balance_amount, target_user)
        return
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        conn.execute("INSERT OR IGNORE INTO user_account(user_id,balance,total_referrals) VALUES(?,0,0)", (int(target_user),))
        conn.execute("UPDATE user_account SET balance=balance+? WHERE user_id=?", (amount, int(target_user)))
        conn.commit(); conn.close()
    log_admin_activity(_message_actor_id(message), "Added balance", f"user={target_user}, amount={amount:g}")
    send_activity_log(f"💰 <b>ADMIN BALANCE ADD</b>\n👤 User: <code>{target_user}</code>\n💵 Amount: <code>{amount:g} BDT</code>\n🛡 Admin: <code>{_message_actor_id(message)}</code>")
    bot.send_message(message.chat.id, f"✅ <b>Balance Added</b>\n\n👤 User: <code>{target_user}</code>\n💰 Added: <b>{amount:g} BDT</b>\n\n{_user_card(target_user)}", parse_mode="HTML", protect_content=True)


def process_deduct_balance_user(message):
    if int(_message_actor_id(message)) not in admin_ids: return
    try:
        uid = int((message.text or "").strip())
        if uid <= 0: raise ValueError
        bot.send_message(message.chat.id, f"➖ User <code>{uid}</code> থেকে কত BDT deduct করবেন?", parse_mode="HTML", protect_content=True)
        bot.register_next_step_handler(message, process_deduct_balance_amount, uid)
    except ValueError:
        bot.send_message(message.chat.id, "❌ Valid numeric User ID দিন।", protect_content=True)


def process_deduct_balance_amount(message, target_user):
    if int(_message_actor_id(message)) not in admin_ids: return
    try:
        amount = float((message.text or "").strip())
        if amount <= 0 or amount > 100000000: raise ValueError
    except ValueError:
        bot.send_message(message.chat.id, "❌ Valid positive amount দিন।", protect_content=True)
        bot.register_next_step_handler(message, process_deduct_balance_amount, target_user)
        return
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        row = conn.execute("SELECT balance FROM user_account WHERE user_id=?", (int(target_user),)).fetchone()
        if not row:
            conn.close(); bot.send_message(message.chat.id, "❌ User not found.", protect_content=True); return
        balance = float(row[0] or 0)
        if amount > balance:
            conn.close(); bot.send_message(message.chat.id, f"❌ Balance মাত্র <b>{balance:g} BDT</b>। এর বেশি deduct করা যাবে না.", parse_mode="HTML", protect_content=True); return
        conn.execute("UPDATE user_account SET balance=balance-? WHERE user_id=?", (amount, int(target_user)))
        conn.commit(); conn.close()
    log_admin_activity(_message_actor_id(message), "Deducted balance", f"user={target_user}, amount={amount:g}")
    bot.send_message(message.chat.id, f"✅ <b>Balance Deducted</b>\n\n👤 User: <code>{target_user}</code>\n➖ Deducted: <b>{amount:g} BDT</b>\n\n{_user_card(target_user)}", parse_mode="HTML", protect_content=True)


def process_admin_ban(message):
    if int(_message_actor_id(message)) not in admin_ids: return
    try: uid = int((message.text or "").strip())
    except ValueError: bot.send_message(message.chat.id, "❌ Valid User ID দিন।", protect_content=True); return
    if uid in admin_ids or uid == OWNER_ID:
        bot.send_message(message.chat.id, "❌ Admin/Owner-কে ban করা যাবে না।", protect_content=True); return
    blocked_users.add(uid)
    with DB_LOCK:
        conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False); conn.execute("INSERT OR IGNORE INTO blocked_users(user_id) VALUES(?)",(uid,)); conn.commit(); conn.close()
    log_admin_activity(_message_actor_id(message),"Banned user",f"user={uid}")
    bot.send_message(message.chat.id,f"🚫 User <code>{uid}</code> banned successfully.",parse_mode="HTML",protect_content=True)


def process_admin_unban(message):
    if int(_message_actor_id(message)) not in admin_ids: return
    try: uid = int((message.text or "").strip())
    except ValueError: bot.send_message(message.chat.id, "❌ Valid User ID দিন।", protect_content=True); return
    blocked_users.discard(uid)
    with DB_LOCK:
        conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False); conn.execute("DELETE FROM blocked_users WHERE user_id=?",(uid,)); conn.commit(); conn.close()
    log_admin_activity(_message_actor_id(message),"Unbanned user",f"user={uid}")
    bot.send_message(message.chat.id,f"♻️ User <code>{uid}</code> unbanned successfully.",parse_mode="HTML",protect_content=True)


def process_make_admin(message):
    if int(_message_actor_id(message)) not in admin_ids: return
    if int(_message_actor_id(message)) not in {int(OWNER_ID), int(globals().get("SECOND_ADMIN_ID",0) or 0)}:
        bot.send_message(message.chat.id,"❌ Permission denied.",protect_content=True); return
    try: uid=int((message.text or "").strip())
    except ValueError: bot.send_message(message.chat.id,"❌ Valid User ID দিন।",protect_content=True); return
    admin_ids.add(uid)
    with DB_LOCK:
        conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False); conn.execute("INSERT OR REPLACE INTO admins(user_id,added_by) VALUES(?,?)",(uid,int(_message_actor_id(message)))); conn.commit(); conn.close()
    log_admin_activity(_message_actor_id(message),"Created admin",f"user={uid}")
    bot.send_message(message.chat.id,f"👑 User <code>{uid}</code> is now an admin.",parse_mode="HTML",protect_content=True)


def process_remove_admin_managed(message):
    if int(_message_actor_id(message)) not in {int(OWNER_ID), int(globals().get("SECOND_ADMIN_ID",0) or 0)}:
        bot.send_message(message.chat.id,"❌ Permission denied.",protect_content=True); return
    try: uid=int((message.text or "").strip())
    except ValueError: bot.send_message(message.chat.id,"❌ Valid User ID দিন।",protect_content=True); return
    if uid in {int(OWNER_ID), int(globals().get("SECOND_ADMIN_ID",0) or 0)}:
        bot.send_message(message.chat.id,"❌ Core admin remove করা যাবে না।",protect_content=True); return
    admin_ids.discard(uid)
    with DB_LOCK:
        conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False); conn.execute("DELETE FROM admins WHERE user_id=?",(uid,)); conn.commit(); conn.close()
    log_admin_activity(_message_actor_id(message),"Removed admin",f"user={uid}")
    bot.send_message(message.chat.id,f"❌ User <code>{uid}</code> admin থেকে remove হয়েছে.",parse_mode="HTML",protect_content=True)


def send_user_statistics(message):
    if int(_message_actor_id(message)) not in admin_ids: return
    with DB_LOCK:
        conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False)
        total=conn.execute("SELECT COUNT(*) FROM user_account").fetchone()[0]
        balance=conn.execute("SELECT COALESCE(SUM(balance),0) FROM user_account").fetchone()[0]
        conn.close()
    files=sum(len(v) for v in user_files.values())
    running=sum(1 for info in bot_scripts.values() if info.get("process"))
    bot.send_message(message.chat.id,
        "📊 <b>User Statistics</b>\n\n"
        f"👥 Total Users: <b>{total}</b>\n"
        f"👑 Admins: <b>{len(admin_ids)}</b>\n"
        f"🚫 Banned: <b>{len(blocked_users)}</b>\n"
        f"💰 Total User Balance: <b>{float(balance):g} BDT</b>\n"
        f"📁 Hosted Files: <b>{files}</b>\n"
        f"🚀 Running Bots: <b>{running}</b>", parse_mode="HTML", protect_content=True)

# --- UI Methods ---
def create_reply_keyboard_main_menu(user_id):
    # Admins stay on the exact same User Board as ordinary users.
    # The only extra control visible to an admin is the Admin Panel button.
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    layout_to_use = [list(row) for row in COMMAND_BUTTONS_LAYOUT_USER_SPEC]
    if int(user_id) in admin_ids:
        layout_to_use.insert(2, ["💰 𝗔𝗱𝗱 𝗠𝗼𝗻𝗲𝘆", "🛡️ 𝗔𝗱𝗺𝗶𝗻 𝗣𝗮𝗻𝗲𝗹"])
        # Remove the original Add Money row so it is not duplicated.
        layout_to_use = [row for i, row in enumerate(layout_to_use) if not (i != 2 and "💰 𝗔𝗱𝗱 𝗠𝗼𝗻𝗲𝘆" in row)]
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
        make_inline_button("📂 𝗔𝗹𝗹 𝗕𝗼𝘁 𝗙𝗶𝗹𝗲𝘀", callback_data="all_bot_files", style="primary"),
        make_inline_button("🎁 𝗚𝗶𝗳𝘁 𝗖𝗼𝗱𝗲𝘀", callback_data="gift_codes", style="success")
    )
    markup.add(
        make_inline_button("👥 𝗨𝘀𝗲𝗿 𝗠𝗮𝗻𝗮𝗴𝗲𝗺𝗲𝗻𝘁", callback_data="user_management", style="primary"),
        make_inline_button("⚙️ 𝗕𝗼𝘁 𝗦𝗲𝘁𝘁𝗶𝗻𝗴𝘀", callback_data="bot_settings", style="primary")
    )
    markup.add(
        make_inline_button("🧾 𝗔𝗱𝗺𝗶𝗻 𝗔𝗰𝘁𝗶𝘃𝗶𝘁𝘆 𝗟𝗼𝗴", callback_data="admin_activity", style="primary"),
        make_inline_button("📋 𝗟𝗼𝗴 / 𝗘𝗿𝗿𝗼𝗿", callback_data="admin_logs", style="primary")
    )
    markup.add(
        make_inline_button("🔗 𝗜𝗻𝗳𝗼 𝗟𝗶𝗻𝗸𝘀", callback_data="info_links", style="primary"),
        make_inline_button("🎥 𝗦𝗲𝘁 𝗧𝘂𝘁𝗼𝗿𝗶𝗮𝗹", callback_data="set_tutorial", style="primary")
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


# =====================================================================
# ⚙️ ADMIN — BOT SETTINGS
# =====================================================================
def send_bot_settings(message):
    if int(_message_actor_id(message)) not in admin_ids:
        return
    maintenance = get_setting("maintenance", "0") == "1"
    activity = get_setting("notify_activity", "1") == "1"
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        make_inline_button(f"{'🔴' if maintenance else '🟢'} Maintenance {'ON' if maintenance else 'OFF'}", callback_data="toggle_maintenance", style="danger" if maintenance else "success"),
        make_inline_button(f"{'🟢' if activity else '🔴'} Notifications {'ON' if activity else 'OFF'}", callback_data="toggle_notifications", style="success" if activity else "danger"),
    )
    markup.add(
        make_inline_button("📝 Welcome Message", callback_data="set_welcome_text", style="primary"),
        make_inline_button("🖼️ Welcome Image", callback_data="set_welcome_image", style="primary"),
    )
    markup.add(make_inline_button("🗑️ Clear Welcome Image", callback_data="clear_welcome_image", style="danger"))
    markup.add(make_inline_button("📢 Force Join Channels", callback_data="force_join_settings", style="primary"))
    markup.add(make_inline_button("⬅️ Back", callback_data="admin_back", style="danger"))
    bot.send_message(
        message.chat.id,
        "⚙️ <b>Bot Settings</b>\n\n"
        f"🔒 Maintenance: <b>{'ON' if maintenance else 'OFF'}</b>\n"
        f"🔔 Admin Notifications: <b>{'ON' if activity else 'OFF'}</b>\n\n"
        "Welcome text/image এবং Force Join এখান থেকে নিয়ন্ত্রণ করুন।",
        parse_mode="HTML", reply_markup=markup, protect_content=True,
    )


def process_set_welcome_text(message):
    if int(_message_actor_id(message)) not in admin_ids: return
    text = (message.text or "").strip()
    if not text or len(text) > 3500:
        bot.send_message(message.chat.id, "❌ Welcome Message 1–3500 characters-এর মধ্যে দিন। আবার পাঠান অথবা /cancel দিন।", protect_content=True)
        bot.register_next_step_handler(message, process_set_welcome_text)
        return
    set_setting("welcome_text", text)
    log_admin_activity(_message_actor_id(message), "Updated welcome message")
    bot.send_message(message.chat.id, "✅ Welcome Message updated successfully.", protect_content=True)


def process_set_welcome_image(message):
    if int(_message_actor_id(message)) not in admin_ids: return
    if not getattr(message, "photo", None):
        bot.send_message(message.chat.id, "❌ একটি photo পাঠান। অথবা /cancel দিন।", protect_content=True)
        bot.register_next_step_handler(message, process_set_welcome_image)
        return
    file_id = message.photo[-1].file_id
    set_setting("welcome_image_file_id", file_id)
    log_admin_activity(_message_actor_id(message), "Updated welcome image")
    bot.send_message(message.chat.id, "✅ Welcome Image saved successfully.", protect_content=True)


def send_admin_activity(message):
    if int(_message_actor_id(message)) not in admin_ids: return
    rows = get_admin_activity(30)
    if not rows:
        bot.send_message(message.chat.id, "🧾 কোনো admin activity log নেই।", protect_content=True); return
    lines=["🧾 <b>Admin Activity Log</b>\n"]
    for aid,action,details,created in rows:
        lines.append(f"🕒 <code>{created}</code> — 👑 <code>{aid}</code>\n<b>{action}</b> {details}")
    bot.send_message(message.chat.id,"\n\n".join(lines),parse_mode="HTML",protect_content=True)


def send_admin_logs_menu(message):
    if int(_message_actor_id(message)) not in admin_ids: return
    markup=types.InlineKeyboardMarkup(row_width=1)
    files=[]
    for uid,items in user_files.items():
        for fname,_ in items:
            log_path=os.path.join(get_user_folder(uid),f"{os.path.splitext(fname)[0]}.log")
            if os.path.isfile(log_path):
                files.append((uid,fname))
    for uid,fname in files[-50:]:
        markup.add(make_inline_button(f"📋 {uid} / {fname}",callback_data=f"viewlog_{uid}_{fname}",style="primary"))
    markup.add(make_inline_button("⬅️ Back",callback_data="admin_back",style="danger"))
    bot.send_message(message.chat.id, "📋 <b>LOG / ERROR</b>\n\nশুধু Admin এখান থেকে log/error দেখতে ও copy করতে পারবে।",parse_mode="HTML",reply_markup=markup,protect_content=True)

# --- Start & Menus ---
@bot.message_handler(commands=["start"])
def start_cmd(message):
    try:
        user_id = _message_actor_id(message)
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

        default_welcome = (
            f"✨ **𝗪𝗲𝗹𝗰𝗼𝗺𝗲, {user_name}!** ✨\n\n"
            f"🆔 **𝗬𝗼𝘂𝗿 𝗜𝗗:** `{user_id}`\n"
            f"🔰 **𝗦𝘁𝗮𝘁𝘂𝘀:** `{vip_status}`\n"
            f"🔰 **𝗛𝗼𝘀𝘁𝗶𝗻𝗴 𝗟𝗶𝗺𝗶𝘁:** `{get_user_file_count(user_id)}` / `{limit}`\n\n"
            f"🔐 *Secure hosting is active — every upload needs admin approval.*\n"
            f"💡 *Python (.py) & JS (.js) hosting supported.*\n"
            f"👇 *Choose an option below to continue:* "
        )
        custom_welcome = get_setting("welcome_text", "").strip()
        welcome_msg = custom_welcome or default_welcome
        welcome_image = get_setting("welcome_image_file_id", "").strip()
        if welcome_image:
            try:
                bot.send_photo(chat_id, welcome_image, caption=welcome_msg, reply_markup=create_reply_keyboard_main_menu(user_id), parse_mode="Markdown", protect_content=True)
            except Exception:
                bot.send_message(chat_id, welcome_msg, reply_markup=create_reply_keyboard_main_menu(user_id), parse_mode="Markdown", protect_content=True)
        else:
            bot.send_message(chat_id, welcome_msg, reply_markup=create_reply_keyboard_main_menu(user_id), parse_mode="Markdown", protect_content=True)

        # Always show plan name, remaining time, and hosting allowance below welcome.
        sub = get_subscription_status(user_id)
        if sub.get("active"):
            plan_limit = "আনলিমিটেড" if int(sub.get("limit", 1)) >= 100000 else str(sub.get("limit", 1))
            plan_text = (
                "💎 <b>আপনার হোস্টিং প্ল্যান</b>\n"
                f"📦 প্ল্যান: <b>{html.escape(sub['name'])}</b>\n"
                f"🤖 ফাইল/বট সীমা: <b>{plan_limit}</b>\n"
                f"⏳ বাকি মেয়াদ: <b>{html.escape(sub['remaining'])}</b>\n"
                f"📅 শেষ হবে: <code>{sub['end'].strftime('%Y-%m-%d %H:%M')}</code>"
            )
        else:
            plan_text = "🆓 <b>বর্তমান প্ল্যান:</b> Free / কোনো সক্রিয় প্ল্যান নেই\n💎 প্ল্যান কিনতে VIP Plans এবং ব্যালেন্স যোগ করতে Account → Add Money ব্যবহার করুন।"
        bot.send_message(chat_id, plan_text, parse_mode="HTML", protect_content=True)
    except Exception as e:
        logger.error(f"Error in start command: {e}")

def _logic_upload_file(message):
    user_id = _message_actor_id(message)
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
    user_id = _message_actor_id(message)
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

        bot.send_message(message.chat.id, "🌟 **আমাদের ভিআইপি (VIP) প্ল্যানসমূহ:**\nআপনার প্রয়োজন অনুযায়ী প্ল্যান বেছে নিন। একসঙ্গে কতগুলো বট চলবে তা সার্ভারের RAM/CPU-র ওপর নির্ভর করে।", parse_mode="Markdown")
        
        for plan in plans:
            plan_id, name, desc, limit, days, price = plan
            plan_msg = (
                f"**{name}**\n"
                f"📝 **বিস্তারিত:** {desc}\n"
                f"🤖 **বট/ফাইল লিমিট:** `{'আনলিমিটেড' if int(limit or 1) >= 100000 else str(limit) + ' টি'}`\n"
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
    start_deposit_session(_message_actor_id(message))
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
    user_id = int(_message_actor_id(message))
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
    user_id = int(_message_actor_id(message))
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
    user_id = int(_message_actor_id(message))
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
    user_id = _message_actor_id(message)
    balance, refs = get_user_account(user_id)
    try:
        bot_username = bot.get_me().username
    except:
        bot_username = "your_bot_username"
        
    ref_link = f"https://t.me/{bot_username}?start={user_id}"
    sub = get_subscription_status(user_id)
    if sub.get("active"):
        plan_limit = "আনলিমিটেড" if int(sub.get("limit", 1)) >= 100000 else str(sub.get("limit", 1))
        plan_status = f"💎 **Plan:** `{sub['name']}`\n🤖 **Bot/File Limit:** `{plan_limit}`\n⏳ **Remaining:** `{sub['remaining']}`\n📅 **Expires:** `{sub['end'].strftime('%Y-%m-%d %H:%M')}`\n\n"
    else:
        plan_status = "🆓 **Plan:** `Free / Expired`\n\n"
    
    msg = (
        f"👤 **??𝘆 𝗔𝗰𝗰𝗼𝘂𝗻𝘁**\n\n"
        f"{plan_status}"
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
    if int(_message_actor_id(message)) != int(globals().get("SECOND_ADMIN_ID", 0) or 0):
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
    user_id = _message_actor_id(message)
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

# Resolve the real actor for normal messages and inline-button callbacks.
def _message_actor_id(message):
    """Return the human user ID; callback.message.from_user is the bot, not the clicker."""
    callback_actor = getattr(message, "_callback_actor_id", None)
    if callback_actor is not None:
        try:
            return int(callback_actor)
        except (TypeError, ValueError):
            pass
    try:
        return int(message.from_user.id)
    except Exception:
        return 0

# --- Callback Routing ---
_ANSWERED_CALLBACKS = set()
_ANSWERED_CALLBACKS_LOCK = threading.Lock()

def answer_callback(call, *args, **kwargs):
    """Answer a callback exactly once and remember it for the final safety fallback."""
    call_id = getattr(call, "id", None)
    if not call_id:
        return False
    with _ANSWERED_CALLBACKS_LOCK:
        if call_id in _ANSWERED_CALLBACKS:
            return True
    try:
        bot.answer_callback_query(call_id, *args, **kwargs)
        with _ANSWERED_CALLBACKS_LOCK:
            _ANSWERED_CALLBACKS.add(call_id)
            if len(_ANSWERED_CALLBACKS) > 5000:
                for old_id in list(_ANSWERED_CALLBACKS)[:2500]:
                    _ANSWERED_CALLBACKS.discard(old_id)
        return True
    except Exception as exc:
        # Do not mark it answered if Telegram rejected/failed the request.
        # The handler's final safety-net can retry the acknowledgement.
        logger.warning("Callback answer failed: %s", exc)
        return False

def _callback_message(call):
    """Message-like context carrying the actual clicking user for admin menu helpers.

    Telegram's call.message.from_user is the bot account, not the admin who clicked.
    Passing call.message to helpers that check message.from_user therefore made them
    return silently. This proxy preserves the chat/message fields and sets from_user
    to the real callback sender.
    """
    original = call.message
    return SimpleNamespace(
        chat=original.chat,
        from_user=call.from_user,
        message_id=getattr(original, "message_id", None),
        text=getattr(original, "text", None),
        caption=getattr(original, "caption", None),
        content_type=getattr(original, "content_type", None),
        date=getattr(original, "date", None),
        message_thread_id=getattr(original, "message_thread_id", None),
    )


@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    # IMPORTANT: Telegram shows a loading spinner until answer_callback_query() is sent.
    # Answer immediately, then perform the actual action. The helper prevents duplicate answers.
    answer_callback(call)
    try:
        user_id = int(call.from_user.id)
        # Functions receive call.message for chat/message context, but its from_user is the bot.
        # Store the actual clicking user so existing admin guards work correctly.
        try:
            setattr(call.message, "_callback_actor_id", user_id)
        except Exception:
            pass
        if user_id in blocked_users:
            return

        global bot_locked
        data = str(call.data or "")

        # Only file-owner callbacks use the numeric owner-id security rule.
        # Do NOT treat del_ch_*, delplan_* or other admin delete callbacks as file callbacks.
        owner_match = re.match(r"^(?:file|start|verify|stop|instmod|viewlog|extend)_(-?\d+)(?:_|$)", data)
        if owner_match:
            owner_id = int(owner_match.group(1))
            if user_id != owner_id and user_id not in admin_ids:
                answer_callback(call, "❌ নিরাপত্তা সতর্কতা: এটি আপনার ফাইল নয়!", show_alert=True)
                return

        if data.startswith("approve_file_") and user_id in APPROVAL_ADMIN_IDS:
            request_id = data[len("approve_file_"):]
            result = finalize_approved_upload(request_id, user_id)
            if not result:
                answer_callback(call, "Already processed or request not found.", show_alert=True)
                return
            if result[0] in ("missing", "error"):
                answer_callback(call, "Approval failed.", show_alert=True)
                return

            _, target_uid, fname, file_path, risk_note = result
            answer_callback(call, f"{get_random_button_prefix('success')} Approved", show_alert=True)
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
                answer_callback(call, "Already processed or request not found.", show_alert=True)
                return

            _, target_uid, fname = result
            answer_callback(call, f"{get_random_button_prefix('danger')} Rejected", show_alert=True)
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
            answer_callback(call, "📋 Number sent — tap/hold it to copy.")
            bot.send_message(call.message.chat.id, f"📱 <code>{number}</code>", parse_mode="HTML")
            return

        if data == "show_vip_plans":
            answer_callback(call)
            _logic_vip_plans(call.message)
            return

        if data == "db_download" and int(user_id) == int(globals().get("SECOND_ADMIN_ID", 0) or 0):
            try:
                with DB_LOCK:
                    if not os.path.exists(DATABASE_PATH):
                        answer_callback(call, "Database not found.", show_alert=True)
                        return
                    with open(DATABASE_PATH, "rb") as dbf:
                        bot.send_document(
                            call.message.chat.id,
                            dbf,
                            caption="🗄️ **Database Backup**\n\nComplete bot database backup.",
                            parse_mode="Markdown"
                        )
                answer_callback(call, "Database sent.", show_alert=True)
            except Exception as e:
                logger.error("DB download failed: %s", e, exc_info=True)
                answer_callback(call, "Database download failed.", show_alert=True)
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
                answer_callback(call, "Plan not found!", show_alert=True)
                return
                
            plan_name, duration_days, price_text = plan_row
            
            try:
                price_num = int(''.join(filter(str.isdigit, str(price_text))))
            except ValueError:
                answer_callback(call, "Error in plan price configuration.", show_alert=True)
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
                    
                answer_callback(call, "✅ Plan Purchased Successfully!", show_alert=True)
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

                purchased_status = get_subscription_status(user_id)
                purchased_limit = "আনলিমিটেড" if int(purchased_status.get("limit", 1)) >= 100000 else str(purchased_status.get("limit", 1))
                bot.send_message(
                    call.message.chat.id,
                    f"🎉 **অভিনন্দন!**\nআপনার **{plan_name}** প্ল্যানটি কেনা সফল হয়েছে।\n"
                    f"🤖 Bot/File limit: `{purchased_limit}`\n"
                    f"⏳ বাকি মেয়াদ: `{purchased_status.get('remaining', str(duration_days) + ' দিন')}`\n"
                    f"📅 শেষ হবে: `{purchased_status['end'].strftime('%Y-%m-%d %H:%M') if purchased_status.get('end') else 'N/A'}`\n"
                    f"💰 ব্যালেন্স থেকে `{price_num} BDT` কাটা হয়েছে।\n\n"
                    "🚀 বট ফাইল আপলোড করার পর Admin Approval হলে সেটি Auto-Run হবে।",
                    parse_mode="Markdown",
                )
            else:
                answer_callback(call, "❌ অপর্যাপ্ত ব্যালেন্স!", show_alert=True)
                bot.send_message(call.message.chat.id, f"❌ **অপর্যাপ্ত ব্যালেন্স!**\nপ্ল্যানটির দাম `{price_num} BDT`, কিন্তু আপনার একাউন্টে আছে `{balance} BDT`। দয়া করে 👤 Account থেকে ডিপোজিট করুন।", parse_mode="Markdown")

        elif data == "deposit_init":
            start_deposit_session(user_id)
            answer_callback(call)
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
            answer_callback(call, "Deposit cancelled.")
            bot.send_message(call.message.chat.id, "❌ Deposit flow cancelled। আবার শুরু করতে **💰 Add Money** চাপুন।", parse_mode="Markdown")

        elif data.startswith("dep_method_"):
            method = data[len("dep_method_"):].lower()
            if method not in ("bkash", "nagad"):
                answer_callback(call, "Invalid payment method.", show_alert=True)
                return
            session = get_deposit_session(user_id)
            if not session or session.get("step") not in ("method", "trx", "sender_phone"):
                start_deposit_session(user_id)
                answer_callback(call, "প্রথমে amount দিন।", show_alert=True)
                bot.send_message(call.message.chat.id, "💵 Amount লিখুন (10–50,000 BDT):")
                return
            if not session.get("amount"):
                answer_callback(call, "প্রথমে amount দিন।", show_alert=True)
                return
            answer_callback(call)
            _show_payment_number(call.message.chat.id, user_id, method)

        elif data.startswith("dep_app_") and user_id in admin_ids:
            deposit_id = data[len("dep_app_"):]
            row = claim_deposit(deposit_id, user_id, "approved")
            if not row:
                answer_callback(call, "Already processed or request not found.", show_alert=True)
                return
            _, target_uid, amount, method, payment_number, trx_id, sender_phone, _ = row
            answer_callback(call, "✅ Approved — balance added.", show_alert=True)
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
                answer_callback(call, "Already processed or request not found.", show_alert=True)
                return
            _, target_uid, amount, method, payment_number, trx_id, sender_phone, _ = row
            answer_callback(call, "❌ Deposit rejected.", show_alert=True)
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
                answer_callback(call, "No pending deposits.", show_alert=True)
                return
            answer_callback(call)
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
            answer_callback(call, "💎 Free limit is 12 hours. Please buy a plan to continue.", show_alert=True)
            _logic_vip_plans(call.message)

        elif data.startswith("file_"):
            _, owner_id, fname = data.split("_", 2)
            owner_id = int(owner_id)
            if int(user_id) != owner_id and user_id not in admin_ids and int(user_id) != int(OWNER_ID):
                answer_callback(call, "❌ এটি আপনার ফাইল নয়!", show_alert=True)
                return
            is_running = is_bot_running(owner_id, fname)
            markup = types.InlineKeyboardMarkup(row_width=2)
            if is_running:
                markup.add(make_inline_button("🛑 Stop", callback_data=f"stop_{owner_id}_{fname}"),
                           make_inline_button("🔄 Restart", callback_data=f"restart_{owner_id}_{fname}"))
            else:
                markup.add(make_inline_button("▶️ Start", callback_data=f"start_{owner_id}_{fname}"),
                           make_inline_button("🔄 Restart", callback_data=f"restart_{owner_id}_{fname}"))
            markup.add(make_inline_button("🗑️ Delete", callback_data=f"del_{owner_id}_{fname}"),
                       make_inline_button("📋 Logs", callback_data=f"userlog_{owner_id}_{fname}"))
            markup.add(make_inline_button("⬅️ Back to Files", callback_data=f"backfiles_{owner_id}"))
            bot.send_message(call.message.chat.id, f"📄 <b>File:</b> <code>{html.escape(fname)}</code>\n🚦 <b>Status:</b> {'🟢 Running' if is_running else '🔴 Stopped'}", reply_markup=markup, parse_mode="HTML", protect_content=True)

        elif data.startswith("backfiles_"):
            owner_id = int(data.split("_", 1)[1])
            if int(user_id) != owner_id and user_id not in admin_ids and int(user_id) != int(OWNER_ID):
                answer_callback(call, "❌ Access denied", show_alert=True)
                return
            answer_callback(call)
            _logic_check_files(_callback_message(call))

        elif data.startswith("restart_"):
            _, owner_id, fname = data.split("_", 2)
            owner_id = int(owner_id)
            if int(user_id) != owner_id and user_id not in admin_ids and int(user_id) != int(OWNER_ID):
                answer_callback(call, "❌ Access denied", show_alert=True)
                return
            force_kill_user_bot(owner_id, fname)
            answer_callback(call, "Restarting...")
            do_start_bot(owner_id, fname, call.message, call.id)

        elif data.startswith("userlog_"):
            _, owner_id, fname = data.split("_", 2)
            owner_id = int(owner_id)
            if int(user_id) != owner_id and user_id not in admin_ids and int(user_id) != int(OWNER_ID):
                answer_callback(call, "❌ Access denied", show_alert=True)
                return
            log_fpath = os.path.join(get_user_folder(owner_id), f"{os.path.splitext(fname)[0]}.log")
            if os.path.exists(log_fpath):
                with open(log_fpath, "r", encoding="utf-8", errors="replace") as f:
                    logs = f.read()[-3500:]
                if not logs.strip(): logs = "No logs yet."
            else:
                logs = "Log file not created yet. Start the bot first."
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(make_inline_button("⬅️ Back to Bot", callback_data=f"file_{owner_id}_{fname}"))
            bot.send_message(call.message.chat.id, f"📋 <b>Logs: {html.escape(fname)}</b>\n<pre>{html.escape(logs)}</pre>", parse_mode="HTML", reply_markup=markup, protect_content=True)

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
                answer_callback(call, "❌ আপনি এখনো সব চ্যানেলে জয়েন করেননি!", show_alert=True)
            else:
                try: bot.delete_message(call.message.chat.id, call.message.message_id)
                except: pass
                do_start_bot(owner_id, fname, call.message, call.id)

        elif data.startswith("stop_"):
            _, owner_id, fname = data.split("_", 2)
            if int(user_id) != int(owner_id) and user_id not in admin_ids and int(user_id) != int(OWNER_ID):
                answer_callback(call, "❌ Access denied", show_alert=True)
                return
            force_kill_user_bot(owner_id, fname)
            answer_callback(call, "Stopped!")
            bot.send_message(call.message.chat.id, f"🛑 Script `{fname}` stopped successfully.", parse_mode="Markdown")

        elif data.startswith("del_"):
            _, owner_id, fname = data.split("_", 2)
            if int(user_id) != int(owner_id) and user_id not in admin_ids and int(user_id) != int(OWNER_ID):
                answer_callback(call, "❌ Access denied", show_alert=True)
                return
            force_kill_user_bot(owner_id, fname)
                
            remove_user_file_db(int(owner_id), fname)
            ufolder = get_user_folder(int(owner_id))
            fpath = os.path.join(ufolder, fname)
            log_fpath = os.path.join(ufolder, f"{os.path.splitext(fname)[0]}.log")
            if os.path.exists(fpath): os.remove(fpath)
            if os.path.exists(log_fpath): os.remove(log_fpath)
            pycache_dir = os.path.join(ufolder, "__pycache__")
            if os.path.exists(pycache_dir): shutil.rmtree(pycache_dir, ignore_errors=True)
                
            answer_callback(call, "Deleted!")
            bot.send_message(call.message.chat.id, f"🗑️ File `{fname}` completely deleted.", parse_mode="Markdown")

        elif data.startswith("instmod_"):
            _, owner_id, fname = data.split("_", 2)
            if int(user_id) != int(owner_id) and user_id not in admin_ids:
                answer_callback(call, "❌ এটি আপনার ফাইল নয়!", show_alert=True)
                return
            install_missing_dependency(int(owner_id), fname, call.message.chat.id, call.id)
            return

        elif data.startswith("viewlog_"):
            # Logs/errors are intentionally copyable only for admins.
            if user_id not in admin_ids:
                answer_callback(call,"🔐 Logs/Error copy is Admin-only.",show_alert=True); return
            _, owner_id, fname = data.split("_", 2)
            log_fpath = os.path.join(get_user_folder(int(owner_id)), f"{os.path.splitext(fname)[0]}.log")
            if os.path.exists(log_fpath):
                with open(log_fpath, "r", encoding="utf-8", errors="replace") as f: logs = f.read()[-3500:]
                if not logs.strip(): logs = "No logs"
                copy_btn=make_copy_text_button(logs)
                markup=types.InlineKeyboardMarkup(row_width=1)
                if copy_btn is not None: markup.add(copy_btn)
                markup.add(make_inline_button("⬅️ Back",callback_data="admin_logs",style="danger"))
                safe_logs=html.escape(logs)
                bot.send_message(call.message.chat.id, f"📋 <b>LOG / ERROR — {html.escape(fname)}</b>\n\n<pre>{safe_logs}</pre>", parse_mode="HTML", reply_markup=markup, protect_content=True)
            else:
                answer_callback(call, "No logs!", show_alert=True)

        elif data == "toggle_bkash" and user_id in admin_ids:
            new_value = "0" if _payment_enabled("bkash") else "1"
            set_setting("bkash_enabled", new_value)
            state = "ON" if new_value == "1" else "OFF"
            answer_callback(call, f"bKash is now {state}", show_alert=True)
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
            answer_callback(call, f"Nagad is now {state}", show_alert=True)
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
                answer_callback(call, "No plans found!", show_alert=True)
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
            answer_callback(call, "Plan deleted!", show_alert=True)
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
                answer_callback(call, "Plan assigned!", show_alert=True)
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

        elif data == "admin_back" and user_id in admin_ids:
            answer_callback(call)
            bot.send_message(call.message.chat.id,"🛡️ <b>Admin Control Center</b>",parse_mode="HTML",reply_markup=create_admin_panel_inline(user_id))

        elif data == "user_management" and user_id in admin_ids:
            send_user_management(_callback_message(call))

        elif data == "user_list" and user_id in admin_ids:
            send_user_list(_callback_message(call))

        elif data == "user_search" and user_id in admin_ids:
            bot.send_message(call.message.chat.id,"🔎 <b>Search User</b>\n\nUser ID দিন:\n❌ <code>/cancel</code>",parse_mode="HTML",protect_content=True)
            bot.register_next_step_handler(call.message,process_admin_user_search)

        elif data == "user_add_balance" and user_id in admin_ids:
            bot.send_message(call.message.chat.id,"💰 <b>Add Balance</b>\n\nTarget User ID দিন:\n❌ <code>/cancel</code>",parse_mode="HTML",protect_content=True)
            bot.register_next_step_handler(call.message,process_add_balance_user)

        elif data == "user_deduct_balance" and user_id in admin_ids:
            bot.send_message(call.message.chat.id,"➖ <b>Deduct Balance</b>\n\nTarget User ID দিন:\n❌ <code>/cancel</code>",parse_mode="HTML",protect_content=True)
            bot.register_next_step_handler(call.message,process_deduct_balance_user)

        elif data == "user_ban" and user_id in admin_ids:
            bot.send_message(call.message.chat.id,"🚫 <b>Ban User</b>\n\nTarget User ID দিন:\n❌ <code>/cancel</code>",parse_mode="HTML",protect_content=True)
            bot.register_next_step_handler(call.message,process_admin_ban)

        elif data == "user_unban" and user_id in admin_ids:
            bot.send_message(call.message.chat.id,"♻️ <b>Unban User</b>\n\nTarget User ID দিন:\n❌ <code>/cancel</code>",parse_mode="HTML",protect_content=True)
            bot.register_next_step_handler(call.message,process_admin_unban)

        elif data == "user_make_admin" and user_id in {int(OWNER_ID),int(globals().get("SECOND_ADMIN_ID",0) or 0)}:
            bot.send_message(call.message.chat.id,"👑 <b>Make Admin</b>\n\nTarget User ID দিন:\n❌ <code>/cancel</code>",parse_mode="HTML",protect_content=True)
            bot.register_next_step_handler(call.message,process_make_admin)

        elif data == "user_remove_admin" and user_id in {int(OWNER_ID),int(globals().get("SECOND_ADMIN_ID",0) or 0)}:
            bot.send_message(call.message.chat.id,"❌ <b>Remove Admin</b>\n\nTarget User ID দিন:\n❌ <code>/cancel</code>",parse_mode="HTML",protect_content=True)
            bot.register_next_step_handler(call.message,process_remove_admin_managed)

        elif data == "user_statistics" and user_id in admin_ids:
            send_user_statistics(_callback_message(call))

        elif data == "bot_settings" and user_id in admin_ids:
            send_bot_settings(_callback_message(call))

        elif data == "toggle_maintenance" and user_id in admin_ids:
            bot_locked = not bot_locked
            set_setting("maintenance", "1" if bot_locked else "0")
            log_admin_activity(user_id,"Maintenance toggled",f"status={'ON' if bot_locked else 'OFF'}")
            bot.send_message(call.message.chat.id,f"{'🔴' if bot_locked else '🟢'} Maintenance is now <b>{'ON' if bot_locked else 'OFF'}</b>.",parse_mode="HTML",reply_markup=create_admin_panel_inline(user_id),protect_content=True)

        elif data == "toggle_notifications" and user_id in admin_ids:
            enabled = get_setting("notify_activity","1") == "1"
            set_setting("notify_activity","0" if enabled else "1")
            bot.send_message(call.message.chat.id,f"🔔 Admin notifications <b>{'OFF' if enabled else 'ON'}</b>.",parse_mode="HTML",reply_markup=types.InlineKeyboardMarkup().add(make_inline_button("⚙️ Bot Settings",callback_data="bot_settings",style="primary")),protect_content=True)

        elif data == "set_welcome_text" and user_id in admin_ids:
            bot.send_message(call.message.chat.id,"📝 <b>Welcome Message</b> পাঠান।\n\n❌ <code>/cancel</code>",parse_mode="HTML",protect_content=True)
            bot.register_next_step_handler(call.message,process_set_welcome_text)

        elif data == "set_welcome_image" and user_id in admin_ids:
            bot.send_message(call.message.chat.id,"🖼️ একটি Welcome Photo পাঠান।\n\n❌ <code>/cancel</code>",parse_mode="HTML",protect_content=True)
            bot.register_next_step_handler(call.message,process_set_welcome_image)

        elif data == "clear_welcome_image" and user_id in admin_ids:
            set_setting("welcome_image_file_id","")
            log_admin_activity(user_id,"Cleared welcome image")
            bot.send_message(call.message.chat.id,"🗑️ Welcome Image cleared.",protect_content=True)

        elif data == "force_join_settings" and user_id in admin_ids:
            markup=types.InlineKeyboardMarkup(row_width=2)
            markup.add(make_inline_button("➕ Add Channel",callback_data="add_channel",style="success"),make_inline_button("🗑️ Remove Channel",callback_data="remove_channel",style="danger"))
            markup.add(make_inline_button("📋 Current Channels",callback_data="force_join_list",style="primary"),make_inline_button("⬅️ Back",callback_data="bot_settings",style="danger"))
            bot.send_message(call.message.chat.id,"📢 <b>Force Join Management</b>",parse_mode="HTML",reply_markup=markup,protect_content=True)

        elif data == "force_join_list" and user_id in admin_ids:
            channels=get_force_channels()
            if not channels:
                bot.send_message(call.message.chat.id,"📭 কোনো Force Join channel নেই।",protect_content=True)
            else:
                lines=["📢 <b>Force Join Channels</b>\n"]+[f"• <code>{cid}</code> — {url}" for cid,url in channels]
                bot.send_message(call.message.chat.id,"\n".join(lines),parse_mode="HTML",protect_content=True)

        elif data == "admin_activity" and user_id in admin_ids:
            try:
                send_admin_activity(_callback_message(call))
            except Exception as exc:
                logger.error("Admin Activity callback failed: %s", exc, exc_info=True)
                bot.send_message(call.message.chat.id, "❌ Admin Activity খুলতে সমস্যা হয়েছে।\n\n<code>" + str(exc)[:500] + "</code>", parse_mode="HTML", protect_content=True)

        elif data == "admin_logs" and user_id in admin_ids:
            try:
                send_admin_logs_menu(_callback_message(call))
            except Exception as exc:
                logger.error("Admin Logs callback failed: %s", exc, exc_info=True)
                bot.send_message(call.message.chat.id, "❌ Admin Logs খুলতে সমস্যা হয়েছে।\n\n<code>" + str(exc)[:500] + "</code>", parse_mode="HTML", protect_content=True)

        elif data == "all_bot_files" and user_id in admin_ids:
            try:
                send_all_bot_files(_callback_message(call))
            except Exception as exc:
                logger.error("All Bot Files callback failed: %s", exc, exc_info=True)
                bot.send_message(call.message.chat.id, "❌ All Bot Files পাঠাতে সমস্যা হয়েছে।\n\n<code>" + str(exc)[:500] + "</code>", parse_mode="HTML", protect_content=True)

        elif data.startswith("all_files_user_") and user_id in admin_ids:
            try:
                send_admin_user_bot_files(_callback_message(call), int(data[len("all_files_user_"):]))
            except Exception as exc:
                logger.error("User Bot Files callback failed: %s", exc, exc_info=True)
                bot.send_message(call.message.chat.id, "❌ User files খুলতে সমস্যা হয়েছে।\n\n<code>" + str(exc)[:500] + "</code>", parse_mode="HTML", protect_content=True)

        elif data == "info_links" and user_id in admin_ids:
            try:
                send_info_link_admin_menu(_callback_message(call))
            except Exception as exc:
                logger.error("Info Links callback failed: %s", exc, exc_info=True)
                bot.send_message(call.message.chat.id, "❌ Info Links খুলতে সমস্যা হয়েছে।\n\n<code>" + str(exc)[:500] + "</code>", parse_mode="HTML", protect_content=True)

        elif data == "info_link_status" and user_id in admin_ids:
            answer_callback(call)
            send_info_link_status(_callback_message(call))

        elif data == "add_info_link" and user_id in admin_ids:
            _set_admin_input_state(user_id, "add_info_link")
            bot.send_message(call.message.chat.id,"🔗 <b>Add Info Link</b>\n\nফরম্যাট: <code>Title | URL</code>\nউদাহরণ: <code>Website | https://example.com</code>\n\n❌ বাতিল: <code>/cancel</code>",parse_mode="HTML",protect_content=True)

        elif data == "info_link_list" and user_id in admin_ids:
            answer_callback(call)
            send_info_link_list(_callback_message(call))

        elif data == "info_link_list_delete" and user_id in admin_ids:
            send_info_link_list(_callback_message(call))

        elif data == "info_edit_list" and user_id in admin_ids:
            send_info_edit_list(_callback_message(call))

        elif data.startswith("info_edit_") and user_id in admin_ids:
            link_id=data[len("info_edit_"):]
            bot.send_message(call.message.chat.id,"✏️ <b>Edit Link</b>\n\nনতুন format: <code>Title | https://example.com</code>\n❌ <code>/cancel</code>",parse_mode="HTML",protect_content=True)
            bot.register_next_step_handler(call.message,process_edit_info_link,link_id)

        elif data.startswith("info_del_") and user_id in admin_ids:
            link_id=data[len("info_del_"):]
            ok=_delete_info_link(link_id)
            answer_callback(call,"Deleted" if ok else "Link not found",show_alert=True)
            send_info_link_list(_callback_message(call))

        elif data == "set_info_dev" and user_id in admin_ids:
            _set_admin_input_state(user_id, "set_info_dev")
            bot.send_message(call.message.chat.id,"🔗 Developer URL দিন:\n\n❌ বাতিল: <code>/cancel</code>",parse_mode="HTML",protect_content=True)

        elif data == "set_info_channel" and user_id in admin_ids:
            _set_admin_input_state(user_id, "set_info_channel")
            bot.send_message(call.message.chat.id,"🔗 Official Channel URL দিন:\n\n❌ বাতিল: <code>/cancel</code>",parse_mode="HTML",protect_content=True)

        elif data == "set_info_notice" and user_id in admin_ids:
            _set_admin_input_state(user_id, "set_info_notice")
            bot.send_message(call.message.chat.id,"🔗 Order Notice URL দিন:\n\n❌ বাতিল: <code>/cancel</code>",parse_mode="HTML",protect_content=True)

        elif data == "set_info_support" and user_id in admin_ids:
            _set_admin_input_state(user_id, "set_info_support")
            bot.send_message(call.message.chat.id,"🔗 Support Admin URL দিন:\n\n❌ বাতিল: <code>/cancel</code>",parse_mode="HTML",protect_content=True)

        elif data == "set_developer_info" and user_id in admin_ids:
            _set_admin_input_state(user_id, "set_developer_info")
            bot.send_message(call.message.chat.id,
                "📝 <b>Developer Info Update</b>\n\n"
                "User-এর ⓘ Information page-এ যে সম্পূর্ণ লেখা দেখাতে চান সেটি পাঠান।\n"
                "HTML tag যেমন <code>&lt;b&gt;bold&lt;/b&gt;</code> ব্যবহার করতে পারবেন।\n\n"
                "❌ বাতিল: <code>/cancel</code>",
                parse_mode="HTML",protect_content=True)

        elif data == "info_back":
            answer_callback(call)
            try: bot.delete_message(call.message.chat.id,call.message.message_id)
            except Exception: pass
            bot.send_message(call.message.chat.id,"🏠 <b>Main Menu</b>",parse_mode="HTML",reply_markup=create_reply_keyboard_main_menu(user_id))

        elif data == "gift_codes" and user_id in admin_ids:
            answer_callback(call)
            send_gift_admin_menu(_callback_message(call))

        elif data == "gift_create" and user_id in admin_ids:
            answer_callback(call)
            _send_gift_create_code_step(_callback_message(call))

        elif data.startswith("gift_submit_") and user_id in admin_ids:
            try: target_admin=int(data[len("gift_submit_"):])
            except Exception: target_admin=-1
            if target_admin != int(user_id):
                answer_callback(call,"❌ এই Gift Code session আপনার নয়।",show_alert=True); return
            result=create_gift_code_from_session(user_id)
            if isinstance(result,tuple):
                code,amount,uses=result
                answer_callback(call,"Gift Code Created!",show_alert=True)
                bot.send_message(call.message.chat.id,
                    f"✅ <b>Gift Code Created Successfully</b>\n\n🎁 Code: <code>{code}</code>\n💰 Amount: <b>{amount:g} BDT</b>\n👥 Users: <b>{uses}</b>",
                    parse_mode="HTML",reply_markup=_gift_admin_menu(),protect_content=True)
            elif result == "exists":
                answer_callback(call,"Code already exists. Start again.",show_alert=True)
                _send_gift_create_code_step(_callback_message(call))
            else:
                answer_callback(call,"Gift Code creation failed.",show_alert=True)

        elif data.startswith("gift_cancel_") and user_id in admin_ids:
            try: target_admin=int(data[len("gift_cancel_"):])
            except Exception: target_admin=-1
            if target_admin == int(user_id): _clear_gift_session(user_id)
            answer_callback(call,"Cancelled")
            send_gift_admin_menu(_callback_message(call))

        elif data == "gift_list" and user_id in admin_ids:
            answer_callback(call)
            send_gift_code_list(_callback_message(call))

        elif data == "gift_delete" and user_id in admin_ids:
            answer_callback(call)
            send_gift_delete_list(_callback_message(call))

        elif data == "gift_search" and user_id in admin_ids:
            bot.send_message(call.message.chat.id,"🔎 <b>Gift Code Search</b>\n\nCode দিন:\n❌ <code>/cancel</code>",parse_mode="HTML",protect_content=True)
            bot.register_next_step_handler(call.message,process_gift_search)

        elif data == "gift_set_uses" and user_id in admin_ids:
            bot.send_message(call.message.chat.id,"👥 <b>Set Max Uses</b>\n\nGift Code দিন:\n❌ <code>/cancel</code>",parse_mode="HTML",protect_content=True)
            bot.register_next_step_handler(call.message,process_gift_set_uses_code)

        elif data == "gift_set_amount" and user_id in admin_ids:
            bot.send_message(call.message.chat.id,"💰 <b>Set Amount</b>\n\nGift Code দিন:\n❌ <code>/cancel</code>",parse_mode="HTML",protect_content=True)
            bot.register_next_step_handler(call.message,process_gift_set_amount_code)

        elif data == "gift_history" and user_id in admin_ids:
            send_gift_usage_history(_callback_message(call))

        elif data.startswith("gift_del_") and user_id in admin_ids:
            code=_normalize_gift_code(data[len("gift_del_"):])
            with DB_LOCK:
                conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False)
                cur=conn.execute("DELETE FROM gift_codes WHERE code=?",(code,)); conn.commit(); conn.close()
            answer_callback(call,"Deleted" if cur.rowcount else "Not found",show_alert=True)
            send_gift_admin_menu(_callback_message(call))

        elif data == "set_tutorial" and user_id in admin_ids:
            msg = bot.send_message(call.message.chat.id, "📝 **নতুন টিউটোরিয়াল ভিডিও এর লিংকটি দিন (যেমন: https://youtu.be/...):**")
            bot.register_next_step_handler(msg, process_set_tutorial_link)

        elif data == "add_channel" and user_id in admin_ids:
            msg = bot.send_message(call.message.chat.id, "📝 **চ্যানেল অ্যাড করুন:**\nফরম্যাট: `@channel_id | https://t.me/link`")
            bot.register_next_step_handler(msg, process_add_channel)

        elif data == "remove_channel" and user_id in admin_ids:
            channels = get_force_channels()
            if not channels:
                answer_callback(call, "No channels added!", show_alert=True)
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
            answer_callback(call, "Channel removed successfully!", show_alert=True)
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
            set_setting("maintenance", "1" if bot_locked else "0")
            status = "🔒 Locked" if bot_locked else "🔓 Unlocked"
            log_admin_activity(user_id, "Bot lock toggled", f"status={status}")
            answer_callback(call, f"Bot is now {status}", show_alert=True)
            bot.send_message(
                call.message.chat.id,
                f"✅ <b>Bot Lock Status:</b> {status}",
                parse_mode="HTML",
                reply_markup=create_admin_panel_inline(user_id),
                protect_content=True,
            )

        elif data == "stats" and user_id in admin_ids:
            answer_callback(call)
            send_bot_stats(_callback_message(call))

        elif data == "run_all_scripts" and user_id in admin_ids:
            answer_callback(call, "Running all stopped scripts...")
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
        logger.error("Error handling callback %s: %s", getattr(call, "data", ""), e, exc_info=True)
        try:
            # The callback is acknowledged at entry; send a chat message as the reliable
            # visible error path because Telegram callback answers cannot be sent twice.
            if getattr(call, "message", None) is not None:
                bot.send_message(
                    call.message.chat.id,
                    "⚠️ <b>এই বাটনের কাজ সম্পন্ন করা যায়নি।</b>\n\n"
                    f"<code>{html.escape(str(e)[:700])}</code>",
                    parse_mode="HTML",
                    protect_content=True,
                )
        except Exception:
            logger.error("Could not send callback error reply", exc_info=True)
    finally:
        # Safety net: every callback gets an answer, even if a new branch throws before answering.
        try:
            with _ANSWERED_CALLBACKS_LOCK:
                already_answered = getattr(call, "id", None) in _ANSWERED_CALLBACKS
            if not already_answered:
                answer_callback(call, "Done")
        except Exception:
            pass

# --- Deposit Input Process Handlers ---\n# Deposit handlers are defined above and use SQLite-backed sessions.\n\n# --- Setting Process Handlers ---
def process_set_bkash(message):
    if int(_message_actor_id(message)) not in admin_ids:
        return
    number = (message.text or "").strip()
    if not re.fullmatch(r"01\d{9}", number):
        bot.send_message(message.chat.id, "❌ সঠিক ১১-ডিজিটের বাংলাদেশি mobile number দিন। উদাহরণ: 017XXXXXXXX")
        return
    set_setting("bkash_number", number)
    bot.send_message(message.chat.id, f"✅ **bKash নাম্বার সেট করা হয়েছে:** `{number}`", parse_mode="Markdown")

def process_set_nagad(message):
    if int(_message_actor_id(message)) not in admin_ids:
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
    name = (message.text or "").strip()
    if not name or len(name)>100:
        bot.send_message(message.chat.id,"❌ Valid plan name দিন (1–100 chars)।",protect_content=True)
        bot.register_next_step_handler(message,process_plan_name); return
    msg = bot.send_message(message.chat.id, "📝 <b>প্ল্যানের বিস্তারিত বিবরণ দিন:</b>",parse_mode="HTML",protect_content=True)
    bot.register_next_step_handler(msg, process_plan_desc, name)


def process_plan_desc(message, name):
    desc=(message.text or "").strip()
    if not desc or len(desc)>1000:
        bot.send_message(message.chat.id,"❌ Valid description দিন।",protect_content=True)
        bot.register_next_step_handler(message,process_plan_desc,name); return
    msg = bot.send_message(message.chat.id, "📝 <b>কয়টি বট হোস্ট করা যাবে?</b> (শুধুমাত্র সংখ্যা)",parse_mode="HTML",protect_content=True)
    bot.register_next_step_handler(msg, process_plan_limit, name, desc)


def process_plan_limit(message, name, desc):
    try: limit=int((message.text or '').strip())
    except ValueError: limit=0
    if limit<1 or limit>100000:
        bot.send_message(message.chat.id,"❌ 1–100000 এর মধ্যে bot/file limit দিন (100000 = কার্যত আনলিমিটেড)।",protect_content=True)
        bot.register_next_step_handler(message,process_plan_limit,name,desc); return
    msg=bot.send_message(message.chat.id,"📝 <b>মেয়াদ কতদিন?</b> (শুধুমাত্র সংখ্যা)",parse_mode="HTML",protect_content=True)
    bot.register_next_step_handler(msg,process_plan_days,name,desc,limit)


def process_plan_days(message, name, desc, limit):
    try: days=int((message.text or '').strip())
    except ValueError: days=0
    if days<1 or days>36500:
        bot.send_message(message.chat.id,"❌ 1–36500 দিনের মধ্যে duration দিন।",protect_content=True)
        bot.register_next_step_handler(message,process_plan_days,name,desc,limit); return
    msg=bot.send_message(message.chat.id,"📝 <b>প্ল্যানের দাম কত?</b> (যেমন: 150)",parse_mode="HTML",protect_content=True)
    bot.register_next_step_handler(msg,process_plan_price,name,desc,limit,days)


def process_plan_price(message, name, desc, limit, days):
    price=(message.text or '').strip()
    try:
        price_num=float(price.replace(',',''))
        if price_num<0 or price_num>100000000: raise ValueError
    except ValueError:
        bot.send_message(message.chat.id,"❌ Valid price দিন।",protect_content=True)
        bot.register_next_step_handler(message,process_plan_price,name,desc,limit,days); return
    with DB_LOCK:
        conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False)
        conn.execute("INSERT INTO plans (name,description,bot_limit,duration_days,price) VALUES (?,?,?,?,?)",(name,desc,limit,days,str(price)))
        conn.commit(); conn.close()
    log_admin_activity(_message_actor_id(message),"Created hosting plan",f"name={name}, limit={limit}, days={days}, price={price}")
    bot.send_message(message.chat.id,f"✅ <b>Plan Created</b>\n\n📦 {html.escape(name)}\n🤖 Limit: <b>{limit}</b>\n⏳ Days: <b>{days}</b>\n💰 Price: <b>{html.escape(price)}</b>",parse_mode="HTML",protect_content=True)


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
        actor = int(_message_actor_id(message))
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
        actor = int(_message_actor_id(message))
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
        bot.register_next_step_handler(msg, process_set_limit_value, target_user)
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

def _save_broadcast_session(admin_id, source_chat_id, source_message_id, button_text="", button_url=""):
    with DB_LOCK:
        conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False)
        conn.execute("INSERT OR REPLACE INTO broadcast_sessions(admin_id,source_chat_id,source_message_id,button_text,button_url,created_at) VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)",(int(admin_id),int(source_chat_id),int(source_message_id),str(button_text),str(button_url)))
        conn.commit(); conn.close()


def _get_broadcast_session(admin_id):
    with DB_LOCK:
        conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False)
        row=conn.execute("SELECT source_chat_id,source_message_id,button_text,button_url FROM broadcast_sessions WHERE admin_id=?",(int(admin_id),)).fetchone(); conn.close()
    return row


def _clear_broadcast_session(admin_id):
    with DB_LOCK:
        conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False); conn.execute("DELETE FROM broadcast_sessions WHERE admin_id=?",(int(admin_id),)); conn.commit(); conn.close()


def process_broadcast(message):
    """First step: capture any Telegram content, then ask for an optional dynamic URL button."""
    admin_id=int(_message_actor_id(message))
    if admin_id not in admin_ids:return
    _save_broadcast_session(admin_id,message.chat.id,message.message_id)
    bot.send_message(
        message.chat.id,
        "🔘 <b>Optional Dynamic Button</b>\n\n"
        "Button দিতে চাইলে পাঠান:\n<code>Button Text | https://example.com</code>\n\n"
        "Button না চাইলে <code>/skip</code> পাঠান।\n❌ পুরো broadcast cancel করতে <code>/cancel</code> দিন।",
        parse_mode="HTML",protect_content=True,
    )
    bot.register_next_step_handler(message,process_broadcast_button)


def _run_broadcast(admin_chat_id, admin_id, session):
    source_chat_id, source_message_id, button_text, button_url = session
    markup=None
    if button_text and button_url:
        markup=types.InlineKeyboardMarkup(row_width=1)
        markup.add(make_inline_button(button_text[:64],url=button_url,style="primary"))
    sent=failed=blocked=0
    for uid in list(active_users):
        try:
            kwargs={}
            if markup is not None: kwargs["reply_markup"]=markup
            kwargs["protect_content"] = True
            bot.copy_message(uid,source_chat_id,source_message_id,**kwargs)
            sent+=1
            time.sleep(0.05)
        except Exception as exc:
            failed+=1
            if "403" in str(exc) or "blocked" in str(exc).lower() or "chat not found" in str(exc).lower():
                blocked+=1
    try:
        bot.send_message(admin_chat_id,
            "✅ <b>Broadcast Complete</b>\n\n"
            f"🟢 Sent: <b>{sent}</b>\n"
            f"🔴 Failed: <b>{failed}</b>\n"
            f"🚫 Blocked/Unavailable: <b>{blocked}</b>",
            parse_mode="HTML",protect_content=True)
    except Exception: pass
    log_admin_activity(admin_id,"Broadcast completed",f"sent={sent}, failed={failed}, blocked={blocked}")


def process_broadcast_button(message):
    admin_id=int(_message_actor_id(message))
    if admin_id not in admin_ids:return
    session=_get_broadcast_session(admin_id)
    if not session:
        bot.send_message(message.chat.id,"❌ Broadcast session পাওয়া যায়নি। আবার Broadcast শুরু করুন।",protect_content=True); return
    text=(message.text or "").strip()
    if text.lower()=="/skip":
        _save_broadcast_session(admin_id,session[0],session[1],"","")
    else:
        parts=[p.strip() for p in text.split('|',1)]
        if len(parts)!=2 or not parts[0] or not _valid_http_url(parts[1]):
            bot.send_message(message.chat.id,"❌ Format: <code>Button Text | https://example.com</code> অথবা <code>/skip</code>",parse_mode="HTML",protect_content=True)
            bot.register_next_step_handler(message,process_broadcast_button); return
        _save_broadcast_session(admin_id,session[0],session[1],parts[0][:64],parts[1])
    final=_get_broadcast_session(admin_id)
    _clear_broadcast_session(admin_id)
    bot.send_message(message.chat.id,"⏳ <b>Broadcast started...</b>\nResult শেষ হলে এখানেই Sent / Failed / Blocked count আসবে।",parse_mode="HTML",protect_content=True)
    threading.Thread(target=_run_broadcast,args=(message.chat.id,admin_id,final),daemon=True).start()


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

def _valid_http_url(url):
    return bool(re.fullmatch(r"https?://[^\s<>]+", str(url or "").strip(), flags=re.IGNORECASE))

def _load_info_links():
    default = {"links": []}
    data = _json_load(INFO_JSON_PATH, default)
    if not isinstance(data, dict): data = default
    if not isinstance(data.get("links"), list): data["links"] = []
    return data

def _save_info_links(data):
    return _json_save(INFO_JSON_PATH, data)

def _add_info_link(title, url, created_by):
    data = _load_info_links()
    links = data["links"]
    links = [x for x in links if str(x.get("title", "")).strip().lower() != title.strip().lower()]
    links.append({"id": uuid.uuid4().hex[:12], "title": title.strip(), "url": url.strip(), "created_by": int(created_by), "created_at": datetime.now().isoformat(timespec="seconds")})
    data["links"] = links
    return _save_info_links(data)

def _delete_info_link(link_id):
    data = _load_info_links()
    before = len(data["links"])
    data["links"] = [x for x in data["links"] if str(x.get("id")) != str(link_id)]
    return before != len(data["links"]) and _save_info_links(data)

def send_information(message):
    """Public Information page. Built-in links + admin-created Title | URL buttons."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        make_inline_button("</> Developer ↗️", url=get_system_setting("info_dev_url", "https://t.me/RBK_Developer"), style="success"),
        make_inline_button("🤝 Official Channel ↗️", url=get_system_setting("info_channel_url", UPDATE_CHANNEL), style="primary"),
    )
    markup.add(
        make_inline_button("📋 Order Notic ↗️", url=get_system_setting("info_notice_url", UPDATE_CHANNEL), style="primary"),
        make_inline_button("💬 Support Admin ↗️", url=get_system_setting("info_support_url", "https://t.me/RBK_Developer"), style="primary"),
    )
    custom = _load_info_links().get("links", [])
    for item in custom:
        title = str(item.get("title", "")).strip()
        url = str(item.get("url", "")).strip()
        if title and _valid_http_url(url):
            markup.add(make_inline_button(title[:64], url=url, style="primary"))
    markup.add(make_inline_button("⬅️ Back", callback_data="info_back", style="danger"))
    default_text = (
        "📁 <b>ⓘ Developer Info</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🤖 <b>বট সম্পর্কে বিস্তারিত তথ্য:</b>\n"
        "আমাদের এই প্ল্যাটফর্মটি আপনাদের অটোমেশন এবং বিভিন্ন ডিজিটাল সেবা সহজ করার জন্য তৈরি করা হয়েছে। আপনি যদি আপনার বিজনেস বা ব্যক্তিগত কাজের জন্য এই ধরনের কিংবা এর চেয়েও আধুনিক কোনো বট তৈরি করতে চান, তবে আমরা আছি আপনার সহায়তায়!\n\n"
        "💡 <b>আমাদের প্রধান সেবাসমূহ:</b>\n"
        "• কাস্টম টেলিগ্রাম বট ও মিনি অ্যাপ ডেভেলপমেন্ট (Mini Apps)\n"
        "• ওয়েবসাইট ও সার্ভিস ভেরিফিকেশনের জন্য <b>OTP Bot</b> সিস্টেম\n"
        "• অটো পেমেন্ট গেটওয়ে ইন্টিগ্রেশন এবং কাস্টম ডাটাবেস ম্যানেজমেন্ট\n"
        "• যে কোনো ধরনের ওয়েব অ্যাপ্লিকেশন ও অটোমেশন সলিউশন\n\n"
        "💰 আমরা অত্যন্ত সাশ্রয়ী মূল্যে এবং কম সময়ে প্রফেশনাল মানের সার্ভিস প্রদান করে থাকি। দেরি না করে নিচের <b>'Developer'</b> অপশনে ক্লিক করে আজই আমাদের সাথে যোগাযোগ করুন এবং আপনার আইডিয়াটি শেয়ার করুন। ধন্যবাদ! 🚀"
    )
    text = get_system_setting("developer_info_text", default_text)
    bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup, protect_content=True)

def send_developer_info(message):
    # Keep the existing Developer button, but make it use the same dynamic developer URL.
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(make_inline_button("👤 𝗖𝗼𝗻𝘁𝗿𝗮𝗰𝘁 𝗗𝗲𝘃", url=get_system_setting("info_dev_url", "https://t.me/RBK_Developer"), style="success"))
    text = (
        "📁 <b>〈/〉 𝗗𝗲𝘃𝗲𝗹𝗼𝗽𝗲𝗿</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🤖 <b>যেকোনো ধরনের বট বানাতে এখনই এসএমএস দিন</b>\n\n"
        "👨‍💻 <b>Developer:</b> @RBK_Developer\n"
        "⚡ <b>Fast • Professional • Reliable</b>"
    )
    bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup, protect_content=True)

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

# =====================================================================
# 🎁 GIFT CODE SYSTEM
# =====================================================================
def _normalize_gift_code(code):
    return re.sub(r"[^A-Za-z0-9_-]", "", str(code or "").strip()).upper()[:64]

def _gift_admin_menu():
    markup=types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        make_inline_button("➕ Create Gift Code",callback_data="gift_create",style="success"),
        make_inline_button("📋 Gift Code List",callback_data="gift_list",style="primary")
    )
    markup.add(
        make_inline_button("🔎 Search",callback_data="gift_search",style="primary"),
        make_inline_button("🗑️ Delete",callback_data="gift_delete",style="danger")
    )
    markup.add(
        make_inline_button("👥 Set Max Uses",callback_data="gift_set_uses",style="primary"),
        make_inline_button("💰 Set Amount",callback_data="gift_set_amount",style="success")
    )
    markup.add(make_inline_button("📜 Usage History",callback_data="gift_history",style="primary"))
    markup.add(make_inline_button("⬅️ Back",callback_data="admin_back",style="danger"))
    return markup

def send_gift_admin_menu(message):
    if _message_actor_id(message) not in admin_ids: return
    bot.send_message(
        message.chat.id,
        "🎁 <b>Gift Code Control</b>\n\n"
        "নতুন Gift Code তৈরি করতে <b>Create Gift Code</b> চাপুন।\n"
        "তারপর ধাপে ধাপে Code → Amount → কতজন ব্যবহার করবে → Submit হবে।",
        parse_mode="HTML", reply_markup=_gift_admin_menu(), protect_content=True
    )

def _gift_session(admin_id):
    with DB_LOCK:
        conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False)
        row=conn.execute("SELECT step,code,amount,max_uses FROM gift_creation_sessions WHERE admin_id=?",(int(admin_id),)).fetchone()
        conn.close()
    return row

def _set_gift_session(admin_id, step, code="", amount=0, max_uses=0):
    with DB_LOCK:
        conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False)
        conn.execute(
            "INSERT OR REPLACE INTO gift_creation_sessions(admin_id,step,code,amount,max_uses,updated_at) VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)",
            (int(admin_id),step,code,float(amount or 0),int(max_uses or 0))
        )
        conn.commit(); conn.close()

def _clear_gift_session(admin_id):
    with DB_LOCK:
        conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False)
        conn.execute("DELETE FROM gift_creation_sessions WHERE admin_id=?",(int(admin_id),)); conn.commit(); conn.close()

def _send_gift_create_code_step(message):
    _set_gift_session(_message_actor_id(message),"code")
    bot.send_message(message.chat.id,"🎁 <b>Step 1/3 — Gift Code</b>\n\nউদাহরণ: <code>RBK100</code>\n\nশুধু Gift Code লিখুন:",parse_mode="HTML",protect_content=True)

def _process_gift_creation_message(message):
    admin_id=int(_message_actor_id(message))
    if admin_id not in admin_ids: return False
    row=_gift_session(admin_id)
    if not row: return False
    step,code,amount,max_uses=row
    text=(message.text or "").strip()
    if step=="code":
        clean=_normalize_gift_code(text)
        if not clean or len(clean)<3:
            bot.send_message(message.chat.id,"❌ কমপক্ষে 3 অক্ষরের valid Gift Code দিন। আবার Code লিখুন:",protect_content=True); return True
        with DB_LOCK:
            conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False)
            exists=conn.execute("SELECT 1 FROM gift_codes WHERE code=?",(clean,)).fetchone()
            conn.close()
        if exists:
            bot.send_message(message.chat.id,"❌ এই Gift Code আগে থেকেই আছে। অন্য Code দিন:",protect_content=True); return True
        _set_gift_session(admin_id,"amount",clean,0,0)
        bot.send_message(message.chat.id,f"✅ Code: <code>{clean}</code>\n\n💰 <b>Step 2/3 — Amount</b>\n\nপ্রতি user কত টাকা পাবে? উদাহরণ: <code>100</code>",parse_mode="HTML",protect_content=True)
        return True
    if step=="amount":
        try: value=float(text.replace(",",""))
        except Exception:
            value=0
        if value<=0 or value>100000000:
            bot.send_message(message.chat.id,"❌ সঠিক Amount দিন। উদাহরণ: <code>100</code>",parse_mode="HTML",protect_content=True); return True
        _set_gift_session(admin_id,"max_uses",code,value,0)
        bot.send_message(message.chat.id,f"💰 Amount: <b>{value:g} BDT</b>\n\n👥 <b>Step 3/3 — User Limit</b>\n\nকতজন user এই Gift Code ব্যবহার করতে পারবে? উদাহরণ: <code>5</code>",parse_mode="HTML",protect_content=True)
        return True
    if step=="max_uses":
        try: uses=int(text)
        except Exception: uses=0
        if uses<1 or uses>1000000:
            bot.send_message(message.chat.id,"❌ 1 বা তার বেশি valid User Limit দিন। উদাহরণ: <code>5</code>",parse_mode="HTML",protect_content=True); return True
        _set_gift_session(admin_id,"confirm",code,amount,uses)
        markup=types.InlineKeyboardMarkup(row_width=2)
        markup.add(make_inline_button("✅ Submit",callback_data=f"gift_submit_{admin_id}",style="success"),make_inline_button("❌ Cancel",callback_data=f"gift_cancel_{admin_id}",style="danger"))
        bot.send_message(message.chat.id,
            f"🎁 <b>Gift Code Preview</b>\n\n"
            f"🔑 Code: <code>{code}</code>\n"
            f"💰 Amount: <b>{float(amount):g} BDT</b>\n"
            f"👥 Max Users: <b>{uses}</b>\n\n"
            "সব ঠিক থাকলে <b>Submit</b> চাপুন।",
            parse_mode="HTML",reply_markup=markup,protect_content=True)
        return True
    if step=="confirm":
        bot.send_message(message.chat.id,"ℹ️ Gift Code তৈরি করার জন্য উপরের <b>Submit</b> বাটনে চাপুন।",parse_mode="HTML",protect_content=True)
        return True
    return False

def process_create_gift_code(message):
    # Backward-compatible entry point; the new flow is state-driven.
    _process_gift_creation_message(message)

def create_gift_code_from_session(admin_id):
    row=_gift_session(admin_id)
    if not row or row[0] != "confirm": return None
    _,code,amount,max_uses=row
    try:
        with DB_LOCK:
            conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False)
            conn.execute("BEGIN IMMEDIATE")
            exists=conn.execute("SELECT 1 FROM gift_codes WHERE code=?",(code,)).fetchone()
            if exists:
                conn.rollback(); conn.close(); return "exists"
            conn.execute("INSERT INTO gift_codes(code,amount,max_uses,used_count,active,created_by) VALUES(?,?,?,0,1,?)",(code,float(amount),int(max_uses),int(admin_id)))
            conn.commit(); conn.close()
        # JSON mirror for portable backup/persistence of Gift Code data.
        data=_json_load(GIFT_JSON_PATH,{"codes":[]})
        codes=data.get("codes",[]) if isinstance(data,dict) else []
        codes=[x for x in codes if str(x.get("code","")) != code]
        codes.append({"code":code,"amount":float(amount),"max_uses":int(max_uses),"used_count":0,"active":1,"expires_at":None,"created_by":int(admin_id),"created_at":datetime.now().isoformat(timespec="seconds")})
        _json_save(GIFT_JSON_PATH,{"codes":codes})
        _clear_gift_session(admin_id)
        log_admin_activity(admin_id,"Created gift code",f"code={code}, amount={float(amount):g}, max_uses={int(max_uses)}")
        return (code,float(amount),int(max_uses))
    except Exception as exc:
        logger.error("Gift code creation failed: %s",exc,exc_info=True)
        try: conn.close()
        except Exception: pass
        return "error"

def send_gift_code_list(message):
    if _message_actor_id(message) not in admin_ids: return
    with DB_LOCK:
        conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False)
        rows=conn.execute("SELECT code,amount,used_count,max_uses,active FROM gift_codes ORDER BY created_at DESC LIMIT 100").fetchall(); conn.close()
    if not rows:
        bot.send_message(message.chat.id,"❌ এখনো কোনো Gift Code তৈরি করা হয়নি।",protect_content=True); return
    lines=["🎁 <b>Gift Code List</b>\n"]
    for code,amount,used,max_uses,active in rows:
        state="🟢 Active" if active and used<max_uses else "🔴 Closed"
        lines.append(f"🎁 <code>{code}</code> — <b>{float(amount):g} BDT</b> — 👥 {used}/{max_uses} — {state}")
    bot.send_message(message.chat.id,"\n".join(lines),parse_mode="HTML",protect_content=True)

def send_gift_delete_list(message):
    if _message_actor_id(message) not in admin_ids: return
    with DB_LOCK:
        conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False)
        rows=conn.execute("SELECT code,amount,used_count,max_uses FROM gift_codes ORDER BY created_at DESC LIMIT 100").fetchall(); conn.close()
    if not rows:
        bot.send_message(message.chat.id,"❌ Delete করার মতো Gift Code নেই।",protect_content=True); return
    markup=types.InlineKeyboardMarkup(row_width=1)
    for code,amount,used,max_uses in rows:
        markup.add(make_inline_button(f"🗑️ {code} — {amount:g} BDT ({used}/{max_uses})", callback_data=f"gift_del_{code}", style="danger"))
    bot.send_message(message.chat.id,"🗑️ Delete করার Gift Code নির্বাচন করুন:",reply_markup=markup,protect_content=True)

def process_gift_search(message):
    if int(_message_actor_id(message)) not in admin_ids: return
    code=_normalize_gift_code(message.text)
    with DB_LOCK:
        conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False)
        row=conn.execute("SELECT code,amount,used_count,max_uses,active,expires_at,created_by,created_at FROM gift_codes WHERE code=?",(code,)).fetchone()
        conn.close()
    if not row:
        bot.send_message(message.chat.id,"❌ Gift Code পাওয়া যায়নি।",protect_content=True); return
    c,a,u,m,active,exp,created,created_at=row
    state="🟢 Active" if active and u<m else "🔴 Closed"
    bot.send_message(message.chat.id,f"🎁 <b>Gift Code</b>\n\n🔑 <code>{c}</code>\n💰 Amount: <b>{float(a):g} BDT</b>\n👥 Uses: <b>{u}/{m}</b>\n📌 Status: <b>{state}</b>\n🕒 Created: <code>{created_at}</code>\n👑 Created By: <code>{created}</code>",parse_mode="HTML",protect_content=True)


def _prompt_gift_code_action(message, handler, title):
    bot.send_message(message.chat.id,f"🎁 <b>{title}</b>\n\nGift Code লিখুন:\n❌ <code>/cancel</code>",parse_mode="HTML",protect_content=True)
    bot.register_next_step_handler(message, handler)


def process_gift_set_uses_code(message):
    if int(_message_actor_id(message)) not in admin_ids:return
    code=_normalize_gift_code(message.text)
    with DB_LOCK:
        conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False)
        exists=conn.execute("SELECT 1 FROM gift_codes WHERE code=?",(code,)).fetchone(); conn.close()
    if not exists:
        bot.send_message(message.chat.id,"❌ Code পাওয়া যায়নি। আবার Code দিন অথবা /cancel দিন।",protect_content=True)
        bot.register_next_step_handler(message,process_gift_set_uses_code); return
    bot.send_message(message.chat.id,f"👥 <b>{code}</b> এর নতুন Max Uses কত হবে?",parse_mode="HTML",protect_content=True)
    bot.register_next_step_handler(message,process_gift_set_uses_value,code)


def process_gift_set_uses_value(message,code):
    try: uses=int((message.text or '').strip())
    except ValueError: uses=0
    if uses<1 or uses>1000000:
        bot.send_message(message.chat.id,"❌ 1–1,000,000 এর মধ্যে সংখ্যা দিন।",protect_content=True)
        bot.register_next_step_handler(message,process_gift_set_uses_value,code); return
    with DB_LOCK:
        conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False)
        conn.execute("UPDATE gift_codes SET max_uses=?, active=CASE WHEN used_count>=? THEN 0 ELSE 1 END WHERE code=?",(uses,uses,code)); conn.commit(); conn.close()
    log_admin_activity(_message_actor_id(message),"Updated gift max uses",f"code={code}, max_uses={uses}")
    bot.send_message(message.chat.id,f"✅ <b>{code}</b> এর Max Uses <b>{uses}</b> করা হয়েছে।",parse_mode="HTML",protect_content=True)


def process_gift_set_amount_code(message):
    if int(_message_actor_id(message)) not in admin_ids:return
    code=_normalize_gift_code(message.text)
    with DB_LOCK:
        conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False)
        exists=conn.execute("SELECT 1 FROM gift_codes WHERE code=?",(code,)).fetchone(); conn.close()
    if not exists:
        bot.send_message(message.chat.id,"❌ Code পাওয়া যায়নি। আবার Code দিন অথবা /cancel দিন।",protect_content=True)
        bot.register_next_step_handler(message,process_gift_set_amount_code); return
    bot.send_message(message.chat.id,f"💰 <b>{code}</b> এর নতুন Amount কত BDT হবে?",parse_mode="HTML",protect_content=True)
    bot.register_next_step_handler(message,process_gift_set_amount_value,code)


def process_gift_set_amount_value(message,code):
    try: amount=float((message.text or '').replace(',','').strip())
    except ValueError: amount=0
    if amount<=0 or amount>100000000:
        bot.send_message(message.chat.id,"❌ Valid positive amount দিন।",protect_content=True)
        bot.register_next_step_handler(message,process_gift_set_amount_value,code); return
    with DB_LOCK:
        conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False)
        conn.execute("UPDATE gift_codes SET amount=? WHERE code=?",(amount,code)); conn.commit(); conn.close()
    log_admin_activity(_message_actor_id(message),"Updated gift amount",f"code={code}, amount={amount:g}")
    bot.send_message(message.chat.id,f"✅ <b>{code}</b> এর Amount <b>{amount:g} BDT</b> করা হয়েছে।",parse_mode="HTML",protect_content=True)


def send_gift_usage_history(message):
    if int(_message_actor_id(message)) not in admin_ids:return
    with DB_LOCK:
        conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False)
        rows=conn.execute("SELECT code,user_id,redeemed_at FROM gift_redemptions ORDER BY redeemed_at DESC LIMIT 100").fetchall(); conn.close()
    if not rows:
        bot.send_message(message.chat.id,"📜 এখনো কোনো Gift Code redemption history নেই।",protect_content=True); return
    lines=["📜 <b>Gift Code Usage History</b>\n"]
    for code,uid,when in rows:
        lines.append(f"🎁 <code>{code}</code> → 👤 <code>{uid}</code> — <code>{when}</code>")
    bot.send_message(message.chat.id,"\n".join(lines),parse_mode="HTML",protect_content=True)

def process_redeem_gift_code(message):
    user_id=int(_message_actor_id(message))
    code=_normalize_gift_code(message.text)
    if not code:
        bot.send_message(message.chat.id,"❌ সঠিক Gift Code দিন।",protect_content=True); return
    with DB_LOCK:
        conn=sqlite3.connect(DATABASE_PATH,check_same_thread=False)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row=conn.execute("SELECT amount,max_uses,used_count,active,expires_at FROM gift_codes WHERE code=?",(code,)).fetchone()
            if not row:
                conn.rollback(); conn.close(); bot.send_message(message.chat.id,"❌ Gift Code পাওয়া যায়নি।",protect_content=True); return
            amount,max_uses,used_count,active,expires_at=row
            if not active or used_count>=max_uses:
                conn.rollback(); conn.close(); bot.send_message(message.chat.id,"❌ এই Gift Code আর ব্যবহার করা যাবে না।",protect_content=True); return
            if expires_at:
                try:
                    if datetime.now() >= datetime.fromisoformat(expires_at):
                        conn.execute("UPDATE gift_codes SET active=0 WHERE code=?",(code,)); conn.commit(); conn.close(); bot.send_message(message.chat.id,"❌ এই Gift Code-এর মেয়াদ শেষ হয়ে গেছে।",protect_content=True); return
                except Exception: pass
            try:
                conn.execute("INSERT INTO gift_redemptions(code,user_id) VALUES(?,?)",(code,user_id))
            except sqlite3.IntegrityError:
                conn.rollback(); conn.close(); bot.send_message(message.chat.id,"⚠️ আপনি এই Gift Code আগে ব্যবহার করেছেন।",protect_content=True); return
            conn.execute("INSERT OR IGNORE INTO user_account(user_id,balance,total_referrals) VALUES(?,0,0)",(user_id,))
            conn.execute("UPDATE user_account SET balance=balance+? WHERE user_id=?",(float(amount),user_id))
            new_used=used_count+1
            conn.execute("UPDATE gift_codes SET used_count=?, active=CASE WHEN ? >= max_uses THEN 0 ELSE active END WHERE code=?",(new_used,new_used,code))
            conn.commit()
            # Keep JSON backup in sync with the authoritative transaction.
            data=_json_load(GIFT_JSON_PATH,{"codes":[]})
            codes=data.get("codes",[]) if isinstance(data,dict) else []
            for item in codes:
                if str(item.get("code","")) == code:
                    item["used_count"]=new_used
                    item["active"]=0 if new_used >= int(max_uses) else int(active)
                    break
            else:
                codes.append({"code":code,"amount":float(amount),"max_uses":int(max_uses),"used_count":new_used,"active":0 if new_used >= int(max_uses) else int(active),"expires_at":expires_at})
            _json_save(GIFT_JSON_PATH,{"codes":codes})
        except Exception as exc:
            conn.rollback(); logger.error("Gift redemption failed: %s",exc,exc_info=True); conn.close(); bot.send_message(message.chat.id,"❌ Gift Code redeem করার সময় সমস্যা হয়েছে।",protect_content=True); return
        conn.close()
    balance=get_user_account(user_id)[0]
    bot.send_message(message.chat.id,f"🎉 <b>Gift Code Redeemed!</b>\n\n🎁 Code: <code>{code}</code>\n💰 Added: <b>{float(amount):g} BDT</b>\n💳 New Balance: <b>{float(balance):g} BDT</b>",parse_mode="HTML",protect_content=True)


# =====================================================================
# 📂 ADMIN — ALL BOT FILES / SOURCE CODE
# =====================================================================
def _admin_all_bot_users_markup():
    markup=types.InlineKeyboardMarkup(row_width=1)
    rows=[]
    for uid,files in sorted(user_files.items(), key=lambda x:int(x[0])):
        if not files: continue
        running=sum(1 for fname,_ in files if is_bot_running(uid,fname))
        rows.append((uid,len(files),running))
    if not rows:
        return markup, 0
    for uid,total,running in rows:
        markup.add(make_inline_button(f"👤 {uid} — 📁 {total} — 🟢 {running} Running",callback_data=f"all_files_user_{uid}"))
    return markup,len(rows)

def _iter_admin_project_files():
    """Return source/config files the owner explicitly requested from this project.

    Includes project .py/.json files plus hosted-user source/config files. Secret-bearing .env files are excluded.
    Runtime databases, caches and virtual environments are intentionally excluded.
    """
    found=[]
    skip_dirs={"__pycache__", ".git", ".venv", "venv", "node_modules"}
    for root, dirs, files in os.walk(BASE_DIR):
        # upload_bots is scanned separately below so it is grouped with owner IDs.
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        for fname in files:
            if not (fname.endswith(".py") or fname.endswith(".json")):
                continue
            path=os.path.join(root,fname)
            # Avoid the SQLite database and generated logs naturally because their extensions
            # are not in the allowed list.
            if os.path.isfile(path):
                found.append(path)
    return sorted(set(found), key=lambda p: (p != os.path.join(BASE_DIR,"bot.py"), p.lower()))

def send_all_bot_files(message):
    if int(_message_actor_id(message)) not in admin_ids:
        return

    sent = 0
    failed = 0
    skipped = 0
    files = _iter_admin_project_files()

    bot.send_message(
        message.chat.id,
        "📂 <b>ALL BOT FILES</b>\n\n"
        f"📦 মোট candidate files: <b>{len(files)}</b>\n"
        "⏳ এখন একে একে পাঠানো হচ্ছে...",
        parse_mode="HTML",
        protect_content=True,
    )

    for path in files:
        try:
            rel = os.path.relpath(path, BASE_DIR)
            size = os.path.getsize(path)
            if size > MAX_FILE_SIZE_BYTES:
                skipped += 1
                bot.send_message(
                    message.chat.id,
                    f"⚠️ <code>{rel}</code> skipped — size {size/(1024*1024):.1f} MB",
                    parse_mode="HTML",
                    protect_content=True,
                )
                continue
            with open(path, "rb") as fh:
                bot.send_document(
                    message.chat.id,
                    fh,
                    caption=f"📄 <b>{rel}</b>\n📦 {size/1024:.1f} KB",
                    parse_mode="HTML",
                    protect_content=True,
                )
            sent += 1
        except Exception as exc:
            failed += 1
            logger.error("All Bot Files send failed for %s: %s", path, exc, exc_info=True)

    bot.send_message(
        message.chat.id,
        "✅ <b>ALL BOT FILES — COMPLETE</b>\n\n"
        f"📤 Successfully sent: <b>{sent}</b>\n"
        f"⚠️ Skipped (too large): <b>{skipped}</b>\n"
        f"❌ Failed: <b>{failed}</b>\n"
        f"📊 Total processed: <b>{sent + skipped + failed}</b>",
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup().add(
            make_inline_button("🔄 Send All Files Again", callback_data="all_bot_files", style="primary"),
            make_inline_button("⬅️ Admin Panel", callback_data="admin_back", style="danger"),
        ),
        protect_content=True,
    )

# =====================================================================
# 🔗 ADMIN INPUT STATE (persistent JSON)
# =====================================================================
ADMIN_INPUT_STATES = {
    "add_info_link", "set_info_dev", "set_info_channel",
    "set_info_notice", "set_info_support", "set_developer_info"
}

def _admin_input_states_load():
    data = _json_load(ADMIN_STATE_JSON_PATH, {"states": {}})
    if not isinstance(data, dict) or not isinstance(data.get("states"), dict):
        data = {"states": {}}
    return data

def _set_admin_input_state(user_id, state):
    data = _admin_input_states_load()
    data["states"][str(int(user_id))] = str(state)
    return _json_save(ADMIN_STATE_JSON_PATH, data)

def _get_admin_input_state(user_id):
    data = _admin_input_states_load()
    return data.get("states", {}).get(str(int(user_id)))

def _clear_admin_input_state(user_id):
    data = _admin_input_states_load()
    data.get("states", {}).pop(str(int(user_id)), None)
    return _json_save(ADMIN_STATE_JSON_PATH, data)

# =====================================================================
# 🔗 ADMIN — INFORMATION LINK CONTROL
# =====================================================================
def send_info_link_admin_menu(message):
    if _message_actor_id(message) not in admin_ids: return
    markup=types.InlineKeyboardMarkup(row_width=2)
    markup.add(make_inline_button("➕ Add Title | URL",callback_data="add_info_link",style="success"), make_inline_button("📋 Link List",callback_data="info_link_list",style="primary"))
    markup.add(make_inline_button("✏️ Edit Link",callback_data="info_edit_list",style="primary"), make_inline_button("🗑️ Delete Link",callback_data="info_link_list_delete",style="danger"))
    markup.add(make_inline_button("</> Developer",callback_data="set_info_dev"),make_inline_button("🤝 Official Channel",callback_data="set_info_channel"))
    markup.add(make_inline_button("📋 Order Notic",callback_data="set_info_notice"),make_inline_button("💬 Support Admin",callback_data="set_info_support"))
    markup.add(make_inline_button("📌 Current Links",callback_data="info_link_status"))
    markup.add(make_inline_button("📝 Developer Info",callback_data="set_developer_info"))
    markup.add(make_inline_button("⬅️ Back",callback_data="admin_back",style="danger"))
    bot.send_message(message.chat.id,"🔗 <b>Information / Link Control</b>\n\nনতুন link দিতে: <code>Title | URL</code>\nউদাহরণ: <code>Our Website | https://example.com</code>",parse_mode="HTML",reply_markup=markup,protect_content=True)

def _process_info_link(message,key,label):
    if int(_message_actor_id(message)) not in admin_ids: return
    url=(message.text or "").strip()
    if not _valid_http_url(url):
        bot.send_message(message.chat.id,"❌ সঠিক http/https URL দিন। আবার URL পাঠান অথবা /cancel দিন।",protect_content=True)
        return
    if set_system_setting(key,url):
        _clear_admin_input_state(_message_actor_id(message))
        bot.send_message(message.chat.id,f"✅ <b>{label}</b> link আপডেট হয়েছে।\n\n🔗 <code>{url}</code>",parse_mode="HTML",protect_content=True)
    else:
        bot.send_message(message.chat.id,"❌ Link save করা যায়নি। আবার চেষ্টা করুন।",protect_content=True)

def process_info_dev(message): _process_info_link(message,"info_dev_url","Developer")
def process_info_channel(message): _process_info_link(message,"info_channel_url","Official Channel")
def process_info_notice(message): _process_info_link(message,"info_notice_url","Order Notice")
def process_info_support(message): _process_info_link(message,"info_support_url","Support Admin")

def process_add_info_link(message):
    if int(_message_actor_id(message)) not in admin_ids: return
    raw=(message.text or "").strip()
    parts=[x.strip() for x in raw.split("|",1)]
    if len(parts)!=2 or not parts[0] or not _valid_http_url(parts[1]):
        bot.send_message(message.chat.id,"❌ ভুল ফরম্যাট।\n\nসঠিক: <code>Title | https://example.com</code>\nআবার পাঠান অথবা /cancel দিন।",parse_mode="HTML",protect_content=True)
        return
    title,url=parts
    if len(title)>64:
        bot.send_message(message.chat.id,"❌ Title সর্বোচ্চ 64 characters হতে পারবে। আবার পাঠান অথবা /cancel দিন।",protect_content=True)
        return
    if _add_info_link(title,url,_message_actor_id(message)):
        _clear_admin_input_state(_message_actor_id(message))
        bot.send_message(message.chat.id,f"✅ <b>Info Link Saved Successfully</b>\n\n🔖 Title: <b>{title}</b>\n🔗 URL: <code>{url}</code>\n\n👤 User Information page-এ button এখনই দেখা যাবে।",parse_mode="HTML",reply_markup=types.InlineKeyboardMarkup().add(make_inline_button("🔗 Open Info Links",callback_data="info_links")),protect_content=True)
    else:
        bot.send_message(message.chat.id,"❌ Link save করা যায়নি। আবার চেষ্টা করুন।",protect_content=True)

def send_info_edit_list(message):
    if int(_message_actor_id(message)) not in admin_ids:return
    links=_load_info_links().get("links",[])
    if not links:
        bot.send_message(message.chat.id,"📭 কোনো custom Info Link নেই।",protect_content=True); return
    markup=types.InlineKeyboardMarkup(row_width=1)
    for item in links:
        markup.add(make_inline_button(f"✏️ {str(item.get('title','Link'))[:50]}",callback_data=f"info_edit_{item.get('id')}",style="primary"))
    markup.add(make_inline_button("⬅️ Back",callback_data="info_links",style="danger"))
    bot.send_message(message.chat.id,"✏️ <b>Edit Info Link</b> — একটি link নির্বাচন করুন:",parse_mode="HTML",reply_markup=markup,protect_content=True)


def process_edit_info_link(message,link_id):
    if int(_message_actor_id(message)) not in admin_ids:return
    parts=[p.strip() for p in (message.text or '').split('|',1)]
    if len(parts)!=2 or not parts[0] or not _valid_http_url(parts[1]):
        bot.send_message(message.chat.id,"❌ Format: <code>Title | https://example.com</code>",parse_mode="HTML",protect_content=True)
        bot.register_next_step_handler(message,process_edit_info_link,link_id); return
    title,url=parts
    if len(title)>64:
        bot.send_message(message.chat.id,"❌ Title সর্বোচ্চ 64 characters.",protect_content=True)
        bot.register_next_step_handler(message,process_edit_info_link,link_id); return
    data=_load_info_links(); found=False
    for item in data.get('links',[]):
        if str(item.get('id'))==str(link_id):
            item['title']=title; item['url']=url; item['updated_at']=datetime.now().isoformat(timespec='seconds'); found=True; break
    if not found or not _save_info_links(data):
        bot.send_message(message.chat.id,"❌ Link update করা যায়নি।",protect_content=True); return
    log_admin_activity(_message_actor_id(message),"Edited info link",f"id={link_id}, title={title}")
    bot.send_message(message.chat.id,"✅ <b>Info Link updated successfully.</b>",parse_mode="HTML",protect_content=True)

def send_info_link_list(message):
    if _message_actor_id(message) not in admin_ids: return
    links=_load_info_links().get("links",[])
    if not links:
        bot.send_message(message.chat.id,"📋 এখনো কোনো custom Info Link নেই।",protect_content=True); return
    markup=types.InlineKeyboardMarkup(row_width=1)
    for item in links:
        title=str(item.get("title","Link"))[:50]
        markup.add(make_inline_button(f"🗑️ {title}",callback_data=f"info_del_{item.get('id')}",style="danger"))
    lines=["📋 <b>Custom Info Links</b>",""]
    for i,item in enumerate(links,1):
        lines.append(f"{i}. <b>{item.get('title','')}</b> — <code>{item.get('url','')}</code>")
    bot.send_message(message.chat.id,"\n".join(lines),parse_mode="HTML",reply_markup=markup,protect_content=True)

def process_developer_info_text(message):
    if int(_message_actor_id(message)) not in admin_ids: return
    text=(message.text or "").strip()
    if not text:
        bot.send_message(message.chat.id,"❌ Developer Info খালি রাখা যাবে না।",protect_content=True); return
    if len(text)>3500:
        bot.send_message(message.chat.id,"❌ Developer Info সর্বোচ্চ 3500 characters দিন।",protect_content=True); return
    if set_system_setting("developer_info_text",text):
        _clear_admin_input_state(_message_actor_id(message))
        bot.send_message(message.chat.id,"✅ <b>Developer Info</b> successfully updated.",parse_mode="HTML",protect_content=True)
    else: bot.send_message(message.chat.id,"❌ Developer Info save করা যায়নি।",protect_content=True)

def send_info_link_status(message):
    if _message_actor_id(message) not in admin_ids:return
    custom=_load_info_links().get("links",[])
    text=("🔗 <b>Current Information Links</b>\n\n"
        f"</> Developer: <code>{get_system_setting('info_dev_url')}</code>\n"
        f"🤝 Official Channel: <code>{get_system_setting('info_channel_url')}</code>\n"
        f"📋 Order Notic: <code>{get_system_setting('info_notice_url')}</code>\n"
        f"💬 Support Admin: <code>{get_system_setting('info_support_url')}</code>\n\n"
        f"➕ Custom Links: <b>{len(custom)}</b>")
    bot.send_message(message.chat.id,text,parse_mode="HTML",protect_content=True)

def _logic_gift_code(message):
    bot.send_message(message.chat.id,"🎁 <b>Gift Code Redeem</b>\n\nআপনার Gift Code লিখুন অথবা সরাসরি <code>/redeem CODE</code> ব্যবহার করুন:",parse_mode="HTML",protect_content=True)
    bot.register_next_step_handler(message, process_redeem_gift_code)

# --- Text Handler Mapping ---
# --- Rich Bot Statistics ---
HOST_START_TIME = datetime.now()

def _format_uptime(seconds):
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days: parts.append(f"{days}d")
    if hours or days: parts.append(f"{hours}h")
    if minutes or hours or days: parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)

def send_bot_stats(message):
    """Admin-only host summary and detailed resource usage for every running user bot."""
    try:
        actor_id = int(_message_actor_id(message))
        if actor_id not in admin_ids:
            return
        _reap_dead_scripts()
        disk = shutil.disk_usage(BASE_DIR)
        disk_total = disk.total / (1024 ** 3)
        disk_used = disk.used / (1024 ** 3)
        disk_free = disk.free / (1024 ** 3)
        total_files = sum(len(v) for v in user_files.values())
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            try:
                pending = conn.execute("SELECT COUNT(*) FROM pending_uploads WHERE status='pending'").fetchone()[0]
                total_users = conn.execute("SELECT COUNT(*) FROM user_account").fetchone()[0]
                db_mb = os.path.getsize(DATABASE_PATH) / (1024 * 1024) if os.path.exists(DATABASE_PATH) else 0
            finally:
                conn.close()
        cpu = psutil.cpu_percent(interval=0.15)
        ram = psutil.virtual_memory()
        uptime = _format_uptime((datetime.now() - HOST_START_TIME).total_seconds())
        instances = len(BOT_INSTANCES) if "BOT_INSTANCES" in globals() else 1
        text = (
            "📊 <b>𝗕𝗢𝗧 𝗛𝗢𝗦𝗧𝗜𝗡𝗚 — ADMIN DASHBOARD</b>\n\n"
            f"👥 <b>Total Users:</b> <code>{total_users}</code>\n"
            f"👑 <b>Total Admins:</b> <code>{len(admin_ids)}</code>\n"
            f"📁 <b>Hosted Files:</b> <code>{total_files}</code>\n"
            f"🚀 <b>Running Bots:</b> <code>{len(bot_scripts)}</code>\n"
            f"⏳ <b>Pending Approvals:</b> <code>{pending}</code>\n"
            f"🚫 <b>Blocked Users:</b> <code>{len(blocked_users)}</code>\n"
            f"🔐 <b>Bot Lock:</b> <code>{'ON' if bot_locked else 'OFF'}</code>\n\n"
            "🖥 <b>𝗦𝗘𝗥𝗩𝗘𝗥 𝗥𝗘𝗦𝗢𝗨𝗥𝗖𝗘𝗦</b>\n"
            f"⚙️ CPU: <code>{cpu:.1f}%</code>\n"
            f"🧠 RAM: <code>{ram.percent:.1f}%</code> — Used <code>{ram.used / (1024**3):.2f} GB</code> / <code>{ram.total / (1024**3):.2f} GB</code>\n"
            f"🟢 RAM Available: <code>{ram.available / (1024**3):.2f} GB</code>\n"
            f"💾 Disk: <code>{disk_used:.2f}/{disk_total:.2f} GB</code> — Free <code>{disk_free:.2f} GB</code>\n"
            f"⏱️ Uptime: <code>{uptime}</code>\n"
            f"🗄️ Database: <code>{db_mb:.2f} MB</code>\n"
            f"🤖 Telegram Instances: <code>{instances}</code>\n"
            f"⚙️ Bot Count Cap: <code>{MAX_RUNNING_SCRIPTS if MAX_RUNNING_SCRIPTS > 0 else 'No fixed cap (RAM checked)'}</code>\n"
            f"🧠 Minimum Free RAM to start: <code>{MIN_FREE_RAM_MB} MB</code>"
        )
        bot.send_message(message.chat.id, text, parse_mode="HTML", protect_content=True)

        details = []
        for key, info in list(bot_scripts.items()):
            try:
                proc = info.get("process")
                if not proc or proc.poll() is not None:
                    continue
                pinfo = psutil.Process(proc.pid)
                rss_mb = pinfo.memory_info().rss / (1024 * 1024)
                child_cpu = pinfo.cpu_percent(interval=None)
                runtime = _format_uptime(max(0, (datetime.now() - info.get("start_time", datetime.now())).total_seconds()))
                owner = int(info.get("script_owner_id", 0))
                sub = get_subscription_status(owner)
                plan_line = f"{sub['name']} — {sub['remaining']}" if sub.get("active") else "Free / expired"
                details.append(
                    f"🤖 <b>{html.escape(str(info.get('file_name', key)))}</b>\n"
                    f"👤 Owner: <code>{owner}</code> | PID: <code>{proc.pid}</code>\n"
                    f"🧠 RAM: <code>{rss_mb:.1f} MB</code> | CPU: <code>{child_cpu:.1f}%</code>\n"
                    f"⏱ Runtime: <code>{html.escape(runtime)}</code>\n"
                    f"💎 Plan: <code>{html.escape(plan_line)}</code> | Type: <code>{html.escape(str(info.get('type', 'py')))}</code>"
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                details.append(f"🤖 <b>{html.escape(str(info.get('file_name', key)))}</b> — process details unavailable")
            except Exception as exc:
                logger.debug("Per-bot stats failed for %s: %s", key, exc)
        if not details:
            bot.send_message(message.chat.id, "📋 <b>Running Bot Details</b>\nএই মুহূর্তে কোনো running user bot নেই।", parse_mode="HTML", protect_content=True)
        else:
            chunk = "📋 <b>RUNNING BOT RESOURCE DETAILS</b>\n\n"
            for item in details:
                if len(chunk) + len(item) + 3 > 3800:
                    bot.send_message(message.chat.id, chunk, parse_mode="HTML", protect_content=True)
                    chunk = "📋 <b>CONTINUED — BOT DETAILS</b>\n\n"
                chunk += item + "\n\n━━━━━━━━━━━━━━\n\n"
            if chunk.strip():
                bot.send_message(message.chat.id, chunk, parse_mode="HTML", protect_content=True)
    except Exception as exc:
        logger.error("Bot stats error: %s", exc, exc_info=True)
        try:
            bot.send_message(message.chat.id, f"❌ Stats error: <code>{html.escape(str(exc)[:250])}</code>", parse_mode="HTML")
        except Exception:
            pass

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
    "ⓘ 𝗜𝗻𝗳𝗼𝗿𝗺𝗮𝘁𝗶𝗼𝗻": send_information,
    "ⓘ Information": send_information,
    "🎁 𝗚𝗶𝗳𝘁 𝗖𝗼𝗱𝗲": _logic_gift_code,
    "📊 𝗕𝗼𝘁 𝗦𝘁𝗮𝘁𝘀": send_bot_stats,
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

@bot.message_handler(commands=["redeem"])
def redeem_command(message):
    try:
        user_id=int(_message_actor_id(message))
        if user_id in blocked_users:
            return
        parts=(message.text or "").split(maxsplit=1)
        if len(parts)<2 or not parts[1].strip():
            bot.send_message(message.chat.id,"🎁 <b>Redeem Gift Code</b>\n\nব্যবহার করুন: <code>/redeem RBK100</code>",parse_mode="HTML",protect_content=True)
            return
        process_redeem_gift_code(SimpleNamespace(from_user=message.from_user, chat=message.chat, text=parts[1].strip()))
    except Exception as exc:
        logger.error("Redeem command error: %s",exc,exc_info=True)
        bot.send_message(message.chat.id,"❌ Gift Code redeem করা যায়নি। আবার চেষ্টা করুন।",protect_content=True)

@bot.message_handler(commands=["cancel"])
def cancel_command(message):
    user_id = int(_message_actor_id(message))
    clear_workflow_session(user_id)
    _clear_admin_input_state(user_id)
    _clear_gift_session(user_id)
    cancel_deposit(user_id)
    bot.send_message(
        message.chat.id,
        "❌ <b>Current input/session cancelled.</b>\n\nআপনি আবার যেকোনো কাজ শুরু করতে পারবেন।",
        parse_mode="HTML",
        reply_markup=create_reply_keyboard_main_menu(user_id),
        protect_content=True,
    )

@bot.message_handler(func=lambda message: True)
def handle_text_messages(message):
    try:
        user_id = int(_message_actor_id(message))
        text = message.text or ""

        # /cancel is handled before every other workflow so it can never be
        # consumed as an amount, TRX ID, search query, or gift code.
        if text.strip().lower() == "/cancel":
            clear_workflow_session(user_id)
            _clear_admin_input_state(user_id)
            _clear_gift_session(user_id)
            cancel_deposit(user_id)
            bot.send_message(
                message.chat.id,
                "❌ <b>Current input/session cancelled.</b>\n\nআপনি আবার যেকোনো কাজ শুরু করতে পারবেন।",
                parse_mode="HTML",
                reply_markup=create_reply_keyboard_main_menu(user_id),
                protect_content=True,
            )
            return

        if user_id in blocked_users:
            return

        # /redeem CODE is handled directly here because the catch-all text handler
        # is registered before the legacy command decorator in this large single file.
        if text.strip().lower().startswith("/redeem"):
            parts=text.strip().split(maxsplit=1)
            if len(parts)<2:
                bot.send_message(message.chat.id,"🎁 <b>Redeem Gift Code</b>\n\nব্যবহার করুন: <code>/redeem RBK100</code>",parse_mode="HTML",protect_content=True)
            else:
                message.text=parts[1].strip()
                process_redeem_gift_code(message)
            return

        if bot_locked and user_id not in admin_ids:
            bot.send_message(message.chat.id, "⚠️ <b>Bot is temporarily under maintenance.</b> Please try again later.", parse_mode="HTML", protect_content=True)
            return

        # Persistent generic input workflows are checked before the deposit flow.
        # This replaces volatile register_next_step_handler sessions.
        if dispatch_workflow_session(message):
            return

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
            
        if text in ("ⓘ Information", "ⓘ 𝗜𝗻𝗳𝗼𝗿𝗺𝗮𝘁𝗶𝗼𝗻", "Information"):
            send_information(message)
            return

        # Persistent admin input flow. This survives restart and avoids fragile
        # register_next_step_handler chains for the critical Info/Link controls.
        if user_id in admin_ids:
            if text.strip().lower() == "/cancel":
                had_state = bool(_get_admin_input_state(user_id) or _gift_session(user_id))
                _clear_admin_input_state(user_id)
                _clear_gift_session(user_id)
                if had_state:
                    bot.send_message(message.chat.id,"❌ Current input flow cancelled.\n\n🛡️ Admin Panel",reply_markup=create_admin_panel_inline(user_id),protect_content=True)
                else:
                    bot.send_message(message.chat.id,"ℹ️ কোনো active input flow নেই।",protect_content=True)
                return

            admin_state = _get_admin_input_state(user_id)
            if admin_state == "add_info_link":
                process_add_info_link(message)
                return
            if admin_state == "set_info_dev":
                process_info_dev(message)
                return
            if admin_state == "set_info_channel":
                process_info_channel(message)
                return
            if admin_state == "set_info_notice":
                process_info_notice(message)
                return
            if admin_state == "set_info_support":
                process_info_support(message)
                return
            if admin_state == "set_developer_info":
                process_developer_info_text(message)
                return

        # Persistent Admin Gift Code creation flow.
        if user_id in admin_ids and _gift_session(user_id):
            if _process_gift_creation_message(message):
                return

        if text == "👑 𝗖𝗼𝗻𝘁𝗮𝗰𝘁 𝗢𝘄𝗻𝗲𝗿":
            bot.send_message(message.chat.id, f"👑 **Owner:** {YOUR_USERNAME}", protect_content=True)
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
SECOND_BOT_TOKEN = ""  # Optional: put a second BotFather token here to enable BOT-2.
SECOND_ADMIN_ID = 8888777331  # Optional: put the second admin Telegram numeric ID here.

if not TOKEN or TOKEN == "PASTE_NEW_BOT_TOKEN_HERE":
    raise RuntimeError(
        "Bot token is missing. Set BOT_TOKEN in hosting environment variables or add a NEW BotFather token in TOKEN near the top of this file."
    )

APPROVAL_ADMIN_IDS = {int(OWNER_ID), int(ADMIN_ID)}
if SECOND_ADMIN_ID:
    APPROVAL_ADMIN_IDS.add(int(SECOND_ADMIN_ID))
    admin_ids.add(int(SECOND_ADMIN_ID))
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        conn.execute("INSERT OR IGNORE INTO admins (user_id, added_by) VALUES (?, ?)", (int(SECOND_ADMIN_ID), 0))
        conn.commit()
        conn.close()

def _safe_create_bot(token, label):
    """Create and validate a Telegram bot once; invalid optional tokens are disabled."""
    token = str(token or "").strip()
    if not token or token == "PUT_YOUR_BOT_TOKEN_HERE":
        return None
    try:
        candidate = telebot.TeleBot(token, parse_mode=None, threaded=True, num_threads=1)
        me = candidate.get_me()
        logger.info("%s connected successfully as @%s.", label, getattr(me, "username", "unknown"))
        return candidate
    except telebot.apihelper.ApiException as exc:
        logger.error("%s disabled: Telegram token/API validation failed: %s", label, exc)
        return None
    except Exception as exc:
        logger.error("%s disabled during startup validation: %s", label, exc)
        return None

BOT_INSTANCES = []
_main_bot = _safe_create_bot(TOKEN, "BOT-1")
if _main_bot is None:
    raise RuntimeError("BOT-1 token is invalid or could not connect. Check the TOKEN value in this file.")
BOT_INSTANCES.append(_main_bot)
_second_bot = _safe_create_bot(SECOND_BOT_TOKEN, "BOT-2")
if _second_bot is not None:
    BOT_INSTANCES.append(_second_bot)

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
    """Run a bot forever and automatically recover from transient network resets.

    A ConnectionResetError/requests ConnectionError is treated as temporary.
    The bot is stopped cleanly, waits with exponential backoff, then polling is
    started again on the same validated bot instance. A bad token (401) exits.
    """
    bot.bind(real_bot)
    logger.info("%s polling started.", label)
    backoff = 3
    while True:
        try:
            real_bot.infinity_polling(
                timeout=30,
                long_polling_timeout=25,
                skip_pending=True,
                allowed_updates=["message", "callback_query"],
            )
            # If polling returns without an exception, do not assume the bot is dead.
            # Re-enter polling after a short delay.
            backoff = 3
            logger.warning("%s polling returned; restarting polling in 2 seconds...", label)
            time.sleep(2)
        except telebot.apihelper.ApiException as exc:
            message = str(exc)
            if "401" in message or "Unauthorized" in message:
                logger.error(
                    "%s disabled after Telegram returned 401 Unauthorized. "
                    "Replace the BotFather token and restart.", label
                )
                return
            logger.warning("%s Telegram API error; retrying in %ss: %s", label, backoff, exc)
            try:
                real_bot.stop_polling()
            except Exception:
                pass
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
        except (ConnectionError, TimeoutError) as exc:
            logger.warning("%s network connection lost; auto-reconnecting in %ss: %s", label, backoff, exc)
            try:
                real_bot.stop_polling()
            except Exception:
                pass
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
        except Exception as exc:
            message = str(exc)
            if "Cannot allocate memory" in message or isinstance(exc, MemoryError):
                gc.collect()
                backoff = max(backoff, 20)
                logger.warning("%s RAM কম (ENOMEM); gc করে %ss পর আবার চেষ্টা...", label, backoff)
            elif "ConnectionResetError" in message or "Connection reset by peer" in message:
                logger.warning("%s connection reset by peer; auto-reconnecting in %ss.", label, backoff)
            else:
                logger.error("%s polling error; retrying in %ss: %s", label, backoff, exc, exc_info=True)
            try:
                real_bot.stop_polling()
            except Exception:
                pass
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)

if __name__ == "__main__":
    keep_alive()
    Thread(target=auto_stopper, daemon=True).start()
    logger.info("🚀 Premium File Host is starting with %d Telegram bot(s)...", len(BOT_INSTANCES))
    for idx, real_bot in enumerate(BOT_INSTANCES, 1):
        Thread(target=_poll_bot, args=(real_bot, f"BOT-{idx}"), daemon=True).start()
    while True:
        time.sleep(3600)
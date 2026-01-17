import asyncio
import random
import json
import logging
import os
import sqlite3
import requests
from datetime import datetime, timedelta
from pathlib import Path
from telethon import TelegramClient, events, functions, Button
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.errors import SessionPasswordNeededError

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, use system env vars only

API_ID = 36053254
API_HASH = '4c63aee24cbc1be5e593329370712e7f'
BOT_TOKEN = '8544528676:AAGWL7WuTONeTo5Lse6AiATtg4nEcssKuWc'
BOT_OWNER_ID = 6730216440

# ============= SUPER ADMINS =============
# Two super admins who can see global stats and manage other admins
SUPER_ADMINS = [6730216440, 5912533270]
# ============= END SUPER ADMINS =============

DB_NAME = 'bot_data.json'
SQLITE_DB = 'bot_advanced.db'
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============= RATE LIMITING & ROTATION SETTINGS =============
# Лимиты скорости отправки сообщений
MIN_MESSAGES_PER_HOUR = 20  # Минимум сообщений в час на аккаунт
MAX_MESSAGES_PER_HOUR = 40  # Максимум сообщений в час на аккаунт
DEFAULT_MESSAGES_PER_HOUR = 20  # По умолчанию используем консервативное значение

# Максимальное количество одновременно активных аккаунтов
DEFAULT_MAX_ACTIVE_ACCOUNTS = 2

# Интервал ротации аккаунтов (в секундах)
# По умолчанию: 4 часа (14400 секунд)
DEFAULT_ROTATION_INTERVAL = 14400

# Минимальный интервал между комментариями от разных аккаунтов в одном чате (в секундах)
MIN_INTERVAL_BETWEEN_OWN_ACCOUNTS = 300  # 5 минут

# Статусы аккаунтов
ACCOUNT_STATUS_ACTIVE = 'active'
ACCOUNT_STATUS_RESERVE = 'reserve'
ACCOUNT_STATUS_BROKEN = 'broken'
# ============= END RATE LIMITING & ROTATION SETTINGS =============

# YandexGPT configuration from environment variables
YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID', 'b1g4or5i5s66hklqfg06')
YANDEX_API_KEY = os.getenv('YANDEX_API_KEY', '')
YANDEX_GPT_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

def generate_neuro_comment(
    post_text: str,
    channel_theme: str = "general",
    temperature: float = 0.8,
    max_tokens: int = 120,
) -> str:
    """
    Генерирует короткий нейтрально‑радостный комментарий к посту с помощью YandexGPT.
    """
    # Fallback comments if API is not configured or fails
    fallback_comments = [
        "Отличный пост, очень вдохновляет! 😊",
        "Спасибо за интересный пост! 👍",
        "Классный материал, было интересно прочитать! 😊",
        "Полезная информация! 💡",
        "Супер контент, спасибо! 🔥"
    ]
    
    # Check if API key is configured
    if not YANDEX_API_KEY:
        logger.warning("YANDEX_API_KEY not configured, using fallback comments")
        return random.choice(fallback_comments)
    
    prompt = f"""
Создай короткий (20–50 слов) нейтрально-радостный комментарий к посту.

ТЕМА КАНАЛА: {channel_theme}
ТЕКСТ ПОСТА: {post_text[:600]}

Требования:
- Русский язык.
- Дружелюбный, живой тон.
- 1–2 подходящих эмодзи.
- Без ссылок, без прямой рекламы, без упоминания нейросетей и ИИ.
- Можно задать уточняющий вопрос или поддержать автора.
"""

    headers = {
        "Authorization": f"Api-Key {YANDEX_API_KEY}",
        "Content-Type": "application/json",
        "x-folder-id": YANDEX_FOLDER_ID,
    }

    payload = {
        "modelUri": f"gpt://{YANDEX_FOLDER_ID}/yandexgpt/latest",
        "completionOptions": {
            "stream": False,
            "temperature": float(temperature),
            "maxTokens": int(max_tokens),
        },
        "messages": [
            {
                "role": "user",
                "text": prompt,
            }
        ],
    }

    try:
        response = requests.post(YANDEX_GPT_URL, headers=headers, json=payload, timeout=30)
        if response.status_code != 200:
            logger.warning(f"YandexGPT API error: {response.status_code}")
            return random.choice(fallback_comments)
        
        data = response.json()
        text = data["result"]["alternatives"][0]["message"]["text"].strip()
        return text
    except Exception as e:
        logger.warning(f"YandexGPT generation failed: {e}")
        return random.choice(fallback_comments)

class UltimateCommentBot:
    def __init__(self):
        self.bot_client = TelegramClient('bot_session', API_ID, API_HASH)
        self.accounts_data = {}
        self.channels = []
        self.max_parallel_accounts = DEFAULT_MAX_ACTIVE_ACCOUNTS  # Количество одновременно активных аккаунтов
        self.templates = [
            'Отличный пост! 👍', 'Интересно! Спасибо!', 'Супер контент! 🔥',
            'Класс! 👌', 'Огонь! 🔥🔥', 'Согласен! 💯', 'Спасибо за контент! 🙌',
            'Супер! 👏', 'Круто! 💎', 'Лучший канал! 👑'
        ]
        self.bio_links = []
        self.admins = []
        self.monitoring = False
        self.monitoring_start_time = None  # Track when monitoring started
        self.stats = {
            'total_comments': 0,
            'blocked_accounts': [],
            'daily_comments': 0,
            'blocked_channels': []
        }
        # Track failed attempts: {channel_username: {phone1, phone2, ...}}
        self.channel_failed_attempts = {}
        # Track commented posts: {channel_username: {post_id1, post_id2, ...}}
        self.commented_posts = {}
        # Channel queue for round-robin distribution
        self.channel_queue = []
        self.channel_queue_index = 0
        self.conn = None
        # State management for account profiles management
        self.user_states = {}  # {user_id: {'state': 'waiting_avatar', 'account_num': 1, 'data': {}}}
        self.account_cache = {}  # Cache for account info from env
        # Authorization state management
        self.pending_auth = {}  # {chat_id: {'phone': '+123', 'proxy': ..., 'client': ..., 'message_id': 123, 'state': 'waiting_code'/'waiting_2fa', 'event': ...}}
        
        # ============= NEW: RATE LIMITING & ROTATION =============
        # Настройки лимитов скорости
        self.messages_per_hour = DEFAULT_MESSAGES_PER_HOUR  # Лимит сообщений в час на аккаунт
        self.rotation_interval = DEFAULT_ROTATION_INTERVAL  # Интервал ротации в секундах
        
        # Отслеживание активности аккаунтов: {phone: {'messages': [(timestamp1, channel1), ...], 'status': 'active/reserve/broken'}}
        self.account_activity = {}
        
        # Отслеживание последних комментариев в чатах: {channel_username: {'phone': phone, 'timestamp': timestamp}}
        self.last_comment_per_channel = {}
        
        # Время последней ротации
        self.last_rotation_time = None
        
        # Индекс для циклической ротации
        self.rotation_index = 0
        
        # ============= TEST MODE =============
        self.test_mode = False  # Флаг тестового режима
        self.test_channels = []  # Список тестовых каналов
        self.test_mode_speed_limit = 10  # Лимит в тестовом режиме (комм/час на аккаунт)
        # ============= END TEST MODE =============
        # ============= END NEW =============
        
        self.init_database()
        self.load_stats()
        self.load_data()
        self.init_account_statuses()  # Инициализация статусов аккаунтов
    
    def init_database(self):
        """Initialize SQLite database with required tables"""
        try:
            self.conn = sqlite3.connect(SQLITE_DB)
            cursor = self.conn.cursor()
            
            # Create blocked_accounts table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS blocked_accounts (
                    phone TEXT PRIMARY KEY,
                    block_date TEXT,
                    reason TEXT,
                    admin_id INTEGER DEFAULT NULL
                )
            ''')
            
            # Create comment_history table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS comment_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone TEXT,
                    channel TEXT,
                    comment TEXT,
                    date TEXT,
                    admin_id INTEGER DEFAULT NULL
                )
            ''')
            
            # Create parsed_channels table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS parsed_channels (
                    username TEXT PRIMARY KEY,
                    theme TEXT,
                    source TEXT DEFAULT 'parsed',
                    added_date TEXT,
                    admin_id INTEGER DEFAULT NULL
                )
            ''')
            
            # Create blocked_channels table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS blocked_channels (
                    username TEXT PRIMARY KEY,
                    block_date TEXT,
                    reason TEXT,
                    admin_id INTEGER DEFAULT NULL
                )
            ''')
            
            # Create profile_changes table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS profile_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone TEXT,
                    change_type TEXT,
                    old_value TEXT,
                    new_value TEXT,
                    change_date TEXT,
                    success INTEGER DEFAULT 1,
                    admin_id INTEGER DEFAULT NULL
                )
            ''')
            
            # Create account_stats table for detailed statistics
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS account_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone TEXT,
                    channel TEXT,
                    event_type TEXT,
                    timestamp TEXT,
                    success INTEGER DEFAULT 1,
                    error_message TEXT,
                    admin_id INTEGER DEFAULT NULL
                )
            ''')
            
            # Create index for faster queries
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_account_stats_phone 
                ON account_stats(phone)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_account_stats_timestamp 
                ON account_stats(timestamp)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_account_stats_channel 
                ON account_stats(channel)
            ''')
            
            # ============= MIGRATION: Add admin_id columns to existing tables =============
            # Try to add admin_id column to existing tables (will fail silently if already exists)
            tables_to_migrate = [
                'blocked_accounts', 'comment_history', 'parsed_channels',
                'blocked_channels', 'profile_changes', 'account_stats'
            ]
            
            for table in tables_to_migrate:
                try:
                    cursor.execute(f'ALTER TABLE {table} ADD COLUMN admin_id INTEGER DEFAULT NULL')
                    logger.info(f"Added admin_id column to {table}")
                except sqlite3.OperationalError:
                    # Column already exists, skip
                    pass
            # ============= END MIGRATION =============
            
            self.conn.commit()
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Database init error: {e}")
    
    def load_data(self):
        try:
            with open(DB_NAME, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.accounts_data = data.get('accounts', {})
                self.channels = data.get('channels', [])
                self.templates = data.get('templates', self.templates)
                self.bio_links = data.get('bio_links', [])
                self.admins = data.get('admins', [])
        except:
            self.save_data()
    
    def save_data(self):
        data = {
            'accounts': self.accounts_data,
            'channels': self.channels,
            'templates': self.templates,
            'bio_links': self.bio_links,
            'admins': self.admins
        }
        with open(DB_NAME, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def load_stats(self):
        try:
            with open('stats.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.stats = data.get('stats', self.stats)
        except:
            self.save_stats()
    
    def save_stats(self):
        data = {'stats': self.stats}
        with open('stats.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def init_account_statuses(self):
        """Инициализация статусов аккаунтов при запуске"""
        # Проверяем и устанавливаем статусы для всех аккаунтов
        active_count = 0
        for phone, data in self.accounts_data.items():
            # Если у аккаунта нет статуса, присваиваем его
            if 'status' not in data:
                # Если у аккаунта есть старое поле 'active', используем его
                if data.get('active', False) and active_count < self.max_parallel_accounts:
                    data['status'] = ACCOUNT_STATUS_ACTIVE
                    active_count += 1
                else:
                    data['status'] = ACCOUNT_STATUS_RESERVE
                # Удаляем старое поле 'active' если оно есть
                if 'active' in data:
                    del data['active']
            elif data['status'] == ACCOUNT_STATUS_ACTIVE:
                active_count += 1
            
            # Инициализируем структуру отслеживания активности
            if phone not in self.account_activity:
                self.account_activity[phone] = {
                    'messages': [],  # [(timestamp, channel), ...]
                    'status': data.get('status', ACCOUNT_STATUS_RESERVE)
                }
        
        # Если активных аккаунтов больше чем max_parallel_accounts, переводим лишние в резерв
        if active_count > self.max_parallel_accounts:
            logger.warning(f"⚠️ Found {active_count} active accounts, but max is {self.max_parallel_accounts}. Moving extras to reserve.")
            count = 0
            for phone, data in self.accounts_data.items():
                if data.get('status') == ACCOUNT_STATUS_ACTIVE:
                    count += 1
                    if count > self.max_parallel_accounts:
                        data['status'] = ACCOUNT_STATUS_RESERVE
                        self.account_activity[phone]['status'] = ACCOUNT_STATUS_RESERVE
                        logger.info(f"🔄 Account {data.get('name', phone)} moved to reserve (over limit)")
        
        # Если активных меньше чем max_parallel_accounts, активируем резервные
        elif active_count < self.max_parallel_accounts:
            needed = self.max_parallel_accounts - active_count
            logger.info(f"📊 Only {active_count} active accounts, activating {needed} more from reserve")
            for phone, data in self.accounts_data.items():
                if needed <= 0:
                    break
                if data.get('status') == ACCOUNT_STATUS_RESERVE and data.get('session'):
                    data['status'] = ACCOUNT_STATUS_ACTIVE
                    self.account_activity[phone]['status'] = ACCOUNT_STATUS_ACTIVE
                    logger.info(f"✅ Account {data.get('name', phone)} activated from reserve")
                    needed -= 1
        
        self.save_data()
        logger.info(f"✅ Account statuses initialized: {self.get_status_counts()}")
    
    def get_status_counts(self):
        """Получить количество аккаунтов по статусам"""
        counts = {
            ACCOUNT_STATUS_ACTIVE: 0,
            ACCOUNT_STATUS_RESERVE: 0,
            ACCOUNT_STATUS_BROKEN: 0
        }
        for data in self.accounts_data.values():
            status = data.get('status', ACCOUNT_STATUS_RESERVE)
            counts[status] = counts.get(status, 0) + 1
        return counts
    
    def get_account_status(self, phone):
        """Получить статус аккаунта"""
        if phone in self.accounts_data:
            return self.accounts_data[phone].get('status', ACCOUNT_STATUS_RESERVE)
        return None
    
    def set_account_status(self, phone, status, reason=""):
        """Установить статус аккаунта с логированием"""
        if phone not in self.accounts_data:
            logger.error(f"❌ Cannot set status for unknown account: {phone}")
            return False
        
        old_status = self.accounts_data[phone].get('status', ACCOUNT_STATUS_RESERVE)
        if old_status == status:
            return True  # Статус не изменился
        
        self.accounts_data[phone]['status'] = status
        if phone in self.account_activity:
            self.account_activity[phone]['status'] = status
        
        account_name = self.accounts_data[phone].get('name', phone)
        reason_str = f" ({reason})" if reason else ""
        logger.info(f"🔄 Account {account_name}: {old_status} → {status}{reason_str}")
        
        self.save_data()
        return True
    
    def can_account_send_message(self, phone):
        """Проверить, может ли аккаунт отправить сообщение с учетом лимитов скорости"""
        if phone not in self.account_activity:
            return True, 0
        
        current_time = datetime.now().timestamp()
        activity = self.account_activity[phone]
        
        # Проверяем статус аккаунта
        if activity['status'] != ACCOUNT_STATUS_ACTIVE:
            return False, 0
        
        # Очищаем старые записи (старше 1 часа)
        hour_ago = current_time - 3600
        activity['messages'] = [(ts, ch) for ts, ch in activity['messages'] if ts > hour_ago]
        
        # Проверяем лимит
        messages_last_hour = len(activity['messages'])
        if messages_last_hour >= self.messages_per_hour:
            # Вычисляем время до следующего возможного отправления
            oldest_msg_time = min(ts for ts, _ in activity['messages']) if activity['messages'] else current_time
            wait_time = int((oldest_msg_time + 3600) - current_time)
            return False, max(wait_time, 0)
        
        return True, 0
    
    def register_message_sent(self, phone, channel):
        """Зарегистрировать отправленное сообщение для отслеживания лимитов"""
        if phone not in self.account_activity:
            self.account_activity[phone] = {'messages': [], 'status': ACCOUNT_STATUS_ACTIVE}
        
        current_time = datetime.now().timestamp()
        self.account_activity[phone]['messages'].append((current_time, channel))
        
        # Обновляем последний комментарий в канале
        self.last_comment_per_channel[channel] = {
            'phone': phone,
            'timestamp': current_time
        }
    
    def can_account_comment_in_channel(self, phone, channel):
        """Проверить, может ли аккаунт комментировать в канале (защита от спама своими аккаунтами)"""
        if channel not in self.last_comment_per_channel:
            return True, 0
        
        last_comment = self.last_comment_per_channel[channel]
        last_phone = last_comment['phone']
        last_timestamp = last_comment['timestamp']
        
        # Если последний комментарий был от другого нашего аккаунта
        if last_phone != phone and last_phone in self.accounts_data:
            current_time = datetime.now().timestamp()
            time_since_last = current_time - last_timestamp
            
            if time_since_last < MIN_INTERVAL_BETWEEN_OWN_ACCOUNTS:
                wait_time = int(MIN_INTERVAL_BETWEEN_OWN_ACCOUNTS - time_since_last)
                return False, wait_time
        
        return True, 0
    
    async def add_comment_stat(self, phone, success=True, channel=None, error_message=None, admin_id=None):
        self.stats['total_comments'] += 1
        if success:
            self.stats['daily_comments'] += 1
        else:
            self.stats['blocked_accounts'].append(phone)
        if len(self.stats['blocked_accounts']) > 50:
            self.stats['blocked_accounts'] = self.stats['blocked_accounts'][-20:]
        
        # Save detailed stat to DB with admin_id
        if self.conn and phone:
            try:
                # If admin_id not provided, try to get it from account data
                if admin_id is None:
                    account_data = self.accounts_data.get(phone, {})
                    admin_id = account_data.get('admin_id')
                
                cursor = self.conn.cursor()
                event_type = 'comment_sent' if success else 'comment_failed'
                cursor.execute(
                    "INSERT INTO account_stats (phone, channel, event_type, timestamp, success, error_message, admin_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (phone, channel or '', event_type, datetime.now().isoformat(), 1 if success else 0, error_message or '', admin_id)
                )
                self.conn.commit()
            except Exception as e:
                logger.error(f"Error saving account stat: {e}")
        
        self.save_stats()
    
    async def mark_channel_failed_for_account(self, username, phone, reason):
        """Mark that this account failed to comment on this channel"""
        try:
            if username not in self.channel_failed_attempts:
                self.channel_failed_attempts[username] = {}
            
            # Track failures per account with reason
            if phone not in self.channel_failed_attempts[username]:
                self.channel_failed_attempts[username][phone] = {'count': 0, 'reasons': []}
            
            self.channel_failed_attempts[username][phone]['count'] += 1
            self.channel_failed_attempts[username][phone]['reasons'].append(reason)
            
            # Record error in DB for stats with admin_id
            if self.conn:
                try:
                    # Get admin_id from account data
                    account_data = self.accounts_data.get(phone, {})
                    admin_id = account_data.get('admin_id')
                    
                    cursor = self.conn.cursor()
                    cursor.execute(
                        "INSERT INTO account_stats (phone, channel, event_type, timestamp, success, error_message, admin_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (phone, username, 'comment_failed', datetime.now().isoformat(), 0, reason, admin_id)
                    )
                    self.conn.commit()
                except Exception as e:
                    logger.error(f"Error saving failure stat: {e}")
            
            # Count active accounts (NEW: use status instead of 'active' field)
            active_accounts = [p for p, data in self.accounts_data.items() 
                             if data.get('status') == ACCOUNT_STATUS_ACTIVE]
            failed_phones = len(self.channel_failed_attempts[username])
            
            # Count how many accounts have failed multiple times (3+ times means persistent issue)
            persistent_failures = sum(1 for data in self.channel_failed_attempts[username].values() 
                                    if data['count'] >= 3)
            
            logger.info(f"Channel {username}: {failed_phones}/{len(active_accounts)} accounts failed, "
                       f"{persistent_failures} with persistent issues")
            
            # Block channel only if:
            # 1. At least 50% of active accounts failed persistently (3+ times each)
            # 2. OR all active accounts failed at least once with same error
            threshold = max(2, len(active_accounts) // 2)  # At least 2 accounts or 50%
            
            if persistent_failures >= threshold:
                # Get most common reason
                all_reasons = []
                for data in self.channel_failed_attempts[username].values():
                    all_reasons.extend(data['reasons'])
                most_common = max(set(all_reasons), key=all_reasons.count) if all_reasons else reason
                await self.block_channel(username, f"{most_common} (confirmed by {persistent_failures} accounts)")
            elif failed_phones >= len(active_accounts) and len(active_accounts) > 0:
                # All accounts failed at least once
                logger.warning(f"Channel {username}: All accounts failed once, but not blocking yet (need 3 failures per account)")
        except Exception as e:
            logger.error(f"Error marking failed attempt for {username}: {e}")
    
    async def handle_account_ban(self, phone, reason):
        """Handle account ban by deactivating it and activating a reserve account"""
        logger.warning(f"🚫 Account ban detected: {phone} - {reason}")
        await self.replace_broken_account(phone, reason)
    
    async def block_channel(self, username, reason):
        """Block channel that doesn't allow comments from ALL accounts and remove from active list"""
        try:
            # Add to stats if not already there
            if username not in self.stats.get('blocked_channels', []):
                if 'blocked_channels' not in self.stats:
                    self.stats['blocked_channels'] = []
                self.stats['blocked_channels'].append(username)
                self.save_stats()
            
            # Add to database
            if self.conn:
                cursor = self.conn.cursor()
                cursor.execute(
                    "INSERT OR IGNORE INTO blocked_channels (username, block_date, reason) VALUES (?, ?, ?)",
                    (username, datetime.now().isoformat(), reason)
                )
                self.conn.commit()
            
            # Remove from active channels list
            self.channels = [
                ch for ch in self.channels
                if (ch.get('username') if isinstance(ch, dict) else str(ch)) != username
            ]
            self.save_data()
            logger.info(f"Blocked and removed channel: {username} - Reason: {reason} (all accounts failed)")
            
            # Clean up failed attempts tracking
            if username in self.channel_failed_attempts:
                del self.channel_failed_attempts[username]
        except Exception as e:
            logger.error(f"Error blocking channel {username}: {e}")
    
    async def rotate_accounts(self):
        """Ротация аккаунтов: выводит часть активных в резерв и активирует следующие из резерва"""
        try:
            # Получаем списки аккаунтов по статусам
            active_accounts = [(phone, data) for phone, data in self.accounts_data.items() 
                             if data.get('status') == ACCOUNT_STATUS_ACTIVE and data.get('session')]
            reserve_accounts = [(phone, data) for phone, data in self.accounts_data.items() 
                              if data.get('status') == ACCOUNT_STATUS_RESERVE and data.get('session')]
            
            if not reserve_accounts:
                logger.info("⚠️ No reserve accounts available for rotation")
                return
            
            if not active_accounts:
                logger.warning("⚠️ No active accounts to rotate")
                return
            
            # Определяем, сколько аккаунтов ротировать (минимум 1, максимум половину активных)
            num_to_rotate = max(1, min(len(active_accounts) // 2, len(reserve_accounts)))
            
            logger.info(f"🔄 Starting account rotation: {num_to_rotate} accounts")
            
            # Создаем упорядоченный список всех аккаунтов для цикличной ротации
            all_accounts_list = list(self.accounts_data.keys())
            
            # Находим текущие активные в общем списке и берем следующие по циклу
            accounts_to_deactivate = []
            accounts_to_activate = []
            
            # Берем первые N активных для деактивации
            for i in range(num_to_rotate):
                if i < len(active_accounts):
                    accounts_to_deactivate.append(active_accounts[i])
            
            # Берем следующие по порядку из резерва для активации
            for i in range(num_to_rotate):
                if i < len(reserve_accounts):
                    accounts_to_activate.append(reserve_accounts[i])
            
            # Выполняем ротацию
            for phone, data in accounts_to_deactivate:
                old_status = data.get('status')
                self.set_account_status(phone, ACCOUNT_STATUS_RESERVE, "Scheduled rotation")
                account_name = data.get('name', phone)
                logger.info(f"  🔵 {account_name} → RESERVE")
            
            for phone, data in accounts_to_activate:
                old_status = data.get('status')
                self.set_account_status(phone, ACCOUNT_STATUS_ACTIVE, "Rotation activation")
                account_name = data.get('name', phone)
                logger.info(f"  🟢 {account_name} → ACTIVE")
            
            # Обновляем время последней ротации
            self.last_rotation_time = datetime.now().timestamp()
            
            # Уведомляем владельца
            try:
                deactivated_names = ", ".join([data.get('name', phone) for phone, data in accounts_to_deactivate])
                activated_names = ", ".join([data.get('name', phone) for phone, data in accounts_to_activate])
                
                await self.bot_client.send_message(
                    BOT_OWNER_ID,
                    f"🔄 **Ротация аккаунтов выполнена**\n\n"
                    f"📤 В резерв: {deactivated_names}\n"
                    f"📥 Активированы: {activated_names}\n\n"
                    f"📊 Текущее состояние: {self.get_status_counts()}"
                )
            except Exception as notify_err:
                logger.error(f"Failed to notify owner about rotation: {notify_err}")
            
            logger.info(f"✅ Rotation completed. Current status: {self.get_status_counts()}")
            
        except Exception as e:
            logger.error(f"Error during account rotation: {e}")
    
    async def check_and_rotate_if_needed(self):
        """Проверить, нужна ли ротация, и выполнить её"""
        if self.last_rotation_time is None:
            self.last_rotation_time = datetime.now().timestamp()
            return
        
        current_time = datetime.now().timestamp()
        time_since_rotation = current_time - self.last_rotation_time
        
        if time_since_rotation >= self.rotation_interval:
            logger.info(f"⏰ Rotation interval reached ({time_since_rotation:.0f}s >= {self.rotation_interval}s)")
            await self.rotate_accounts()
    
    async def replace_broken_account(self, phone, reason):
        """Заменить сломанный аккаунт на резервный"""
        try:
            # Помечаем аккаунт как broken
            self.set_account_status(phone, ACCOUNT_STATUS_BROKEN, reason)
            account_name = self.accounts_data[phone].get('name', phone)
            
            # Ищем резервный аккаунт для замены
            reserve_accounts = [(p, data) for p, data in self.accounts_data.items() 
                              if data.get('status') == ACCOUNT_STATUS_RESERVE and data.get('session')]
            
            if reserve_accounts:
                # Активируем первый доступный резервный аккаунт
                reserve_phone, reserve_data = reserve_accounts[0]
                self.set_account_status(reserve_phone, ACCOUNT_STATUS_ACTIVE, f"Replacing {account_name}")
                reserve_name = reserve_data.get('name', reserve_phone)
                
                logger.info(f"✅ Replaced broken account: {account_name} → {reserve_name}")
                
                # Уведомляем владельца
                try:
                    await self.bot_client.send_message(
                        BOT_OWNER_ID,
                        f"⚠️ **Автоматическая замена аккаунта**\n\n"
                        f"🔴 Сломан: `{account_name}` ({phone})\n"
                        f"Причина: {reason}\n\n"
                        f"✅ Активирован резервный: `{reserve_name}` ({reserve_phone})\n\n"
                        f"📊 Состояние: {self.get_status_counts()}"
                    )
                except Exception as notify_err:
                    logger.error(f"Failed to notify owner: {notify_err}")
                
                return True
            else:
                logger.error(f"❌ No reserve accounts available to replace {account_name}!")
                try:
                    await self.bot_client.send_message(
                        BOT_OWNER_ID,
                        f"🚨 **ВНИМАНИЕ: Нет резервных аккаунтов!**\n\n"
                        f"🔴 Сломан: `{account_name}` ({phone})\n"
                        f"Причина: {reason}\n\n"
                        f"❌ Все резервные аккаунты уже активны или отсутствуют.\n\n"
                        f"📊 Состояние: {self.get_status_counts()}"
                    )
                except Exception as notify_err:
                    logger.error(f"Failed to notify owner: {notify_err}")
                
                return False
                
        except Exception as e:
            logger.error(f"Error replacing broken account: {e}")
            return False
    
    def is_super_admin(self, user_id):
        """Check if user is a super admin (can see global stats and manage admins)"""
        return user_id in SUPER_ADMINS
    
    async def is_admin(self, user_id):
        """Check if user is any admin (super admin or regular admin)"""
        return user_id in SUPER_ADMINS or user_id in self.admins
    
    def get_admin_id(self, user_id):
        """Get admin_id for filtering data. Super admins can see all data."""
        if self.is_super_admin(user_id):
            return None  # None means "all admins" for super admins
        return user_id  # Regular admins see only their own data
    
    async def authorize_account(self, phone, proxy=None, event=None):
        """Начинает процесс авторизации и сохраняет состояние в pending_auth"""
        try:
            client = TelegramClient(StringSession(''), API_ID, API_HASH, proxy=proxy)
            await client.connect()
            
            if not await client.is_user_authorized():
                await client.send_code_request(phone)
                logger.info(f"Код отправлен на {phone}")
                
                if event:
                    # Отправляем сообщение и сохраняем состояние
                    msg = await event.respond(f"📱 Код отправлен на `{phone}`\n\nОтветьте на это сообщение с кодом авторизации (5 цифр)")
                    
                    # Сохраняем состояние ожидания кода
                    self.pending_auth[event.chat_id] = {
                        'phone': phone,
                        'proxy': proxy,
                        'client': client,
                        'message_id': msg.id,
                        'state': 'waiting_code',
                        'event': event
                    }
                    logger.info(f"Сохранено состояние авторизации для chat_id={event.chat_id}, phone={phone}, msg_id={msg.id}")
                    
                    # Возвращаем None, чтобы показать, что процесс не завершен
                    return 'pending'
                else:
                    # Fallback на консоль (если нет event)
                    print(f"Код отправлен на {phone}")
                    code = input("Введите код из Telegram: ")
                    try:
                        await client.sign_in(phone, code)
                    except SessionPasswordNeededError:
                        password = input("Введите пароль 2FA: ")
                        await client.sign_in(password=password)
                    
                    me = await client.get_me()
                    session = client.session.save()
                    await client.disconnect()
                    
                    # Determine admin_id: None for super admins, user_id for regular admins
                    admin_id = None if (event and self.is_super_admin(event.sender_id)) else (event.sender_id if event else None)
                    
                    return {
                        'session': session,
                        'active': True,
                        'name': me.first_name or 'Без имени',
                        'username': getattr(me, 'username', None),
                        'phone': phone,
                        'proxy': proxy,
                        'admin_id': admin_id
                    }
            else:
                # Уже авторизован
                me = await client.get_me()
                session = client.session.save()
                await client.disconnect()
                
                # Determine admin_id: None for super admins, user_id for regular admins
                admin_id = None if (event and self.is_super_admin(event.sender_id)) else (event.sender_id if event else None)
                
                return {
                    'session': session,
                    'active': True,
                    'name': me.first_name or 'Без имени',
                    'username': getattr(me, 'username', None),
                    'phone': phone,
                    'proxy': proxy,
                    'admin_id': admin_id
                }
                
        except Exception as e:
            logger.error(f"Ошибка авторизации {phone}: {e}")
            if event:
                await event.respond(f"❌ Ошибка: {str(e)}")
            # Очистка состояния при ошибке
            if event and event.chat_id in self.pending_auth:
                try:
                    await self.pending_auth[event.chat_id]['client'].disconnect()
                except:
                    pass
                del self.pending_auth[event.chat_id]
            return None
    
    async def set_account_bio(self, session_data, bio_text):
        try:
            client = TelegramClient(StringSession(session_data['session']), API_ID, API_HASH, proxy=session_data.get('proxy'))
            await client.connect()
            if await client.is_user_authorized():
                await client(UpdateProfileRequest(about=bio_text))
                await client.disconnect()
                return True
        except:
            pass
        return False
    
    # ============= PROFILE MANAGEMENT FUNCTIONS =============
    
    def get_all_accounts_from_env(self):
        """
        Динамически получает все аккаунты из переменных окружения.
        Ищет ACCOUNT_N_PHONE, ACCOUNT_N_SESSION, ACCOUNT_N_PROXY (где N = 1, 2, 3...)
        Возвращает список кортежей: [(номер, телефон, сессия, прокси), ...]
        """
        if self.account_cache:
            return self.account_cache.get('accounts', [])
        
        accounts = []
        n = 1
        while True:
            phone_key = f'ACCOUNT_{n}_PHONE'
            phone = os.getenv(phone_key)
            
            if not phone:
                break  # Нет больше аккаунтов
            
            session = os.getenv(f'ACCOUNT_{n}_SESSION', '')
            proxy_str = os.getenv(f'ACCOUNT_{n}_PROXY', '')
            
            # Parse proxy if exists (format: socks5:host:port:rdns:user:pass OR socks5:host:port:user:pass)
            proxy = None
            if proxy_str:
                try:
                    parts = proxy_str.split(':')
                    # Telethon expects: (type, host, port, rdns, username, password)
                    if len(parts) == 6:
                        # Full format: socks5:host:port:rdns:user:pass
                        proxy = (parts[0], parts[1], int(parts[2]), 
                                parts[3].lower() == 'true', parts[4], parts[5])
                    elif len(parts) >= 5:
                        # Short format: socks5:host:port:user:pass (rdns=True by default)
                        proxy = (parts[0], parts[1], int(parts[2]), True, parts[3], parts[4])
                except Exception as e:
                    logger.warning(f"Failed to parse proxy for ACCOUNT_{n}: {e}")
            
            accounts.append((n, phone, session, proxy))
            n += 1
        
        # Cache results
        self.account_cache['accounts'] = accounts
        logger.info(f"Found {len(accounts)} accounts in environment variables")
        return accounts
    
    def create_accounts_keyboard(self, page=0, per_page=5):
        """
        Создаёт inline клавиатуру со списком аккаунтов с пагинацией.
        """
        accounts = self.get_all_accounts_from_env()
        
        if not accounts:
            return [[Button.inline("❌ Аккаунты не найдены", b"no_accounts")]]
        
        total_accounts = len(accounts)
        total_pages = (total_accounts + per_page - 1) // per_page
        page = max(0, min(page, total_pages - 1))  # Validate page
        
        start_idx = page * per_page
        end_idx = min(start_idx + per_page, total_accounts)
        
        buttons = []
        
        # Account buttons
        for i in range(start_idx, end_idx):
            num, phone, session, proxy = accounts[i]
            status = "✅" if session else "❌"
            button_text = f"{status} Аккаунт {num} - {phone}"
            buttons.append([Button.inline(button_text, f"acc_{num}".encode())])
        
        # Pagination buttons
        nav_buttons = []
        if page > 0:
            nav_buttons.append(Button.inline("◀️ Назад", f"acc_page_{page-1}".encode()))
        
        if total_pages > 1:
            nav_buttons.append(Button.inline(f"📄 {page+1}/{total_pages}", b"page_info"))
        
        if page < total_pages - 1:
            nav_buttons.append(Button.inline("Вперёд ▶️", f"acc_page_{page+1}".encode()))
        
        if nav_buttons:
            buttons.append(nav_buttons)
        
        # Main menu button
        buttons.append([Button.inline("🏠 Главное меню", b"main_menu")])
        
        return buttons
    
    def create_account_menu_keyboard(self, account_num):
        """
        Создаёт меню для конкретного аккаунта с кнопками:
        - Аватарка
        - Имя и Фамилия
        - О себе (Био)
        - Назад
        """
        buttons = [
            [Button.inline("📷 Аватарка", f"acc_{account_num}_avatar".encode())],
            [Button.inline("👤 Имя и Фамилия", f"acc_{account_num}_name".encode())],
            [Button.inline("📝 О себе (Био)", f"acc_{account_num}_bio".encode())],
            [Button.inline("◀️ Назад к списку", b"back_to_accounts")],
            [Button.inline("🏠 Главное меню", b"main_menu")]
        ]
        return buttons
    
    async def get_account_info(self, account_num):
        """
        Получает информацию об аккаунте из переменных окружения
        и пытается получить текущие данные профиля из Telegram.
        """
        accounts = self.get_all_accounts_from_env()
        account_data = None
        
        for num, phone, session, proxy in accounts:
            if num == account_num:
                account_data = {
                    'num': num,
                    'phone': phone,
                    'session': session,
                    'proxy': proxy
                }
                break
        
        if not account_data:
            return None
        
        # Try to get current profile info
        if account_data['session']:
            try:
                client = TelegramClient(
                    StringSession(account_data['session']), 
                    API_ID, 
                    API_HASH,
                    proxy=account_data.get('proxy')
                )
                await client.connect()
                
                if await client.is_user_authorized():
                    me = await client.get_me()
                    account_data['first_name'] = me.first_name or ''
                    account_data['last_name'] = me.last_name or ''
                    account_data['username'] = me.username or ''
                    
                    # Get full user info to retrieve bio
                    try:
                        full_user = await client(GetFullUserRequest(me))
                        account_data['bio'] = full_user.full_user.about or ''
                    except Exception:
                        account_data['bio'] = ''
                    
                    account_data['authorized'] = True
                else:
                    account_data['authorized'] = False
                
                await client.disconnect()
            except Exception as e:
                logger.error(f"Error getting account info for {account_num}: {e}")
                account_data['authorized'] = False
        else:
            account_data['authorized'] = False
        
        return account_data
    
    async def apply_account_changes(self, account_num, avatar_file=None, first_name=None, last_name=None, bio=None):
        """
        Применяет изменения к профилю аккаунта:
        - avatar_file: путь к файлу изображения
        - first_name: новое имя
        - last_name: новая фамилия
        - bio: новая информация о себе
        
        Возвращает (success: bool, message: str)
        """
        try:
            account_info = await self.get_account_info(account_num)
            
            if not account_info:
                return False, f"❌ Аккаунт {account_num} не найден"
            
            if not account_info.get('authorized'):
                return False, f"❌ Аккаунт {account_num} не авторизован"
            
            # Create client
            client = TelegramClient(
                StringSession(account_info['session']), 
                API_ID, 
                API_HASH,
                proxy=account_info.get('proxy')
            )
            
            await client.connect()
            
            if not await client.is_user_authorized():
                await client.disconnect()
                return False, f"❌ Аккаунт {account_num} потерял авторизацию"
            
            results = []
            
            # Update avatar
            if avatar_file and os.path.exists(avatar_file):
                try:
                    await client(UploadProfilePhotoRequest(
                        file=await client.upload_file(avatar_file)
                    ))
                    results.append("✅ Аватарка обновлена")
                    logger.info(f"Avatar updated for account {account_num}")
                except Exception as e:
                    results.append(f"❌ Ошибка загрузки аватарки: {str(e)[:50]}")
                    logger.error(f"Avatar upload error for account {account_num}: {e}")
            
            # Update name and/or bio
            if first_name is not None or last_name is not None or bio is not None:
                try:
                    # Get current values if not provided
                    if first_name is None:
                        first_name = account_info.get('first_name', '')
                    if last_name is None:
                        last_name = account_info.get('last_name', '')
                    if bio is None:
                        bio = account_info.get('bio', '')
                    
                    await client(UpdateProfileRequest(
                        first_name=first_name or '',
                        last_name=last_name or '',
                        about=bio or ''
                    ))
                    
                    if first_name is not None or last_name is not None:
                        results.append(f"✅ Имя обновлено: {first_name} {last_name}")
                    if bio is not None:
                        results.append(f"✅ Био обновлено")
                    
                    logger.info(f"Profile updated for account {account_num}")
                except Exception as e:
                    results.append(f"❌ Ошибка обновления профиля: {str(e)[:50]}")
                    logger.error(f"Profile update error for account {account_num}: {e}")
            
            await client.disconnect()
            
            if results:
                return True, "\n".join(results)
            else:
                return False, "❌ Нечего обновлять"
                
        except Exception as e:
            logger.error(f"Error applying changes to account {account_num}: {e}")
            return False, f"❌ Ошибка: {str(e)[:100]}"
    
    async def clear_user_state(self, user_id):
        """Очищает состояние пользователя"""
        if user_id in self.user_states:
            # Clean up temp files if any
            state = self.user_states[user_id]
            if 'temp_avatar' in state.get('data', {}):
                temp_file = state['data']['temp_avatar']
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except:
                        pass
            
            del self.user_states[user_id]
    
    async def save_temp_avatar(self, user_id, file_path):
        """Сохраняет временный файл аватарки"""
        # Create temp directory if not exists
        temp_dir = Path("/tmp/bot_avatars")
        temp_dir.mkdir(exist_ok=True)
        
        # Generate unique filename
        filename = f"avatar_{user_id}_{datetime.now().timestamp()}.jpg"
        temp_path = temp_dir / filename
        
        # Copy file
        import shutil
        shutil.copy(file_path, temp_path)
        
        return str(temp_path)
    
    async def log_profile_change(self, phone, change_type, old_value, new_value, success=True):
        """Логирует изменение профиля в БД"""
        try:
            if self.conn:
                cursor = self.conn.cursor()
                cursor.execute('''
                    INSERT INTO profile_changes (phone, change_type, old_value, new_value, change_date, success)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (phone, change_type, old_value or '', new_value or '', 
                      datetime.now().isoformat(), 1 if success else 0))
                self.conn.commit()
                logger.info(f"Profile change logged: {phone} - {change_type}")
        except Exception as e:
            logger.error(f"Error logging profile change: {e}")
    
    # ============= END PROFILE MANAGEMENT FUNCTIONS =============
    
    async def start(self):
        await self.bot_client.start(bot_token=BOT_TOKEN)
        self.setup_handlers()
        logger.info("@comapc_bot ULTIMATE ЗАПУЩЕН!")
    
    def setup_handlers(self):
        @self.bot_client.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            # Only owner and admins can use the bot
            if not await self.is_admin(event.sender_id):
                await event.respond("❌ У вас нет доступа к этому боту.")
                return
            
            text = f"""**@comapc_bot ULTIMATE**
=

Владелец: `{BOT_OWNER_ID}`
Админов: `{len(self.admins)}`

Аккаунтов: `{len(self.accounts_data)}`
Каналов: `{len(self.channels)}`
Шаблонов: `{len(self.templates)}`

**/help** - все команды"""
            await event.respond(text)
        
        @self.bot_client.on(events.NewMessage(pattern='/help'))
        async def help_handler(event):
            if not await self.is_admin(event.sender_id): return
            text = """**📱 АККАУНТЫ:**
`/auth +79123456789 [socks5:host:port:user:pass]` - авторизовать
`/accounts` - управление профилями (аватар, имя, био) 🆕
`/listaccounts` - все аккаунты (🟢 active / 🔵 reserve / 🔴 broken)
`/activeaccounts` - только активные ✅
`/reserveaccounts` - только резервные 🔄
`/blockedaccounts` - сломанные/заблокированные 🚫
`/delaccount +79123456789` - удалить
`/toggleaccount +79123456789` - переключить active ⇄ reserve

**👤 УПРАВЛЕНИЕ ПРОФИЛЕМ:**
`/setname` - изменить имя (выбор аккаунта → ввод имени)
`/setbio` - изменить био (выбор аккаунта → ввод био)
`/setavatar` - загрузить аватар (выбор аккаунта → отправка фото)
`/profile` - показать профили всех активных аккаунтов

**⚙️ НАСТРОЙКИ:**
`/setparallel 2` - кол-во одновременно активных аккаунтов
`/getparallel` - текущие настройки
`/setratelimit 20` - лимит сообщений/час на аккаунт (20-40) 🆕
`/getratelimit` - текущий лимит скорости 🆕
`/setrotation 14400` - интервал ротации в секундах (по умолчанию 4ч) 🆕
`/getrotation` - текущий интервал ротации 🆕
`/rotatenow` - выполнить ротацию немедленно 🆕
`/accountstats` - статистика активности аккаунтов 🆕

**📢 КАНАЛЫ:**
`/addchannel @username` - добавить
`/listchannels` - список
`/delchannel @username` - удалить
`/searchchannels тема` - поиск по теме
`/addparsed тема 10` - добавить найденные в работу

**💬 КОММЕНТАРИИ:**
`/listtemplates` - шаблоны
`/addtemplate Текст!` - новый
`/edittemplate 1 Текст` - изменить
`/del-template 2` - удалить
`/cleartemplates` - очистить

**🤖 АВТО:**
`/startmon` - ЗАПУСТИТЬ (с автоматической ротацией)
`/stopmon` - остановить
`/safetyinfo` - настройки безопасности

**📊 СТАТИСТИКА:**
`/stats` - подробная статистика
`/listparsed` - спарсенные каналы
`/listbans` - заблокированные аккаунты
`/listblockedchannels` - каналы без комментариев
`/history` - история комментариев
`/resetfails` - сбросить счетчики неудач
`/showfails` - показать текущие неудачи

**🧪 ТЕСТОВЫЙ РЕЖИМ:**
`/testmode` - статус тестового режима
`/testmode on @channel1 @channel2` - включить с каналами
`/testmode off` - выключить
`/testmode speed 10` - установить скорость (комм/час)

**🔗 BIO:**
`/addbio t.me/link` - добавить
`/setbioall` - применить всем активным

**👑 АДМИНЫ:**
`/addadmin 123456789` - новый админ"""
            await event.respond(text)
        
        @self.bot_client.on(events.NewMessage(pattern='/auth'))
        async def auth_account(event):
            if not await self.is_admin(event.sender_id): return
            try:
                parts = event.text.split()
                phone = parts[1]
                proxy = None
                if len(parts) > 2:
                    proxy_parts = parts[2].split(':')
                    # Telethon expects: (type, host, port, rdns, username, password)
                    if len(proxy_parts) == 6:
                        # Full format: socks5:host:port:rdns:user:pass
                        proxy = (proxy_parts[0], proxy_parts[1], int(proxy_parts[2]), 
                                proxy_parts[3].lower() == 'true', proxy_parts[4], proxy_parts[5])
                    elif len(proxy_parts) == 5:
                        # Short format: socks5:host:port:user:pass (rdns=True by default)
                        proxy = (proxy_parts[0], proxy_parts[1], int(proxy_parts[2]), 
                                True, proxy_parts[3], proxy_parts[4])
                await event.respond(f"🔄 Начинаем авторизацию: `{phone}`")
                result = await self.authorize_account(phone, proxy, event)
                
                # Если результат 'pending', значит ждём ввода кода через обработчик сообщений
                if result == 'pending':
                    logger.info(f"Авторизация {phone} в режиме ожидания кода")
                    # Не отвечаем здесь - ответим после получения кода
                elif result:
                    # Успешная авторизация (уже был авторизован)
                    self.accounts_data[phone] = result
                    self.save_data()
                    await event.respond(f"✅ **{result['name']}** авторизован!\n@{result.get('username', 'нет')}\n`{phone}` ✅ АКТИВЕН")
                else:
                    await event.respond("❌ Ошибка авторизации!")
            except Exception as e:
                logger.error(f"Ошибка в /auth: {e}")
                await event.respond(f"❌ Ошибка: `{str(e)[:50]}`")
        
        # Обработчик для входящих сообщений (для перехвата кодов авторизации и паролей 2FA)
        @self.bot_client.on(events.NewMessage(func=lambda e: not e.text.startswith('/')))
        async def handle_auth_code(event):
            """Обрабатывает входящие сообщения для авторизации"""
            if not await self.is_admin(event.sender_id):
                return
            
            chat_id = event.chat_id
            
            # Проверяем, есть ли ожидание авторизации для этого чата
            if chat_id not in self.pending_auth:
                # Нет ожидания - игнорируем
                return
            
            auth_data = self.pending_auth[chat_id]
            logger.info(f"Получено сообщение в чате с pending_auth: chat_id={chat_id}, user_id={event.sender_id}")
            logger.info(f"pending_auth[{chat_id}] = {{'phone': '{auth_data['phone']}', 'state': '{auth_data['state']}', 'message_id': {auth_data['message_id']}}}")
            
            # Проверяем, что это ответ на наше сообщение
            if not event.reply_to_msg_id:
                logger.warning(f"Сообщение не является ответом (reply_to_msg_id=None), игнорируем")
                return
            
            if event.reply_to_msg_id != auth_data['message_id']:
                logger.warning(f"Ответ на другое сообщение: reply_to={event.reply_to_msg_id}, ожидаем={auth_data['message_id']}")
                return
            
            # Получаем данные
            phone = auth_data['phone']
            proxy = auth_data['proxy']
            client = auth_data['client']
            state = auth_data['state']
            code_or_password = event.text.strip()
            
            try:
                if state == 'waiting_code':
                    logger.info(f"Получен код авторизации для {phone}: {code_or_password}")
                    
                    try:
                        await client.sign_in(phone, code_or_password)
                        logger.info(f"Аккаунт {phone} успешно авторизован")
                        
                        # Успешная авторизация!
                        me = await client.get_me()
                        session = client.session.save()
                        await client.disconnect()
                        
                        result = {
                            'session': session,
                            'active': True,
                            'name': me.first_name or 'Без имени',
                            'username': getattr(me, 'username', None),
                            'phone': phone,
                            'proxy': proxy
                        }
                        
                        # Сохраняем в базу
                        self.accounts_data[phone] = result
                        self.save_data()
                        
                        # Очищаем состояние
                        del self.pending_auth[chat_id]
                        
                        await event.respond(f"✅ **{result['name']}** авторизован!\n@{result.get('username', 'нет')}\n`{phone}` ✅ АКТИВЕН")
                        
                    except SessionPasswordNeededError:
                        # Нужен пароль 2FA
                        logger.info(f"Для {phone} требуется пароль 2FA")
                        msg = await event.respond(f"🔐 Требуется пароль 2FA\n\nОтветьте на это сообщение с паролем двухфакторной аутентификации")
                        
                        # Обновляем состояние
                        auth_data['state'] = 'waiting_2fa'
                        auth_data['message_id'] = msg.id
                        logger.info(f"Обновлено состояние на waiting_2fa, новый message_id={msg.id}")
                        
                elif state == 'waiting_2fa':
                    logger.info(f"Получен пароль 2FA для {phone}")
                    
                    await client.sign_in(password=code_or_password)
                    logger.info(f"Аккаунт {phone} успешно авторизован (с 2FA)")
                    
                    # Успешная авторизация!
                    me = await client.get_me()
                    session = client.session.save()
                    await client.disconnect()
                    
                    result = {
                        'session': session,
                        'active': True,
                        'name': me.first_name or 'Без имени',
                        'username': getattr(me, 'username', None),
                        'phone': phone,
                        'proxy': proxy
                    }
                    
                    # Сохраняем в базу
                    self.accounts_data[phone] = result
                    self.save_data()
                    
                    # Очищаем состояние
                    del self.pending_auth[chat_id]
                    
                    await event.respond(f"✅ **{result['name']}** авторизован (с 2FA)!\n@{result.get('username', 'нет')}\n`{phone}` ✅ АКТИВЕН")
                    
            except Exception as e:
                logger.error(f"Ошибка при обработке кода/пароля для {phone}: {e}")
                await event.respond(f"❌ Ошибка: {str(e)}\n\nПопробуйте заново: /auth {phone}")
                
                # Очистка при ошибке
                try:
                    await client.disconnect()
                except:
                    pass
                if chat_id in self.pending_auth:
                    del self.pending_auth[chat_id]
        
        @self.bot_client.on(events.NewMessage(pattern='/listaccounts'))
        async def list_accounts(event):
            if not await self.is_admin(event.sender_id): return
            
            # Determine admin_id for filtering
            admin_id = self.get_admin_id(event.sender_id)
            
            # Filter accounts by admin_id
            if admin_id is None:  # Super admin - show all
                filtered_accounts = self.accounts_data
            else:  # Regular admin - show only their accounts
                filtered_accounts = {phone: data for phone, data in self.accounts_data.items()
                                   if data.get('admin_id') == admin_id}
            
            if not filtered_accounts:
                await event.respond("Нет авторизованных аккаунтов")
                return
            
            # Show all accounts, split into multiple messages if needed
            total = len(filtered_accounts)
            accounts_per_msg = 20
            accounts_list = list(filtered_accounts.items())
            
            for batch_num in range(0, total, accounts_per_msg):
                batch_accounts = accounts_list[batch_num:batch_num + accounts_per_msg]
                text = f"АККАУНТЫ ({total}) - Часть {batch_num//accounts_per_msg + 1}:\n\n"
                
                for i, (phone, data) in enumerate(batch_accounts, batch_num + 1):
                    # NEW: Используем новые статусы
                    status_val = data.get('status', ACCOUNT_STATUS_RESERVE)
                    if status_val == ACCOUNT_STATUS_ACTIVE:
                        status = "✅ ACTIVE"
                    elif status_val == ACCOUNT_STATUS_BROKEN:
                        status = "🔴 BROKEN"
                    else:
                        status = "🔵 RESERVE"
                    
                    name = data.get('name', 'Не авторизован')
                    username = data.get('username', 'нет')
                    text += f"{i}. {status} `{name}` (@{username})\n`   {phone}`\n"
                
                await event.respond(text)
                # Small delay between messages to avoid flood
                if batch_num + accounts_per_msg < total:
                    await asyncio.sleep(0.5)
        
        @self.bot_client.on(events.NewMessage(pattern='/delaccount'))
        async def del_account(event):
            if not await self.is_admin(event.sender_id): return
            try:
                phone = event.text.split(maxsplit=1)[1]
                if phone in self.accounts_data:
                    del self.accounts_data[phone]
                    self.save_data()
                    await event.respond(f"Удален: `{phone}`")
                else:
                    await event.respond("Аккаунт не найден")
            except:
                await event.respond("Формат: `/delaccount +79123456789`")
        
        @self.bot_client.on(events.NewMessage(pattern='/toggleaccount'))
        async def toggle_account(event):
            """Toggle account between active and reserve mode"""
            if not await self.is_admin(event.sender_id): return
            try:
                phone = event.text.split(maxsplit=1)[1]
                if phone in self.accounts_data:
                    # NEW: Используем новые статусы
                    current_status = self.accounts_data[phone].get('status', ACCOUNT_STATUS_RESERVE)
                    
                    # Переключаем между active и reserve (игнорируем broken)
                    if current_status == ACCOUNT_STATUS_ACTIVE:
                        new_status = ACCOUNT_STATUS_RESERVE
                        status_text = "🔵 RESERVE"
                    elif current_status == ACCOUNT_STATUS_BROKEN:
                        # Если аккаунт broken, переводим в reserve
                        new_status = ACCOUNT_STATUS_RESERVE
                        status_text = "🔵 RESERVE (восстановлен из broken)"
                    else:
                        new_status = ACCOUNT_STATUS_ACTIVE
                        status_text = "✅ ACTIVE"
                    
                    self.set_account_status(phone, new_status, "Manual toggle")
                    account_name = self.accounts_data[phone].get('name', phone)
                    
                    await event.respond(
                        f"Аккаунт `{account_name}` ({phone})\n"
                        f"Статус изменен: {status_text}\n\n"
                        f"📊 Текущее состояние: {self.get_status_counts()}"
                    )
                else:
                    await event.respond("Аккаунт не найден")
            except:
                await event.respond(
                    "Формат: `/toggleaccount +79123456789`\n\n"
                    "⚠️ Эта команда переключает статус ОДНОГО аккаунта:\n"
                    "✅ ACTIVE → 🔵 RESERVE\n"
                    "🔵 RESERVE → ✅ ACTIVE\n"
                    "🔴 BROKEN → 🔵 RESERVE"
                )
        
        @self.bot_client.on(events.NewMessage(pattern='/activeaccounts'))
        async def active_accounts(event):
            """Show only active accounts"""
            if not await self.is_admin(event.sender_id): return
            
            # NEW: Используем новые статусы
            active = {phone: data for phone, data in self.accounts_data.items() 
                     if data.get('status') == ACCOUNT_STATUS_ACTIVE}
            
            if not active:
                await event.respond("❌ Нет активных аккаунтов")
                return
            
            text = f"✅ **АКТИВНЫЕ АККАУНТЫ** ({len(active)}/{self.max_parallel_accounts}):\n\n"
            for i, (phone, data) in enumerate(active.items(), 1):
                name = data.get('name', 'Не авторизован')
                username = data.get('username', 'нет')
                
                # Показываем статистику сообщений
                if phone in self.account_activity:
                    msgs_count = len(self.account_activity[phone]['messages'])
                    text += f"{i}. `{name}` (@{username})\n   `{phone}` (💬 {msgs_count}/h)\n"
                else:
                    text += f"{i}. `{name}` (@{username})\n   `{phone}`\n"
            
            text += f"\n📊 Лимит: {self.messages_per_hour} сообщ/час на аккаунт"
            await event.respond(text)
        
        @self.bot_client.on(events.NewMessage(pattern='/reserveaccounts'))
        async def reserve_accounts(event):
            """Show only reserve accounts"""
            if not await self.is_admin(event.sender_id): return
            
            # NEW: Используем новые статусы
            reserve = {phone: data for phone, data in self.accounts_data.items() 
                      if data.get('status') == ACCOUNT_STATUS_RESERVE and data.get('session')}
            
            if not reserve:
                await event.respond(
                    "❌ Нет резервных аккаунтов\n\n"
                    "💡 Используйте `/toggleaccount +номер` чтобы перевести аккаунт в резерв"
                )
                return
            
            text = f"🔵 **РЕЗЕРВНЫЕ АККАУНТЫ** ({len(reserve)}):\n\n"
            for i, (phone, data) in enumerate(reserve.items(), 1):
                name = data.get('name', 'Не авторизован')
                username = data.get('username', 'нет')
                text += f"{i}. `{name}` (@{username})\n   `{phone}`\n"
            
            text += f"\n💡 Эти аккаунты автоматически активируются при бане активных\n"
            text += f"🔄 Ротация каждые {self.rotation_interval // 3600} часов"
            await event.respond(text)
        
        @self.bot_client.on(events.NewMessage(pattern='/blockedaccounts'))
        async def blocked_accounts_cmd(event):
            """Show blocked/broken accounts with reasons from database"""
            if not await self.is_admin(event.sender_id): return
            
            # NEW: Показываем аккаунты со статусом BROKEN
            broken = {phone: data for phone, data in self.accounts_data.items() 
                     if data.get('status') == ACCOUNT_STATUS_BROKEN}
            
            text = f"🔴 **СЛОМАННЫЕ АККАУНТЫ** ({len(broken)}):\n\n"
            
            if not broken:
                text += "✅ Нет сломанных аккаунтов\n\n"
            else:
                for i, (phone, data) in enumerate(broken.items(), 1):
                    name = data.get('name', 'Не авторизован')
                    username = data.get('username', 'нет')
                    text += f"{i}. `{name}` (@{username})\n   `{phone}`\n"
                text += "\n"
            
            # Также проверяем БД для истории блокировок
            if self.conn:
                try:
                    cursor = self.conn.cursor()
                    cursor.execute("SELECT phone, block_date, reason FROM blocked_accounts ORDER BY block_date DESC LIMIT 10")
                    blocked = cursor.fetchall()
                    
                    if blocked:
                        text += f"\n📜 **История блокировок** (последние 10):\n\n"
                        for phone, block_date, reason in blocked:
                            date_str = block_date[:10] if block_date else "N/A"
                            text += f"• `{phone}`\n  📅 {date_str}\n  ℹ️ {reason}\n\n"
                except Exception as e:
                    text += f"\n⚠️ Ошибка чтения БД: {e}"
            
            text += "\n💡 Используйте `/toggleaccount +номер` чтобы восстановить аккаунт в резерв"
            
            await event.respond(text)
            
            try:
                cursor = self.conn.cursor()
                cursor.execute("SELECT phone, block_date, reason FROM blocked_accounts ORDER BY block_date DESC LIMIT 50")
                blocked = cursor.fetchall()
                
                if not blocked:
                    await event.respond("✅ Нет заблокированных аккаунтов")
                    return
                
                text = f"🚫 **ЗАБЛОКИРОВАННЫЕ АККАУНТЫ** ({len(blocked)}):\n\n"
                for i, (phone, block_date, reason) in enumerate(blocked, 1):
                    # Format date
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(block_date)
                        date_str = dt.strftime("%d.%m.%Y %H:%M")
                    except:
                        date_str = block_date[:16]
                    
                    # Get account name if exists
                    name = self.accounts_data.get(phone, {}).get('name', 'Неизвестен')
                    
                    text += f"{i}. `{name}` ({phone})\n"
                    text += f"   📅 {date_str}\n"
                    text += f"   ⚠️ {reason}\n\n"
                
                await event.respond(text)
            except Exception as e:
                logger.error(f"Blocked accounts error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:50]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/setparallel'))
        async def set_parallel(event):
            """Set number of parallel working accounts"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                num = int(event.text.split(maxsplit=1)[1])
                if num < 1 or num > 10:
                    await event.respond("❌ Число должно быть от 1 до 10")
                    return
                
                self.max_parallel_accounts = num
                await event.respond(f"✅ Количество параллельных аккаунтов установлено: **{num}**\n\n⚠️ Изменения вступят в силу после перезапуска мониторинга (`/stopmon` → `/startmon`)")
            except (IndexError, ValueError):
                await event.respond("Формат: `/setparallel 3`\n\n📊 Рекомендации:\n• 1-2 аккаунта - безопасно\n• 3-4 аккаунта - средний риск\n• 5+ аккаунтов - высокий риск банов")
        
        @self.bot_client.on(events.NewMessage(pattern='/getparallel'))
        async def get_parallel(event):
            """Show current number of parallel accounts"""
            if not await self.is_admin(event.sender_id): return
            
            # NEW: Используем новые статусы
            active_count = sum(1 for d in self.accounts_data.values() if d.get('status') == ACCOUNT_STATUS_ACTIVE)
            actual_parallel = min(active_count, self.max_parallel_accounts)
            
            text = f"📊 **НАСТРОЙКИ ПАРАЛЛЕЛЬНОЙ РАБОТЫ:**\n\n"
            text += f"⚙️ Установлено: {self.max_parallel_accounts} аккаунтов\n"
            text += f"✅ Активных аккаунтов: {active_count}\n"
            text += f"🚀 Реально работает: {actual_parallel} аккаунтов\n\n"
            
            if actual_parallel < self.max_parallel_accounts:
                text += f"💡 Для использования {self.max_parallel_accounts} аккаунтов нужно иметь минимум {self.max_parallel_accounts} активных"
            
            await event.respond(text)
        
        # ============= NEW RATE LIMITING COMMANDS =============
        @self.bot_client.on(events.NewMessage(pattern='/setratelimit'))
        async def set_rate_limit(event):
            """Set messages per hour limit for each account"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                limit = int(event.text.split(maxsplit=1)[1])
                if limit < MIN_MESSAGES_PER_HOUR or limit > MAX_MESSAGES_PER_HOUR:
                    await event.respond(
                        f"❌ Лимит должен быть от {MIN_MESSAGES_PER_HOUR} до {MAX_MESSAGES_PER_HOUR} сообщений/час\n\n"
                        f"📊 Рекомендации:\n"
                        f"• 20 msg/h - максимально безопасно (по умолчанию)\n"
                        f"• 30 msg/h - средний режим\n"
                        f"• 40 msg/h - агрессивный режим (риск флуда)"
                    )
                    return
                
                self.messages_per_hour = limit
                await event.respond(
                    f"✅ Лимит установлен: **{limit} сообщений/час** на аккаунт\n\n"
                    f"⏱️ Это означает ~{3600 // limit} секунд между сообщениями\n"
                    f"⚠️ Изменения применяются немедленно ко всем активным аккаунтам"
                )
                logger.info(f"Rate limit set to {limit} messages/hour")
            except (IndexError, ValueError):
                await event.respond(
                    f"Формат: `/setratelimit 20`\n\n"
                    f"Диапазон: {MIN_MESSAGES_PER_HOUR}-{MAX_MESSAGES_PER_HOUR} сообщений/час\n"
                    f"Текущий лимит: {self.messages_per_hour} msg/h"
                )
        
        @self.bot_client.on(events.NewMessage(pattern='/getratelimit'))
        async def get_rate_limit(event):
            """Show current rate limit settings"""
            if not await self.is_admin(event.sender_id): return
            
            avg_interval = 3600 // self.messages_per_hour if self.messages_per_hour > 0 else 0
            
            text = f"⚡ **ЛИМИТЫ СКОРОСТИ:**\n\n"
            text += f"📊 Лимит: **{self.messages_per_hour} сообщений/час** на аккаунт\n"
            text += f"⏱️ Средний интервал: ~{avg_interval} сек между сообщениями\n"
            text += f"🛡️ Защита от спама: {MIN_INTERVAL_BETWEEN_OWN_ACCOUNTS} сек между своими аккаунтами\n\n"
            text += f"💡 Диапазон: {MIN_MESSAGES_PER_HOUR}-{MAX_MESSAGES_PER_HOUR} msg/h"
            
            await event.respond(text)
        
        @self.bot_client.on(events.NewMessage(pattern='/setrotation'))
        async def set_rotation_interval(event):
            """Set account rotation interval in seconds"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                interval = int(event.text.split(maxsplit=1)[1])
                if interval < 3600:  # Minimum 1 hour
                    await event.respond(
                        "❌ Интервал не может быть меньше 1 часа (3600 секунд)\n\n"
                        "📊 Рекомендации:\n"
                        "• 14400 сек (4 часа) - по умолчанию\n"
                        "• 21600 сек (6 часов) - средний\n"
                        "• 28800 сек (8 часов) - долгий"
                    )
                    return
                
                self.rotation_interval = interval
                hours = interval // 3600
                await event.respond(
                    f"✅ Интервал ротации установлен: **{interval} секунд** ({hours}ч)\n\n"
                    f"🔄 Следующая ротация через ~{hours}ч\n"
                    f"⚠️ Изменения применяются немедленно"
                )
                logger.info(f"Rotation interval set to {interval} seconds ({hours}h)")
            except (IndexError, ValueError):
                current_hours = self.rotation_interval // 3600
                await event.respond(
                    f"Формат: `/setrotation 14400`\n\n"
                    f"Текущий интервал: {self.rotation_interval} сек ({current_hours}ч)\n"
                    f"Минимум: 3600 сек (1ч)"
                )
        
        @self.bot_client.on(events.NewMessage(pattern='/getrotation'))
        async def get_rotation_info(event):
            """Show rotation interval and status"""
            if not await self.is_admin(event.sender_id): return
            
            hours = self.rotation_interval // 3600
            
            text = f"🔄 **РОТАЦИЯ АККАУНТОВ:**\n\n"
            text += f"⚙️ Интервал: **{self.rotation_interval} сек** ({hours}ч)\n"
            
            if self.last_rotation_time:
                from datetime import datetime
                last_rot = datetime.fromtimestamp(self.last_rotation_time)
                time_since = datetime.now().timestamp() - self.last_rotation_time
                time_until = self.rotation_interval - time_since
                
                text += f"🕐 Последняя ротация: {last_rot.strftime('%H:%M:%S')}\n"
                text += f"⏳ Прошло: {int(time_since // 60)} мин\n"
                
                if time_until > 0:
                    text += f"⏰ Следующая через: {int(time_until // 60)} мин\n"
                else:
                    text += f"⚠️ Ротация просрочена на {int(-time_until // 60)} мин\n"
            else:
                text += f"❌ Ротация еще не выполнялась\n"
            
            text += f"\n💡 Используйте `/rotatenow` для немедленной ротации"
            
            await event.respond(text)
        
        @self.bot_client.on(events.NewMessage(pattern='/rotatenow'))
        async def rotate_now(event):
            """Perform account rotation immediately"""
            if not await self.is_admin(event.sender_id): return
            
            if not self.monitoring:
                await event.respond("❌ Мониторинг не запущен. Запустите `/startmon` сначала")
                return
            
            await event.respond("🔄 Выполняю ротацию аккаунтов...")
            await self.rotate_accounts()
            await event.respond("✅ Ротация выполнена успешно!")
        
        @self.bot_client.on(events.NewMessage(pattern='/accountstats'))
        async def account_stats(event):
            """Show detailed account activity statistics"""
            if not await self.is_admin(event.sender_id): return
            
            text = f"📊 **СТАТИСТИКА АКТИВНОСТИ АККАУНТОВ:**\n\n"
            
            active_accounts = [(phone, data) for phone, data in self.accounts_data.items() 
                             if data.get('status') == ACCOUNT_STATUS_ACTIVE]
            
            if not active_accounts:
                text += "❌ Нет активных аккаунтов\n"
            else:
                for phone, data in active_accounts:
                    name = data.get('name', phone)
                    
                    if phone in self.account_activity:
                        activity = self.account_activity[phone]
                        msgs_last_hour = len(activity['messages'])
                        
                        can_send, wait_time = self.can_account_send_message(phone)
                        status_icon = "✅" if can_send else "⏳"
                        
                        text += f"{status_icon} **{name}**\n"
                        text += f"   📱 `{phone}`\n"
                        text += f"   💬 {msgs_last_hour}/{self.messages_per_hour} сообщений за час\n"
                        
                        if not can_send:
                            text += f"   ⏱️ Ожидание: {wait_time // 60} мин {wait_time % 60} сек\n"
                        
                        text += "\n"
                    else:
                        text += f"⚪ **{name}** - нет активности\n\n"
            
            text += f"\n📈 Лимит: {self.messages_per_hour} msg/h на аккаунт"
            
            await event.respond(text)
        # ============= END NEW COMMANDS =============
        
        @self.bot_client.on(events.NewMessage(pattern='/addchannel'))
        async def add_channel(event):
            if not await self.is_admin(event.sender_id):
                logger.info(f"Unauthorized access attempt from {event.sender_id}")
                return
            try:
                username = event.text.split(maxsplit=1)[1]
                # Ensure @ prefix for consistency
                if not username.startswith('@'):
                    username = '@' + username
                logger.info(f"Trying to add channel: {username}")
                # Check if channel already exists
                existing_usernames = [ch.get('username') if isinstance(ch, dict) else ch for ch in self.channels]
                if username not in existing_usernames:
                    self.channels.append({'username': username})
                    self.save_data()
                    logger.info(f"Channel {username} added successfully")
                    await event.respond(f"✅ Канал `{username}` добавлен")
                else:
                    logger.info(f"Channel {username} already exists")
                    await event.respond("❌ Уже добавлен")
            except Exception as e:
                logger.error(f"Error adding channel: {e}")
                await event.respond("❌ Формат: `/addchannel @username`")
        
        @self.bot_client.on(events.NewMessage(pattern='/searchchannels (.+)'))
        async def search_channels(event):
            if not await self.is_admin(event.sender_id): return
            try:
                query = event.pattern_match.group(1).strip()
                await event.respond(f"🔍 Ищу каналы по '{query}'...")
                
                # Use user account instead of bot (bots can't search)
                user_account = None
                for phone, data in self.accounts_data.items():
                    if data.get('session'):
                        user_account = (phone, data)
                        break
                
                if not user_account:
                    await event.respond("❌ Нет авторизованных аккаунтов для поиска")
                    return
                
                phone, account_data = user_account
                client = TelegramClient(StringSession(account_data['session']), API_ID, API_HASH, proxy=account_data.get('proxy'))
                
                try:
                    await client.connect()
                    if not await client.is_user_authorized():
                        await event.respond(f"❌ Аккаунт {phone} не авторизован")
                        await client.disconnect()
                        return
                    
                    result = await client(functions.contacts.SearchRequest(q=query, limit=50))
                    channels = []
                    for chat in result.chats:
                        if hasattr(chat, 'username') and chat.username and chat.username.strip():
                            channels.append(chat.username)
                    
                    if channels:
                        msg = f"✅ Найдено {len(channels)} каналов по '{query}':\n\n"
                        for i, ch in enumerate(channels[:15], 1):
                            msg += f"{i}. @{ch}\n"
                        
                        if len(channels) > 15:
                            msg += f"\n... и еще {len(channels)-15}"
                        
                        msg += f"\n\n💡 Используйте:\n"
                        msg += f"`/addparsed {query} 10` - добавить 10 каналов в работу\n"
                        msg += f"`/addparsed {query} all` - добавить все каналы"
                        
                        await event.respond(msg)
                        
                        # Save to parsed_channels database
                        if self.conn:
                            cursor = self.conn.cursor()
                            added_count = 0
                            for ch in channels:
                                try:
                                    # Add @ prefix to channel username
                                    ch_with_at = ch if ch.startswith('@') else '@' + ch
                                    cursor.execute(
                                        "INSERT OR IGNORE INTO parsed_channels (username, theme, source, added_date) VALUES (?, ?, ?, ?)",
                                        (ch_with_at, query, 'search', datetime.now().isoformat())
                                    )
                                    if cursor.rowcount > 0:
                                        added_count += 1
                                except Exception as e:
                                    logger.error(f"DB insert error: {e}")
                            self.conn.commit()
                            await event.respond(f"💾 Сохранено {added_count} новых каналов в БД\n\nИспользуйте `/addparsed {query} 10` чтобы добавить их в работу")
                    else:
                        await event.respond("❌ Каналы не найдены")
                except Exception as e:
                    logger.error(f"Search error: {e}")
                    await event.respond(f"❌ Ошибка поиска: {str(e)[:100]}")
                finally:
                    try:
                        await client.disconnect()
                    except:
                        pass
            except Exception as outer_e:
                logger.error(f"Outer search error: {outer_e}")
                await event.respond("Формат: `/searchchannels новости`")
        
        @self.bot_client.on(events.NewMessage(pattern='/addparsed'))
        async def add_parsed(event):
            """Add parsed channels from database to active channel list"""
            if not await self.is_admin(event.sender_id): return
            
            if not self.conn:
                await event.respond("❌ БД недоступна")
                return
            
            try:
                parts = event.text.split()
                if len(parts) < 2:
                    await event.respond("Формат: `/addparsed [тема] [количество|all]`\n\nПример:\n`/addparsed новости 10` - добавить 10 каналов\n`/addparsed all 20` - добавить 20 из всех тем\n`/addparsed новости all` - добавить все каналы темы")
                    return
                
                theme = parts[1]
                limit = parts[2] if len(parts) > 2 else "10"
                
                cursor = self.conn.cursor()
                
                # Get parsed channels
                if theme.lower() == 'all':
                    cursor.execute("SELECT username FROM parsed_channels")
                else:
                    cursor.execute("SELECT username FROM parsed_channels WHERE theme LIKE ?", (f"%{theme}%",))
                
                parsed = cursor.fetchall()
                
                if not parsed:
                    await event.respond(f"❌ Нет спарсенных каналов по теме '{theme}'\n\nИспользуйте `/listparsed` для просмотра всех")
                    return
                
                # Determine how many to add
                if limit.lower() == 'all':
                    channels_to_add = [p[0] for p in parsed]
                else:
                    try:
                        count = int(limit)
                        channels_to_add = [p[0] for p in parsed[:count]]
                    except ValueError:
                        await event.respond("❌ Неверное количество. Используйте число или 'all'")
                        return
                
                # Get existing channel usernames
                existing = {ch.get('username') if isinstance(ch, dict) else ch for ch in self.channels}
                
                # Add new channels
                added = 0
                for username in channels_to_add:
                    if username not in existing:
                        self.channels.append({'username': username})
                        added += 1
                
                self.save_data()
                
                msg = f"✅ Добавлено каналов: {added}\n"
                msg += f"📊 Всего каналов теперь: {len(self.channels)}\n\n"
                
                if added > 0:
                    msg += f"💡 Новые каналы:\n"
                    for i, username in enumerate([u for u in channels_to_add if u not in existing][:10], 1):
                        # Display with @ (add if not present)
                        display_name = username if username.startswith('@') else '@' + username
                        msg += f"{i}. {display_name}\n"
                    if added > 10:
                        msg += f"... и еще {added - 10}\n"
                
                await event.respond(msg)
                
            except Exception as e:
                logger.error(f"Add parsed error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/findchannels'))
        async def find_channels(event):
            """Find channels with 50k+ subscribers and open comments"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                # Parse command: /findchannels @channel1 @channel2 @channel3
                text_parts = event.text.split()
                
                if len(text_parts) < 2:
                    await event.respond(
                        "**🔍 ПОИСК ПОДХОДЯЩИХ КАНАЛОВ**\n\n"
                        "Формат: `/findchannels @channel1 @channel2 @channel3 ...`\n\n"
                        "**Критерии поиска:**\n"
                        "✅ От 50,000 подписчиков\n"
                        "✅ Публичные каналы (без вступления)\n"
                        "✅ Открытые комментарии\n\n"
                        "**Пример:**\n"
                        "`/findchannels @durov @telegram @channel`"
                    )
                    return
                
                # Extract channel usernames
                channels_to_check = [ch.strip() for ch in text_parts[1:]]
                
                if not channels_to_check:
                    await event.respond("❌ Укажите хотя бы один канал для проверки")
                    return
                
                # Get active account
                user_account = None
                for phone, data in self.accounts_data.items():
                    if data.get('status') == ACCOUNT_STATUS_ACTIVE and data.get('session'):
                        user_account = (phone, data)
                        break
                
                if not user_account:
                    await event.respond("❌ Нет активных аккаунтов для проверки каналов")
                    return
                
                phone, account_data = user_account
                
                await event.respond(
                    f"🔍 Начинаю проверку {len(channels_to_check)} каналов...\n"
                    f"Используется аккаунт: {account_data.get('name', phone)}\n\n"
                    f"⏳ Это может занять несколько минут..."
                )
                
                # Create client
                client = TelegramClient(StringSession(account_data['session']), API_ID, API_HASH, proxy=account_data.get('proxy'))
                
                try:
                    await client.connect()
                    
                    if not await client.is_user_authorized():
                        await event.respond("❌ Аккаунт не авторизован")
                        return
                    
                    found_channels = []
                    
                    for i, channel_username in enumerate(channels_to_check, 1):
                        try:
                            # Get channel entity
                            entity = await client.get_entity(channel_username)
                            
                            # Check if it's a channel
                            from telethon.tl.types import Channel
                            if not isinstance(entity, Channel):
                                logger.info(f"❌ {channel_username}: не является каналом")
                                continue
                            
                            # Check subscribers
                            participants_count = getattr(entity, 'participants_count', 0)
                            
                            if participants_count < 50000:
                                logger.info(f"❌ {channel_username}: только {participants_count} подписчиков")
                                continue
                            
                            # Check if public
                            if entity.broadcast and not entity.megagroup:
                                join_request = getattr(entity, 'join_request', False)
                                
                                if join_request:
                                    logger.info(f"❌ {channel_username}: требуется заявка")
                                    continue
                                
                                # Check comments
                                messages = await client.get_messages(entity, limit=5)
                                
                                has_comments = False
                                for msg in messages:
                                    if hasattr(msg, 'replies') and msg.replies:
                                        if hasattr(msg.replies, 'comments') and msg.replies.comments:
                                            has_comments = True
                                            break
                                
                                if has_comments:
                                    found_channels.append({
                                        'username': channel_username,
                                        'title': entity.title,
                                        'subscribers': participants_count,
                                        'link': f"https://t.me/{channel_username}"
                                    })
                                    logger.info(f"✅ {channel_username}: ПОДХОДИТ!")
                                else:
                                    logger.info(f"❌ {channel_username}: комментарии недоступны")
                            
                        except Exception as e:
                            logger.error(f"❌ {channel_username}: ошибка - {e}")
                        
                        # Delay between checks
                        await asyncio.sleep(2)
                        
                        # Progress update every 5 channels
                        if i % 5 == 0:
                            await event.respond(f"⏳ Проверено {i}/{len(channels_to_check)}...")
                    
                    # Send results
                    if found_channels:
                        result_text = f"✅ **НАЙДЕНО ПОДХОДЯЩИХ КАНАЛОВ: {len(found_channels)}**\n\n"
                        
                        for i, ch in enumerate(found_channels, 1):
                            result_text += f"{i}. **@{ch['username']}**\n"
                            result_text += f"   {ch['title']}\n"
                            result_text += f"   👥 {ch['subscribers']:,} подписчиков\n"
                            result_text += f"   🔗 {ch['link']}\n\n"
                        
                        result_text += "\n📋 **СПИСОК ДЛЯ КОПИРОВАНИЯ:**\n"
                        for ch in found_channels:
                            result_text += f"@{ch['username']}\n"
                        
                        await event.respond(result_text)
                    else:
                        await event.respond(
                            f"❌ Из {len(channels_to_check)} проверенных каналов не найдено ни одного подходящего.\n\n"
                            f"**Возможные причины:**\n"
                            f"• Менее 50,000 подписчиков\n"
                            f"• Комментарии отключены\n"
                            f"• Требуется вступление в канал\n"
                            f"• Канал приватный"
                        )
                
                finally:
                    await client.disconnect()
                    
            except Exception as e:
                logger.error(f"Find channels error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:200]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/listchannels'))
        async def list_channels(event):
            if not await self.is_admin(event.sender_id): return
            if not self.channels:
                await event.respond("Нет каналов")
                return
            
            # Show all channels, split into multiple messages if needed
            total = len(self.channels)
            channels_per_msg = 50
            
            for batch_num in range(0, total, channels_per_msg):
                batch_channels = self.channels[batch_num:batch_num + channels_per_msg]
                text = f"КАНАЛЫ ({total}) - Часть {batch_num//channels_per_msg + 1}:\n\n"
                
                for i, ch in enumerate(batch_channels, batch_num + 1):
                    username = ch.get('username') if isinstance(ch, dict) else ch
                    # Display with @ (add if not present)
                    display_name = username if username.startswith('@') else '@' + username
                    text += f"{i}. `{display_name}`\n"
                
                await event.respond(text)
                # Small delay between messages to avoid flood
                if batch_num + channels_per_msg < total:
                    await asyncio.sleep(0.5)
        
        @self.bot_client.on(events.NewMessage(pattern='/delchannel'))
        async def del_channel(event):
            if not await self.is_admin(event.sender_id): return
            try:
                username = event.text.split(maxsplit=1)[1]
                # Ensure @ prefix for consistency
                if not username.startswith('@'):
                    username = '@' + username
                # Remove channel from list
                initial_count = len(self.channels)
                self.channels = [ch for ch in self.channels 
                               if (ch.get('username') if isinstance(ch, dict) else ch) != username]
                removed = initial_count - len(self.channels)
                self.save_data()
                if removed > 0:
                    await event.respond(f"Удален: `{username}`")
                else:
                    await event.respond(f"Канал `{username}` не найден")
            except:
                await event.respond("Формат: `/delchannel @username`")
        
        @self.bot_client.on(events.NewMessage(pattern='/listtemplates'))
        async def list_templates(event):
            if not await self.is_admin(event.sender_id): return
            text = f"Шаблоны ({len(self.templates)})\n\n"
            for i, template in enumerate(self.templates, 1):
                text += f"{i}. `{template}`\n"
            text += "\n**/addtemplate текст**\n**/edittemplate 1 текст**"
            await event.respond(text)
        
        @self.bot_client.on(events.NewMessage(pattern='/addtemplate'))
        async def add_template(event):
            if not await self.is_admin(event.sender_id): return
            try:
                new_template = event.text.replace('/addtemplate ', '').strip()
                if new_template and new_template not in self.templates:
                    self.templates.append(new_template)
                    self.save_data()
                    await event.respond(f"Добавлен: `{new_template}`")
                else:
                    await event.respond("Уже есть или пусто!")
            except:
                await event.respond("Формат: `/addtemplate Крутой пост!`")
        
        @self.bot_client.on(events.NewMessage(pattern='/edittemplate'))
        async def edit_template(event):
            if not await self.is_admin(event.sender_id): return
            try:
                parts = event.text.split(maxsplit=2)
                num = int(parts[1]) - 1
                new_text = parts[2]
                if 0 <= num < len(self.templates):
                    old = self.templates[num]
                    self.templates[num] = new_text
                    self.save_data()
                    await event.respond(f"#{num+1}: `{old}` → `{new_text}`")
                else:
                    await event.respond("Неверный номер!")
            except:
                await event.respond("Формат: `/edittemplate 1 Новый текст!`")
        
        @self.bot_client.on(events.NewMessage(pattern='/del-template'))
        async def del_template(event):
            if not await self.is_admin(event.sender_id): return
            try:
                num = int(event.text.split()[1]) - 1
                if 0 <= num < len(self.templates):
                    deleted = self.templates.pop(num)
                    self.save_data()
                    await event.respond(f"Удален: `{deleted}`")
                else:
                    await event.respond("Неверный номер!")
            except:
                await event.respond("Формат: `/del-template 1`")
        
        @self.bot_client.on(events.NewMessage(pattern='/cleartemplates'))
        async def clear_templates(event):
            if not await self.is_admin(event.sender_id): return
            self.templates.clear()
            self.save_data()
            await event.respond("Все шаблоны очищены!")
        
        @self.bot_client.on(events.NewMessage(pattern='/startmon'))
        async def start_monitor(event):
            if not await self.is_admin(event.sender_id): return
            if self.monitoring:
                await event.respond("Уже запущен!")
                return
            if not self.accounts_data:
                await event.respond("Сначала авторизуйте аккаунты! /auth")
                return
            self.monitoring = True
            self.monitoring_start_time = datetime.now()
            
            # ============= РЕАЛЬНЫЕ ДАННЫЕ =============
            # Подсчёт аккаунтов по статусам
            active_count = sum(1 for data in self.accounts_data.values() 
                             if data.get('status') == ACCOUNT_STATUS_ACTIVE)
            reserve_count = sum(1 for data in self.accounts_data.values() 
                              if data.get('status') == ACCOUNT_STATUS_RESERVE)
            broken_count = sum(1 for data in self.accounts_data.values() 
                             if data.get('status') == ACCOUNT_STATUS_BROKEN)
            
            # Количество параллельных аккаунтов
            parallel_limit = self.max_parallel_accounts
            
            # Количество каналов (с учётом тестового режима)
            if self.test_mode and self.test_channels:
                channels_count = len(self.test_channels)
                channels_note = f" (ТЕСТОВЫЙ РЕЖИМ: {', '.join(self.test_channels[:3])}{'...' if len(self.test_channels) > 3 else ''})"
            else:
                channels_count = len(self.channels)
                channels_note = ""
            
            # Количество шаблонов
            templates_count = len(self.templates)
            
            # Расчёт задержки между комментариями
            # Интервал = 3600 секунд / лимит_сообщений_в_час
            avg_interval_sec = 3600 // self.messages_per_hour if self.messages_per_hour > 0 else 0
            avg_interval_min = avg_interval_sec // 60
            
            # Расчёт ожидаемой скорости
            # Скорость = лимит_на_аккаунт × количество_активных_аккаунтов
            expected_speed = self.messages_per_hour * active_count
            
            # Определение режима безопасности
            is_safe_mode = (
                self.messages_per_hour <= 20 and  # Лимит консервативный
                active_count <= 3 and              # Немного активных аккаунтов
                parallel_limit <= 2                # Мало параллельных работников
            )
            
            if is_safe_mode:
                mode_text = "БЕЗОПАСНЫЙ РЕЖИМ"
                mode_emoji = "🛡️"
                risk_text = "🟢 **Риск бана: НИЗКИЙ**"
            elif self.messages_per_hour > 30 or active_count > 5:
                mode_text = "АГРЕССИВНЫЙ РЕЖИМ"
                mode_emoji = "⚡"
                risk_text = "🟡 **Риск бана: СРЕДНИЙ** (рекомендуется снизить лимиты)"
            else:
                mode_text = "СТАНДАРТНЫЙ РЕЖИМ"
                mode_emoji = "⚙️"
                risk_text = "🟢 **Риск бана: НИЗКИЙ**"
            
            # Расчёт интервала ротации в часах
            rotation_hours = self.rotation_interval // 3600
            
            # Формирование сообщения
            text = f"""🚀 **АВТОКОММЕНТАРИИ ЗАПУЩЕНЫ** {mode_emoji}

📊 **КОНФИГУРАЦИЯ:**
✅ Активных аккаунтов: `{active_count}`
🔵 Резервных: `{reserve_count}`
🔴 Заблокированных: `{broken_count}`

⚡ Параллельно работают: `{parallel_limit}` аккаунтов
📢 Каналов в работе: `{channels_count}`{channels_note}
💬 Шаблонов комментариев: `{templates_count}`

⏱️ **НАСТРОЙКИ СКОРОСТИ:**
📊 Лимит: `{self.messages_per_hour}` комм/час на аккаунт
⏳ Средний интервал: ~`{avg_interval_min}` мин между комментариями
🔄 Ротация аккаунтов: каждые `{rotation_hours}` часов

📈 **ОЖИДАЕМАЯ СКОРОСТЬ:**
Максимум: `{expected_speed}` комм/час
(= {self.messages_per_hour} × {active_count} аккаунтов)

{risk_text}
🔐 Режим: **{mode_text}**"""
            
            await event.respond(text)
            
            # Start ONE worker (safe mode) - it will handle parallel accounts internally
            asyncio.create_task(self.pro_auto_comment())
            
            # Schedule auto-stop after 4 hours
            asyncio.create_task(self.auto_stop_after_4_hours(event.chat_id))
        
        @self.bot_client.on(events.NewMessage(pattern='/stopmon'))
        async def stop_monitor(event):
            if not await self.is_admin(event.sender_id): return
            self.monitoring = False
            await event.respond("Автокомментарии остановлены")
        
        @self.bot_client.on(events.NewMessage(pattern='/addbio'))
        async def add_bio(event):
            if not await self.is_admin(event.sender_id): return
            try:
                link = event.text.split(maxsplit=1)[1]
                if 't.me' in link and link not in self.bio_links:
                    self.bio_links.append(link)
                    self.save_data()
                    await event.respond(f"BIO добавлен: `{link}`")
                else:
                    await event.respond("Новая ссылка t.me!")
            except:
                await event.respond("Формат: `/addbio https://t.me/channel`")
        
        @self.bot_client.on(events.NewMessage(pattern='/setbioall'))
        async def set_bio_all(event):
            if not await self.is_admin(event.sender_id): return
            if not self.bio_links:
                await event.respond("Сначала `/addbio`!")
                return
            bio_text = " | ".join(self.bio_links[:4])
            updated = 0
            for phone, data in self.accounts_data.items():
                if data.get('active') and data.get('session'):
                    if await self.set_account_bio(data, bio_text):
                        updated += 1
            await event.respond(f"BIO обновлен: `{bio_text}`\n{updated} аккаунтов")
        
        @self.bot_client.on(events.NewMessage(pattern='/stats'))
        async def show_stats(event):
            if not await self.is_admin(event.sender_id): return
            
            # Determine admin_id for filtering
            admin_id = self.get_admin_id(event.sender_id)
            
            text = "📊 **УПРАВЛЕНЧЕСКИЙ ОТЧЁТ**\n\n"
            
            # ============= FIX: Define today_start once at the beginning =============
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            # ============= END FIX =============
            
            # 1. Общая сводка + скорость
            total_comments = self.stats.get('total_comments', 0)
            
            # ============= FIX: Calculate today's comments from DB with admin_id filter =============
            daily_comments = 0
            
            if self.conn:
                try:
                    cursor = self.conn.cursor()
                    if admin_id is None:  # Super admin - global view
                        cursor.execute(
                            "SELECT COUNT(*) FROM account_stats WHERE timestamp >= ? AND event_type = 'comment_sent'",
                            (today_start,)
                        )
                    else:  # Regular admin - filtered view
                        cursor.execute(
                            "SELECT COUNT(*) FROM account_stats WHERE timestamp >= ? AND event_type = 'comment_sent' AND admin_id = ?",
                            (today_start, admin_id)
                        )
                    daily_comments = cursor.fetchone()[0]
                except Exception as e:
                    logger.error(f"Error counting today's comments: {e}")
            # ============= END FIX =============
            
            # Calculate hourly rate - filter by admin_id
            current_time = datetime.now().timestamp()
            hour_ago = current_time - 3600
            comments_last_hour = 0
            
            # Filter accounts by admin_id
            filtered_accounts = {phone: data for phone, data in self.accounts_data.items()
                               if admin_id is None or data.get('admin_id') == admin_id}
            
            for phone, activity in self.account_activity.items():
                # Skip if account doesn't belong to this admin
                if phone not in filtered_accounts:
                    continue
                messages = activity.get('messages', [])
                comments_last_hour += sum(1 for ts, _ in messages if ts >= hour_ago)
            
            active_accounts_count = sum(1 for d in filtered_accounts.values() 
                                       if d.get('status') == ACCOUNT_STATUS_ACTIVE)
            
            text += f"⚡ **Скорость:** `{comments_last_hour}` комм/час\n"
            text += f"👥 **Активных аккаунтов:** `{active_accounts_count}`\n"
            text += f"📋 **Лимит:** `{self.messages_per_hour}` комм/час на аккаунт\n"
            text += f"✅ **Всего комментариев:** `{total_comments}`\n"
            text += f"📈 **Сегодня комментариев:** `{daily_comments}`\n\n"
            
            # 2. Статистика по аккаунтам (filtered)
            if self.conn:
                try:
                    cursor = self.conn.cursor()
                    
                    text += "👤 **АККАУНТЫ:**\n"
                    
                    for phone, data in filtered_accounts.items():
                        status_val = data.get('status', ACCOUNT_STATUS_RESERVE)
                        if status_val == ACCOUNT_STATUS_ACTIVE:
                            status_emoji = "✅"
                        elif status_val == ACCOUNT_STATUS_BROKEN:
                            status_emoji = "🔴"
                        else:
                            status_emoji = "🔵"
                        
                        # Count today's comments (always filter by phone)
                        cursor.execute(
                            "SELECT COUNT(*) FROM account_stats WHERE phone = ? AND timestamp >= ? AND event_type = 'comment_sent'",
                            (phone, today_start)
                        )
                        today_count = cursor.fetchone()[0]
                        
                        # Count total comments
                        cursor.execute(
                            "SELECT COUNT(*) FROM account_stats WHERE phone = ? AND event_type = 'comment_sent'",
                            (phone,)
                        )
                        total_count = cursor.fetchone()[0]
                        
                        # Count errors
                        cursor.execute(
                            "SELECT COUNT(*) FROM account_stats WHERE phone = ? AND success = 0",
                            (phone,)
                        )
                        error_count = cursor.fetchone()[0]
                        
                        short_phone = phone[-10:] if len(phone) > 10 else phone
                        text += f"{status_emoji} `{short_phone}` • сегодня: {today_count} • всего: {total_count} • ошибки: {error_count}\n"
                    
                    text += "\n"
                    
                    # 3. Топ аккаунтов (filtered by admin_id)
                    if admin_id is None:  # Super admin
                        cursor.execute(
                            """SELECT phone, COUNT(*) as count FROM account_stats 
                            WHERE timestamp >= ? AND event_type = 'comment_sent' 
                            GROUP BY phone ORDER BY count DESC LIMIT 3""",
                            (today_start,)
                        )
                    else:  # Regular admin
                        cursor.execute(
                            """SELECT phone, COUNT(*) as count FROM account_stats 
                            WHERE timestamp >= ? AND event_type = 'comment_sent' AND admin_id = ?
                            GROUP BY phone ORDER BY count DESC LIMIT 3""",
                            (today_start, admin_id)
                        )
                    top_accounts = cursor.fetchall()
                    
                    if top_accounts:
                        text += "🏆 **ТОП АККАУНТОВ СЕГОДНЯ:**\n"
                        for idx, (phone, count) in enumerate(top_accounts, 1):
                            short_phone = phone[-10:] if len(phone) > 10 else phone
                            text += f"{idx}. `{short_phone}` — {count} комм\n"
                        text += "\n"
                    
                    # 4. Статистика по каналам (filtered by admin_id)
                    cursor.execute("SELECT COUNT(*) FROM parsed_channels")
                    total_channels = cursor.fetchone()[0]
                    
                    if admin_id is None:  # Super admin
                        cursor.execute(
                            """SELECT COUNT(DISTINCT channel) FROM account_stats 
                            WHERE timestamp >= ? AND event_type = 'comment_sent'""",
                            (today_start,)
                        )
                    else:  # Regular admin
                        cursor.execute(
                            """SELECT COUNT(DISTINCT channel) FROM account_stats 
                            WHERE timestamp >= ? AND event_type = 'comment_sent' AND admin_id = ?""",
                            (today_start, admin_id)
                        )
                    active_channels_today = cursor.fetchone()[0]
                    
                    cursor.execute("SELECT COUNT(*) FROM blocked_channels")
                    blocked_channels_count = cursor.fetchone()[0]
                    
                    text += "📺 **КАНАЛЫ:**\n"
                    text += f"• Всего в работе: `{total_channels}`\n"
                    text += f"• Активных сегодня: `{active_channels_today}`\n"
                    text += f"• Без комментариев: `{blocked_channels_count}`\n\n"
                    
                    # Top channels (filtered by admin_id)
                    if admin_id is None:  # Super admin
                        cursor.execute(
                            """SELECT channel, COUNT(*) as count FROM account_stats 
                            WHERE timestamp >= ? AND event_type = 'comment_sent' AND channel != '' 
                            GROUP BY channel ORDER BY count DESC LIMIT 3""",
                            (today_start,)
                        )
                    else:  # Regular admin
                        cursor.execute(
                            """SELECT channel, COUNT(*) as count FROM account_stats 
                            WHERE timestamp >= ? AND event_type = 'comment_sent' AND channel != '' AND admin_id = ?
                            GROUP BY channel ORDER BY count DESC LIMIT 3""",
                            (today_start, admin_id)
                        )
                    top_channels = cursor.fetchall()
                    
                    if top_channels:
                        text += "📊 **ТОП КАНАЛОВ СЕГОДНЯ:**\n"
                        for idx, (channel, count) in enumerate(top_channels, 1):
                            text += f"{idx}. `@{channel}` — {count} комм\n"
                        text += "\n"
                    
                    # 5. Последние блокировки
                    cursor.execute(
                        "SELECT phone, block_date, reason FROM blocked_accounts ORDER BY block_date DESC LIMIT 5"
                    )
                    blocks = cursor.fetchall()
                    
                    if blocks:
                        text += "🚫 **ПОСЛЕДНИЕ БЛОКИРОВКИ:**\n"
                        for phone, date, reason in blocks:
                            short_phone = phone[-10:] if len(phone) > 10 else phone
                            date_str = date[:10] if date else 'N/A'
                            text += f"• `{short_phone}` — {reason} ({date_str})\n"
                        text += "\n"
                    
                    # 6. Последние комментарии
                    cursor.execute(
                        "SELECT phone, channel, comment, date FROM comment_history ORDER BY id DESC LIMIT 5"
                    )
                    comments = cursor.fetchall()
                    
                    if comments:
                        text += "💬 **ПОСЛЕДНИЕ КОММЕНТАРИИ:**\n"
                        for phone, channel, comment, date in comments:
                            short_phone = phone[-10:] if len(phone) > 10 else phone
                            short_comment = comment[:25] if len(comment) > 25 else comment
                            date_str = date[:10] if date else 'N/A'
                            text += f"• `@{channel}` | {short_comment}... ({date_str})\n"
                        text += "\n"
                    
                    # 7. Предупреждения/риски (filtered by admin_id)
                    warnings = []
                    
                    # Check blocks in last 24h (filtered)
                    yesterday = (datetime.now() - timedelta(days=1)).isoformat()
                    if admin_id is None:  # Super admin
                        cursor.execute(
                            "SELECT COUNT(*) FROM blocked_accounts WHERE block_date >= ?",
                            (yesterday,)
                        )
                    else:  # Regular admin
                        cursor.execute(
                            "SELECT COUNT(*) FROM blocked_accounts WHERE block_date >= ? AND admin_id = ?",
                            (yesterday, admin_id)
                        )
                    blocks_24h = cursor.fetchone()[0]
                    
                    if blocks_24h >= 2:
                        warnings.append(
                            "⚠️ **ВНИМАНИЕ:** Повышенное число блокировок за последние 24 часа. "
                            f"Рекомендуется снизить скорость и проверить прокси."
                        )
                    
                    # ============= FIX: Check % of blocked accounts by current status (filtered) =============
                    # Count accounts by status (only filtered accounts)
                    total_accounts = len(filtered_accounts)
                    broken_accounts = sum(1 for d in filtered_accounts.values() 
                                         if d.get('status') == ACCOUNT_STATUS_BROKEN)
                    
                    if total_accounts > 0 and broken_accounts > 0:
                        blocked_percent = (broken_accounts / total_accounts) * 100
                        if blocked_percent >= 30:
                            warnings.append(
                                f"⚠️ **ВЫСОКИЙ РИСК:** {blocked_percent:.1f}% аккаунтов заблокировано "
                                f"({broken_accounts} из {total_accounts}). Необходима ротация аккаунтов."
                            )
                    # ============= END FIX =============
                    
                    # Check if hourly rate is too high
                    if active_accounts_count > 0:
                        avg_rate_per_account = comments_last_hour / active_accounts_count
                        if avg_rate_per_account > self.messages_per_hour * 0.9:
                            warnings.append(
                                f"⚡ **ПРЕДУПРЕЖДЕНИЕ:** Приближение к лимиту скорости "
                                f"({avg_rate_per_account:.1f}/{self.messages_per_hour} комм/час)."
                            )
                    
                    if warnings:
                        text += "🔔 **РИСКИ И ПРЕДУПРЕЖДЕНИЯ:**\n"
                        for warning in warnings:
                            text += f"{warning}\n\n"
                    
                except Exception as e:
                    logger.error(f"Stats DB error: {e}")
                    text += f"\n⚠️ Ошибка получения статистики: {str(e)[:100]}\n"
            
            await event.respond(text)
        
        @self.bot_client.on(events.NewMessage(pattern='/listparsed'))
        async def list_parsed(event):
            if not await self.is_admin(event.sender_id): return
            
            if not self.conn:
                await event.respond("❌ БД недоступна")
                return
            
            try:
                cursor = self.conn.cursor()
                
                # Get total count
                cursor.execute("SELECT COUNT(*) FROM parsed_channels")
                total = cursor.fetchone()[0]
                
                if total == 0:
                    await event.respond("❌ Нет спарсенных каналов. Используйте /searchchannels")
                    return
                
                # Get all parsed channels
                cursor.execute("SELECT username, theme FROM parsed_channels ORDER BY added_date DESC")
                parsed = cursor.fetchall()
                
                # Show all channels, split into multiple messages if needed
                channels_per_msg = 50
                
                for batch_num in range(0, total, channels_per_msg):
                    batch_channels = parsed[batch_num:batch_num + channels_per_msg]
                    text = f"📋 **СПАРСЕННЫЕ КАНАЛЫ** ({total}) - Часть {batch_num//channels_per_msg + 1}:\n\n"
                    
                    for i, (username, theme) in enumerate(batch_channels, batch_num + 1):
                        # Display with @ (add if not present)
                        display_name = username if username.startswith('@') else '@' + username
                        text += f"{i}. {display_name} ({theme})\n"
                    
                    await event.respond(text)
                    # Small delay between messages to avoid flood
                    if batch_num + channels_per_msg < total:
                        await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Listparsed error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:50]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/testmode'))
        async def testmode_command(event):
            """Управление тестовым режимом: /testmode on @channel1 @channel2 или /testmode off"""
            if not await self.is_admin(event.sender_id):
                await event.respond("❌ У вас нет доступа к этому боту.")
                return
            
            # Log command received
            logger.info(f"🧪 TESTMODE command received from {event.sender_id}")
            
            try:
                parts = event.text.strip().split()
                
                if len(parts) == 1:
                    # Show current status
                    status = "🟢 ВКЛЮЧЕН" if self.test_mode else "🔴 ВЫКЛЮЧЕН"
                    text = f"""🧪 **ТЕСТОВЫЙ РЕЖИМ**

Статус: {status}
"""
                    if self.test_mode and self.test_channels:
                        text += f"\n📢 Тестовые каналы ({len(self.test_channels)}):\n"
                        for ch in self.test_channels:
                            text += f"  • `{ch}`\n"
                        text += f"\n⚡ Лимит: `{self.test_mode_speed_limit}` комм/час\n"
                    
                    text += "\n📝 **Использование:**\n"
                    text += "`/testmode on @channel1 @channel2` - включить\n"
                    text += "`/testmode off` - выключить\n"
                    text += "`/testmode speed 5` - установить скорость\n"
                    
                    await event.respond(text)
                    return
                
                action = parts[1].lower()
                
                if action == 'on':
                    # Enable test mode with specified channels
                    if len(parts) < 3:
                        await event.respond(
                            "❌ Укажите каналы:\n"
                            "`/testmode on @channel1 @channel2`"
                        )
                        return
                    
                    # Parse channels
                    channels = []
                    for part in parts[2:]:
                        ch = part.strip()
                        if not ch.startswith('@'):
                            ch = '@' + ch
                        channels.append(ch)
                    
                    self.test_mode = True
                    self.test_channels = channels
                    
                    text = """🧪 **ТЕСТОВЫЙ РЕЖИМ ВКЛЮЧЕН**

✅ Бот будет комментировать ТОЛЬКО:
"""
                    for ch in self.test_channels:
                        text += f"  • `{ch}`\n"
                    
                    text += f"\n⚡ Лимит скорости: `{self.test_mode_speed_limit}` комм/час на аккаунт\n"
                    text += "\n⚠️ **Все остальные каналы игнорируются!**\n"
                    text += "\n💡 Для выключения: `/testmode off`"
                    
                    await event.respond(text)
                    
                    # Log
                    logger.info(f"🧪 TEST MODE ENABLED: {channels}")
                    logger.info(f"🧪 Speed limit: {self.test_mode_speed_limit} msg/hour")
                    
                elif action == 'off':
                    # Disable test mode
                    was_enabled = self.test_mode
                    self.test_mode = False
                    old_channels = self.test_channels.copy()
                    self.test_channels = []
                    
                    if was_enabled:
                        text = """🔴 **ТЕСТОВЫЙ РЕЖИМ ВЫКЛЮЧЕН**

✅ Бот вернулся к обычной работе со всеми каналами
"""
                        if old_channels:
                            text += "\n📢 Были в тесте:\n"
                            for ch in old_channels:
                                text += f"  • `{ch}`\n"
                    else:
                        text = "ℹ️ Тестовый режим уже был выключен"
                    
                    await event.respond(text)
                    logger.info("🔴 TEST MODE DISABLED")
                    
                elif action == 'speed':
                    # Set test mode speed limit
                    if len(parts) < 3:
                        await event.respond(
                            f"❌ Укажите скорость:\n"
                            f"`/testmode speed 10`\n\n"
                            f"Текущая: `{self.test_mode_speed_limit}` комм/час"
                        )
                        return
                    
                    try:
                        speed = int(parts[2])
                        if speed < 1 or speed > 30:
                            await event.respond(
                                "❌ Скорость должна быть от 1 до 30 комм/час"
                            )
                            return
                        
                        old_speed = self.test_mode_speed_limit
                        self.test_mode_speed_limit = speed
                        
                        await event.respond(
                            f"✅ Лимит тестового режима изменен:\n"
                            f"Было: `{old_speed}` комм/час\n"
                            f"Стало: `{self.test_mode_speed_limit}` комм/час"
                        )
                        
                        logger.info(f"🧪 TEST MODE speed changed: {old_speed} -> {speed}")
                        
                    except ValueError:
                        await event.respond("❌ Неверное значение скорости")
                        return
                
                else:
                    await event.respond(
                        "❌ Неверная команда. Используйте:\n"
                        "`/testmode` - статус\n"
                        "`/testmode on @channel1 @channel2` - включить\n"
                        "`/testmode off` - выключить\n"
                        "`/testmode speed 10` - установить скорость"
                    )
                    
            except Exception as e:
                logger.error(f"Testmode command error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/listbans'))
        async def list_bans(event):
            if not await self.is_admin(event.sender_id): return
            
            if not self.conn:
                await event.respond("❌ БД недоступна")
                return
            
            try:
                cursor = self.conn.cursor()
                
                # Get total count
                cursor.execute("SELECT COUNT(*) FROM blocked_accounts")
                total = cursor.fetchone()[0]
                
                if total == 0:
                    await event.respond("✅ Нет заблокированных аккаунтов")
                    return
                
                # Get all blocked accounts
                cursor.execute("SELECT phone, block_date, reason FROM blocked_accounts ORDER BY block_date DESC")
                bans = cursor.fetchall()
                
                # Show all bans, split into multiple messages if needed
                bans_per_msg = 30
                
                for batch_num in range(0, total, bans_per_msg):
                    batch_bans = bans[batch_num:batch_num + bans_per_msg]
                    text = f"🚫 **ЗАБЛОКИРОВАННЫЕ АККАУНТЫ** ({total}) - Часть {batch_num//bans_per_msg + 1}:\n\n"
                    
                    for i, (phone, date, reason) in enumerate(batch_bans, batch_num + 1):
                        text += f"{i}. `{phone}` | {reason}\n     {date[:19]}\n\n"
                    
                    await event.respond(text)
                    # Small delay between messages to avoid flood
                    if batch_num + bans_per_msg < total:
                        await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Listbans error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:50]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/history'))
        async def show_history(event):
            if not await self.is_admin(event.sender_id): return
            
            if not self.conn:
                await event.respond("❌ БД недоступна")
                return
            
            try:
                cursor = self.conn.cursor()
                
                # Get total count
                cursor.execute("SELECT COUNT(*) FROM comment_history")
                total = cursor.fetchone()[0]
                
                if total == 0:
                    await event.respond("❌ История пуста")
                    return
                
                # Get all history
                cursor.execute(
                    "SELECT phone, channel, comment, date FROM comment_history ORDER BY id DESC"
                )
                history = cursor.fetchall()
                
                # Show all history, split into multiple messages if needed
                history_per_msg = 30
                
                for batch_num in range(0, total, history_per_msg):
                    batch_history = history[batch_num:batch_num + history_per_msg]
                    text = f"📝 **ИСТОРИЯ КОММЕНТАРИЕВ** ({total}) - Часть {batch_num//history_per_msg + 1}:\n\n"
                    
                    for i, (phone, channel, comment, date) in enumerate(batch_history, batch_num + 1):
                        short_comment = comment[:40] if len(comment) > 40 else comment
                        # Display with @ (add if not present)
                        display_channel = channel if channel.startswith('@') else '@' + channel
                        text += f"{i}. `{phone[:12]}...` → {display_channel}\n     \"{short_comment}\"\n     {date[:19]}\n\n"
                    
                    await event.respond(text)
                    # Small delay between messages to avoid flood
                    if batch_num + history_per_msg < total:
                        await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"History error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:50]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/listblockedchannels'))
        async def list_blocked_channels(event):
            if not await self.is_admin(event.sender_id): return
            
            if not self.conn:
                await event.respond("❌ БД недоступна")
                return
            
            try:
                cursor = self.conn.cursor()
                
                # Get total count
                cursor.execute("SELECT COUNT(*) FROM blocked_channels")
                total = cursor.fetchone()[0]
                
                if total == 0:
                    await event.respond("✅ Нет заблокированных каналов")
                    return
                
                # Get all blocked channels
                cursor.execute("SELECT username, block_date, reason FROM blocked_channels ORDER BY block_date DESC")
                blocked = cursor.fetchall()
                
                # Show all blocked channels, split into multiple messages if needed
                channels_per_msg = 40
                
                for batch_num in range(0, total, channels_per_msg):
                    batch_blocked = blocked[batch_num:batch_num + channels_per_msg]
                    text = f"🔇 **КАНАЛЫ БЕЗ КОММЕНТАРИЕВ** ({total}) - Часть {batch_num//channels_per_msg + 1}:\n\n"
                    
                    for i, (username, date, reason) in enumerate(batch_blocked, batch_num + 1):
                        # Display with @ (add if not present)
                        display_name = username if username.startswith('@') else '@' + username
                        text += f"{i}. {display_name}\n     {reason}\n     {date[:19]}\n\n"
                    
                    await event.respond(text)
                    # Small delay between messages to avoid flood
                    if batch_num + channels_per_msg < total:
                        await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"List blocked channels error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:50]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/safetyinfo'))
        async def safety_info(event):
            if not await self.is_admin(event.sender_id): return
            text = """🛡️ **НАСТРОЙКИ БЕЗОПАСНОСТИ**

**Текущая конфигурация:**
• Задержка между комментариями: `50-100 сек` (~1-2 мин)
• Перерыв между циклами: `3-7 мин`
• Параллельных аккаунтов: `2` (максимум)
• Прогрев перед стартом: `5-30 сек`
• Вариации комментариев: `ВКЛЮЧЕНЫ`

**Защита от бана:**
✅ Случайные задержки (имитация человека)
✅ Длинные паузы между циклами
✅ Ограничение параллельных аккаунтов
✅ Вариации текста комментариев
✅ Прогрев аккаунтов перед работой
✅ Отслеживание FloodWait ошибок

**Рекомендации:**
1️⃣ Не запускайте бота 24/7
2️⃣ Делайте перерывы по 2-3 часа
3️⃣ Добавьте больше шаблонов (>50)
4️⃣ Не комментируйте один канал часто
5️⃣ Меняйте био-ссылки раз в неделю

**Статистика рисков:**
• Текущий режим: `БЕЗОПАСНЫЙ`
• Скорость: `36-72 комм/час`
• Риск бана: `НИЗКИЙ` 🟢"""
            await event.respond(text)
        
        # ============= ACCOUNTS PROFILE MANAGEMENT HANDLERS =============
        
        @self.bot_client.on(events.NewMessage(pattern='/accounts'))
        async def accounts_command(event):
            """Показывает список всех аккаунтов из переменных окружения"""
            if not await self.is_admin(event.sender_id):
                await event.respond("❌ У вас нет доступа к этому боту.")
                return
            
            try:
                accounts = self.get_all_accounts_from_env()
                
                if not accounts:
                    await event.respond(
                        "❌ **Аккаунты не найдены**\n\n"
                        "Убедитесь, что в переменных окружения есть:\n"
                        "`ACCOUNT_1_PHONE`\n"
                        "`ACCOUNT_1_SESSION`\n"
                        "`ACCOUNT_1_PROXY` (опционально)"
                    )
                    return
                
                text = f"🔐 **УПРАВЛЕНИЕ ПРОФИЛЯМИ АККАУНТОВ**\n\n"
                text += f"Найдено аккаунтов: **{len(accounts)}**\n\n"
                text += "Выберите аккаунт для управления профилем:"
                
                keyboard = self.create_accounts_keyboard(page=0)
                await event.respond(text, buttons=keyboard)
                
            except Exception as e:
                logger.error(f"Error in accounts command: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        @self.bot_client.on(events.CallbackQuery)
        async def handle_callback(event):
            """Обработчик всех callback кнопок для управления профилями"""
            if not await self.is_admin(event.sender_id):
                await event.answer("❌ Нет доступа")
                return
            
            data = event.data.decode('utf-8', errors='ignore')
            user_id = event.sender_id
            
            try:
                # Main menu
                if data == "main_menu":
                    await self.clear_user_state(user_id)
                    await event.edit(
                        "🏠 **Главное меню**\n\n"
                        "Используйте команды:\n"
                        "`/accounts` - управление профилями\n"
                        "`/help` - все команды",
                        buttons=None
                    )
                    return
                
                # Back to accounts list
                if data == "back_to_accounts":
                    await self.clear_user_state(user_id)
                    accounts = self.get_all_accounts_from_env()
                    text = f"🔐 **УПРАВЛЕНИЕ ПРОФИЛЯМИ АККАУНТОВ**\n\n"
                    text += f"Найдено аккаунтов: **{len(accounts)}**\n\n"
                    text += "Выберите аккаунт для управления профилем:"
                    keyboard = self.create_accounts_keyboard(page=0)
                    await event.edit(text, buttons=keyboard)
                    return
                
                # Page navigation
                if data.startswith("acc_page_"):
                    page = int(data.split("_")[-1])
                    accounts = self.get_all_accounts_from_env()
                    text = f"🔐 **УПРАВЛЕНИЕ ПРОФИЛЯМИ АККАУНТОВ**\n\n"
                    text += f"Найдено аккаунтов: **{len(accounts)}**\n\n"
                    text += "Выберите аккаунт для управления профилем:"
                    keyboard = self.create_accounts_keyboard(page=page)
                    await event.edit(text, buttons=keyboard)
                    return
                
                # Page info (do nothing)
                if data == "page_info":
                    await event.answer("ℹ️ Информация о странице")
                    return
                
                # No accounts found
                if data == "no_accounts":
                    await event.answer("❌ Аккаунты не настроены")
                    return
                
                # Account selected
                if data.startswith("acc_") and not "_" in data[4:]:
                    account_num = int(data[4:])
                    
                    # Get account info
                    account_info = await self.get_account_info(account_num)
                    
                    if not account_info:
                        await event.answer("❌ Аккаунт не найден")
                        return
                    
                    # Build info text
                    text = f"🔐 **АККАУНТ #{account_num}**\n\n"
                    text += f"📱 Телефон: `{account_info['phone']}`\n"
                    
                    if account_info.get('authorized'):
                        text += f"✅ Статус: **Авторизован**\n\n"
                        text += f"👤 Имя: {account_info.get('first_name', 'Не указано')}\n"
                        text += f"👤 Фамилия: {account_info.get('last_name', 'Не указано')}\n"
                        if account_info.get('username'):
                            text += f"🔗 Username: @{account_info['username']}\n"
                        text += f"📝 Био: {account_info.get('bio', 'Не указано')[:100]}\n"
                    else:
                        text += f"❌ Статус: **Не авторизован**\n\n"
                        text += "⚠️ Этот аккаунт не может быть изменён.\n"
                    
                    text += f"\nВыберите действие:"
                    
                    keyboard = self.create_account_menu_keyboard(account_num)
                    await event.edit(text, buttons=keyboard)
                    return
                
                # Avatar button
                if data.endswith("_avatar"):
                    account_num = int(data.split("_")[1])
                    account_info = await self.get_account_info(account_num)
                    
                    if not account_info or not account_info.get('authorized'):
                        await event.answer("❌ Аккаунт не авторизован")
                        return
                    
                    # Set state
                    self.user_states[user_id] = {
                        'state': 'waiting_avatar',
                        'account_num': account_num,
                        'data': {}
                    }
                    
                    await event.edit(
                        f"📷 **ЗАГРУЗКА АВАТАРКИ**\n\n"
                        f"Аккаунт: `{account_info['phone']}`\n\n"
                        f"Отправьте фото для аватарки (jpg, png)\n"
                        f"Или нажмите Отмена",
                        buttons=[
                            [Button.inline("❌ Отмена", f"cancel_acc_{account_num}".encode())]
                        ]
                    )
                    return
                
                # Name button
                if data.endswith("_name"):
                    account_num = int(data.split("_")[1])
                    account_info = await self.get_account_info(account_num)
                    
                    if not account_info or not account_info.get('authorized'):
                        await event.answer("❌ Аккаунт не авторизован")
                        return
                    
                    # Set state
                    self.user_states[user_id] = {
                        'state': 'waiting_name',
                        'account_num': account_num,
                        'data': {}
                    }
                    
                    current_name = f"{account_info.get('first_name', '')} {account_info.get('last_name', '')}".strip()
                    
                    await event.edit(
                        f"👤 **ИЗМЕНЕНИЕ ИМЕНИ**\n\n"
                        f"Аккаунт: `{account_info['phone']}`\n"
                        f"Текущее: {current_name or 'Не указано'}\n\n"
                        f"Введите имя и фамилию через пробел:\n"
                        f"Пример: `Иван Петров`\n\n"
                        f"Или нажмите Отмена",
                        buttons=[
                            [Button.inline("❌ Отмена", f"cancel_acc_{account_num}".encode())]
                        ]
                    )
                    return
                
                # Bio button
                if data.endswith("_bio"):
                    account_num = int(data.split("_")[1])
                    account_info = await self.get_account_info(account_num)
                    
                    if not account_info or not account_info.get('authorized'):
                        await event.answer("❌ Аккаунт не авторизован")
                        return
                    
                    # Set state
                    self.user_states[user_id] = {
                        'state': 'waiting_bio',
                        'account_num': account_num,
                        'data': {}
                    }
                    
                    current_bio = account_info.get('bio', 'Не указано')
                    
                    await event.edit(
                        f"📝 **ИЗМЕНЕНИЕ ИНФОРМАЦИИ О СЕБЕ**\n\n"
                        f"Аккаунт: `{account_info['phone']}`\n"
                        f"Текущее: {current_bio[:100]}\n\n"
                        f"Введите новую информацию о себе (до 500 символов):\n"
                        f"Можете добавить ссылку\n\n"
                        f"Пример: `Digital Marketing 🌐 https://example.com`\n\n"
                        f"Или нажмите Отмена",
                        buttons=[
                            [Button.inline("❌ Отмена", f"cancel_acc_{account_num}".encode())]
                        ]
                    )
                    return
                
                # Cancel button
                if data.startswith("cancel_acc_"):
                    account_num = int(data.split("_")[-1])
                    await self.clear_user_state(user_id)
                    
                    # Return to account menu
                    account_info = await self.get_account_info(account_num)
                    if account_info:
                        text = f"🔐 **АККАУНТ #{account_num}**\n\n"
                        text += f"📱 Телефон: `{account_info['phone']}`\n"
                        text += f"✅ Операция отменена\n\n"
                        text += "Выберите действие:"
                        
                        keyboard = self.create_account_menu_keyboard(account_num)
                        await event.edit(text, buttons=keyboard)
                    return
                
                # Apply changes (avatar)
                if data.startswith("apply_avatar_"):
                    account_num = int(data.split("_")[-1])
                    
                    if user_id not in self.user_states:
                        await event.answer("❌ Сессия истекла")
                        return
                    
                    state = self.user_states[user_id]
                    avatar_file = state.get('data', {}).get('temp_avatar')
                    
                    if not avatar_file or not os.path.exists(avatar_file):
                        await event.answer("❌ Файл не найден")
                        return
                    
                    await event.edit("⏳ Загрузка аватарки...")
                    
                    # Apply changes
                    success, message = await self.apply_account_changes(
                        account_num, 
                        avatar_file=avatar_file
                    )
                    
                    await self.clear_user_state(user_id)
                    
                    # Show result and return to account menu
                    account_info = await self.get_account_info(account_num)
                    text = f"🔐 **АККАУНТ #{account_num}**\n\n"
                    text += f"{message}\n\n"
                    text += "Выберите следующее действие:"
                    
                    keyboard = self.create_account_menu_keyboard(account_num)
                    await event.edit(text, buttons=keyboard)
                    return
                
                # Apply changes (name)
                if data.startswith("apply_name_"):
                    account_num = int(data.split("_")[-1])
                    
                    if user_id not in self.user_states:
                        await event.answer("❌ Сессия истекла")
                        return
                    
                    state = self.user_states[user_id]
                    first_name = state.get('data', {}).get('first_name', '')
                    last_name = state.get('data', {}).get('last_name', '')
                    
                    await event.edit("⏳ Обновление имени...")
                    
                    # Apply changes
                    success, message = await self.apply_account_changes(
                        account_num,
                        first_name=first_name,
                        last_name=last_name
                    )
                    
                    await self.clear_user_state(user_id)
                    
                    # Show result and return to account menu
                    account_info = await self.get_account_info(account_num)
                    text = f"🔐 **АККАУНТ #{account_num}**\n\n"
                    text += f"{message}\n\n"
                    text += "Выберите следующее действие:"
                    
                    keyboard = self.create_account_menu_keyboard(account_num)
                    await event.edit(text, buttons=keyboard)
                    return
                
                # Apply changes (bio)
                if data.startswith("apply_bio_"):
                    account_num = int(data.split("_")[-1])
                    
                    if user_id not in self.user_states:
                        await event.answer("❌ Сессия истекла")
                        return
                    
                    state = self.user_states[user_id]
                    bio = state.get('data', {}).get('bio', '')
                    
                    await event.edit("⏳ Обновление био...")
                    
                    # Apply changes
                    success, message = await self.apply_account_changes(
                        account_num,
                        bio=bio
                    )
                    
                    await self.clear_user_state(user_id)
                    
                    # Show result and return to account menu
                    account_info = await self.get_account_info(account_num)
                    text = f"🔐 **АККАУНТ #{account_num}**\n\n"
                    text += f"{message}\n\n"
                    text += "Выберите следующее действие:"
                    
                    keyboard = self.create_account_menu_keyboard(account_num)
                    await event.edit(text, buttons=keyboard)
                    return
                
            except Exception as e:
                logger.error(f"Callback error: {e}")
                await event.answer(f"❌ Ошибка: {str(e)[:50]}")
        
        # Handler for photo uploads (avatar)
        @self.bot_client.on(events.NewMessage(func=lambda e: e.photo))
        async def handle_photo(event):
            """Обработчик загрузки фотографий для аватарок"""
            if not await self.is_admin(event.sender_id):
                return
            
            user_id = event.sender_id
            
            # Check if user is in avatar upload state
            if user_id not in self.user_states:
                return
            
            state = self.user_states[user_id]
            if state.get('state') != 'waiting_avatar':
                return
            
            account_num = state['account_num']
            
            try:
                await event.respond("⏳ Загрузка изображения...")
                
                # Download photo
                photo = await event.download_media()
                
                if not photo:
                    await event.respond("❌ Ошибка загрузки фото")
                    return
                
                # Save to temp
                temp_file = await self.save_temp_avatar(user_id, photo)
                
                # Update state
                self.user_states[user_id]['data']['temp_avatar'] = temp_file
                
                # Clean up original download
                if os.path.exists(photo):
                    try:
                        os.remove(photo)
                    except:
                        pass
                
                # Show confirmation
                await event.respond(
                    f"✅ **Фото выбрано!**\n\n"
                    f"Аккаунт: `{(await self.get_account_info(account_num))['phone']}`\n\n"
                    f"Применить это фото как аватарку?",
                    buttons=[
                        [
                            Button.inline("✅ Применить", f"apply_avatar_{account_num}".encode()),
                            Button.inline("❌ Отменить", f"cancel_acc_{account_num}".encode())
                        ]
                    ]
                )
                
            except Exception as e:
                logger.error(f"Photo upload error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        # Handler for text messages (name and bio)
        @self.bot_client.on(events.NewMessage(func=lambda e: e.text and not e.text.startswith('/')))
        async def handle_text(event):
            """Обработчик текстовых сообщений для имени и био"""
            if not await self.is_admin(event.sender_id):
                return
            
            user_id = event.sender_id
            
            # Check if user is in text input state
            if user_id not in self.user_states:
                return
            
            state = self.user_states[user_id]
            account_num = state['account_num']
            
            try:
                # Handle name input
                if state.get('state') == 'waiting_name':
                    text = event.text.strip()
                    
                    # Split by first space
                    parts = text.split(' ', 1)
                    first_name = parts[0] if parts else ''
                    last_name = parts[1] if len(parts) > 1 else ''
                    
                    # Validate
                    if not first_name:
                        await event.respond("❌ Имя не может быть пустым. Попробуйте ещё раз:")
                        return
                    
                    if len(first_name) > 64 or len(last_name) > 64:
                        await event.respond("❌ Имя слишком длинное (макс 64 символа). Попробуйте ещё раз:")
                        return
                    
                    # Save to state
                    self.user_states[user_id]['data']['first_name'] = first_name
                    self.user_states[user_id]['data']['last_name'] = last_name
                    
                    # Show preview
                    account_info = await self.get_account_info(account_num)
                    preview_text = (
                        f"📋 **ПРЕВЬЮ ИЗМЕНЕНИЙ**\n\n"
                        f"Аккаунт: `{account_info['phone']}`\n\n"
                        f"👤 Имя: {first_name}\n"
                        f"👤 Фамилия: {last_name or '(не указано)'}\n\n"
                        f"Применить эти изменения?"
                    )
                    
                    await event.respond(
                        preview_text,
                        buttons=[
                            [
                                Button.inline("✅ Применить", f"apply_name_{account_num}".encode()),
                                Button.inline("❌ Отменить", f"cancel_acc_{account_num}".encode())
                            ]
                        ]
                    )
                    return
                
                # Handle bio input
                if state.get('state') == 'waiting_bio':
                    text = event.text.strip()
                    
                    # Validate length
                    if len(text) > 500:
                        await event.respond(
                            f"❌ Текст слишком длинный ({len(text)}/500 символов)\n"
                            f"Сократите текст и попробуйте ещё раз:"
                        )
                        return
                    
                    # Save to state
                    self.user_states[user_id]['data']['bio'] = text
                    
                    # Show preview
                    account_info = await self.get_account_info(account_num)
                    preview_text = (
                        f"📋 **ПРЕВЬЮ ИЗМЕНЕНИЙ**\n\n"
                        f"Аккаунт: `{account_info['phone']}`\n\n"
                        f"📝 Новое био:\n{text}\n\n"
                        f"Применить эти изменения?"
                    )
                    
                    await event.respond(
                        preview_text,
                        buttons=[
                            [
                                Button.inline("✅ Применить", f"apply_bio_{account_num}".encode()),
                                Button.inline("❌ Отменить", f"cancel_acc_{account_num}".encode())
                            ]
                        ]
                    )
                    return
                
            except Exception as e:
                logger.error(f"Text handler error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        # ============= END ACCOUNTS PROFILE MANAGEMENT HANDLERS =============
        
        @self.bot_client.on(events.NewMessage(pattern='/addadmin'))
        async def add_admin(event):
            # Only super admins can add new admins
            if not self.is_super_admin(event.sender_id):
                await event.respond("❌ Только супер-админы могут добавлять новых админов")
                return
            
            try:
                admin_id = int(event.text.split(maxsplit=1)[1])
                
                # Check if already a super admin
                if admin_id in SUPER_ADMINS:
                    await event.respond(f"ℹ️ `{admin_id}` уже является супер-админом")
                    return
                
                if admin_id not in self.admins:
                    self.admins.append(admin_id)
                    self.save_data()
                    
                    text = f"""✅ **Новый админ добавлен**

👤 ID: `{admin_id}`
🆔 Добавил: `{event.sender_id}`
📅 Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}

🔹 Этот админ теперь имеет свой отдельный кабинет
🔹 Он видит только свои аккаунты и статистику
🔹 Не имеет доступа к глобальным данным"""
                    
                    await event.respond(text)
                    logger.info(f"New admin added: {admin_id} by super admin {event.sender_id}")
                else:
                    await event.respond("ℹ️ Этот админ уже добавлен")
            except Exception as e:
                await event.respond(f"❌ Ошибка: Формат: `/addadmin 123456789`")
                logger.error(f"Add admin error: {e}")
        
        @self.bot_client.on(events.NewMessage(pattern='/listadmins'))
        async def list_admins_command(event):
            """List all admins (super admins only)"""
            if not self.is_super_admin(event.sender_id):
                await event.respond("❌ Только супер-админы могут видеть список всех админов")
                return
            
            try:
                text = "👑 **СПИСОК АДМИНОВ**\n\n"
                
                # Super admins
                text += "🌟 **СУПЕР-АДМИНЫ:**\n"
                for admin_id in SUPER_ADMINS:
                    text += f"  • `{admin_id}` (глобальный доступ)\n"
                
                text += "\n👥 **ОБЫЧНЫЕ АДМИНЫ:**\n"
                if self.admins:
                    for idx, admin_id in enumerate(self.admins, 1):
                        # Count accounts for this admin
                        admin_accounts = sum(1 for d in self.accounts_data.values() 
                                            if d.get('admin_id') == admin_id)
                        text += f"{idx}. `{admin_id}` — аккаунтов: {admin_accounts}\n"
                else:
                    text += "  • Нет обычных админов\n"
                
                text += f"\n📊 Всего админов: {len(SUPER_ADMINS) + len(self.admins)}"
                
                await event.respond(text)
                
            except Exception as e:
                logger.error(f"List admins error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/removeadmin'))
        async def remove_admin_command(event):
            """Remove an admin (super admins only)"""
            if not self.is_super_admin(event.sender_id):
                await event.respond("❌ Только супер-админы могут удалять админов")
                return
            
            try:
                admin_id = int(event.text.split(maxsplit=1)[1])
                
                # Can't remove super admins
                if admin_id in SUPER_ADMINS:
                    await event.respond("❌ Нельзя удалить супер-админа")
                    return
                
                if admin_id in self.admins:
                    self.admins.remove(admin_id)
                    self.save_data()
                    
                    # Count their accounts
                    admin_accounts = sum(1 for d in self.accounts_data.values() 
                                        if d.get('admin_id') == admin_id)
                    
                    text = f"""✅ **Админ удалён**

👤 ID: `{admin_id}`
📊 У него было аккаунтов: {admin_accounts}

⚠️ Его аккаунты и данные остались в системе
💡 Для полной очистки используйте команды удаления аккаунтов"""
                    
                    await event.respond(text)
                    logger.info(f"Admin removed: {admin_id} by super admin {event.sender_id}")
                else:
                    await event.respond("❌ Этот ID не является админом")
                    
            except Exception as e:
                await event.respond(f"❌ Ошибка: Формат: `/removeadmin 123456789`")
                logger.error(f"Remove admin error: {e}")
        
        @self.bot_client.on(events.NewMessage(pattern='/stats_global'))
        async def stats_global_command(event):
            """Global stats for super admins - same as /stats but explicit"""
            if not self.is_super_admin(event.sender_id):
                await event.respond("❌ Только супер-админы могут видеть глобальную статистику")
                return
            
            # Just call the regular stats command (it already shows global for super admins)
            await show_stats(event)
        
        @self.bot_client.on(events.NewMessage(pattern='/stats_admin'))
        async def stats_admin_command(event):
            """View stats for specific admin (super admins only)"""
            if not self.is_super_admin(event.sender_id):
                await event.respond("❌ Только супер-админы могут просматривать статистику других админов")
                return
            
            try:
                target_admin_id = int(event.text.split(maxsplit=1)[1])
                
                # Filter accounts for this admin
                filtered_accounts = {phone: data for phone, data in self.accounts_data.items()
                                   if data.get('admin_id') == target_admin_id}
                
                if not filtered_accounts:
                    await event.respond(f"❌ У админа {target_admin_id} нет аккаунтов")
                    return
                
                text = f"📊 **СТАТИСТИКА АДМИНА {target_admin_id}**\n\n"
                
                today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
                
                # Calculate stats
                if self.conn:
                    try:
                        cursor = self.conn.cursor()
                        
                        # Today's comments
                        cursor.execute(
                            "SELECT COUNT(*) FROM account_stats WHERE timestamp >= ? AND event_type = 'comment_sent' AND admin_id = ?",
                            (today_start, target_admin_id)
                        )
                        daily_comments = cursor.fetchone()[0]
                        
                        # Total comments
                        cursor.execute(
                            "SELECT COUNT(*) FROM account_stats WHERE event_type = 'comment_sent' AND admin_id = ?",
                            (target_admin_id,)
                        )
                        total_comments = cursor.fetchone()[0]
                        
                        active_accounts = sum(1 for d in filtered_accounts.values() 
                                            if d.get('status') == ACCOUNT_STATUS_ACTIVE)
                        reserve_accounts = sum(1 for d in filtered_accounts.values() 
                                             if d.get('status') == ACCOUNT_STATUS_RESERVE)
                        broken_accounts = sum(1 for d in filtered_accounts.values() 
                                            if d.get('status') == ACCOUNT_STATUS_BROKEN)
                        
                        text += f"👥 **Аккаунты:**\n"
                        text += f"  • ✅ Активных: {active_accounts}\n"
                        text += f"  • 🔵 Резервных: {reserve_accounts}\n"
                        text += f"  • 🔴 Заблокированных: {broken_accounts}\n\n"
                        
                        text += f"📈 **Комментарии:**\n"
                        text += f"  • Сегодня: {daily_comments}\n"
                        text += f"  • Всего: {total_comments}\n\n"
                        
                        # Top accounts
                        cursor.execute(
                            """SELECT phone, COUNT(*) as count FROM account_stats 
                            WHERE timestamp >= ? AND event_type = 'comment_sent' AND admin_id = ?
                            GROUP BY phone ORDER BY count DESC LIMIT 5""",
                            (today_start, target_admin_id)
                        )
                        top_accounts = cursor.fetchall()
                        
                        if top_accounts:
                            text += "🏆 **Топ аккаунтов сегодня:**\n"
                            for idx, (phone, count) in enumerate(top_accounts, 1):
                                short_phone = phone[-10:] if len(phone) > 10 else phone
                                text += f"  {idx}. `{short_phone}` — {count} комм\n"
                        
                        await event.respond(text)
                        
                    except Exception as e:
                        logger.error(f"Stats admin DB error: {e}")
                        await event.respond(f"❌ Ошибка БД: {str(e)[:100]}")
                else:
                    await event.respond("❌ БД недоступна")
                    
            except ValueError:
                await event.respond("❌ Формат: `/stats_admin 123456789`")
            except Exception as e:
                logger.error(f"Stats admin error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/listaccounts_admin'))
        async def listaccounts_admin_command(event):
            """List accounts for specific admin (super admins only)"""
            if not self.is_super_admin(event.sender_id):
                await event.respond("❌ Только супер-админы могут просматривать аккаунты других админов")
                return
            
            try:
                target_admin_id = int(event.text.split(maxsplit=1)[1])
                
                # Filter accounts for this admin
                filtered_accounts = {phone: data for phone, data in self.accounts_data.items()
                                   if data.get('admin_id') == target_admin_id}
                
                if not filtered_accounts:
                    await event.respond(f"❌ У админа {target_admin_id} нет аккаунтов")
                    return
                
                text = f"👥 **АККАУНТЫ АДМИНА {target_admin_id}**\n\n"
                text += f"Всего: {len(filtered_accounts)}\n\n"
                
                for i, (phone, data) in enumerate(filtered_accounts.items(), 1):
                    status_val = data.get('status', ACCOUNT_STATUS_RESERVE)
                    if status_val == ACCOUNT_STATUS_ACTIVE:
                        status = "✅"
                    elif status_val == ACCOUNT_STATUS_BROKEN:
                        status = "🔴"
                    else:
                        status = "🔵"
                    
                    name = data.get('name', 'Не авторизован')
                    username = data.get('username', 'нет')
                    text += f"{i}. {status} `{name}` (@{username})\n`   {phone}`\n"
                
                await event.respond(text)
                
            except ValueError:
                await event.respond("❌ Формат: `/listaccounts_admin 123456789`")
            except Exception as e:
                logger.error(f"Listaccounts admin error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/resetfails'))
        async def reset_fails(event):
            """Reset channel failure counters"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                old_count = len(self.channel_failed_attempts)
                self.channel_failed_attempts.clear()
                
                await event.respond(
                    f"✅ **Счетчики неудач сброшены!**\n\n"
                    f"Очищено записей: {old_count}\n\n"
                    f"💡 Теперь бот будет заново пробовать комментировать все каналы.\n"
                    f"⚠️ Каналы будут блокироваться только после 3+ неудачных попыток с каждого аккаунта."
                )
                logger.info(f"Channel failure counters reset by admin {event.sender_id}")
            except Exception as e:
                logger.error(f"Reset fails error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/showfails'))
        async def show_fails(event):
            """Show current channel failure attempts"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                if not self.channel_failed_attempts:
                    await event.respond("✅ Нет записей о неудачных попытках")
                    return
                
                # Sort channels by number of failed accounts (descending)
                sorted_channels = sorted(
                    self.channel_failed_attempts.items(),
                    key=lambda x: len(x[1]),
                    reverse=True
                )
                
                text = f"⚠️ **НЕУДАЧНЫЕ ПОПЫТКИ КОММЕНТИРОВАНИЯ**\n\n"
                text += f"Всего каналов с проблемами: {len(sorted_channels)}\n\n"
                
                # Show top 20 problematic channels
                for i, (channel, failures) in enumerate(sorted_channels[:20], 1):
                    display_name = channel if channel.startswith('@') else '@' + channel
                    
                    # Count persistent failures (3+ times)
                    persistent = sum(1 for data in failures.values() if data['count'] >= 3)
                    total_accounts = len(failures)
                    
                    text += f"{i}. {display_name}\n"
                    text += f"   📊 {total_accounts} аккаунтов | 🔴 {persistent} стабильных неудач\n"
                    
                    # Show most common reason
                    all_reasons = []
                    for data in failures.values():
                        all_reasons.extend(data['reasons'])
                    if all_reasons:
                        most_common = max(set(all_reasons), key=all_reasons.count)
                        text += f"   ⚠️ {most_common}\n"
                    text += "\n"
                
                if len(sorted_channels) > 20:
                    text += f"... и еще {len(sorted_channels) - 20} каналов\n\n"
                
                text += f"💡 Используйте `/resetfails` чтобы очистить счетчики"
                
                await event.respond(text)
            except Exception as e:
                logger.error(f"Show fails error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/clearblocked'))
        async def clear_blocked(event):
            """Clear blocked channels from database"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                if not self.conn:
                    await event.respond("❌ БД недоступна")
                    return
                
                cursor = self.conn.cursor()
                
                # Get count before deletion
                cursor.execute("SELECT COUNT(*) FROM blocked_channels")
                count_before = cursor.fetchone()[0]
                
                # Clear blocked channels table
                cursor.execute("DELETE FROM blocked_channels")
                self.conn.commit()
                
                await event.respond(
                    f"✅ **Заблокированные каналы очищены!**\n\n"
                    f"Удалено записей: {count_before}\n\n"
                    f"💡 Бот теперь будет пробовать комментировать эти каналы снова.\n"
                    f"⚠️ Используйте `/resetfails` чтобы также очистить счетчики неудач."
                )
                logger.info(f"Blocked channels cleared by admin {event.sender_id}")
            except Exception as e:
                logger.error(f"Clear blocked error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        # ============= PROFILE MANAGEMENT COMMANDS =============
        
        @self.bot_client.on(events.NewMessage(pattern='/setname'))
        async def setname_command(event):
            """Шаг 1: Показывает список аккаунтов для выбора"""
            if not await self.is_admin(event.sender_id):
                await event.respond("❌ У вас нет доступа к этому боту.")
                return
            
            try:
                # Get ALL accounts (not just active)
                all_accounts = [(phone, data) for phone, data in self.accounts_data.items() 
                                if data.get('session')]
                
                if not all_accounts:
                    await event.respond("❌ Нет авторизованных аккаунтов")
                    return
                
                # Build accounts list with status indicators
                text = "👤 **ИЗМЕНЕНИЕ ИМЕНИ**\n\n"
                text += "Выберите номер аккаунта:\n\n"
                
                for idx, (phone, data) in enumerate(all_accounts, 1):
                    # Get status indicator like in /listaccounts
                    status_val = data.get('status', ACCOUNT_STATUS_RESERVE)
                    if status_val == ACCOUNT_STATUS_ACTIVE:
                        status = "✅"
                    elif status_val == ACCOUNT_STATUS_BROKEN:
                        status = "🔴"
                    else:
                        status = "🔵"
                    
                    text += f"{idx}. {status} `{phone}`\n"
                
                text += "\n📝 Ответьте (reply) на это сообщение с номером аккаунта"
                
                # Send message and save state
                msg = await event.respond(text)
                self.user_states[event.sender_id] = {
                    'state': 'waiting_account_selection_for_name',
                    'message_id': msg.id,
                    'accounts': all_accounts
                }
                
            except Exception as e:
                logger.error(f"Setname command error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/setbio'))
        async def setbio_command(event):
            """Шаг 1: Показывает список аккаунтов для выбора"""
            if not await self.is_admin(event.sender_id):
                await event.respond("❌ У вас нет доступа к этому боту.")
                return
            
            try:
                # Get ALL accounts (not just active)
                all_accounts = [(phone, data) for phone, data in self.accounts_data.items() 
                                if data.get('session')]
                
                if not all_accounts:
                    await event.respond("❌ Нет авторизованных аккаунтов")
                    return
                
                # Build accounts list with status indicators
                text = "📝 **ИЗМЕНЕНИЕ БИО**\n\n"
                text += "Выберите номер аккаунта:\n\n"
                
                for idx, (phone, data) in enumerate(all_accounts, 1):
                    # Get status indicator like in /listaccounts
                    status_val = data.get('status', ACCOUNT_STATUS_RESERVE)
                    if status_val == ACCOUNT_STATUS_ACTIVE:
                        status = "✅"
                    elif status_val == ACCOUNT_STATUS_BROKEN:
                        status = "🔴"
                    else:
                        status = "🔵"
                    
                    text += f"{idx}. {status} `{phone}`\n"
                
                text += "\n📝 Ответьте (reply) на это сообщение с номером аккаунта"
                
                # Send message and save state
                msg = await event.respond(text)
                self.user_states[event.sender_id] = {
                    'state': 'waiting_account_selection_for_bio',
                    'message_id': msg.id,
                    'accounts': all_accounts
                }
                
            except Exception as e:
                logger.error(f"Setbio command error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/setavatar'))
        async def setavatar_command(event):
            """Шаг 1: Показывает список аккаунтов для выбора"""
            if not await self.is_admin(event.sender_id):
                await event.respond("❌ У вас нет доступа к этому боту.")
                return
            
            try:
                # Get ALL accounts (not just active)
                all_accounts = [(phone, data) for phone, data in self.accounts_data.items() 
                                if data.get('session')]
                
                if not all_accounts:
                    await event.respond("❌ Нет авторизованных аккаунтов")
                    return
                
                # Build accounts list with status indicators
                text = "📷 **ЗАГРУЗКА АВАТАРКИ**\n\n"
                text += "Выберите номер аккаунта:\n\n"
                
                for idx, (phone, data) in enumerate(all_accounts, 1):
                    # Get status indicator like in /listaccounts
                    status_val = data.get('status', ACCOUNT_STATUS_RESERVE)
                    if status_val == ACCOUNT_STATUS_ACTIVE:
                        status = "✅"
                    elif status_val == ACCOUNT_STATUS_BROKEN:
                        status = "🔴"
                    else:
                        status = "🔵"
                    
                    text += f"{idx}. {status} `{phone}`\n"
                
                text += "\n📝 Ответьте (reply) на это сообщение с номером аккаунта"
                
                # Send message and save state
                msg = await event.respond(text)
                self.user_states[event.sender_id] = {
                    'state': 'waiting_account_selection_for_avatar',
                    'message_id': msg.id,
                    'accounts': all_accounts
                }
                
            except Exception as e:
                logger.error(f"Setavatar command error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/profile'))
        async def profile_command(event):
            """Показывает текущую информацию о профилях всех активных аккаунтов"""
            if not await self.is_admin(event.sender_id):
                await event.respond("❌ У вас нет доступа к этому боту.")
                return
            
            try:
                # Get all active accounts (NEW: use status)
                active_accounts = [(phone, data) for phone, data in self.accounts_data.items() 
                                 if data.get('status') == ACCOUNT_STATUS_ACTIVE and data.get('session')]
                
                if not active_accounts:
                    await event.respond("❌ Нет активных авторизованных аккаунтов")
                    return
                
                text = f"👥 **ПРОФИЛИ АКТИВНЫХ АККАУНТОВ**\n\n"
                text += f"Всего аккаунтов: {len(active_accounts)}\n\n"
                
                profiles = []
                for phone, data in active_accounts[:10]:  # Limit to 10 for message size
                    try:
                        client = TelegramClient(
                            StringSession(data['session']), 
                            API_ID, 
                            API_HASH,
                            proxy=data.get('proxy')
                        )
                        await client.connect()
                        
                        if await client.is_user_authorized():
                            me = await client.get_me()
                            
                            profile_text = f"📱 `{phone[-4:]}`\n"
                            profile_text += f"👤 {me.first_name or ''} {me.last_name or ''}\n"
                            
                            if me.username:
                                profile_text += f"🔗 @{me.username}\n"
                            
                            bio = me.about or "Не указано"
                            profile_text += f"📝 {bio[:50]}{'...' if len(bio) > 50 else ''}\n"
                            profile_text += f"✅ Статус: Активен\n"
                            
                            profiles.append(profile_text)
                        else:
                            profiles.append(f"📱 `{phone[-4:]}`\n❌ Не авторизован\n")
                        
                        await client.disconnect()
                        
                    except Exception as e:
                        profiles.append(f"📱 `{phone[-4:]}`\n❌ Ошибка: {str(e)[:30]}\n")
                        logger.error(f"Error getting profile for {phone}: {e}")
                
                text += "\n".join(profiles)
                
                if len(active_accounts) > 10:
                    text += f"\n\n... и еще {len(active_accounts) - 10} аккаунтов"
                
                text += f"\n\n💡 Используйте:\n"
                text += f"`/setname` - изменить имя\n"
                text += f"`/setbio` - изменить описание\n"
                text += f"`/setavatar` - загрузить аватар"
                
                await event.respond(text)
                
            except Exception as e:
                logger.error(f"Profile command error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        # Handle text messages for account selection and data input
        @self.bot_client.on(events.NewMessage(func=lambda e: e.text and not e.text.startswith('/') and e.reply_to_msg_id))
        async def handle_profile_input(event):
            """Обрабатывает ввод номера аккаунта и данных профиля"""
            if not await self.is_admin(event.sender_id):
                return
            
            if event.sender_id not in self.user_states:
                return
            
            state_data = self.user_states[event.sender_id]
            state = state_data.get('state')
            
            try:
                # Step 2: Handle account selection (user replied with number)
                if state in ['waiting_account_selection_for_name', 'waiting_account_selection_for_bio', 'waiting_account_selection_for_avatar']:
                    # Check if reply is to our message
                    if event.reply_to_msg_id != state_data.get('message_id'):
                        return
                    
                    # Parse account number
                    try:
                        account_num = int(event.text.strip())
                    except ValueError:
                        await event.respond("❌ Введите число (номер аккаунта)")
                        return
                    
                    accounts = state_data.get('accounts', [])
                    if account_num < 1 or account_num > len(accounts):
                        await event.respond(f"❌ Неверный номер. Выберите от 1 до {len(accounts)}")
                        return
                    
                    # Get selected account
                    selected_phone, selected_data = accounts[account_num - 1]
                    
                    # Update state based on command type
                    if state == 'waiting_account_selection_for_name':
                        self.user_states[event.sender_id] = {
                            'state': 'waiting_name_input',
                            'phone': selected_phone,
                            'data': selected_data
                        }
                        await event.respond(
                            f"👤 **Аккаунт {account_num}: `{selected_phone}`**\n\n"
                            f"Отправьте новое имя (и фамилию):\n"
                            f"Например: `Иван Петров`"
                        )
                    elif state == 'waiting_account_selection_for_bio':
                        self.user_states[event.sender_id] = {
                            'state': 'waiting_bio_input',
                            'phone': selected_phone,
                            'data': selected_data
                        }
                        await event.respond(
                            f"📝 **Аккаунт {account_num}: `{selected_phone}`**\n\n"
                            f"Отправьте новое описание (био):\n"
                            f"Например: `Инвестор | Трейдер | Крипто 🚀`"
                        )
                    elif state == 'waiting_account_selection_for_avatar':
                        self.user_states[event.sender_id] = {
                            'state': 'waiting_avatar_photo',
                            'phone': selected_phone,
                            'data': selected_data
                        }
                        await event.respond(
                            f"📷 **Аккаунт {account_num}: `{selected_phone}`**\n\n"
                            f"Отправьте фото для аватарки (jpg, png)"
                        )
                
                # Step 3: Handle data input for selected account
                elif state == 'waiting_name_input':
                    new_name = event.text.strip()
                    phone = state_data.get('phone')
                    data = state_data.get('data')
                    
                    if not new_name:
                        await event.respond("❌ Имя не может быть пустым")
                        return
                    
                    # Parse name
                    name_parts = new_name.split(maxsplit=1)
                    first_name = name_parts[0]
                    last_name = name_parts[1] if len(name_parts) > 1 else ""
                    
                    await event.respond("⏳ Обновляю имя...")
                    
                    # Update profile
                    try:
                        client = TelegramClient(
                            StringSession(data['session']), 
                            API_ID, 
                            API_HASH,
                            proxy=data.get('proxy')
                        )
                        await client.connect()
                        
                        if await client.is_user_authorized():
                            # Get current name
                            me = await client.get_me()
                            old_name = f"{me.first_name or ''} {me.last_name or ''}".strip()
                            
                            # Update
                            await client(UpdateProfileRequest(
                                first_name=first_name,
                                last_name=last_name
                            ))
                            
                            # Log
                            await self.log_profile_change(phone, 'name', old_name, new_name, True)
                            
                            await event.respond(
                                f"✅ **Имя обновлено для `{phone}`**\n\n"
                                f"Новое имя: {first_name} {last_name}"
                            )
                            logger.info(f"Name updated for {phone}: {new_name}")
                        else:
                            await event.respond(f"❌ Аккаунт `{phone}` не авторизован")
                        
                        await client.disconnect()
                    except Exception as e:
                        await self.log_profile_change(phone, 'name', '', new_name, False)
                        await event.respond(f"❌ Ошибка: {str(e)[:100]}")
                        logger.error(f"Error updating name for {phone}: {e}")
                    
                    # Clear state
                    await self.clear_user_state(event.sender_id)
                
                elif state == 'waiting_bio_input':
                    new_bio = event.text.strip()
                    phone = state_data.get('phone')
                    data = state_data.get('data')
                    
                    if not new_bio:
                        await event.respond("❌ Описание не может быть пустым")
                        return
                    
                    await event.respond("⏳ Обновляю био...")
                    
                    # Update profile
                    try:
                        client = TelegramClient(
                            StringSession(data['session']), 
                            API_ID, 
                            API_HASH,
                            proxy=data.get('proxy')
                        )
                        await client.connect()
                        
                        if await client.is_user_authorized():
                            # Update bio using UpdateProfileRequest
                            await client(UpdateProfileRequest(about=new_bio))
                            
                            # Log (without old bio, as it requires additional request)
                            await self.log_profile_change(phone, 'bio', '', new_bio, True)
                            
                            await event.respond(
                                f"✅ **Био обновлено для `{phone}`**\n\n"
                                f"Новое био: {new_bio[:100]}"
                            )
                            logger.info(f"Bio updated for {phone}: {new_bio[:50]}")
                        else:
                            await event.respond(f"❌ Аккаунт `{phone}` не авторизован")
                        
                        await client.disconnect()
                    except Exception as e:
                        await self.log_profile_change(phone, 'bio', '', new_bio, False)
                        await event.respond(f"❌ Ошибка: {str(e)[:100]}")
                        logger.error(f"Error updating bio for {phone}: {e}")
                    
                    # Clear state
                    await self.clear_user_state(event.sender_id)
                    
            except Exception as e:
                logger.error(f"Handle profile input error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
                await self.clear_user_state(event.sender_id)
        
        # Handle photo upload for avatar
        @self.bot_client.on(events.NewMessage(func=lambda e: e.photo))
        async def handle_avatar_photo(event):
            """Обрабатывает загрузку фото для аватарки выбранного аккаунта"""
            if not await self.is_admin(event.sender_id):
                return
            
            if event.sender_id not in self.user_states:
                return
            
            state_data = self.user_states[event.sender_id]
            state = state_data.get('state')
            
            if state != 'waiting_avatar_photo':
                return
            
            try:
                phone = state_data.get('phone')
                data = state_data.get('data')
                
                # Download photo
                photo_path = await event.download_media(file=f"/tmp/avatar_{event.sender_id}.jpg")
                
                if not photo_path or not os.path.exists(photo_path):
                    await event.respond("❌ Ошибка загрузки фото")
                    await self.clear_user_state(event.sender_id)
                    return
                
                await event.respond("⏳ Загружаю аватарку...")
                
                # Upload to selected account
                try:
                    client = TelegramClient(
                        StringSession(data['session']), 
                        API_ID, 
                        API_HASH,
                        proxy=data.get('proxy')
                    )
                    await client.connect()
                    
                    if await client.is_user_authorized():
                        # Upload profile photo
                        await client(UploadProfilePhotoRequest(
                            file=await client.upload_file(photo_path)
                        ))
                        
                        # Log
                        await self.log_profile_change(phone, 'avatar', '', 'uploaded', True)
                        
                        await event.respond(f"✅ **Аватарка загружена для `{phone}`**")
                        logger.info(f"Avatar uploaded for {phone}")
                    else:
                        await event.respond(f"❌ Аккаунт `{phone}` не авторизован")
                    
                    await client.disconnect()
                except Exception as e:
                    await self.log_profile_change(phone, 'avatar', '', '', False)
                    await event.respond(f"❌ Ошибка: {str(e)[:100]}")
                    logger.error(f"Error uploading avatar for {phone}: {e}")
                
                # Clean up temp file
                try:
                    os.remove(photo_path)
                except:
                    pass
                
                # Clear state
                await self.clear_user_state(event.sender_id)
                
            except Exception as e:
                logger.error(f"Handle avatar photo error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
                await self.clear_user_state(event.sender_id)
        
        # ============= END PROFILE MANAGEMENT COMMANDS =============
    
    async def auto_stop_after_4_hours(self, chat_id):
        """Automatically stop monitoring after 4 hours"""
        try:
            # Disabled for maximum runtime - bot runs indefinitely
            return  # Skip auto-stop
            
            if self.monitoring:  # Check if still running
                self.monitoring = False
                elapsed_time = datetime.now() - self.monitoring_start_time if self.monitoring_start_time else None
                
                msg = f"""⏱ АВТОКОММЕНТАРИИ ОСТАНОВЛЕНЫ\n\n✅ Работа завершена автоматически после 4 часов\n\n📊 Статистика сессии:\n• Комментариев сегодня: `{self.stats.get('daily_comments', 0)}`\n• Всего комментариев: `{self.stats.get('total_comments', 0)}`"""
                
                await self.bot_client.send_message(chat_id, msg)
                logger.info("Monitoring auto-stopped after 4 hours")
        except Exception as e:
            logger.error(f"Auto-stop error: {e}")
    
    def generate_comment_variation(self, template):
        """Generate natural variations of comments to avoid detection"""
        # Add random spaces, emojis, or punctuation variations
        variations = [
            template,  # Original
            template + " 😊",
            template + "!",
            template.replace("!", " !"),
            template + " ❤️",
        ]
        
        # Add trailing spaces or line breaks sometimes (natural typing)
        if random.random() < 0.3:
            variations.append(template + " ")
        
        # Randomly capitalize first letter differently
        if random.random() < 0.2 and len(template) > 0:
            variations.append(template[0].lower() + template[1:] if template[0].isupper() else template[0].upper() + template[1:])
        
        return random.choice(variations)
    
    async def account_worker(self, phone, account_data, channel_subset):
        """Worker function for each account to process its assigned channels"""
        logger.info("="*60)
        logger.info(f"👷 WORKER STARTED: {account_data.get('name', phone)} ({phone[-10:]})")
        logger.info(f"📢 Assigned channels: {len(channel_subset)}")
        for i, ch in enumerate(channel_subset[:5], 1):
            ch_name = ch.get('username') if isinstance(ch, dict) else ch
            logger.info(f"   {i}. {ch_name}")
        if len(channel_subset) > 5:
            logger.info(f"   ... and {len(channel_subset) - 5} more")
        logger.info("="*60)
        
        # Add initial random delay (warmup) to avoid all accounts starting simultaneously
        initial_delay = random.randint(5, 30)
        logger.info(f"[{account_data.get('name', phone)}] ⏳ Initial warmup delay: {initial_delay}s")
        await asyncio.sleep(initial_delay)
        
        logger.info(f"[{account_data.get('name', phone)}] 🔄 Entering main loop (monitoring={self.monitoring})")
        
        while self.monitoring:
            logger.info(f"[{account_data.get('name', phone)}] 🔄 Starting new cycle...")
            
            # ============= NEW: Check account status and rate limits =============
            # Проверяем статус аккаунта
            current_status = self.get_account_status(phone)
            logger.info(f"[{account_data.get('name', phone)}] 📊 Status check: {current_status}")
            
            if current_status != ACCOUNT_STATUS_ACTIVE:
                logger.warning(f"[{account_data.get('name', phone)}] ⚠️ Status is {current_status}, pausing worker")
                await asyncio.sleep(30)  # Ждем и проверяем снова
                continue
            
            # Проверяем лимит сообщений
            can_send, wait_time = self.can_account_send_message(phone)
            logger.info(f"[{account_data.get('name', phone)}] 📊 Rate limit check: can_send={can_send}, wait_time={wait_time}")
            
            if not can_send:
                logger.warning(f"[{account_data.get('name', phone)}] ⚠️ Rate limit reached. Waiting {wait_time}s")
                await asyncio.sleep(min(wait_time + 10, 300))  # Ждем с небольшим запасом, но не более 5 минут
                continue
            
            logger.info(f"[{account_data.get('name', phone)}] ✅ All checks passed, starting channel processing...")
            # ============= END NEW =============
            
            # Process each channel in the subset
            logger.info(f"[{account_data.get('name', phone)}] 📢 Processing {len(channel_subset)} channels...")
            for idx, channel in enumerate(channel_subset, 1):
                if not self.monitoring:
                    break
                
                # ============= NEW: Re-check status before each channel =============
                current_status = self.get_account_status(phone)
                if current_status != ACCOUNT_STATUS_ACTIVE:
                    logger.info(f"[{account_data.get('name', phone)}] Status changed to {current_status}, stopping")
                    break
                
                # Проверяем лимит перед каждым комментарием
                can_send, wait_time = self.can_account_send_message(phone)
                if not can_send:
                    logger.warning(f"[{account_data.get('name', phone)}] Rate limit reached mid-cycle. Pausing for {wait_time}s")
                    await asyncio.sleep(min(wait_time + 10, 300))
                    continue
                # ============= END NEW =============
                
                # normalize channel entry
                if isinstance(channel, dict):
                    username = channel.get('username') or channel.get('name')
                else:
                    username = str(channel)
                username = str(username).strip()
                
                # ============= NEW: Check if we can comment in this channel (anti-spam protection) =============
                can_comment, wait_for_channel = self.can_account_comment_in_channel(phone, username)
                if not can_comment:
                    logger.info(f"[{account_data.get('name', phone)}] Another account commented in {username} recently. Waiting {wait_for_channel}s")
                    await asyncio.sleep(wait_for_channel)
                    # После ожидания пропускаем этот канал и идем к следующему
                    continue
                # ============= END NEW =============
                
                # Initialize tracking for this channel
                if username not in self.commented_posts:
                    self.commented_posts[username] = set()

                client = TelegramClient(StringSession(account_data['session']), API_ID, API_HASH, proxy=account_data.get('proxy'))
                await client.connect()
                try:
                    if not await client.is_user_authorized():
                        logger.warning(f"Account not authorized: {phone}")
                        await asyncio.sleep(5)
                        continue

                    # resolve channel entity with auto-join for public channels
                    channel_entity = None
                    # Remove @ if present for URL construction
                    username_clean = username.lstrip('@') if username.startswith('@') else username
                    try:
                        # Try get_entity (works if already cached or subscribed)
                        try:
                            channel_entity = await client.get_entity(username)
                        except:
                            channel_entity = await client.get_entity('https://t.me/' + username_clean)
                    except Exception as e_get:
                        # If not found, try to join the channel first
                        logger.info(f"[{account_data.get('name', phone)}] Trying to join {username}...")
                        try:
                            # Join via URL (works for public channels)
                            result = await client(functions.channels.JoinChannelRequest('https://t.me/' + username_clean))
                            await asyncio.sleep(1)
                            # Now try to get entity again
                            try:
                                channel_entity = await client.get_entity(username)
                                logger.info(f"[{account_data.get('name', phone)}] Joined and got {username}")
                            except:
                                channel_entity = await client.get_entity('https://t.me/' + username_clean)
                        except Exception as e_join:
                            logger.error(f"[{account_data.get('name', phone)}] Cannot join/get {username}: {e_join}")
                            await self.mark_channel_failed_for_account(username, phone, f"Cannot access: {str(e_join)[:50]}")
                            await asyncio.sleep(1)
                            continue
                    
                    if not channel_entity:
                        logger.error(f"[{account_data.get('name', phone)}] Failed to get entity for {username}")
                        await self.mark_channel_failed_for_account(username, phone, "Failed to get entity")
                        await asyncio.sleep(1)
                        continue

                    # find linked discussion chat id with improved error handling
                    linked_chat_id = None
                    discussion_entity = None
                    comments_disabled = False
                    
                    try:
                        full = await client(functions.channels.GetFullChannelRequest(channel=channel_entity))
                        
                        # Try multiple ways to get linked_chat_id
                        if hasattr(full, 'full_chat'):
                            # Check if comments are explicitly disabled
                            if hasattr(full.full_chat, 'available_reactions') and not full.full_chat.available_reactions:
                                logger.info(f"[{account_data.get('name', phone)}] {username} has reactions disabled")
                            
                            if hasattr(full.full_chat, 'linked_chat_id'):
                                linked_chat_id = full.full_chat.linked_chat_id
                                logger.info(f"[{account_data.get('name', phone)}] Found linked_chat_id: {linked_chat_id}")
                        
                        # Fallback: check in chats list
                        if not linked_chat_id and hasattr(full, 'chats'):
                            for ch in full.chats:
                                # Check if this is a discussion chat (megagroup)
                                if hasattr(ch, 'megagroup') and ch.megagroup:
                                    try:
                                        discussion_entity = ch
                                        linked_chat_id = ch.id
                                        logger.info(f"[{account_data.get('name', phone)}] Found discussion group in chats for {username}")
                                        break
                                    except Exception:
                                        continue
                    except Exception as e_full:
                        logger.error(f"[{account_data.get('name', phone)}] GetFullChannel error for {username}: {e_full}")
                        # If we can't get full info, mark as potentially no discussion
                        await asyncio.sleep(2)
                        continue

                    # If we don't have discussion_entity yet, try to get it by ID
                    if linked_chat_id and not discussion_entity:
                        # Try multiple methods to resolve the entity
                        methods_tried = 0
                        for attempt in range(3):
                            try:
                                methods_tried += 1
                                if attempt == 0:
                                    # Method 1: Direct get by ID
                                    discussion_entity = await client.get_entity(int(linked_chat_id))
                                elif attempt == 1:
                                    # Method 2: Using PeerChannel
                                    from telethon.tl.types import PeerChannel
                                    discussion_entity = await client.get_entity(PeerChannel(int(linked_chat_id)))
                                else:
                                    # Method 3: Negative ID (sometimes works)
                                    discussion_entity = await client.get_entity(-100 + int(linked_chat_id) if linked_chat_id > 0 else linked_chat_id)
                                
                                if discussion_entity:
                                    logger.info(f"[{account_data.get('name', phone)}] Resolved discussion entity (method {attempt+1})")
                                    break
                            except Exception as e_get:
                                if attempt == 2:
                                    logger.error(f"[{account_data.get('name', phone)}] All methods failed to get discussion entity: {e_get}")
                                await asyncio.sleep(0.5)
                    
                    # Check if we successfully got discussion entity
                    if not discussion_entity and not linked_chat_id:
                        # Channel has no discussion group - mark as failed with specific reason
                        await self.mark_channel_failed_for_account(username, phone, "No discussion group")
                        logger.warning(f"[{account_data.get('name', phone)}] {username} has no discussion - marking as failed")
                        await asyncio.sleep(1)
                        continue
                    elif not discussion_entity:
                        # Has linked_chat_id but couldn't resolve - might be temporary
                        logger.warning(f"[{account_data.get('name', phone)}] Could not resolve discussion for {username} - will retry later")
                        await asyncio.sleep(2)
                        continue

                    # Get recent messages to find new posts (check last 10 messages for better coverage)
                    try:
                        msgs = await client.get_messages(discussion_entity, limit=10)
                        
                        # Find first message that hasn't been commented on yet
                        reply_id = None
                        post_text = ""
                        for msg in msgs:
                            if msg.id not in self.commented_posts[username]:
                                reply_id = msg.id
                                # Get text from this message
                                post_text = msg.text or msg.message or ""
                                break
                        
                        # If all recent posts are commented, comment on the latest one
                        if not reply_id and msgs:
                            reply_id = msgs[0].id
                            post_text = msgs[0].text or msgs[0].message or ""
                            # Clean old tracking to prevent memory issues
                            if len(self.commented_posts[username]) > 30:
                                oldest_ids = sorted(list(self.commented_posts[username]))[:15]
                                for old_id in oldest_ids:
                                    self.commented_posts[username].discard(old_id)
                        
                        # If we don't have post text from discussion, try to get from channel
                        if not post_text:
                            try:
                                channel_msgs = await client.get_messages(channel_entity, limit=5)
                                if channel_msgs:
                                    post_text = channel_msgs[0].text or channel_msgs[0].message or "Интересный пост!"
                            except Exception as e_ch:
                                logger.debug(f"Could not get channel messages: {e_ch}")
                                post_text = "Интересный пост!"
                        
                        # Generate AI comment based on post text
                        channel_theme_str = channel.get('theme', 'общая') if isinstance(channel, dict) else 'общая'
                        comment = generate_neuro_comment(
                            post_text=post_text,
                            channel_theme=channel_theme_str
                        )
                        
                        # ============= TEST MODE: Check for duplicate comments =============
                        if self.test_mode:
                            if not hasattr(self, '_last_test_comments'):
                                self._last_test_comments = []
                            
                            # Check if this comment was used recently
                            if comment in self._last_test_comments:
                                logger.warning(f"🧪 TEST MODE: Duplicate comment detected! Regenerating...")
                                # Try to regenerate
                                comment = generate_neuro_comment(
                                    post_text=post_text,
                                    channel_theme=channel_theme_str
                                )
                                # If still duplicate, use variation
                                if comment in self._last_test_comments:
                                    base_comment = random.choice(self.templates)
                                    comment = self.generate_comment_variation(base_comment)
                            
                            # Keep last 10 comments to check for duplicates
                            self._last_test_comments.append(comment)
                            if len(self._last_test_comments) > 10:
                                self._last_test_comments.pop(0)
                        # ============= END TEST MODE =============
                        
                    except Exception as e_msgs:
                        logger.error(f"Error getting messages: {e_msgs}")
                        reply_id = None
                        # Use fallback comment generation
                        base_comment = random.choice(self.templates)
                        comment = self.generate_comment_variation(base_comment)

                    # Try to join discussion group first (auto-join for guests)
                    try:
                        await client(functions.channels.JoinChannelRequest(discussion_entity))
                        logger.info(f"[{account_data.get('name', phone)}] Joined discussion for {username}")
                        await asyncio.sleep(1)
                    except Exception as join_err:
                        # Already joined or can't join - not critical
                        logger.debug(f"[{account_data.get('name', phone)}] Join discussion: {join_err}")
                    
                    # send comment into discussion
                    comment_success = False
                    try:
                        if reply_id:
                            await client.send_message(discussion_entity, comment, reply_to=reply_id)
                            # Mark this post as commented
                            self.commented_posts[username].add(reply_id)
                        else:
                            await client.send_message(discussion_entity, comment)
                        
                        comment_success = True
                        
                        # ============= NEW: Register message sent for rate limiting =============
                        self.register_message_sent(phone, username)
                        # ============= END NEW =============
                        
                        # ============= TEST MODE: Detailed logging =============
                        if self.test_mode:
                            short_comment = comment[:50] if len(comment) > 50 else comment
                            logger.info(f"🧪 TEST MODE SUCCESS:")
                            logger.info(f"   Channel: @{username}")
                            logger.info(f"   Account: {account_data.get('name', phone)} ({phone})")
                            logger.info(f"   Comment: {short_comment}...")
                            logger.info(f"   Time: {datetime.now().strftime('%H:%M:%S')}")
                            logger.info(f"   Post ID: {reply_id}")
                        # ============= END TEST MODE =============
                        
                        logger.info(f"[{account_data.get('name', phone)}] ✅ @{username} (post {reply_id}): {comment}")
                        await self.add_comment_stat(phone, True, channel=username)

                        if self.conn:
                            try:
                                cursor = self.conn.cursor()
                                cursor.execute(
                                    "INSERT INTO comment_history (phone, channel, comment, date) VALUES (?, ?, ?, ?)",
                                    (phone, username, comment, datetime.now().isoformat()),
                                )
                                self.conn.commit()
                            except Exception as db_err:
                                logger.error(f"DB log error: {db_err}")
                                
                    except Exception as send_exc:
                        err_text = str(send_exc)
                        
                        # ============= TEST MODE: Detailed error logging =============
                        if self.test_mode:
                            logger.error(f"🧪 TEST MODE ERROR:")
                            logger.error(f"   Channel: @{username}")
                            logger.error(f"   Account: {account_data.get('name', phone)} ({phone})")
                            logger.error(f"   Error: {err_text[:100]}")
                            logger.error(f"   Time: {datetime.now().strftime('%H:%M:%S')}")
                        # ============= END TEST MODE =============
                        
                        logger.error(f"[{account_data.get('name', phone)}] ❌ Send error for @{username}: {err_text}")
                        
                        # Categorize errors for better handling
                        permanent_errors = [
                            "You can't write in this chat",
                            "CHAT_WRITE_FORBIDDEN",
                            "CHAT_SEND_PLAIN_FORBIDDEN",
                            "CHANNEL_PRIVATE"
                        ]
                        
                        temp_errors = [
                            "FloodWait",
                            "SLOWMODE_WAIT",
                            "TIMEOUT",
                            "CONNECTION"
                        ]
                        
                        # Check for permanent errors
                        is_permanent = any(err in err_text for err in permanent_errors)
                        is_temp = any(err in err_text for err in temp_errors)
                        
                        if is_permanent:
                            await self.mark_channel_failed_for_account(username, phone, "Comments disabled/forbidden")
                            logger.warning(f"[{account_data.get('name', phone)}] {username} marked as no-comment channel")
                        elif "CHAT_GUEST_SEND_FORBIDDEN" in err_text:
                            # Need to join - retry
                            logger.info(f"[{account_data.get('name', phone)}] Guest forbidden - trying to join {username}")
                            try:
                                await client(functions.channels.JoinChannelRequest(discussion_entity))
                                await asyncio.sleep(2)
                                # Retry sending after join
                                if reply_id:
                                    await client.send_message(discussion_entity, comment, reply_to=reply_id)
                                    self.commented_posts[username].add(reply_id)
                                else:
                                    await client.send_message(discussion_entity, comment)
                                
                                comment_success = True
                                
                                # ============= NEW: Register message sent for rate limiting =============
                                self.register_message_sent(phone, username)
                                # ============= END NEW =============
                                
                                logger.info(f"[{account_data.get('name', phone)}] ✅ Joined & commented {username}")
                                await self.add_comment_stat(phone, True, channel=username)
                                
                                if self.conn:
                                    try:
                                        cursor = self.conn.cursor()
                                        cursor.execute(
                                            "INSERT INTO comment_history (phone, channel, comment, date) VALUES (?, ?, ?, ?)",
                                            (phone, username, comment, datetime.now().isoformat()),
                                        )
                                        self.conn.commit()
                                    except Exception as db_err:
                                        logger.error(f"DB log error: {db_err}")
                            except Exception as retry_err:
                                logger.error(f"[{account_data.get('name', phone)}] Retry failed: {retry_err}")
                                # Only mark as failed after retry failed
                                await self.mark_channel_failed_for_account(username, phone, "Guest send forbidden (after retry)")
                        elif "CHAT_RESTRICTED" in err_text:
                            await self.mark_channel_failed_for_account(username, phone, "Chat restricted")
                        elif "USER_BANNED_IN_CHANNEL" in err_text:
                            logger.warning(f"[{account_data.get('name', phone)}] Banned in {username} - account specific")
                            await self.mark_channel_failed_for_account(username, phone, "Account banned in this channel")
                        elif is_temp:
                            # Temporary errors - don't mark as failed
                            logger.warning(f"[{account_data.get('name', phone)}] Temporary error on {username}: {err_text}")
                            if "FloodWait" in err_text:
                                raise  # Re-raise to trigger FloodWait handling below
                        else:
                            # Unknown error - log but don't fail immediately
                            logger.error(f"[{account_data.get('name', phone)}] Unknown error on {username}: {err_text}")
                            # Mark as failed only after 2nd attempt
                            if username not in self.channel_failed_attempts or phone not in self.channel_failed_attempts.get(username, {}):
                                logger.info(f"[{account_data.get('name', phone)}] First unknown error - will retry {username} later")
                            else:
                                await self.mark_channel_failed_for_account(username, phone, f"Unknown: {err_text[:30]}")
                except Exception as e:
                    error_str = str(e)
                    logger.error(f"[{account_data.get('name', phone)}] Error commenting on {username}: {error_str}")
                    
                    # Only handle serious account-level errors
                    if "FloodWait" in error_str:
                        # Extract wait time if available
                        try:
                            import re
                            wait_match = re.search(r'(\d+)', error_str)
                            wait_seconds = int(wait_match.group(1)) if wait_match else 60
                            logger.warning(f"[{account_data.get('name', phone)}] FloodWait {wait_seconds}s - waiting...")
                            await asyncio.sleep(min(wait_seconds + 5, 120))  # Wait but max 2 minutes
                        except Exception:
                            await asyncio.sleep(60)
                    elif "USER_DEACTIVATED" in error_str or "AUTH_KEY_UNREGISTERED" in error_str:
                        # Account is permanently banned
                        logger.error(f"[{account_data.get('name', phone)}] ACCOUNT PERMANENTLY BANNED!")
                        try:
                            if self.conn:
                                cursor = self.conn.cursor()
                                cursor.execute(
                                    "INSERT OR IGNORE INTO blocked_accounts (phone, block_date, reason) VALUES (?, ?, ?)",
                                    (phone, datetime.now().isoformat(), "Account Deactivated"),
                                )
                                self.conn.commit()
                            await self.handle_account_ban(phone, "Account Deactivated")
                            # Stop this worker
                            break
                        except Exception as db_err:
                            logger.error(f"DB error: {db_err}")
                    elif "banned" in error_str.lower() and "channel" not in error_str.lower():
                        # Account banned (not just in one channel)
                        logger.error(f"[{account_data.get('name', phone)}] ACCOUNT BANNED!")
                        try:
                            if self.conn:
                                cursor = self.conn.cursor()
                                cursor.execute(
                                    "INSERT OR IGNORE INTO blocked_accounts (phone, block_date, reason) VALUES (?, ?, ?)",
                                    (phone, datetime.now().isoformat(), "Account Ban"),
                                )
                                self.conn.commit()
                            await self.handle_account_ban(phone, "Account Ban")
                            # Stop this worker
                            break
                        except Exception as db_err:
                            logger.error(f"DB error: {db_err}")
                    else:
                        # Temporary error - continue with next channel
                        logger.info(f"[{account_data.get('name', phone)}] Skipping {username} due to temporary error")
                        await asyncio.sleep(3)
                finally:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
                
                # Delay between comments from same account (50-100 sec for optimal mode)
                # Random delays make activity look more human
                delay = random.randint(50, 100)  # 50-100 seconds between comments (optimal mode)
                logger.info(f"[{account_data.get('name', phone)}] Waiting {delay}s before next comment...")
                await asyncio.sleep(delay)
            
            # After completing all channels, shuffle and start over
            random.shuffle(channel_subset)
            logger.info(f"[{account_data.get('name', phone)}] Completed cycle, restarting...")
            # Longer break between cycles (3-7 minutes)
            await asyncio.sleep(random.randint(180, 420))
    
    async def pro_auto_comment(self):
        """Main commenting loop - runs accounts in parallel with rate limiting, rotation, and auto-replacement!"""
        logger.info("="*80)
        logger.info("🚀 PRO_AUTO_COMMENT STARTED")
        logger.info("="*80)
        
        # ============= NEW: Работаем только с активными аккаунтами (статус 'active') =============
        logger.info(f"📊 Total accounts in system: {len(self.accounts_data)}")
        
        # Debug: show all accounts with statuses
        for phone, data in self.accounts_data.items():
            status = data.get('status', 'UNKNOWN')
            has_session = 'session' in data and data.get('session')
            logger.info(f"   Account {phone[-10:]}: status={status}, has_session={has_session}")
        
        active_accounts = {phone: data for phone, data in self.accounts_data.items()
                         if data.get('status') == ACCOUNT_STATUS_ACTIVE and data.get('session')}
        # ============= END NEW =============
        
        logger.info(f"✅ Active accounts with sessions: {len(active_accounts)}")
        if active_accounts:
            for phone in active_accounts:
                logger.info(f"   ✅ {phone[-10:]}")
        
        if not active_accounts:
            logger.error("❌ No active accounts found!")
            logger.error("💡 Use /listaccounts to check account statuses")
            logger.error("💡 Use /toggleaccount to activate accounts")
            return
        
        logger.info(f"📢 Total channels in system: {len(self.channels)}")
        if not self.channels:
            logger.error("❌ No channels found!")
            logger.error("💡 Use /addchannel to add channels")
            return
        
        # ============= TEST MODE: Filter channels =============
        channels_to_use = self.channels
        logger.info(f"🔍 Checking TEST MODE: enabled={self.test_mode}")
        
        if self.test_mode and self.test_channels:
            logger.info(f"🧪 TEST MODE IS ACTIVE!")
            logger.info(f"🧪 Test channels defined: {self.test_channels}")
            logger.info(f"🧪 Filtering from {len(self.channels)} total channels...")
            
            # В тестовом режиме используем только тестовые каналы
            channels_to_use = []
            for ch in self.channels:
                ch_username = ch.get('username') if isinstance(ch, dict) else ch
                # Normalize username
                if not ch_username.startswith('@'):
                    ch_username = '@' + ch_username
                
                logger.debug(f"   Checking channel: {ch_username}")
                if ch_username in self.test_channels:
                    channels_to_use.append(ch)
                    logger.info(f"   ✅ MATCH: {ch_username}")
            
            if not channels_to_use:
                logger.error(f"🧪 ❌ TEST MODE: None of test channels {self.test_channels} found in channels list!")
                logger.error(f"Available channels (first 10): {[ch.get('username') if isinstance(ch, dict) else ch for ch in self.channels[:10]]}")
                logger.error("💡 Check that test channel usernames match exactly (with @)")
                logger.error("💡 Use /listchannels to see all available channels")
                return
            
            logger.info(f"🧪 TEST MODE ACTIVE: Using {len(channels_to_use)} test channels: {self.test_channels}")
            logger.info(f"🧪 Speed limit: {self.test_mode_speed_limit} msg/hour per account")
            logger.warning("🧪 ⚠️ ALL OTHER CHANNELS WILL BE IGNORED!")
        else:
            logger.info(f"ℹ️ NORMAL MODE: Using all {len(self.channels)} channels")
        # ============= END TEST MODE =============
        
        # Use configured max parallel accounts
        MAX_PARALLEL_ACCOUNTS = self.max_parallel_accounts
        
        # ============= NEW: Initialize rotation timer =============
        if self.last_rotation_time is None:
            self.last_rotation_time = datetime.now().timestamp()
        # ============= END NEW =============
        
        # Divide channels among accounts for parallel processing
        accounts_list = list(active_accounts.items())
        num_accounts = min(len(accounts_list), MAX_PARALLEL_ACCOUNTS)
        
        if len(accounts_list) > MAX_PARALLEL_ACCOUNTS:
            logger.warning(f"⚠️ You have {len(accounts_list)} active accounts, but only {MAX_PARALLEL_ACCOUNTS} will work in parallel")
            logger.warning(f"⚠️ Use /setparallel to change this limit")
        
        accounts_list = accounts_list[:MAX_PARALLEL_ACCOUNTS]  # Use first N accounts
        
        # ============= TEST MODE: Use filtered channels =============
        if self.test_mode and self.test_channels:
            channels_copy = channels_to_use.copy()
        else:
            channels_copy = self.channels.copy()
        # ============= END TEST MODE =============
        
        random.shuffle(channels_copy)
        
        # Calculate channels per account
        channels_per_account = len(channels_copy) // num_accounts if num_accounts > 0 else 0
        remainder = len(channels_copy) % num_accounts if num_accounts > 0 else 0
        
        # ============= TEST MODE: Log info =============
        if self.test_mode:
            logger.info(f"🧪 TEST MODE: {num_accounts} accounts × {len(channels_copy)} TEST channels")
            logger.info(f"🧪 Test channels: {self.test_channels}")
            logger.info(f"🧪 Speed limit: {self.test_mode_speed_limit} msg/hour per account")
        else:
            logger.info(f"🚀 SMART MODE: {num_accounts} active accounts (max {MAX_PARALLEL_ACCOUNTS}) × {len(channels_copy)} channels")
        # ============= END TEST MODE =============
        
        logger.info(f"📊 Each account handles ~{channels_per_account} channels")
        logger.info(f"⚡ Rate limit: {self.messages_per_hour} msg/hour per account")
        logger.info(f"🔄 Rotation interval: {self.rotation_interval // 3600}h ({self.rotation_interval}s)")
        logger.info(f"🛡️ Anti-spam: {MIN_INTERVAL_BETWEEN_OWN_ACCOUNTS}s between own accounts in same chat")
        
        # ============= NEW: Start rotation task =============
        rotation_task = asyncio.create_task(self.rotation_worker())
        # ============= END NEW =============
        
        # Create worker tasks for each account
        tasks = []
        start_idx = 0
        
        for i, (phone, data) in enumerate(accounts_list):
            # Give extra channels to first accounts if there's a remainder
            end_idx = start_idx + channels_per_account + (1 if i < remainder else 0)
            channel_subset = channels_copy[start_idx:end_idx]
            
            logger.info(f"[{data.get('name', phone)}] Assigned channels {start_idx+1}-{end_idx}")
            
            # Create worker task for this account
            task = asyncio.create_task(self.account_worker(phone, data, channel_subset))
            tasks.append(task)
            
            start_idx = end_idx
        
        # Wait for all workers (they run until self.monitoring becomes False)
        try:
            # ============= NEW: Wait for both worker tasks and rotation task =============
            all_tasks = tasks + [rotation_task]
            await asyncio.gather(*all_tasks, return_exceptions=True)
            # ============= END NEW =============
        except Exception as e:
            logger.error(f"Error in parallel workers: {e}")
    
    async def rotation_worker(self):
        """Background worker that performs periodic account rotation"""
        logger.info(f"🔄 Rotation worker started (interval: {self.rotation_interval}s)")
        
        while self.monitoring:
            try:
                # Wait and check rotation periodically (every 5 minutes)
                await asyncio.sleep(300)  # Check every 5 minutes
                
                if not self.monitoring:
                    break
                
                # Check if rotation is needed
                await self.check_and_rotate_if_needed()
                
            except Exception as e:
                logger.error(f"Error in rotation worker: {e}")
                await asyncio.sleep(60)  # Wait a bit before retry
        
        logger.info("🔄 Rotation worker stopped")
    
    async def run(self):
        await self.start()
        await self.bot_client.run_until_disconnected()

if __name__ == '__main__':
    bot = UltimateCommentBot()
    asyncio.run(bot.run())

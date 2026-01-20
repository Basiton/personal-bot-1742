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

# ============= PROFILE OPERATIONS PROTECTION =============
# Список проверенных рабочих аккаунтов (обновляется по результатам тестов)
WORKING_ACCOUNTS = [
    '+13434919340'  # Проверено: BIO ✅, NAME ✅, AVATAR ✅
]

# Аккаунты с FROZEN блокировкой (не использовать для profile operations)
FROZEN_ACCOUNTS = [
    '+13435909132',  # FROZEN: все методы заблокированы
    '+15482373234'   # FROZEN: все методы заблокированы
]

# Лог операций с профилем для rate limiting
profile_operations_log = {}  # {f"{phone}:{operation}": datetime}

# Лимиты операций (защита от блокировки)
PROFILE_OPERATION_LIMITS = {
    'bio': timedelta(hours=1),      # BIO: макс 1 раз в час
    'name': timedelta(hours=1),     # NAME: макс 1 раз в час
    'avatar': timedelta(hours=24)   # AVATAR: макс 1 раз в день
}

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
# Поддержка YC_API_KEY/YC_FOLDER_ID или старых названий
YANDEX_API_KEY = os.getenv('YC_API_KEY') or os.getenv('YANDEX_API_KEY', '')
YANDEX_FOLDER_ID = os.getenv('YC_FOLDER_ID') or os.getenv('YANDEX_FOLDER_ID', 'b1g4or5i5s66hklqfg06')
YANDEX_GPT_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

# Опция логирования комментариев для отладки промптов
ENABLE_COMMENT_LOGGING = os.getenv('LOG_COMMENTS', '').lower() in ('true', '1', 'yes')

def generate_neuro_comment(
    post_text: str,
    channel_theme: str = "general",
    temperature: float = 0.8,
    max_tokens: int = 120,
) -> str:
    """
    Генерирует короткий живой комментарий к посту с помощью YandexGPT.
    Стиль: разговорный, конкретный, без формальностей.
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
    
    # Рандомизация стиля комментария (больше вариантов)
    style_variants = [
        ("короткий вопрос по сути поста", True, 0.3),  # (стиль, может_без_эмодзи, вероятность)
        ("реакция на конкретные цифры/сроки", True, 0.4),
        ("короткая резкая фраза-оценка, без вопроса", True, 0.5),
        ("мини-реплика одним предложением", False, 0.6),
        ("обрывистая реплика 3-5 слов", False, 0.7),
    ]
    
    chosen_variant = random.choice(style_variants)
    chosen_style, can_skip_emoji, emoji_skip_chance = chosen_variant
    use_emoji = random.random() > emoji_skip_chance  # Иногда без эмодзи вообще
    
    # Еще более простой, разговорный промпт
    prompt = f"""Короткий комментарий к Telegram-посту.

СТИЛЬ: простой, разговорный, как живой человек пишет в чате.

ФОРМАТ: {chosen_style}
{"БЕЗ ЭМОДЗИ" if not use_emoji else "Можно 1 эмодзи (разный каждый раз)"}

ВАЖНО:
• Опирайся на КОНКРЕТИКУ: даты, цифры, факты из поста
• Если в посте год/число — используй ТОЧНО его
• Простые короткие фразы, не литературный язык
• Можно обрывисто: "Смело", "Жёсткий дедлайн", "Звучит реально"

ЗАПРЕЩЕНО:
❌ "Желаю успехов", "Здорово, что", "Благодарю", "Спасибо за пост"
❌ Длинные сложные предложения
❌ Формальный/корпоративный тон
❌ Вводные слова ("честно говоря", "на самом деле", "в общем")

Тема: {channel_theme}

Пост:
{post_text[:800]}

Комментарий:"""

    headers = {
        "Authorization": f"Api-Key {YANDEX_API_KEY}",
        "Content-Type": "application/json",
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
        raw_comment = data["result"]["alternatives"][0]["message"]["text"].strip()
        
        # Постобработка для "человечности"
        final_comment = humanize_comment(raw_comment)
        
        # Логирование (если включено)
        if ENABLE_COMMENT_LOGGING:
            logger.info(f"[COMMENT_GEN] Raw: {raw_comment}")
            logger.info(f"[COMMENT_GEN] Final: {final_comment}")
        
        return final_comment
    except Exception as e:
        logger.warning(f"YandexGPT generation failed: {e}")
        return random.choice(fallback_comments)

def humanize_comment(text: str) -> str:
    """
    Постобработка комментария для большей естественности.
    Убирает отполированные формулировки, делает более разговорным и "шероховатым".
    """
    import re
    
    # Убираем лишние пробелы
    text = " ".join(text.split())
    
    # Сначала удаляем формальные фразы (самые приоритетные)
    formal_replacements = {
        "Желаю вам успехов": "",
        "Желаю успехов": "",
        "Желаю удачи": "",
        "Благодарю за пост": "",
        "Спасибо за пост": "",
        "Здорово, что вы": "",
        "Здорово что вы": "",
        "Рада за вас": "",
        "Рад за вас": "",
        "Это вдохновляет": "",
    }
    
    for formal, replacement in formal_replacements.items():
        if formal.lower() in text.lower():
            text = re.sub(re.escape(formal), replacement, text, flags=re.IGNORECASE)
    
    # Удаляем вводные слова
    filler_patterns = [
        r'\bчестно говоря,?\s*',
        r'\bна самом деле,?\s*',
        r'\bв общем,?\s*',
        r'\bв принципе,?\s*',
        r'\bкак бы,?\s+',
        r'\bпо сути,?\s*',
        r'\bдействительно,?\s*',
        r'\bбезусловно,?\s*',
    ]
    
    for pattern in filler_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    
    # Упрощаем длинные конструкции
    text = text.replace("Очень интересно", "Интересно")
    text = text.replace("Очень круто", "Круто")
    text = text.replace("Действительно интересно", "Интересно")
    
    # Иногда убираем запятые перед союзами (делаем более разговорным)
    if random.random() < 0.4:
        text = text.replace(", а ", " а ").replace(", но ", " но ").replace(", и ", " и ")
    
    # Иногда заменяем длинные конструкции на короткие
    if random.random() < 0.3:
        text = text.replace("является ", "— ")
        text = text.replace("представляет собой ", "— ")
        text = text.replace("не могу не сказать", "")
        text = text.replace("хочется отметить", "")
        text = text.replace("стоит отметить", "")
    
    # Убираем множественные пробелы и лишние знаки
    text = re.sub(r'\s+', ' ', text)  # Любое количество пробелов → 1
    text = re.sub(r'\s+([.,!?])', r'\1', text)  # Пробел перед знаком
    text = re.sub(r'^[.,!?\s]+', '', text)  # Знаки в начале
    text = re.sub(r'[.,!?\s]+$', '', text)  # Знаки в конце (кроме одного)
    
    # Восстанавливаем один знак в конце если нужно
    if text and not text[-1] in '.!?':
        # Если это вопрос, добавляем ?
        if any(word in text.lower() for word in ['как', 'что', 'где', 'когда', 'почему', 'зачем', 'какой', 'сколько']):
            text += '?'
    
    # Если текст стал слишком коротким или пустым
    text = text.strip()
    if not text or len(text) < 3:
        return "Интересно"
    
    # Делаем первую букву заглавной
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    
    return text

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
        
        # Worker mode: 'cyclic' (all workers process all channels) or 'distributed' (channels divided)
        # cyclic - для тестов и малых проектов (5-20 каналов)
        # distributed - для продакшна (50+ каналов)
        self.worker_mode = 'distributed'  # По умолчанию distributed для 100+ каналов
        self.max_cycles_per_worker = 3  # Количество циклов перед ротацией (0 = бесконечно)
        
        # Worker tracking for automatic recovery
        self.active_worker_tasks = []  # Список активных воркеров
        self.worker_recovery_enabled = True  # Автоматическое восстановление воркеров
    
    async def can_do_profile_operation(self, phone, operation_type):
        """
        Проверяет можно ли выполнить операцию с профилем (rate limiting)
        
        Args:
            phone: Номер телефона аккаунта
            operation_type: Тип операции ('bio', 'name', 'avatar')
        
        Returns:
            (can_do: bool, wait_time: timedelta|None, reason: str)
        """
        now = datetime.now()
        key = f"{phone}:{operation_type}"
        
        # Проверяем не заморожен ли аккаунт
        if phone in FROZEN_ACCOUNTS:
            logger.warning(f"PROFILE: Account {phone} is FROZEN, operation denied")
            return False, None, f"Аккаунт {phone} заблокирован Telegram (FROZEN)"
        
        # Проверяем лимиты
        if key in profile_operations_log:
            last_op = profile_operations_log[key]
            limit = PROFILE_OPERATION_LIMITS.get(operation_type, timedelta(hours=1))
            
            if now - last_op < limit:
                wait_time = (last_op + limit) - now
                logger.info(f"PROFILE: Rate limit for {phone}:{operation_type}, wait {wait_time}")
                return False, wait_time, "Rate limit"
        
        # Операция разрешена
        profile_operations_log[key] = now
        logger.info(f"PROFILE: Operation {operation_type} allowed for {phone}")
        return True, None, "OK"
    
    async def get_working_account_for_profile(self, preferred_phone=None):
        """
        Выбирает рабочий аккаунт для операций с профилем
        
        Args:
            preferred_phone: Предпочтительный номер (если пользователь выбрал)
        
        Returns:
            phone номер рабочего аккаунта или None
        """
        accounts = self.load_bot_data().get('accounts', {})
        
        # Если указан предпочтительный - проверяем его
        if preferred_phone:
            if preferred_phone in FROZEN_ACCOUNTS:
                logger.warning(f"PROFILE: Preferred account {preferred_phone} is FROZEN")
                return None
            if preferred_phone in accounts:
                return preferred_phone
        
        # Ищем рабочий аккаунт
        for phone in WORKING_ACCOUNTS:
            if phone in accounts:
                status = accounts[phone].get('status')
                if status in ['active', 'reserve']:
                    logger.info(f"PROFILE: Selected working account {phone}")
                    return phone
        
        logger.warning("PROFILE: No working accounts available!")
        return None
        
        
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
        """
        Загружает данные.
        """
        try:
            with open(DB_NAME, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.accounts_data = data.get('accounts', {})
                self.channels = data.get('channels', [])
                self.templates = data.get('templates', self.templates)
                self.bio_links = data.get('bio_links', [])
                self.admins = data.get('admins', [])
                logger.info(f"✅ Loaded {len(self.accounts_data)} accounts, {len(self.channels)} channels, {len(self.templates)} templates")
        except FileNotFoundError:
            logger.warning(f"⚠️ {DB_NAME} not found, creating new")
            self.save_data()
        except json.JSONDecodeError as e:
            logger.error(f"❌ {DB_NAME} corrupted: {e}")
            logger.error("❌ Use /restore to restore from safe backup (data only, not sessions)")
            # Не пытаемся автоматически восстанавливать - может быть опасно
            self.save_data()
        except Exception as e:
            logger.error(f"❌ Error loading data: {e}")
            self.save_data()
    

    
    def save_data(self):
        """
        Сохраняет данные с атомарной записью.
        Автоматические бэкапы сессий ОТКЛЮЧЕНЫ для безопасности.
        """
        data = {
            'accounts': self.accounts_data,
            'channels': self.channels,
            'templates': self.templates,
            'bio_links': self.bio_links,
            'admins': self.admins
        }
        
        # Сохраняем во временный файл сначала (атомарная запись)
        temp_file = f'{DB_NAME}.tmp'
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # Только после успешной записи перезаписываем основной файл
            import shutil
            shutil.move(temp_file, DB_NAME)
            logger.debug("Data saved successfully")
        except Exception as e:
            logger.error(f"❌ Failed to save data: {e}")
            # Удаляем временный файл при ошибке
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass
            raise
    
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
                        f"📊 Состояние: {self.get_status_counts()}\n\n"
                        f"🔄 Система автоматически перезапустится через 10 секунд"
                    )
                except Exception as notify_err:
                    logger.error(f"Failed to notify owner: {notify_err}")
                
                # ============= NEW: Автоматический перезапуск =============
                if self.monitoring and self.worker_recovery_enabled:
                    logger.info("🔄 Scheduling monitoring restart in 10 seconds...")
                    asyncio.create_task(self.restart_monitoring_after_replacement())
                # ============= END NEW =============
                
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
    
    async def restart_monitoring_after_replacement(self):
        """Перезапускает мониторинг после замены аккаунта"""
        try:
            await asyncio.sleep(10)  # Даём время на завершение старых воркеров
            
            if not self.monitoring:
                logger.info("⚠️ Monitoring already stopped, skipping restart")
                return
            
            logger.info("="*80)
            logger.info("🔄 RESTARTING MONITORING AFTER ACCOUNT REPLACEMENT")
            logger.info("="*80)
            
            # Останавливаем текущие воркеры
            logger.info("⏸️ Stopping current workers...")
            self.monitoring = False
            
            # Ждём завершения старых воркеров
            if self.active_worker_tasks:
                logger.info(f"⏳ Waiting for {len(self.active_worker_tasks)} workers to finish...")
                await asyncio.sleep(5)
                self.active_worker_tasks.clear()
            
            # Перезапускаем
            logger.info("🚀 Starting new workers with updated accounts...")
            self.monitoring = True
            asyncio.create_task(self.pro_auto_comment())
            
            logger.info("✅ Monitoring restarted successfully")
            
            # Уведомляем владельца
            try:
                await self.bot_client.send_message(
                    BOT_OWNER_ID,
                    f"✅ **Мониторинг перезапущен**\n\n"
                    f"🚀 Новые воркеры запущены с обновлённым составом аккаунтов\n"
                    f"📊 Состояние: {self.get_status_counts()}"
                )
            except Exception as notify_err:
                logger.error(f"Failed to notify owner: {notify_err}")
                
        except Exception as e:
            logger.error(f"Error restarting monitoring: {e}")
            try:
                await self.bot_client.send_message(
                    BOT_OWNER_ID,
                    f"❌ **Ошибка перезапуска мониторинга**\n\n"
                    f"Причина: {str(e)}\n\n"
                    f"💡 Используйте /stopmon и /startmon вручную"
                )
            except:
                pass
    
    async def health_check_worker(self):
        """Периодически проверяет количество воркеров и восстанавливает при необходимости"""
        logger.info("🏥 Health check worker started")
        
        while self.monitoring:
            try:
                await asyncio.sleep(120)  # Проверка каждые 2 минуты
                
                if not self.monitoring:
                    break
                
                # Подсчёт активных аккаунтов
                active_accounts = {phone: data for phone, data in self.accounts_data.items()
                                 if data.get('status') == ACCOUNT_STATUS_ACTIVE and data.get('session')}
                
                expected_workers = min(len(active_accounts), self.max_parallel_accounts)
                
                # Подсчёт живых воркеров
                alive_workers = sum(1 for task in self.active_worker_tasks if not task.done())
                
                if alive_workers < expected_workers:
                    logger.warning("="*80)
                    logger.warning(f"⚠️ WORKER COUNT MISMATCH DETECTED!")
                    logger.warning(f"   Expected: {expected_workers} workers")
                    logger.warning(f"   Running: {alive_workers} workers")
                    logger.warning(f"   Missing: {expected_workers - alive_workers} workers")
                    logger.warning("="*80)
                    
                    if self.worker_recovery_enabled:
                        logger.info("🔄 Initiating automatic recovery...")
                        
                        # Уведомляем владельца
                        try:
                            await self.bot_client.send_message(
                                BOT_OWNER_ID,
                                f"⚠️ **Обнаружена проблема с воркерами**\n\n"
                                f"Ожидается: {expected_workers}\n"
                                f"Работает: {alive_workers}\n"
                                f"Недостаёт: {expected_workers - alive_workers}\n\n"
                                f"🔄 Автоматическое восстановление через 10 секунд"
                            )
                        except:
                            pass
                        
                        # Перезапуск
                        await self.restart_monitoring_after_replacement()
                        break  # Выходим, новый health check запустится с новым мониторингом
                else:
                    logger.debug(f"✅ Health check OK: {alive_workers}/{expected_workers} workers")
                    
            except Exception as e:
                logger.error(f"Health check error: {e}")
                await asyncio.sleep(60)
        
        logger.info("🏥 Health check worker stopped")
    
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
    
    # ============= PROFILE CHANNEL FUNCTIONS =============
    
    async def create_profile_channel(self, phone, title, about=''):
        """
        Создать новый канал от имени аккаунта.
        
        Returns: (success: bool, result: dict/str)
            result может быть dict с информацией о канале или строкой с ошибкой
        """
        try:
            account_data = self.accounts_data.get(phone)
            if not account_data:
                return False, f"❌ Аккаунт {phone} не найден"
            
            if not account_data.get('session'):
                return False, f"❌ Аккаунт {phone} не авторизован"
            
            client = TelegramClient(
                StringSession(account_data['session']), 
                API_ID, 
                API_HASH,
                proxy=account_data.get('proxy')
            )
            
            await client.connect()
            
            if not await client.is_user_authorized():
                await client.disconnect()
                return False, f"❌ Аккаунт {phone} потерял авторизацию"
            
            # Создаём канал через MTProto
            from telethon.tl.functions.channels import CreateChannelRequest
            from telethon.tl.types import Channel
            
            result = await client(CreateChannelRequest(
                title=title,
                about=about,
                broadcast=True,  # broadcast channel (not megagroup)
                megagroup=False
            ))
            
            # Получаем информацию о созданном канале
            created_channel = result.chats[0]
            
            if not isinstance(created_channel, Channel):
                await client.disconnect()
                return False, "❌ Не удалось создать канал"
            
            # Получаем username канала (может быть None)
            channel_username = getattr(created_channel, 'username', None)
            channel_id = created_channel.id
            
            channel_info = {
                'id': channel_id,
                'title': title,
                'username': f"@{channel_username}" if channel_username else None,
                'about': about,
                'created': datetime.now().isoformat()
            }
            
            # Сохраняем в аккаунте
            account_data['profile_channel'] = channel_info
            self.save_data()
            
            await client.disconnect()
            
            logger.info(f"✅ Profile channel created for {phone}: {channel_info}")
            return True, channel_info
            
        except Exception as e:
            logger.error(f"Error creating profile channel for {phone}: {e}")
            return False, f"❌ Ошибка: {str(e)}"
    
    async def link_existing_channel(self, phone, channel_identifier):
        """
        Привязать существующий канал к профилю аккаунта.
        Проверяет, что аккаунт является админом канала.
        
        channel_identifier: @username или ID канала
        
        Returns: (success: bool, result: dict/str)
        """
        try:
            account_data = self.accounts_data.get(phone)
            if not account_data:
                return False, f"❌ Аккаунт {phone} не найден"
            
            if not account_data.get('session'):
                return False, f"❌ Аккаунт {phone} не авторизован"
            
            client = TelegramClient(
                StringSession(account_data['session']), 
                API_ID, 
                API_HASH,
                proxy=account_data.get('proxy')
            )
            
            await client.connect()
            
            if not await client.is_user_authorized():
                await client.disconnect()
                return False, f"❌ Аккаунт {phone} потерял авторизацию"
            
            # Получаем информацию о канале
            from telethon.tl.types import Channel
            
            try:
                entity = await client.get_entity(channel_identifier)
            except Exception as e:
                await client.disconnect()
                return False, f"❌ Канал не найден: {str(e)}"
            
            if not isinstance(entity, Channel):
                await client.disconnect()
                return False, f"❌ {channel_identifier} не является каналом"
            
            # Проверяем права админа
            from telethon.tl.functions.channels import GetParticipantRequest
            from telethon.tl.types import ChannelParticipantCreator, ChannelParticipantAdmin
            
            try:
                me = await client.get_me()
                participant = await client(GetParticipantRequest(
                    channel=entity,
                    participant=me
                ))
                
                # Проверяем, что пользователь - создатель или админ
                is_admin = isinstance(participant.participant, (ChannelParticipantCreator, ChannelParticipantAdmin))
                
                if not is_admin:
                    await client.disconnect()
                    return False, f"❌ Вы не являетесь админом канала {channel_identifier}"
                    
            except Exception as e:
                await client.disconnect()
                return False, f"❌ Не удалось проверить права: {str(e)}"
            
            # Получаем полную информацию о канале
            from telethon.tl.functions.channels import GetFullChannelRequest
            full_channel = await client(GetFullChannelRequest(channel=entity))
            
            channel_username = getattr(entity, 'username', None)
            channel_info = {
                'id': entity.id,
                'title': entity.title,
                'username': f"@{channel_username}" if channel_username else None,
                'about': full_channel.full_chat.about or '',
                'linked': datetime.now().isoformat()
            }
            
            # Сохраняем в аккаунте
            account_data['profile_channel'] = channel_info
            self.save_data()
            
            await client.disconnect()
            
            logger.info(f"✅ Profile channel linked for {phone}: {channel_info}")
            return True, channel_info
            
        except Exception as e:
            logger.error(f"Error linking profile channel for {phone}: {e}")
            return False, f"❌ Ошибка: {str(e)}"
    
    async def set_profile_channel_avatar(self, phone, avatar_file):
        """
        Установить аватар для profile_channel.
        
        Returns: (success: bool, message: str)
        """
        try:
            account_data = self.accounts_data.get(phone)
            if not account_data:
                return False, f"❌ Аккаунт {phone} не найден"
            
            profile_channel = account_data.get('profile_channel')
            if not profile_channel:
                return False, f"❌ У аккаунта {phone} нет привязанного канала"
            
            if not account_data.get('session'):
                return False, f"❌ Аккаунт {phone} не авторизован"
            
            client = TelegramClient(
                StringSession(account_data['session']), 
                API_ID, 
                API_HASH,
                proxy=account_data.get('proxy')
            )
            
            await client.connect()
            
            if not await client.is_user_authorized():
                await client.disconnect()
                return False, f"❌ Аккаунт {phone} потерял авторизацию"
            
            # Получаем канал
            channel_id = profile_channel['id']
            entity = await client.get_entity(channel_id)
            
            # Загружаем аватар
            from telethon.tl.functions.channels import EditPhotoRequest
            
            uploaded_file = await client.upload_file(avatar_file)
            await client(EditPhotoRequest(
                channel=entity,
                photo=uploaded_file
            ))
            
            await client.disconnect()
            
            logger.info(f"✅ Avatar set for profile channel of {phone}")
            return True, "✅ Аватар канала обновлён"
            
        except Exception as e:
            logger.error(f"Error setting profile channel avatar for {phone}: {e}")
            return False, f"❌ Ошибка: {str(e)}"
    
    async def create_profile_channel_post(self, phone, text, pin=False):
        """
        Создать пост в profile_channel.
        
        Args:
            phone: номер телефона аккаунта
            text: текст поста
            pin: закрепить ли пост
        
        Returns: (success: bool, message: str, post_id: int)
        """
        try:
            account_data = self.accounts_data.get(phone)
            if not account_data:
                return False, f"❌ Аккаунт {phone} не найден", None
            
            profile_channel = account_data.get('profile_channel')
            if not profile_channel:
                return False, f"❌ У аккаунта {phone} нет привязанного канала", None
            
            if not account_data.get('session'):
                return False, f"❌ Аккаунт {phone} не авторизован", None
            
            client = TelegramClient(
                StringSession(account_data['session']), 
                API_ID, 
                API_HASH,
                proxy=account_data.get('proxy')
            )
            
            await client.connect()
            
            if not await client.is_user_authorized():
                await client.disconnect()
                return False, f"❌ Аккаунт {phone} потерял авторизацию", None
            
            # Получаем канал
            channel_id = profile_channel['id']
            entity = await client.get_entity(channel_id)
            
            # Отправляем пост
            message = await client.send_message(entity, text)
            post_id = message.id
            
            # Закрепляем если нужно
            if pin:
                from telethon.tl.functions.messages import UpdatePinnedMessageRequest
                await client(UpdatePinnedMessageRequest(
                    peer=entity,
                    id=post_id,
                    unpin=False,
                    pm_oneside=False
                ))
            
            await client.disconnect()
            
            logger.info(f"✅ Post created in profile channel of {phone}, post_id={post_id}, pinned={pin}")
            return True, "✅ Пост создан" + (" и закреплён" if pin else ""), post_id
            
        except Exception as e:
            logger.error(f"Error creating post in profile channel for {phone}: {e}")
            return False, f"❌ Ошибка: {str(e)}", None
    
    async def update_profile_channel_info(self, phone, title=None, about=None):
        """
        Обновить название и/или описание profile_channel.
        
        Returns: (success: bool, message: str)
        """
        try:
            account_data = self.accounts_data.get(phone)
            if not account_data:
                return False, f"❌ Аккаунт {phone} не найден"
            
            profile_channel = account_data.get('profile_channel')
            if not profile_channel:
                return False, f"❌ У аккаунта {phone} нет привязанного канала"
            
            if not account_data.get('session'):
                return False, f"❌ Аккаунт {phone} не авторизован"
            
            client = TelegramClient(
                StringSession(account_data['session']), 
                API_ID, 
                API_HASH,
                proxy=account_data.get('proxy')
            )
            
            await client.connect()
            
            if not await client.is_user_authorized():
                await client.disconnect()
                return False, f"❌ Аккаунт {phone} потерял авторизацию"
            
            # Получаем канал
            channel_id = profile_channel['id']
            entity = await client.get_entity(channel_id)
            
            # Обновляем информацию
            from telethon.tl.functions.channels import EditTitleRequest, EditAboutRequest
            
            results = []
            
            if title is not None:
                await client(EditTitleRequest(
                    channel=entity,
                    title=title
                ))
                profile_channel['title'] = title
                results.append("✅ Название обновлено")
            
            if about is not None:
                await client(EditAboutRequest(
                    channel=entity,
                    about=about
                ))
                profile_channel['about'] = about
                results.append("✅ Описание обновлено")
            
            if results:
                self.save_data()
            
            await client.disconnect()
            
            logger.info(f"✅ Profile channel info updated for {phone}")
            return True, "\n".join(results)
            
        except Exception as e:
            logger.error(f"Error updating profile channel info for {phone}: {e}")
            return False, f"❌ Ошибка: {str(e)}"
    
    # ============= END PROFILE CHANNEL FUNCTIONS =============
    
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

**🔄 РЕЖИМ РАБОТЫ (для 100+ каналов):**
`/setworkermode distributed` - каналы делятся между аккаунтами 🆕
`/setworkermode cyclic` - каждый аккаунт проходит все каналы 🆕
`/setmaxcycles 3` - лимит циклов перед ротацией (0=∞) 🆕
`/getworkersettings` - посмотреть все настройки воркеров 🆕
`/togglerecovery` - вкл/выкл автовосстановление после бана 🆕

**📢 КАНАЛЫ:**
`/addchannel @username` - добавить
`/listchannels` - список
`/delchannel @username` - удалить
`/searchchannels тема` - поиск по теме
`/addparsed тема 10` - добавить найденные в работу

**� КАНАЛЫ-ВИТРИНЫ:**
`/create_profile_channel +1234 Название` - создать новый
`/link_profile_channel +1234 @channel` - привязать существующий
`/list_profile_channels` - список всех витрин
`/set_profile_channel_avatar +1234` - установить аватар
`/set_profile_channel_post +1234 Текст` - создать пост
`/set_profile_channel_post +1234 pin Текст` - пост с закреплением
`/update_profile_channel_info +1234 title:Новое|about:Описание`
`/unlink_profile_channel +1234` - отвязать канал

**�💬 КОММЕНТАРИИ:**
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
`/addadmin 123456789` - новый админ

**💾 ЗАЩИТА ДАННЫХ (НЕ СЕССИЙ!):**
`/backup` - сохранить каналы и шаблоны
`/listbackups` - список всех безопасных бэкапов
`/restore` - восстановить каналы/шаблоны

⚠️ **ВАЖНО:** Бэкапы НЕ содержат сессий!
Сессии всегда остаются нетронутыми."""
            await event.respond(text)
        
        # ============= SESSION PROTECTION COMMANDS =============
        @self.bot_client.on(events.NewMessage(pattern='/backup'))
        async def manual_backup(event):
            """
            Создаёт резервную копию ДАННЫХ (каналы, шаблоны).
            КРИТИЧНО: НИКОГДА не бэкапирует сессии аккаунтов!
            """
            if not await self.is_admin(event.sender_id): return
            
            try:
                from datetime import datetime
                
                # ============= ЗАЩИТА: Бэкапируем ТОЛЬКО данные, НЕ сессии! =============
                backup_data = {
                    'channels': self.channels,
                    'templates': self.templates,
                    'bio_links': self.bio_links,
                    'admins': self.admins,
                    # ВАЖНО: НЕ включаем 'accounts' - там сессии!
                }
                
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                backup_name = f'bot_data_safe.backup_{timestamp}.json'
                
                # Сохраняем только данные (без сессий)
                with open(backup_name, 'w', encoding='utf-8') as f:
                    json.dump(backup_data, f, indent=2, ensure_ascii=False)
                
                # Также создаём быстрый бэкап
                with open('bot_data_safe.bak.json', 'w', encoding='utf-8') as f:
                    json.dump(backup_data, f, indent=2, ensure_ascii=False)
                # ============= END ЗАЩИТА =============
                
                await event.respond(
                    f"✅ **Безопасная резервная копия создана**\n\n"
                    f"📁 Файл: `{backup_name}`\n"
                    f"📊 Каналов: {len(self.channels)}\n"
                    f"💬 Шаблонов: {len(self.templates)}\n"
                    f"🔗 Bio-ссылок: {len(self.bio_links)}\n"
                    f"👑 Админов: {len(self.admins)}\n\n"
                    f"🔒 **Сессии аккаунтов НЕ включены** (безопасно!)\n\n"
                    f"💡 Используйте `/listbackups` для просмотра всех бэкапов"
                )
                logger.info(f"Safe backup created by user {event.sender_id}: {backup_name} (NO SESSIONS)")
                
            except Exception as e:
                await event.respond(f"❌ Ошибка создания бэкапа: {str(e)}")
                logger.error(f"Manual backup error: {e}")
        
        @self.bot_client.on(events.NewMessage(pattern='/listbackups'))
        async def list_backups(event):
            """Показывает список всех доступных безопасных бэкапов (без сессий)"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                # Ищем безопасные бэкапы (без сессий)
                safe_backups = sorted([f for f in os.listdir('.') if f.startswith('bot_data_safe.backup_')], reverse=True)
                
                # .bak файл
                bak_file = 'bot_data_safe.bak.json' if os.path.exists('bot_data_safe.bak.json') else None
                
                if not safe_backups and not bak_file:
                    await event.respond(
                        "❌ Безопасные бэкапы не найдены\n\n"
                        "💡 Создайте первый бэкап: `/backup`\n\n"
                        "🔒 Новые бэкапы НЕ содержат сессий (безопасно!)"
                    )
                    return
                
                text = "💾 **БЕЗОПАСНЫЕ РЕЗЕРВНЫЕ КОПИИ**\n"
                text += "🔒 Содержат только данные (каналы, шаблоны)\n"
                text += "✅ Сессии аккаунтов НЕ включены\n\n"
                
                if bak_file:
                    file_size = os.path.getsize(bak_file) / 1024  # KB
                    file_time = datetime.fromtimestamp(os.path.getmtime(bak_file))
                    text += f"📌 **Последний бэкап (.bak):**\n"
                    text += f"   `{bak_file}`\n"
                    text += f"   📅 {file_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    text += f"   💾 {file_size:.1f} KB\n\n"
                
                if safe_backups:
                    text += f"🖐️ **Все бэкапы ({len(safe_backups)}):**\n"
                    for backup in safe_backups[:10]:  # Показываем последние 10
                        file_size = os.path.getsize(backup) / 1024
                        file_time = datetime.fromtimestamp(os.path.getmtime(backup))
                        # Извлекаем timestamp из имени
                        timestamp_part = backup.replace('bot_data_safe.backup_', '').replace('.json', '')
                        text += f"• `{timestamp_part}`\n"
                        text += f"  📅 {file_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                        text += f"  💾 {file_size:.1f} KB\n"
                    if len(safe_backups) > 10:
                        text += f"\n... и ещё {len(safe_backups) - 10} бэкапов\n"
                    text += "\n"
                
                text += "💡 **Команды:**\n"
                text += "`/restore` - восстановить данные из последнего бэкапа\n"
                text += "`/backup` - создать новый бэкап\n\n"
                text += "⚠️ **Важно:** При восстановлении сессии НЕ затрагиваются!"
                
                await event.respond(text)
                
            except Exception as e:
                await event.respond(f"❌ Ошибка: {str(e)}")
                logger.error(f"List backups error: {e}")
        
        @self.bot_client.on(events.NewMessage(pattern='/restore'))
        async def restore_backup(event):
            """
            Восстанавливает ТОЛЬКО данные (каналы, шаблоны) из бэкапа.
            КРИТИЧНО: НИКОГДА не трогает сессии аккаунтов!
            """
            if not await self.is_admin(event.sender_id): return
            
            try:
                # Находим последний безопасный бэкап (без сессий)
                backup_file = None
                
                # Проверяем .bak файл
                if os.path.exists('bot_data_safe.bak.json'):
                    backup_file = 'bot_data_safe.bak.json'
                
                # Проверяем безопасные бэкапы
                if not backup_file:
                    safe_backups = sorted([f for f in os.listdir('.') if f.startswith('bot_data_safe.backup_')], reverse=True)
                    if safe_backups:
                        backup_file = safe_backups[0]
                
                if not backup_file:
                    await event.respond(
                        "❌ Безопасные бэкапы не найдены\n\n"
                        "💡 Создайте бэкап: `/backup`\n\n"
                        "🔒 Новые бэкапы безопасны (без сессий)"
                    )
                    return
                
                # Загружаем данные из бэкапа
                with open(backup_file, 'r', encoding='utf-8') as f:
                    backup_data = json.load(f)
                
                # Проверяем структуру
                if 'channels' not in backup_data and 'templates' not in backup_data:
                    await event.respond(f"❌ Файл `{backup_file}` не содержит данных")
                    return
                
                # Сохраняем текущее состояние для сравнения
                old_channels = len(self.channels)
                old_templates = len(self.templates)
                
                # ============= ЗАЩИТА: Восстанавливаем ТОЛЬКО данные, НЕ трогаем accounts! =============
                # Восстанавливаем каналы
                if 'channels' in backup_data:
                    self.channels = backup_data['channels']
                
                # Восстанавливаем шаблоны
                if 'templates' in backup_data:
                    self.templates = backup_data['templates']
                
                # Восстанавливаем bio_links
                if 'bio_links' in backup_data:
                    self.bio_links = backup_data['bio_links']
                
                # Восстанавливаем admins
                if 'admins' in backup_data:
                    self.admins = backup_data['admins']
                
                # ВАЖНО: self.accounts_data НЕ трогаем - сессии остаются нетронутыми!
                # ============= END ЗАЩИТА =============
                
                # Сохраняем изменения (включая нетронутые accounts)
                self.save_data()
                
                await event.respond(
                    f"✅ **Данные восстановлены**\n\n"
                    f"📁 Из файла: `{backup_file}`\n\n"
                    f"📊 Каналов: {old_channels} → {len(self.channels)}\n"
                    f"💬 Шаблонов: {old_templates} → {len(self.templates)}\n"
                    f"🔗 Bio-ссылок: {len(self.bio_links)}\n"
                    f"👑 Админов: {len(self.admins)}\n\n"
                    f"🔒 **Сессии аккаунтов НЕ затронуты!**\n"
                    f"👥 Все аккаунты ({len(self.accounts_data)}) остались авторизованы\n\n"
                    f"✅ Можно сразу продолжать работу или `/startmon`"
                )
                logger.info(f"Safe restore from {backup_file} by user {event.sender_id} (SESSIONS PRESERVED)")
                
            except json.JSONDecodeError as e:
                await event.respond(f"❌ Файл бэкапа повреждён: {str(e)}")
                logger.error(f"Backup restore JSON error: {e}")
            except Exception as e:
                await event.respond(f"❌ Ошибка восстановления: {str(e)}")
                logger.error(f"Backup restore error: {e}")
        
        # ============= END SESSION PROTECTION COMMANDS =============
        
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
            """
            Удаляет аккаунт с подтверждением для защиты от случайного удаления сессий.
            КРИТИЧНО: Требует явного подтверждения 'CONFIRM' для безопасности.
            """
            if not await self.is_admin(event.sender_id): return
            try:
                parts = event.text.split(maxsplit=2)
                if len(parts) < 2:
                    await event.respond(
                        "**❌ Неверный формат**\n\n"
                        "**Использование:**\n"
                        "`/delaccount +79123456789 CONFIRM`\n\n"
                        "⚠️ **ВНИМАНИЕ:** Эта команда УДАЛИТ аккаунт и его сессию!\n"
                        "Потребуется заново авторизоваться через `/auth`\n\n"
                        "💡 Для отключения аккаунта без удаления используйте:\n"
                        "`/toggleaccount +79123456789`"
                    )
                    return
                
                phone = parts[1]
                
                # Требуем явного подтверждения
                if len(parts) < 3 or parts[2].upper() != 'CONFIRM':
                    if phone in self.accounts_data:
                        account_name = self.accounts_data[phone].get('name', phone)
                        await event.respond(
                            f"⚠️ **ПОДТВЕРДИТЕ УДАЛЕНИЕ**\n\n"
                            f"Аккаунт: `{account_name}`\n"
                            f"Телефон: `{phone}`\n\n"
                            f"**Будет удалено:**\n"
                            f"• Сессия аккаунта (потребуется переавторизация)\n"
                            f"• Все настройки и статистика\n\n"
                            f"**Для подтверждения отправьте:**\n"
                            f"`/delaccount {phone} CONFIRM`\n\n"
                            f"💡 **Альтернатива:** Используйте `/toggleaccount {phone}` чтобы просто отключить аккаунт"
                        )
                    else:
                        await event.respond(f"❌ Аккаунт `{phone}` не найден")
                    return
                
                # Удаляем только после подтверждения
                if phone in self.accounts_data:
                    account_name = self.accounts_data[phone].get('name', phone)
                    
                    # ============= ЗАЩИТА: Создаём бэкап перед удалением =============
                    import shutil
                    from datetime import datetime
                    backup_name = f'bot_data.json.before_delete_{phone.replace("+", "")}_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
                    shutil.copy2(DB_NAME, backup_name)
                    logger.warning(f"🔴 DELETING ACCOUNT: {phone} ({account_name}) by user {event.sender_id}, backup: {backup_name}")
                    # ============= END ЗАЩИТА =============
                    
                    del self.accounts_data[phone]
                    self.save_data()
                    
                    await event.respond(
                        f"✅ **Аккаунт удалён**\n\n"
                        f"Имя: `{account_name}`\n"
                        f"Телефон: `{phone}`\n\n"
                        f"💾 Резервная копия создана:\n"
                        f"`{backup_name}`\n\n"
                        f"⚠️ Для восстановления используйте `/restore`"
                    )
                else:
                    await event.respond(f"❌ Аккаунт `{phone}` не найден")
            except Exception as e:
                logger.error(f"Error in /delaccount: {e}")
                await event.respond(
                    f"❌ Ошибка: `{str(e)[:100]}`\n\n"
                    "**Формат:**\n"
                    "`/delaccount +79123456789 CONFIRM`"
                )
        
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
        

        # ============= NEW: WORKER MODE & CYCLES COMMANDS =============
        @self.bot_client.on(events.NewMessage(pattern='/setworkermode'))
        async def set_worker_mode(event):
            """Set worker mode: cyclic or distributed"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                mode = event.text.split(maxsplit=1)[1].lower()
                if mode not in ['cyclic', 'distributed']:
                    await event.respond(
                        "❌ Режим должен быть: `cyclic` или `distributed`\n\n"
                        "🔄 **CYCLIC** - каждый аккаунт проходит ВСЕ каналы\n"
                        "   • Для тестов и 5-20 каналов\n"
                        "   • Предсказуемое поведение\n\n"
                        "📊 **DISTRIBUTED** - каналы делятся между аккаунтами\n"
                        "   • Для продакшна с 50+ каналами\n"
                        "   • Быстрая обработка больших списков"
                    )
                    return
                
                self.worker_mode = mode
                await event.respond(
                    f"✅ Режим установлен: **{mode.upper()}**\n\n"
                    f"{'🔄' if mode == 'cyclic' else '📊'} "
                    f"{'Каждый аккаунт проходит ВСЕ каналы' if mode == 'cyclic' else 'Каналы делятся между аккаунтами'}\n"
                    f"⚠️ Изменения вступят в силу после перезапуска (`/stopmon` → `/startmon`)"
                )
                logger.info(f"Worker mode set to: {mode}")
            except (IndexError, ValueError):
                await event.respond(
                    f"Формат: `/setworkermode distributed` или `/setworkermode cyclic`\n\n"
                    f"Текущий режим: **{self.worker_mode}**"
                )
        
        @self.bot_client.on(events.NewMessage(pattern='/setmaxcycles'))
        async def set_max_cycles(event):
            """Set maximum cycles per worker before rotation"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                cycles = int(event.text.split(maxsplit=1)[1])
                if cycles < 0 or cycles > 100:
                    await event.respond("❌ Количество циклов должно быть от 0 до 100\n\n0 = бесконечно")
                    return
                
                self.max_cycles_per_worker = cycles
                if cycles == 0:
                    await event.respond(
                        f"✅ Воркеры будут работать **бесконечно**\n\n"
                        f"🔄 Циклы не ограничены\n"
                        f"⚠️ Ротация аккаунтов отключена"
                    )
                else:
                    await event.respond(
                        f"✅ Максимум циклов: **{cycles}**\n\n"
                        f"🔄 Каждый воркер отработает {cycles} циклов\n"
                        f"🔄 Потом уйдёт в резерв (если есть резервные)\n"
                        f"⚠️ Изменения вступят в силу после перезапуска"
                    )
                logger.info(f"Max cycles per worker set to: {cycles}")
            except (IndexError, ValueError):
                await event.respond(
                    f"Формат: `/setmaxcycles 3`\n\n"
                    f"Текущее значение: **{self.max_cycles_per_worker}** (0=бесконечно)"
                )
        
        @self.bot_client.on(events.NewMessage(pattern='/getworkersettings'))
        async def get_worker_settings(event):
            """Show all worker settings"""
            if not await self.is_admin(event.sender_id): return
            
            active_count = sum(1 for d in self.accounts_data.values() if d.get('status') == ACCOUNT_STATUS_ACTIVE)
            
            text = f"⚙️ **НАСТРОЙКИ ВОРКЕРОВ:**\n\n"
            
            text += f"📊 **Режим:** {self.worker_mode.upper()}\n"
            if self.worker_mode == 'cyclic':
                text += f"   • Каждый аккаунт проходит ВСЕ каналы\n"
                text += f"   • Идеально для 5-20 каналов\n"
            else:
                text += f"   • Каналы делятся между аккаунтами\n"
                text += f"   • Оптимально для 50+ каналов\n"
            
            text += f"\n🔄 **Макс циклов:** {self.max_cycles_per_worker if self.max_cycles_per_worker > 0 else 'бесконечно'}\n"
            if self.max_cycles_per_worker > 0:
                text += f"   • Каждый воркер = {self.max_cycles_per_worker} циклов\n"
                text += f"   • Потом уходит в резерв\n"
            else:
                text += f"   • Ротация отключена\n"
            
            text += f"\n🚀 **Параллельность:** {self.max_parallel_accounts}\n"
            text += f"✅ **Активных:** {active_count}\n"
            text += f"⚡ **Скорость:** {self.messages_per_hour} msg/h\n"
            
            text += f"\n📊 **Каналов:** {len(self.channels)}\n"
            if self.worker_mode == 'distributed' and active_count > 0:
                channels_per_worker = len(self.channels) // min(active_count, self.max_parallel_accounts)
                text += f"   • На воркер: ~{channels_per_worker}\n"
            
            text += f"\n📄 **Команды:**\n"
            text += f"`/setworkermode distributed` - для 100+ каналов\n"
            text += f"`/setworkermode cyclic` - для тестов\n"
            text += f"`/setmaxcycles 3` - лимит циклов (0=∞)\n"
            text += f"`/setparallel 2` - кол-во воркеров\n"
            text += f"`/togglerecovery` - вкл/выкл автовосстановление"
            
            await event.respond(text)
        
        @self.bot_client.on(events.NewMessage(pattern='/togglerecovery'))
        async def toggle_recovery(event):
            """Toggle automatic worker recovery"""
            if not await self.is_admin(event.sender_id): return
            
            self.worker_recovery_enabled = not self.worker_recovery_enabled
            status = "✅ Включено" if self.worker_recovery_enabled else "❌ Выключено"
            
            await event.respond(
                f"🔄 **Автовосстановление воркеров:** {status}\n\n"
                f"{'📌 Система автоматически перезапустится при замене аккаунта' if self.worker_recovery_enabled else '⚠️ Требуется ручной перезапуск после бана'}\n\n"
                f"💡 Health check проверяет воркеры каждые 2 минуты"
            )
            logger.info(f"Worker recovery {'enabled' if self.worker_recovery_enabled else 'disabled'}")
        # ============= END NEW COMMANDS =============

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
            
            # Determine admin_id for filtering
            admin_id = self.get_admin_id(event.sender_id)
            
            # Filter accounts by admin_id
            if admin_id is None:  # Super admin - show all
                filtered_accounts = self.accounts_data
            else:  # Regular admin - show only their accounts
                filtered_accounts = {phone: data for phone, data in self.accounts_data.items()
                                   if data.get('admin_id') == admin_id}
            
            bio_text = " | ".join(self.bio_links[:4])
            updated = 0
            
            # Update only ACTIVE accounts with sessions
            for phone, data in filtered_accounts.items():
                if data.get('status') == ACCOUNT_STATUS_ACTIVE and data.get('session'):
                    if await self.set_account_bio(data, bio_text):
                        updated += 1
                        logger.info(f"Bio updated via /setbioall for {phone}")
            
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
                    text += "`/testmode on` - включить (дефолтные каналы)\n"
                    text += "`/testmode on @channel1 @channel2` - включить (свои каналы)\n"
                    text += "`/testmode off` - выключить\n"
                    text += "`/testmode speed 5` - установить скорость\n"
                    
                    await event.respond(text)
                    return
                
                action = parts[1].lower()
                
                if action == 'on':
                    # Enable test mode
                    # Дефолтные тестовые каналы (если не указаны свои)
                    DEFAULT_TEST_CHANNELS = [
                        '@AIGIRLSARTS',
                        '@testertesti',
                        '@testtestista',
                        '@testingmana',
                        '@chiptesterchip'
                    ]
                    
                    # Если указаны каналы - используем их, иначе дефолтные
                    if len(parts) >= 3:
                        # Parse указанные каналы
                        channels = []
                        for part in parts[2:]:
                            ch = part.strip()
                            if not ch.startswith('@'):
                                ch = '@' + ch
                            channels.append(ch)
                        self.test_channels = channels
                    else:
                        # Используем дефолтные
                        self.test_channels = DEFAULT_TEST_CHANNELS
                    
                    self.test_mode = True
                    
                    # Определяем, используются ли дефолтные каналы
                    is_default = (len(parts) < 3)
                    
                    text = """✅ **TEST MODE: ON**

🎯 Комменты идут ТОЛЬКО в:
"""
                    for ch in self.test_channels:
                        text += f"  • `{ch}`\n"
                    
                    if is_default:
                        text += "\n📌 Используются дефолтные тестовые каналы\n"
                        text += "💡 Для своих каналов: `/testmode on @channel1 @channel2`\n"
                    else:
                        text += f"\n✅ Указано {len(self.test_channels)} своих каналов\n"
                    
                    text += f"\n⚡ Лимит скорости: `{self.test_mode_speed_limit}` комм/час\n"
                    text += "\n⚠️ **ВСЕ остальные каналы ИГНОРИРУЮТСЯ!**\n"
                    text += "\n💡 Для выхода: `/testmode off`"
                    
                    await event.respond(text)
                    
                    # Log
                    logger.info("="*80)
                    logger.info("🧪 TEST MODE: ENABLED")
                    logger.info(f"🧪 Test channels: {self.test_channels}")
                    logger.info(f"🧪 Speed limit: {self.test_mode_speed_limit} msg/hour")
                    logger.info("="*80)
                    
                elif action == 'off':
                    # Disable test mode
                    was_enabled = self.test_mode
                    old_channels = self.test_channels.copy() if self.test_channels else []
                    
                    self.test_mode = False
                    self.test_channels = []
                    
                    if was_enabled:
                        text = """✅ **TEST MODE: OFF**

🎯 Возвращаемся к боевым каналам
"""
                        if old_channels:
                            text += "\n📢 Были в тесте:\n"
                            for ch in old_channels:
                                text += f"  • `{ch}`\n"
                    else:
                        text = "ℹ️ TEST MODE уже был выключен"
                    
                    await event.respond(text)
                    
                    logger.info("="*80)
                    logger.info("🔴 TEST MODE: DISABLED")
                    logger.info("✅ Switching to LIVE channels")
                    logger.info("="*80)
                    
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
                        "`/testmode on` - включить (дефолтные каналы)\n"
                        "`/testmode on @channel1 @channel2` - включить (свои каналы)\n"
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
            # Поддержка старого формата ('state') и нового ('action')
            action = state.get('action') or state.get('state')
            
            # Обработка аватара аккаунта
            if action == 'waiting_avatar':
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
                    logger.error(f"Error handling photo upload: {e}")
                    await event.respond(f"❌ Ошибка: {str(e)[:100]}")
                    await self.clear_user_state(user_id)
            
            # Обработка аватара канала-витрины
            elif action == 'waiting_profile_channel_avatar':
                phone = state['phone']
                
                try:
                    await event.respond("⏳ Загрузка изображения для канала...")
                    
                    # Download photo
                    photo = await event.download_media()
                    
                    if not photo:
                        await event.respond("❌ Ошибка загрузки фото")
                        return
                    
                    await event.respond("⏳ Устанавливаю аватар канала...")
                    
                    # Set channel avatar
                    success, message = await self.set_profile_channel_avatar(phone, photo)
                    
                    # Clean up downloaded photo
                    if os.path.exists(photo):
                        try:
                            os.remove(photo)
                        except:
                            pass
                    
                    await event.respond(message)
                    
                    if success:
                        logger.info(f"Profile channel avatar set by admin {user_id} for {phone}")
                    
                    # Clear state
                    await self.clear_user_state(user_id)
                    
                except Exception as e:
                    logger.error(f"Error setting profile channel avatar: {e}")
                    await event.respond(f"❌ Ошибка: {str(e)[:200]}")
                    await self.clear_user_state(user_id)
        
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
        
        # ============= PROFILE CHANNEL COMMANDS =============
        
        @self.bot_client.on(events.NewMessage(pattern='/create_profile_channel'))
        async def create_profile_channel_command(event):
            """Создать канал-витрину для аккаунта"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                parts = event.text.split(maxsplit=2)
                
                if len(parts) < 3:
                    await event.respond(
                        "**🎨 СОЗДАНИЕ КАНАЛА-ВИТРИНЫ**\n\n"
                        "Формат: `/create_profile_channel <phone> <название>`\n\n"
                        "**Пример:**\n"
                        "`/create_profile_channel +13434919340 Мой Магазин`\n\n"
                        "Канал создаётся от имени указанного аккаунта."
                    )
                    return
                
                phone = parts[1]
                title = parts[2]
                
                # Нормализация номера
                if not phone.startswith('+'):
                    phone = '+' + phone
                
                # Проверяем что аккаунт принадлежит админу
                account_data = self.accounts_data.get(phone)
                if not account_data:
                    await event.respond(f"❌ Аккаунт `{phone}` не найден")
                    return
                
                # Проверяем права доступа
                if not self.is_super_admin(event.sender_id):
                    if account_data.get('admin_id') != event.sender_id:
                        await event.respond("❌ Вы можете создавать каналы только для своих аккаунтов")
                        return
                
                # Проверяем, нет ли уже канала
                if account_data.get('profile_channel'):
                    existing = account_data['profile_channel']
                    username = existing.get('username', 'без username')
                    await event.respond(
                        f"⚠️ У аккаунта уже есть канал-витрина:\n"
                        f"• Название: `{existing.get('title')}`\n"
                        f"• Username: `{username}`\n"
                        f"• ID: `{existing.get('id')}`\n\n"
                        f"Используйте `/unlink_profile_channel {phone}` чтобы отвязать"
                    )
                    return
                
                await event.respond(f"⏳ Создаю канал `{title}` для аккаунта `{phone}`...")
                
                # Создаём канал
                success, result = await self.create_profile_channel(phone, title)
                
                if success:
                    channel_info = result
                    username = channel_info.get('username', 'пока нет username')
                    
                    text = f"""✅ **КАНАЛ-ВИТРИНА СОЗДАН**

📱 Аккаунт: `{phone}`
📺 Канал: `{channel_info['title']}`
🆔 ID: `{channel_info['id']}`
👤 Username: `{username}`

🎨 **Следующие шаги:**
1. `/set_profile_channel_avatar {phone}` - установить аватар
2. `/set_profile_channel_post {phone}` - создать приветственный пост
3. Вручную добавить канал в профиль через клиент

💡 Пока у канала нет username, его нельзя найти через поиск."""
                    
                    await event.respond(text)
                    logger.info(f"Profile channel created by admin {event.sender_id} for {phone}")
                else:
                    await event.respond(result)
                    
            except Exception as e:
                logger.error(f"Create profile channel command error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:200]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/link_profile_channel'))
        async def link_profile_channel_command(event):
            """Привязать существующий канал к профилю аккаунта"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                parts = event.text.split(maxsplit=2)
                
                if len(parts) < 3:
                    await event.respond(
                        "**🔗 ПРИВЯЗКА СУЩЕСТВУЮЩЕГО КАНАЛА**\n\n"
                        "Формат: `/link_profile_channel <phone> <@channel>`\n\n"
                        "**Пример:**\n"
                        "`/link_profile_channel +13434919340 @myshowcase`\n\n"
                        "⚠️ Аккаунт должен быть админом канала!"
                    )
                    return
                
                phone = parts[1]
                channel_identifier = parts[2]
                
                # Нормализация номера
                if not phone.startswith('+'):
                    phone = '+' + phone
                
                # Проверяем что аккаунт принадлежит админу
                account_data = self.accounts_data.get(phone)
                if not account_data:
                    await event.respond(f"❌ Аккаунт `{phone}` не найден")
                    return
                
                # Проверяем права доступа
                if not self.is_super_admin(event.sender_id):
                    if account_data.get('admin_id') != event.sender_id:
                        await event.respond("❌ Вы можете привязывать каналы только к своим аккаунтам")
                        return
                
                # Проверяем, нет ли уже канала
                if account_data.get('profile_channel'):
                    existing = account_data['profile_channel']
                    username = existing.get('username', 'без username')
                    await event.respond(
                        f"⚠️ У аккаунта уже есть канал-витрина:\n"
                        f"• Название: `{existing.get('title')}`\n"
                        f"• Username: `{username}`\n\n"
                        f"Используйте `/unlink_profile_channel {phone}` чтобы отвязать"
                    )
                    return
                
                await event.respond(f"⏳ Привязываю канал `{channel_identifier}` к аккаунту `{phone}`...")
                
                # Привязываем канал
                success, result = await self.link_existing_channel(phone, channel_identifier)
                
                if success:
                    channel_info = result
                    username = channel_info.get('username', 'без username')
                    
                    text = f"""✅ **КАНАЛ ПРИВЯЗАН К ПРОФИЛЮ**

📱 Аккаунт: `{phone}`
📺 Канал: `{channel_info['title']}`
👤 Username: `{username}`
🆔 ID: `{channel_info['id']}`
📝 Описание: {channel_info.get('about', 'не задано')}

🎨 **Управление:**
• `/set_profile_channel_avatar {phone}` - изменить аватар
• `/set_profile_channel_post {phone}` - создать пост
• `/update_profile_channel_info {phone}` - обновить название/описание

💡 Для отображения в профиле добавьте канал вручную через клиент"""
                    
                    await event.respond(text)
                    logger.info(f"Profile channel linked by admin {event.sender_id} for {phone}")
                else:
                    await event.respond(result)
                    
            except Exception as e:
                logger.error(f"Link profile channel command error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:200]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/unlink_profile_channel'))
        async def unlink_profile_channel_command(event):
            """Отвязать канал-витрину от аккаунта"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                parts = event.text.split()
                
                if len(parts) < 2:
                    await event.respond("Формат: `/unlink_profile_channel <phone>`")
                    return
                
                phone = parts[1]
                
                # Нормализация номера
                if not phone.startswith('+'):
                    phone = '+' + phone
                
                # Проверяем что аккаунт принадлежит админу
                account_data = self.accounts_data.get(phone)
                if not account_data:
                    await event.respond(f"❌ Аккаунт `{phone}` не найден")
                    return
                
                # Проверяем права доступа
                if not self.is_super_admin(event.sender_id):
                    if account_data.get('admin_id') != event.sender_id:
                        await event.respond("❌ Вы можете отвязывать каналы только у своих аккаунтов")
                        return
                
                # Проверяем, есть ли канал
                if not account_data.get('profile_channel'):
                    await event.respond(f"❌ У аккаунта `{phone}` нет привязанного канала")
                    return
                
                channel_info = account_data['profile_channel']
                username = channel_info.get('username', 'без username')
                
                # Отвязываем
                del account_data['profile_channel']
                self.save_data()
                
                await event.respond(
                    f"✅ Канал отвязан от аккаунта\n\n"
                    f"📺 Канал: `{channel_info['title']}`\n"
                    f"👤 Username: `{username}`\n\n"
                    f"⚠️ Сам канал НЕ удалён, только отвязан от бота.\n"
                    f"Вы можете привязать его снова или удалить через клиент."
                )
                logger.info(f"Profile channel unlinked by admin {event.sender_id} for {phone}")
                
            except Exception as e:
                logger.error(f"Unlink profile channel command error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:200]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/set_profile_channel_avatar'))
        async def set_profile_channel_avatar_command(event):
            """Установить аватар для канала-витрины"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                parts = event.text.split()
                
                if len(parts) < 2:
                    await event.respond(
                        "**🖼️ УСТАНОВКА АВАТАРА КАНАЛА**\n\n"
                        "Формат:\n"
                        "1. Отправьте команду: `/set_profile_channel_avatar <phone>`\n"
                        "2. Затем отправьте изображение (reply на эту команду)\n\n"
                        "**Пример:**\n"
                        "`/set_profile_channel_avatar +13434919340`\n"
                        "затем прикрепите фото"
                    )
                    return
                
                phone = parts[1]
                
                # Нормализация номера
                if not phone.startswith('+'):
                    phone = '+' + phone
                
                # Проверяем что аккаунт принадлежит админу
                account_data = self.accounts_data.get(phone)
                if not account_data:
                    await event.respond(f"❌ Аккаунт `{phone}` не найден")
                    return
                
                # Проверяем права доступа
                if not self.is_super_admin(event.sender_id):
                    if account_data.get('admin_id') != event.sender_id:
                        await event.respond("❌ Вы можете управлять каналами только своих аккаунтов")
                        return
                
                # Проверяем, есть ли канал
                if not account_data.get('profile_channel'):
                    await event.respond(f"❌ У аккаунта `{phone}` нет канала-витрины")
                    return
                
                # Ждём изображение
                msg = await event.respond(f"📸 Отправьте изображение для аватара канала (reply на это сообщение)")
                
                # Сохраняем состояние ожидания
                self.user_states[event.sender_id] = {
                    'action': 'waiting_profile_channel_avatar',
                    'phone': phone,
                    'message_id': msg.id
                }
                
            except Exception as e:
                logger.error(f"Set profile channel avatar command error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:200]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/set_profile_channel_post'))
        async def set_profile_channel_post_command(event):
            """Создать пост в канале-витрине"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                parts = event.text.split(maxsplit=2)
                
                if len(parts) < 3:
                    await event.respond(
                        "**📝 СОЗДАНИЕ ПОСТА В КАНАЛЕ**\n\n"
                        "Формат: `/set_profile_channel_post <phone> <текст>`\n\n"
                        "**Пример:**\n"
                        "`/set_profile_channel_post +13434919340 Добро пожаловать! 🎉`\n\n"
                        "Для закрепления поста добавьте `pin` в конец:\n"
                        "`/set_profile_channel_post +13434919340 pin Закреплённое объявление`"
                    )
                    return
                
                phone = parts[1]
                text_part = parts[2]
                
                # Проверяем наличие флага pin
                pin = False
                if text_part.startswith('pin '):
                    pin = True
                    post_text = text_part[4:]  # Убираем "pin "
                else:
                    post_text = text_part
                
                # Нормализация номера
                if not phone.startswith('+'):
                    phone = '+' + phone
                
                # Проверяем что аккаунт принадлежит админу
                account_data = self.accounts_data.get(phone)
                if not account_data:
                    await event.respond(f"❌ Аккаунт `{phone}` не найден")
                    return
                
                # Проверяем права доступа
                if not self.is_super_admin(event.sender_id):
                    if account_data.get('admin_id') != event.sender_id:
                        await event.respond("❌ Вы можете управлять каналами только своих аккаунтов")
                        return
                
                # Проверяем, есть ли канал
                profile_channel = account_data.get('profile_channel')
                if not profile_channel:
                    await event.respond(f"❌ У аккаунта `{phone}` нет канала-витрины")
                    return
                
                await event.respond(f"⏳ Создаю пост в канале `{profile_channel['title']}`...")
                
                # Создаём пост
                success, message, post_id = await self.create_profile_channel_post(phone, post_text, pin)
                
                if success:
                    channel_username = profile_channel.get('username', 'без username')
                    
                    text = f"""✅ **ПОСТ СОЗДАН**

📺 Канал: `{profile_channel['title']}`
👤 Username: `{channel_username}`
🆔 Post ID: `{post_id}`
📌 Закреплён: {"Да" if pin else "Нет"}

📝 Текст:
{post_text[:100]}{"..." if len(post_text) > 100 else ""}"""
                    
                    await event.respond(text)
                    logger.info(f"Post created by admin {event.sender_id} in profile channel of {phone}")
                else:
                    await event.respond(message)
                    
            except Exception as e:
                logger.error(f"Set profile channel post command error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:200]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/update_profile_channel_info'))
        async def update_profile_channel_info_command(event):
            """Обновить название и описание канала-витрины"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                parts = event.text.split(maxsplit=2)
                
                if len(parts) < 3:
                    await event.respond(
                        "**✏️ ОБНОВЛЕНИЕ ИНФОРМАЦИИ КАНАЛА**\n\n"
                        "Формат: `/update_profile_channel_info <phone> title:<название>|about:<описание>`\n\n"
                        "**Примеры:**\n"
                        "`/update_profile_channel_info +1234 title:Новое Название`\n"
                        "`/update_profile_channel_info +1234 about:Описание канала`\n"
                        "`/update_profile_channel_info +1234 title:Магазин|about:Лучшие товары`"
                    )
                    return
                
                phone = parts[1]
                params = parts[2]
                
                # Нормализация номера
                if not phone.startswith('+'):
                    phone = '+' + phone
                
                # Проверяем что аккаунт принадлежит админу
                account_data = self.accounts_data.get(phone)
                if not account_data:
                    await event.respond(f"❌ Аккаунт `{phone}` не найден")
                    return
                
                # Проверяем права доступа
                if not self.is_super_admin(event.sender_id):
                    if account_data.get('admin_id') != event.sender_id:
                        await event.respond("❌ Вы можете управлять каналами только своих аккаунтов")
                        return
                
                # Проверяем, есть ли канал
                if not account_data.get('profile_channel'):
                    await event.respond(f"❌ У аккаунта `{phone}` нет канала-витрины")
                    return
                
                # Парсим параметры
                title = None
                about = None
                
                for param in params.split('|'):
                    param = param.strip()
                    if param.startswith('title:'):
                        title = param[6:]
                    elif param.startswith('about:'):
                        about = param[6:]
                
                if not title and not about:
                    await event.respond("❌ Укажите хотя бы один параметр: title: или about:")
                    return
                
                await event.respond("⏳ Обновляю информацию канала...")
                
                # Обновляем
                success, message = await self.update_profile_channel_info(phone, title, about)
                await event.respond(message)
                
                if success:
                    logger.info(f"Profile channel info updated by admin {event.sender_id} for {phone}")
                    
            except Exception as e:
                logger.error(f"Update profile channel info command error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:200]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/list_profile_channels'))
        async def list_profile_channels_command(event):
            """Показать все каналы-витрины"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                # Фильтруем аккаунты по админу
                admin_id = self.get_admin_id(event.sender_id)
                
                channels_list = []
                for phone, account_data in self.accounts_data.items():
                    # Проверяем права доступа
                    if admin_id is not None and account_data.get('admin_id') != admin_id:
                        continue
                    
                    profile_channel = account_data.get('profile_channel')
                    if profile_channel:
                        channels_list.append((phone, account_data, profile_channel))
                
                if not channels_list:
                    await event.respond("📺 У ваших аккаунтов пока нет каналов-витрин")
                    return
                
                text = f"**📺 КАНАЛЫ-ВИТРИНЫ ({len(channels_list)})**\n\n"
                
                for idx, (phone, account_data, channel) in enumerate(channels_list, 1):
                    account_name = account_data.get('name', phone[-10:])
                    channel_username = channel.get('username', 'без username')
                    
                    text += f"{idx}. **{account_name}** (`{phone}`)\n"
                    text += f"   📺 `{channel['title']}`\n"
                    text += f"   👤 {channel_username}\n"
                    text += f"   🆔 ID: `{channel['id']}`\n\n"
                
                text += "💡 Команды управления: /help"
                
                await event.respond(text)
                
            except Exception as e:
                logger.error(f"List profile channels command error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:200]}")
        
        # ============= END PROFILE CHANNEL COMMANDS =============
        
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
                # Determine admin_id for filtering (same as /listaccounts)
                admin_id = self.get_admin_id(event.sender_id)
                
                # Filter accounts by admin_id
                if admin_id is None:  # Super admin - show all
                    filtered_accounts = self.accounts_data
                else:  # Regular admin - show only their accounts
                    filtered_accounts = {phone: data for phone, data in self.accounts_data.items()
                                       if data.get('admin_id') == admin_id}
                
                # Get accounts with sessions only, sorted for stable order
                all_accounts = [(phone, data) for phone, data in sorted(filtered_accounts.items()) 
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
                # Determine admin_id for filtering (same as /listaccounts)
                admin_id = self.get_admin_id(event.sender_id)
                
                # Filter accounts by admin_id
                if admin_id is None:  # Super admin - show all
                    filtered_accounts = self.accounts_data
                else:  # Regular admin - show only their accounts
                    filtered_accounts = {phone: data for phone, data in self.accounts_data.items()
                                       if data.get('admin_id') == admin_id}
                
                # Get accounts with sessions only, sorted for stable order
                all_accounts = [(phone, data) for phone, data in sorted(filtered_accounts.items()) 
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
                # Determine admin_id for filtering (same as /listaccounts)
                admin_id = self.get_admin_id(event.sender_id)
                
                # Filter accounts by admin_id
                if admin_id is None:  # Super admin - show all
                    filtered_accounts = self.accounts_data
                else:  # Regular admin - show only their accounts
                    filtered_accounts = {phone: data for phone, data in self.accounts_data.items()
                                       if data.get('admin_id') == admin_id}
                
                # Get accounts with sessions only, sorted for stable order
                all_accounts = [(phone, data) for phone, data in sorted(filtered_accounts.items()) 
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
                    
                    # Log selected account details
                    logger.info(f"PROFILE UPDATE: Account selected - index={account_num}, phone={selected_phone}, "
                               f"status={selected_data.get('status')}, admin_id={selected_data.get('admin_id')}, "
                               f"has_session={bool(selected_data.get('session'))}")
                    
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
                    
                    # ⏰ ПРОВЕРКА RATE LIMITING
                    can_do, wait_time, reason = await self.can_do_profile_operation(phone, 'name')
                    if not can_do:
                        if phone in FROZEN_ACCOUNTS:
                            await event.respond(
                                f"❌ **Аккаунт `{phone}` заблокирован Telegram**\n\n"
                                f"⚠️ Этот аккаунт имеет FROZEN блокировку.\n"
                                f"Изменение профиля невозможно.\n\n"
                                f"💡 Рабочие аккаунты: {', '.join(WORKING_ACCOUNTS)}"
                            )
                        elif wait_time:
                            wait_minutes = int(wait_time.total_seconds() / 60)
                            wait_hours = wait_minutes // 60
                            wait_mins_left = wait_minutes % 60
                            
                            if wait_hours > 0:
                                time_str = f"{wait_hours}ч {wait_mins_left}м"
                            else:
                                time_str = f"{wait_minutes} минут"
                            
                            await event.respond(
                                f"⏰ **Слишком частые операции!**\n\n"
                                f"Аккаунт `{phone}` использовался недавно.\n"
                                f"Подождите: **{time_str}**\n\n"
                                f"⚠️ Это защищает аккаунт от блокировки Telegram."
                            )
                        await self.clear_user_state(event.sender_id)
                        return
                    
                    await event.respond("⏳ Обновляю имя...")
                    
                    # Log profile update details
                    logger.info(f"PROFILE UPDATE: cmd=/setname, phone={phone}, "
                               f"status={data.get('status')}, admin_id={data.get('admin_id')}, "
                               f"has_session={bool(data.get('session'))}")
                    
                    # Update profile
                    client = None
                    try:
                        logger.info(f"PROFILE UPDATE: Creating client for phone={phone}")
                        client = TelegramClient(
                            StringSession(data['session']), 
                            API_ID, 
                            API_HASH,
                            proxy=data.get('proxy')
                        )
                        
                        logger.info(f"PROFILE UPDATE: Connecting client for phone={phone}")
                        await client.connect()
                        
                        logger.info(f"PROFILE UPDATE: Checking authorization for phone={phone}")
                        if not await client.is_user_authorized():
                            logger.error(f"PROFILE UPDATE: FAILED - Account {phone} not authorized")
                            await event.respond(f"❌ Аккаунт `{phone}` не авторизован. Возможно, сессия устарела.")
                            await client.disconnect()
                            await self.clear_user_state(event.sender_id)
                            return
                        
                        # Get current name
                        logger.info(f"PROFILE UPDATE: Getting current profile for phone={phone}")
                        me = await client.get_me()
                        logger.info(f"PROFILE UPDATE: Got user object - id={me.id}, username={me.username}, phone={me.phone}")
                        old_name = f"{me.first_name or ''} {me.last_name or ''}".strip()
                        logger.info(f"PROFILE UPDATE: Current name for {phone}: '{old_name}' (first_name='{me.first_name}', last_name='{me.last_name}')")
                        
                        # Update name
                        logger.info(f"PROFILE UPDATE: Calling UpdateProfileRequest for phone={phone}, "
                                   f"first_name='{first_name}', last_name='{last_name}'")
                        logger.info(f"PROFILE UPDATE: About to call UpdateProfileRequest with params: {{first_name: '{first_name}', last_name: '{last_name}'}}")
                        
                        result = await client(UpdateProfileRequest(
                            first_name=first_name,
                            last_name=last_name
                        ))
                        
                        logger.info(f"PROFILE UPDATE: UpdateProfileRequest completed. Result type: {type(result).__name__}")
                        logger.info(f"PROFILE UPDATE: Result object: {result}")
                        
                        # ВЕРИФИКАЦИЯ: Проверяем что профиль реально изменился
                        logger.info(f"PROFILE UPDATE: Verifying name change...")
                        await asyncio.sleep(0.3)  # Пауза для синхронизации
                        me_after = await client.get_me()
                        logger.info(f"PROFILE UPDATE: After update - first_name='{me_after.first_name}', last_name='{me_after.last_name}'")
                        
                        if me_after.first_name == first_name and me_after.last_name == last_name:
                            logger.info(f"PROFILE UPDATE: ✅ VERIFIED - Name REALLY changed for phone={phone}")
                            logger.info(f"PROFILE UPDATE: Old name: '{old_name}'")
                            logger.info(f"PROFILE UPDATE: New name: '{first_name} {last_name}'")
                            
                            # Log to DB
                            await self.log_profile_change(phone, 'name', old_name, new_name, True)
                            
                            await event.respond(
                                f"✅ **Имя обновлено для `{phone}`**\n\n"
                                f"Было: {old_name or '(не задано)'}\n"
                                f"Стало: {first_name} {last_name}\n\n"
                                f"✅ Изменение подтверждено в Telegram"
                            )
                        else:
                            # API вернул success, но имя НЕ изменилось!
                            logger.warning(f"PROFILE UPDATE: ⚠️ FALSE SUCCESS - API OK but name NOT changed!")
                            logger.warning(f"PROFILE UPDATE: Expected: '{first_name} {last_name}'")
                            logger.warning(f"PROFILE UPDATE: Actual: '{me_after.first_name} {me_after.last_name}'")
                            
                            await self.log_profile_change(phone, 'name', old_name, new_name, False)
                            
                            await event.respond(
                                f"⚠️ **API вернул успех, но имя НЕ изменилось для `{phone}`**\n\n"
                                f"Telegram принял запрос, но профиль остался без изменений.\n\n"
                                f"Ожидали: {first_name} {last_name}\n"
                                f"Получили: {me_after.first_name or ''} {me_after.last_name or ''}\n\n"
                                f"💡 Возможно аккаунт имеет скрытые ограничения.\n"
                                f"Попробуйте другой аккаунт."
                            )
                        
                    except Exception as e:
                        await self.log_profile_change(phone, 'name', '', new_name, False)
                        error_msg = str(e)
                        logger.error(f"PROFILE UPDATE: ERROR - Failed to update name for phone={phone}")
                        logger.error(f"PROFILE UPDATE: ERROR Type: {type(e).__name__}")
                        logger.error(f"PROFILE UPDATE: ERROR Message: {error_msg}")
                        import traceback
                        logger.error(f"PROFILE UPDATE: ERROR Traceback:\n{traceback.format_exc()}")
                        
                        # Специальная обработка FROZEN ошибки
                        if "FROZEN" in error_msg or "420" in error_msg:
                            await event.respond(
                                f"❌ **Аккаунт `{phone}` не может изменять профиль**\n\n"
                                f"Telegram заблокировал эту функцию для данного аккаунта (FROZEN_METHOD).\n\n"
                                f"💡 Это означает что аккаунт имеет ограничения.\n"
                                f"Попробуйте другой аккаунт или обратитесь к администратору."
                            )
                        else:
                            await event.respond(
                                f"❌ **Ошибка при обновлении имени для `{phone}`**\n\n"
                            f"Тип: {type(e).__name__}\n"
                            f"Сообщение: {str(e)[:200]}"
                        )
                    finally:
                        if client and client.is_connected():
                            logger.info(f"PROFILE UPDATE: Disconnecting client for phone={phone}")
                            await client.disconnect()
                    
                    # Clear state
                    await self.clear_user_state(event.sender_id)
                
                elif state == 'waiting_bio_input':
                    new_bio = event.text.strip()
                    phone = state_data.get('phone')
                    data = state_data.get('data')
                    
                    if not new_bio:
                        await event.respond("❌ Описание не может быть пустым")
                        return
                    
                    # ⏰ ПРОВЕРКА RATE LIMITING
                    can_do, wait_time, reason = await self.can_do_profile_operation(phone, 'bio')
                    if not can_do:
                        if phone in FROZEN_ACCOUNTS:
                            await event.respond(
                                f"❌ **Аккаунт `{phone}` заблокирован Telegram**\n\n"
                                f"⚠️ Этот аккаунт имеет FROZEN блокировку.\n"
                                f"Изменение профиля невозможно.\n\n"
                                f"💡 Рабочие аккаунты: {', '.join(WORKING_ACCOUNTS)}"
                            )
                        elif wait_time:
                            wait_minutes = int(wait_time.total_seconds() / 60)
                            wait_hours = wait_minutes // 60
                            wait_mins_left = wait_minutes % 60
                            
                            if wait_hours > 0:
                                time_str = f"{wait_hours}ч {wait_mins_left}м"
                            else:
                                time_str = f"{wait_minutes} минут"
                            
                            await event.respond(
                                f"⏰ **Слишком частые операции!**\n\n"
                                f"Аккаунт `{phone}` использовался недавно.\n"
                                f"Подождите: **{time_str}**\n\n"
                                f"⚠️ Это защищает аккаунт от блокировки Telegram.\n\n"
                                f"Лимиты:\n"
                                f"• BIO: не чаще 1 раза в час\n"
                                f"• NAME: не чаще 1 раза в час\n"
                                f"• AVATAR: не чаще 1 раза в день"
                            )
                        await self.clear_user_state(event.sender_id)
                        return
                    
                    await event.respond("⏳ Обновляю био...")
                    
                    # Log profile update details
                    logger.info(f"PROFILE UPDATE: cmd=/setbio, phone={phone}, "
                               f"status={data.get('status')}, admin_id={data.get('admin_id')}, "
                               f"has_session={bool(data.get('session'))}, bio_length={len(new_bio)}")
                    
                    # Update profile
                    client = None
                    try:
                        logger.info(f"PROFILE UPDATE: Creating client for phone={phone}")
                        client = TelegramClient(
                            StringSession(data['session']), 
                            API_ID, 
                            API_HASH,
                            proxy=data.get('proxy')
                        )
                        
                        logger.info(f"PROFILE UPDATE: Connecting client for phone={phone}")
                        await client.connect()
                        
                        logger.info(f"PROFILE UPDATE: Checking authorization for phone={phone}")
                        if not await client.is_user_authorized():
                            logger.error(f"PROFILE UPDATE: FAILED - Account {phone} not authorized")
                            await event.respond(f"❌ Аккаунт `{phone}` не авторизован. Возможно, сессия устарела.")
                            await client.disconnect()
                            await self.clear_user_state(event.sender_id)
                            return
                        
                        # Get current bio (if possible)
                        logger.info(f"PROFILE UPDATE: Getting current profile for phone={phone}")
                        me = await client.get_me()
                        # Note: me.about might not be available, need to use GetFullUserRequest
                        full = await client(GetFullUserRequest(me))
                        old_bio = full.full_user.about or ''
                        logger.info(f"PROFILE UPDATE: Current bio for {phone}: '{old_bio[:50]}...'")
                        
                        # Update bio
                        logger.info(f"PROFILE UPDATE: Calling UpdateProfileRequest for phone={phone} with bio='{new_bio[:50]}...'")
                        
                        result = await client(UpdateProfileRequest(about=new_bio))
                        
                        logger.info(f"PROFILE UPDATE: UpdateProfileRequest result type: {type(result).__name__}")
                        
                        # ВЕРИФИКАЦИЯ: проверяем что профиль реально изменился
                        logger.info(f"PROFILE UPDATE: Verifying bio change...")
                        await asyncio.sleep(0.3)  # Пауза для синхронизации
                        full_after = await client(GetFullUserRequest(me))
                        actual_bio = full_after.full_user.about or ''
                        
                        if actual_bio == new_bio:
                            logger.info(f"PROFILE UPDATE: SUCCESS - Bio VERIFIED changed for phone={phone}")
                            logger.info(f"PROFILE UPDATE: Old bio: '{old_bio[:50]}...'")
                            logger.info(f"PROFILE UPDATE: New bio: '{actual_bio[:50]}...'")
                            
                            # Log to DB
                            await self.log_profile_change(phone, 'bio', old_bio, new_bio, True)
                            
                            await event.respond(
                                f"✅ **Био обновлено для `{phone}`**\n\n"
                                f"Было: {old_bio[:50]}...\n"
                                f"Стало: {new_bio[:150]}\n\n"
                                f"✅ Изменение подтверждено в Telegram"
                            )
                        else:
                            # API вернул success, но профиль НЕ изменился!
                            logger.warning(f"PROFILE UPDATE: FALSE SUCCESS - API OK but bio NOT changed!")
                            logger.warning(f"PROFILE UPDATE: Expected: '{new_bio}'")
                            logger.warning(f"PROFILE UPDATE: Actual: '{actual_bio}'")
                            
                            await self.log_profile_change(phone, 'bio', old_bio, new_bio, False)
                            
                            await event.respond(
                                f"⚠️ **API вернул успех, но био НЕ изменилось для `{phone}`**\n\n"
                                f"Telegram принял запрос, но профиль остался без изменений.\n\n"
                                f"Ожидали: {new_bio[:100]}\n"
                                f"Получили: {actual_bio[:100]}\n\n"
                                f"💡 Возможно аккаунт имеет скрытые ограничения.\n"
                                f"Попробуйте другой аккаунт."
                            )
                        
                    except Exception as e:
                        await self.log_profile_change(phone, 'bio', '', new_bio, False)
                        error_msg = str(e)
                        error_type = type(e).__name__
                        
                        logger.error(f"PROFILE UPDATE: ERROR - Failed to update bio for phone={phone}")
                        logger.error(f"PROFILE UPDATE: ERROR Type: {error_type}")
                        logger.error(f"PROFILE UPDATE: ERROR Message: {error_msg}")
                        import traceback
                        logger.error(f"PROFILE UPDATE: ERROR Traceback:\n{traceback.format_exc()}")
                        
                        # Детальная обработка конкретных ошибок
                        if "ABOUT_TOO_LONG" in error_msg:
                            await event.respond(
                                f"❌ **Био слишком длинное для `{phone}`**\n\n"
                                f"📏 Длина: {len(new_bio)} символов\n"
                                f"⚠️ Telegram: максимум 70 символов\n\n"
                                f"💡 Сократите текст и попробуйте снова"
                            )
                        elif "FROZEN" in error_msg or "USER_DEACTIVATED" in error_msg:
                            await event.respond(
                                f"❌ **Аккаунт `{phone}` заморожен/деактивирован**\n\n"
                                f"⚠️ Telegram полностью ограничил этот аккаунт\n"
                                f"🚫 Изменение профиля невозможно\n\n"
                                f"💡 Используйте другой активный аккаунт"
                            )
                        elif "FLOOD_WAIT" in error_msg:
                            # Извлекаем время ожидания из ошибки
                            import re
                            wait_match = re.search(r'(\d+)', error_msg)
                            wait_seconds = int(wait_match.group(1)) if wait_match else 60
                            wait_minutes = wait_seconds // 60
                            
                            await event.respond(
                                f"⏰ **Флуд-контроль Telegram для `{phone}`**\n\n"
                                f"⚠️ Слишком частые изменения профиля\n"
                                f"⏳ Подождите: {wait_minutes} минут ({wait_seconds} сек)\n\n"
                                f"💡 Это ограничение самого Telegram, не бота"
                            )
                        elif "AUTH_KEY_UNREGISTERED" in error_msg:
                            await event.respond(
                                f"❌ **Сессия `{phone}` недействительна**\n\n"
                                f"🔑 Аккаунт разлогинен в Telegram\n"
                                f"⚠️ Требуется повторная авторизация\n\n"
                                f"💡 Используйте /auth {phone} для входа заново"
                            )
                        elif "PHONE_NUMBER_BANNED" in error_msg:
                            await event.respond(
                                f"🚫 **Аккаунт `{phone}` забанен в Telegram**\n\n"
                                f"⛔ Номер заблокирован на уровне Telegram\n"
                                f"❌ Использование невозможно\n\n"
                                f"💡 Этот аккаунт нужно пометить как broken"
                            )
                        else:
                            await event.respond(
                                f"❌ **Ошибка при обновлении био для `{phone}`**\n\n"
                                f"Тип ошибки: `{error_type}`\n"
                                f"Сообщение: `{error_msg[:200]}`\n\n"
                                f"📋 Детали записаны в лог\n\n"
                                f"💡 Попробуйте:\n"
                                f"• Другой аккаунт\n"
                                f"• Более короткий текст\n"
                                f"• Подождать 1 час"
                            )
                    finally:
                        if client and client.is_connected():
                            logger.info(f"PROFILE UPDATE: Disconnecting client for phone={phone}")
                            await client.disconnect()
                    
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
                
                # Log profile update details
                logger.info(f"PROFILE UPDATE: cmd=/setavatar, phone={phone}, "
                           f"status={data.get('status')}, admin_id={data.get('admin_id')}, "
                           f"has_session={bool(data.get('session'))}")
                
                # Download photo
                logger.info(f"PROFILE UPDATE: Downloading photo for phone={phone}")
                photo_path = await event.download_media(file=f"/tmp/avatar_{event.sender_id}.jpg")
                
                if not photo_path or not os.path.exists(photo_path):
                    logger.error(f"PROFILE UPDATE: FAILED - Photo download failed for phone={phone}")
                    await event.respond("❌ Ошибка загрузки фото")
                    await self.clear_user_state(event.sender_id)
                    return
                
                logger.info(f"PROFILE UPDATE: Photo downloaded to {photo_path} for phone={phone}")
                
                # ✅ ЗАЩИТА: Проверяем rate limiting перед загрузкой аватара
                can_do, wait_time, reason = await self.can_do_profile_operation(phone, 'avatar')
                if not can_do:
                    if phone in FROZEN_ACCOUNTS:
                        await event.respond(
                            f"❌ Аккаунт `{phone}` заблокирован Telegram для изменения аватара.\n\n"
                            f"**Причина:** {reason}\n\n"
                            f"🔧 **Что делать:**\n"
                            f"1. Используйте другой аккаунт из списка\n"
                            f"2. Или получите новый незаблокированный аккаунт"
                        )
                        # Clean up temp file
                        try:
                            os.remove(photo_path)
                        except:
                            pass
                        await self.clear_user_state(event.sender_id)
                        return
                    elif wait_time:
                        hours = int(wait_time.total_seconds() // 3600)
                        minutes = int((wait_time.total_seconds() % 3600) // 60)
                        wait_msg = f"{hours} ч {minutes} мин" if hours > 0 else f"{minutes} мин"
                        await event.respond(
                            f"⏰ Аккаунт `{phone}` можно использовать для аватара через {wait_msg}\n\n"
                            f"**Причина:** {reason}\n\n"
                            f"Лимит: 1 раз в 24 часа (защита от блокировки)"
                        )
                        # Clean up temp file
                        try:
                            os.remove(photo_path)
                        except:
                            pass
                        await self.clear_user_state(event.sender_id)
                        return
                
                await event.respond("⏳ Загружаю аватарку...")
                
                # Upload to selected account
                client = None
                try:
                    logger.info(f"PROFILE UPDATE: Creating client for phone={phone}")
                    client = TelegramClient(
                        StringSession(data['session']), 
                        API_ID, 
                        API_HASH,
                        proxy=data.get('proxy')
                    )
                    
                    logger.info(f"PROFILE UPDATE: Connecting client for phone={phone}")
                    await client.connect()
                    
                    logger.info(f"PROFILE UPDATE: Checking authorization for phone={phone}")
                    if not await client.is_user_authorized():
                        logger.error(f"PROFILE UPDATE: FAILED - Account {phone} not authorized")
                        await event.respond(f"❌ Аккаунт `{phone}` не авторизован. Возможно, сессия устарела.")
                        await client.disconnect()
                        await self.clear_user_state(event.sender_id)
                        # Clean up temp file
                        try:
                            os.remove(photo_path)
                        except:
                            pass
                        return
                    
                    # Upload profile photo using upload_profile_photo method
                    logger.info(f"PROFILE UPDATE: Uploading photo file for phone={phone}")
                    
                    # Получаем количество фото ДО загрузки
                    photos_before = await client.get_profile_photos('me')
                    count_before = len(photos_before)
                    logger.info(f"PROFILE UPDATE: Photos count BEFORE: {count_before}")
                    
                    uploaded_file = await client.upload_file(photo_path)
                    logger.info(f"PROFILE UPDATE: File uploaded, type: {type(uploaded_file).__name__}")
                    
                    logger.info(f"PROFILE UPDATE: Calling UploadProfilePhotoRequest for phone={phone}")
                    result = await client(UploadProfilePhotoRequest(file=uploaded_file))
                    
                    logger.info(f"PROFILE UPDATE: UploadProfilePhotoRequest result type: {type(result).__name__}")
                    
                    # ВЕРИФИКАЦИЯ: Проверяем что фото реально добавилось
                    logger.info(f"PROFILE UPDATE: Verifying avatar upload...")
                    await asyncio.sleep(0.5)  # Пауза для синхронизации
                    photos_after = await client.get_profile_photos('me')
                    count_after = len(photos_after)
                    logger.info(f"PROFILE UPDATE: Photos count AFTER: {count_after}")
                    
                    if count_after > count_before:
                        logger.info(f"PROFILE UPDATE: ✅ VERIFIED - Avatar REALLY uploaded for phone={phone}")
                        logger.info(f"PROFILE UPDATE: Photos before: {count_before}, after: {count_after}")
                        
                        # Log to DB
                        await self.log_profile_change(phone, 'avatar', '', 'uploaded', True)
                        
                        await event.respond(
                            f"✅ **Аватарка загружена для `{phone}`**\n\n"
                            f"Было фото: {count_before}\n"
                            f"Стало фото: {count_after}\n\n"
                            f"✅ Загрузка подтверждена в Telegram"
                        )
                    else:
                        # API вернул success, но фото НЕ добавилось!
                        logger.warning(f"PROFILE UPDATE: ⚠️ FALSE SUCCESS - API OK but avatar NOT uploaded!")
                        logger.warning(f"PROFILE UPDATE: Photos before: {count_before}, after: {count_after}")
                        
                        await self.log_profile_change(phone, 'avatar', '', '', False)
                        
                        await event.respond(
                            f"⚠️ **API вернул успех, но аватарка НЕ загружена для `{phone}`**\n\n"
                            f"Telegram принял запрос, но фото не появилось в профиле.\n\n"
                            f"Количество фото: до={count_before}, после={count_after}\n\n"
                            f"💡 Возможно аккаунт имеет скрытые ограничения.\n"
                            f"Попробуйте другой аккаунт."
                        )
                    
                except Exception as e:
                    await self.log_profile_change(phone, 'avatar', '', '', False)
                    error_msg = str(e)
                    logger.error(f"PROFILE UPDATE: ERROR - Failed to upload avatar for phone={phone}")
                    logger.error(f"PROFILE UPDATE: ERROR Type: {type(e).__name__}")
                    logger.error(f"PROFILE UPDATE: ERROR Message: {error_msg}")
                    import traceback
                    logger.error(f"PROFILE UPDATE: ERROR Traceback:\n{traceback.format_exc()}")
                    
                    # Специальная обработка FROZEN ошибки
                    if "FROZEN" in error_msg or "420" in error_msg:
                        await event.respond(
                            f"❌ **Загрузка АВАТАРА заблокирована для `{phone}`**\n\n"
                            f"⚠️ Telegram ограничил UploadProfilePhotoRequest для этого аккаунта.\n\n"
                            f"💡 Возможно работают другие операции:\n"
                            f"• Попробуйте /setname или /setbio\n"
                            f"• Или выберите другой аккаунт для /setavatar"
                        )
                    else:
                        await event.respond(
                            f"❌ **Ошибка при загрузке аватарки для `{phone}`**\n\n"
                            f"Тип: {type(e).__name__}\n"
                            f"Сообщение: {error_msg[:200]}"
                        )
                finally:
                    if client and client.is_connected():
                        logger.info(f"PROFILE UPDATE: Disconnecting client for phone={phone}")
                        await client.disconnect()
                    
                    # Clean up temp file
                    try:
                        if photo_path and os.path.exists(photo_path):
                            os.remove(photo_path)
                            logger.info(f"PROFILE UPDATE: Temp file removed: {photo_path}")
                    except Exception as cleanup_error:
                        logger.warning(f"PROFILE UPDATE: Failed to remove temp file: {cleanup_error}")
                
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
    
    async def account_worker(self, phone, account_data, all_channels, worker_index, total_workers, mode='distributed'):
        """Worker function: processes channels based on mode (cyclic or distributed)"""
        account_name = account_data.get('name', phone[-10:])
        
        # В distributed режиме делим каналы между воркерами
        if mode == 'distributed':
            channels_per_worker = len(all_channels) // total_workers
            remainder = len(all_channels) % total_workers
            
            start_idx = worker_index * channels_per_worker + min(worker_index, remainder)
            end_idx = start_idx + channels_per_worker + (1 if worker_index < remainder else 0)
            my_channels = all_channels[start_idx:end_idx]
            
            logger.info("="*60)
            logger.info(f"WORKER STARTED: account={phone}, parallel_idx={worker_index+1}/{total_workers}")
            logger.info(f"   Name: {account_name}")
            logger.info(f"   Mode: DISTRIBUTED (dedicated channels)")
            logger.info(f"   My channels: {start_idx+1}-{end_idx} ({len(my_channels)} total)")
            logger.info(f"   Status: {account_data.get('status', 'unknown')}")
            logger.info("="*60)
        else:  # cyclic mode
            my_channels = all_channels
            logger.info("="*60)
            logger.info(f"WORKER STARTED: account={phone}, parallel_idx={worker_index+1}/{total_workers}")
            logger.info(f"   Name: {account_name}")
            logger.info(f"   Mode: CYCLIC (all channels with offset)")
            logger.info(f"   Total channels: {len(all_channels)}")
            logger.info(f"   Offset: starts from channel #{(worker_index % len(all_channels)) + 1}")
            logger.info(f"   Status: {account_data.get('status', 'unknown')}")
            logger.info("="*60)
        
        # Offset delay to spread workers
        initial_offset = worker_index * 10
        if initial_offset > 0:
            logger.info(f"[{account_name}] Offset delay: {initial_offset}s")
            await asyncio.sleep(initial_offset)
        
        # Create Telethon client once
        worker_client = None
        try:
            logger.info(f"[{account_name}] Creating Telethon client...")
            worker_client = TelegramClient(
                StringSession(account_data['session']), 
                API_ID, 
                API_HASH,
                proxy=account_data.get('proxy')
            )
            await worker_client.connect()
            
            if not await worker_client.is_user_authorized():
                logger.error(f"[{account_name}] Account not authorized!")
                return
            
            logger.info(f"[{account_name}] Client ready")
        except Exception as e:
            logger.error(f"[{account_name}] Failed to create client: {e}")
            return
        
        # Main cycle loop
        cycle_number = 0
        max_cycles = self.max_cycles_per_worker
        
        try:
            while self.monitoring:
                # Проверка лимита циклов (если установлен)
                if max_cycles > 0 and cycle_number >= max_cycles:
                    logger.info("="*60)
                    logger.info(f"[{account_name}] ROTATION: completed {max_cycles} cycles")
                    logger.info(f"[{account_name}] Moving to reserve, next account will take over")
                    logger.info("="*60)
                    break
                
                cycle_number += 1
                commented_channels = []
                
                logger.info("="*60)
                logger.info(f"[{account_name}] CYCLE #{cycle_number} STARTED")
                logger.info(f"[{account_name}] Channels: {len(my_channels)}")
                if max_cycles > 0:
                    logger.info(f"[{account_name}] Progress: {cycle_number}/{max_cycles} cycles")
                logger.info("="*60)
                
                # Check account status
                current_status = self.get_account_status(phone)
                if current_status != ACCOUNT_STATUS_ACTIVE:
                    logger.warning(f"[{account_name}] Status: {current_status}, pausing...")
                    await asyncio.sleep(30)
                    continue
                
                # Process channels based on mode
                if mode == 'cyclic':
                    # В cyclic режиме используем offset для распределения
                    start_offset = worker_index % len(my_channels)
                else:
                    # В distributed режиме обрабатываем последовательно
                    start_offset = 0
                
                for step, idx in enumerate(range(len(my_channels)), 1):
                    if not self.monitoring:
                        break
                    
                    # Check status before each comment
                    current_status = self.get_account_status(phone)
                    if current_status != ACCOUNT_STATUS_ACTIVE:
                        logger.info(f"[{account_name}] Status changed, stopping cycle")
                        break
                    
                    # Check rate limit
                    can_send, wait_time = self.can_account_send_message(phone)
                    if not can_send:
                        logger.warning(f"[{account_name}] Rate limit. Wait: {wait_time}s")
                        await asyncio.sleep(min(wait_time + 10, 300))
                        can_send, wait_time = self.can_account_send_message(phone)
                        if not can_send:
                            logger.info(f"[{account_name}] Still limited, skipping")
                            continue
                    
                    # Get channel with offset
                    channel_idx = (start_offset + idx) % len(my_channels)
                    channel = my_channels[channel_idx]
                    
                    # Normalize channel
                    if isinstance(channel, dict):
                        username = channel.get('username') or channel.get('name')
                    else:
                        username = str(channel)
                    username = str(username).strip().lstrip('@')
                    
                    # Anti-spam protection
                    can_comment, wait_for_channel = self.can_account_comment_in_channel(phone, username)
                    if not can_comment:
                        logger.info(f"[{account_name}] @{username} recently commented, skipping")
                        continue
                    
                    # Initialize tracking
                    if username not in self.commented_posts:
                        self.commented_posts[username] = set()
                    
                    client = worker_client
                    
                    try:
                        # Get/join channel
                        channel_entity = None
                        try:
                            try:
                                channel_entity = await client.get_entity(username)
                            except:
                                channel_entity = await client.get_entity('https://t.me/' + username)
                        except Exception as e_get:
                            logger.info(f"[{account_name}] Joining @{username}...")
                            try:
                                result = await client(functions.channels.JoinChannelRequest('https://t.me/' + username))
                                await asyncio.sleep(1)
                                try:
                                    channel_entity = await client.get_entity(username)
                                except:
                                    channel_entity = await client.get_entity('https://t.me/' + username)
                            except Exception as e_join:
                                logger.error(f"[{account_name}] Cannot access @{username}: {e_join}")
                                await self.mark_channel_failed_for_account(username, phone, f"Access error")
                                await asyncio.sleep(1)
                                continue
                        
                        if not channel_entity:
                            logger.error(f"[{account_name}] Failed to get @{username}")
                            await asyncio.sleep(1)
                            continue
                        
                        # Find discussion group
                        linked_chat_id = None
                        discussion_entity = None
                        
                        try:
                            full = await client(functions.channels.GetFullChannelRequest(channel=channel_entity))
                            
                            if hasattr(full, 'full_chat'):
                                if hasattr(full.full_chat, 'linked_chat_id'):
                                    linked_chat_id = full.full_chat.linked_chat_id
                            
                            if not linked_chat_id and hasattr(full, 'chats'):
                                for ch in full.chats:
                                    if hasattr(ch, 'megagroup') and ch.megagroup:
                                        try:
                                            discussion_entity = ch
                                            linked_chat_id = ch.id
                                            break
                                        except Exception:
                                            continue
                        except Exception as e_full:
                            logger.error(f"[{account_name}] GetFullChannel error for @{username}: {e_full}")
                            await asyncio.sleep(2)
                            continue
                        
                        # Resolve discussion entity
                        if linked_chat_id and not discussion_entity:
                            for attempt in range(3):
                                try:
                                    if attempt == 0:
                                        discussion_entity = await client.get_entity(int(linked_chat_id))
                                    elif attempt == 1:
                                        from telethon.tl.types import PeerChannel
                                        discussion_entity = await client.get_entity(PeerChannel(int(linked_chat_id)))
                                    else:
                                        discussion_entity = await client.get_entity(-100 + int(linked_chat_id) if linked_chat_id > 0 else linked_chat_id)
                                    
                                    if discussion_entity:
                                        break
                                except Exception as e_get:
                                    if attempt == 2:
                                        logger.error(f"[{account_name}] Cannot resolve discussion for @{username}")
                                    await asyncio.sleep(0.5)
                        
                        if not discussion_entity and not linked_chat_id:
                            await self.mark_channel_failed_for_account(username, phone, "No discussion group")
                            logger.warning(f"[{account_name}] @{username} has no discussion")
                            await asyncio.sleep(1)
                            continue
                        elif not discussion_entity:
                            logger.warning(f"[{account_name}] Could not resolve discussion for @{username}")
                            await asyncio.sleep(2)
                            continue
                        
                        # Get messages
                        try:
                            msgs = await client.get_messages(discussion_entity, limit=10)
                            
                            reply_id = None
                            post_text = ""
                            for msg in msgs:
                                if msg.id not in self.commented_posts[username]:
                                    reply_id = msg.id
                                    post_text = msg.text or msg.message or ""
                                    break
                            
                            if not reply_id and msgs:
                                reply_id = msgs[0].id
                                post_text = msgs[0].text or msgs[0].message or ""
                                if len(self.commented_posts[username]) > 30:
                                    oldest_ids = sorted(list(self.commented_posts[username]))[:15]
                                    for old_id in oldest_ids:
                                        self.commented_posts[username].discard(old_id)
                            
                            if not post_text:
                                try:
                                    channel_msgs = await client.get_messages(channel_entity, limit=5)
                                    if channel_msgs:
                                        post_text = channel_msgs[0].text or channel_msgs[0].message or "Интересный пост!"
                                except Exception:
                                    post_text = "Интересный пост!"
                            
                            # Generate comment
                            channel_theme_str = channel.get('theme', 'общая') if isinstance(channel, dict) else 'общая'
                            comment = generate_neuro_comment(
                                post_text=post_text,
                                channel_theme=channel_theme_str
                            )
                            
                            # Test mode duplicate check
                            if self.test_mode:
                                if not hasattr(self, '_last_test_comments'):
                                    self._last_test_comments = []
                                
                                if comment in self._last_test_comments:
                                    logger.warning(f"[{account_name}] Duplicate comment detected, regenerating...")
                                    comment = generate_neuro_comment(
                                        post_text=post_text,
                                        channel_theme=channel_theme_str
                                    )
                                    if comment in self._last_test_comments:
                                        base_comment = random.choice(self.templates)
                                        comment = self.generate_comment_variation(base_comment)
                                
                                self._last_test_comments.append(comment)
                                if len(self._last_test_comments) > 10:
                                    self._last_test_comments.pop(0)
                            
                        except Exception as e_msgs:
                            logger.error(f"[{account_name}] Error getting messages: {e_msgs}")
                            reply_id = None
                            base_comment = random.choice(self.templates)
                            comment = self.generate_comment_variation(base_comment)
                        
                        # Join discussion
                        try:
                            await client(functions.channels.JoinChannelRequest(discussion_entity))
                            await asyncio.sleep(1)
                        except Exception:
                            pass
                        
                        # Send comment
                        comment_success = False
                        try:
                            if reply_id:
                                await client.send_message(discussion_entity, comment, reply_to=reply_id)
                                self.commented_posts[username].add(reply_id)
                            else:
                                await client.send_message(discussion_entity, comment)
                            
                            comment_success = True
                            self.register_message_sent(phone, username)
                            
                            # Logging with MODE indicator
                            short_comment = comment[:50] if len(comment) > 50 else comment
                            current_time = datetime.now().strftime('%H:%M:%S')
                            commented_channels.append(f"@{username}")
                            
                            # КРИТИЧНО: Явный индикатор режима в логах
                            mode_indicator = "🧪 mode=TEST" if self.test_mode else "🚀 mode=LIVE"
                            
                            logger.info("="*80)
                            logger.info(f"{mode_indicator} | COMMENT SENT")
                            logger.info(f"   Channel: @{username}")
                            logger.info(f"   Account: {account_name} ({phone[-10:]})")
                            logger.info(f"   Time: {current_time}")
                            logger.info(f"   Comment: {short_comment}...")
                            if reply_id:
                                logger.info(f"   Reply to: post #{reply_id}")
                            logger.info("="*80)
                            
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
                            
                            if self.test_mode:
                                logger.error(f"TEST MODE ERROR:")
                                logger.error(f"   Channel: @{username}")
                                logger.error(f"   Account: {account_name} ({phone})")
                                logger.error(f"   Error: {err_text[:100]}")
                            
                            logger.error(f"[{account_name}] Send error for @{username}: {err_text}")
                            
                            # Error handling...
                            permanent_errors = [
                                "You can't write in this chat",
                                "CHAT_WRITE_FORBIDDEN",
                                "CHAT_SEND_PLAIN_FORBIDDEN",
                                "CHANNEL_PRIVATE"
                            ]
                            
                            is_permanent = any(err in err_text for err in permanent_errors)
                            
                            if is_permanent:
                                await self.mark_channel_failed_for_account(username, phone, "Comments forbidden")
                            elif "FloodWait" in err_text:
                                try:
                                    import re
                                    wait_match = re.search(r'(\d+)', err_text)
                                    wait_seconds = int(wait_match.group(1)) if wait_match else 60
                                    logger.warning(f"[{account_name}] FloodWait {wait_seconds}s")
                                    await asyncio.sleep(min(wait_seconds + 5, 120))
                                except Exception:
                                    await asyncio.sleep(60)
                            elif "USER_DEACTIVATED" in err_text or "AUTH_KEY_UNREGISTERED" in err_text:
                                logger.error(f"[{account_name}] ACCOUNT BANNED!")
                                await self.handle_account_ban(phone, "Account Deactivated")
                                break
                            else:
                                await asyncio.sleep(3)
                    
                    except Exception as e:
                        logger.error(f"[{account_name}] Error on @{username}: {str(e)[:100]}")
                        await asyncio.sleep(3)
                    
                    # Delay between comments
                    if self.test_mode:
                        target_rate = self.test_mode_speed_limit
                    else:
                        target_rate = self.messages_per_hour
                    
                    base_delay = (3600 // target_rate) if target_rate > 0 else 60
                    delay = random.randint(int(base_delay * 0.8), int(base_delay * 1.2))
                    
                    logger.info(f"[{account_name}] Waiting {delay}s (target: {target_rate} msg/hour)")
                    await asyncio.sleep(delay)
                
                # Cycle completed
                logger.info("="*60)
                logger.info(f"WORKER FINISHED CYCLE: account={phone}, cycle={cycle_number}")
                logger.info(f"   Commented channels: {commented_channels}")
                logger.info(f"   Total: {len(commented_channels)}")
                logger.info("="*60)
                
                # Break between cycles
                cycle_break = random.randint(30, 60)
                logger.info(f"[{account_name}] Break: {cycle_break}s")
                await asyncio.sleep(cycle_break)
        
        except Exception as outer_e:
            logger.error(f"[{account_name}] Fatal error: {outer_e}")
        finally:
            # Cleanup
            logger.info(f"[{account_name}] WORKER STOPPING")
            if worker_client and worker_client.is_connected():
                try:
                    await worker_client.disconnect()
                    logger.info(f"[{account_name}] Client disconnected")
                except Exception as e:
                    logger.error(f"[{account_name}] Disconnect error: {e}")

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
        if self.test_mode and self.test_channels:
            # ТЕСТОВЫЙ РЕЖИМ АКТИВЕН
            logger.info("="*80)
            logger.info("🧪 MODE: TEST")
            logger.info("="*80)
            logger.info(f"🎯 Test channels: {self.test_channels}")
            logger.info(f"📊 Total channels in system: {len(self.channels)}")
            logger.info("🔍 Filtering channels...")
            
            # Нормализуем test_channels (добавляем @ если нет)
            normalized_test_channels = []
            for tc in self.test_channels:
                if not tc.startswith('@'):
                    normalized_test_channels.append('@' + tc)
                else:
                    normalized_test_channels.append(tc)
            
            # В тестовом режиме используем ТОЛЬКО тестовые каналы
            channels_to_use = []
            for ch in self.channels:
                ch_username = ch.get('username') if isinstance(ch, dict) else ch
                # Normalize username
                if not ch_username.startswith('@'):
                    ch_username = '@' + ch_username
                
                # Сравниваем case-insensitive
                if ch_username.lower() in [tc.lower() for tc in normalized_test_channels]:
                    channels_to_use.append(ch)
                    logger.info(f"   ✅ TEST channel: {ch_username}")
            
            if not channels_to_use:
                logger.error("="*80)
                logger.error("🧪 ❌ ERROR: NO TEST CHANNELS FOUND!")
                logger.error(f"🔍 Looking for: {normalized_test_channels}")
                logger.error(f"📋 Available: {[ch.get('username') if isinstance(ch, dict) else ch for ch in self.channels[:10]]}")
                logger.error("💡 Use /addchannel to add test channels")
                logger.error("="*80)
                return
            
            logger.info(f"✅ Will use {len(channels_to_use)} TEST channels")
            logger.info("⚠️  ALL other channels are IGNORED in TEST MODE")
            logger.info("="*80)
        else:
            # БОЕВОЙ РЕЖИМ
            logger.info("="*80)
            logger.info("🚀 MODE: LIVE")
            logger.info("="*80)
            logger.info(f"📊 Using all {len(self.channels)} channels")
            logger.info("="*80)
            channels_to_use = self.channels
        # ============= END TEST MODE =============
        
        # Use configured max parallel accounts
        MAX_PARALLEL_ACCOUNTS = self.max_parallel_accounts
        
        logger.info("="*80)
        logger.info("⚙️  PARALLEL PROCESSING CONFIGURATION")
        logger.info("="*80)
        logger.info(f"📊 Total active accounts available: {len(active_accounts)}")
        logger.info(f"⚡ MAX_PARALLEL_ACCOUNTS setting: {MAX_PARALLEL_ACCOUNTS}")
        logger.info(f"🎯 Will create workers for: {min(len(active_accounts), MAX_PARALLEL_ACCOUNTS)} accounts")
        
        if len(active_accounts) == 1:
            logger.warning("⚠️⚠️⚠️ ONLY 1 ACTIVE ACCOUNT! ⚠️⚠️⚠️")
            logger.warning("⚠️ This means NO PARALLEL PROCESSING!")
            logger.warning("⚠️ To enable parallel work:")
            logger.warning("⚠️   1. Use /listaccounts to see all accounts")
            logger.warning("⚠️   2. Use /toggleaccount to activate more accounts")
            logger.warning("⚠️   3. Or add new accounts with /auth")
        elif MAX_PARALLEL_ACCOUNTS == 1:
            logger.warning("⚠️⚠️⚠️ MAX_PARALLEL_ACCOUNTS = 1 ⚠️⚠️⚠️")
            logger.warning("⚠️ Even though you have multiple active accounts,")
            logger.warning("⚠️ only 1 will work due to parallel limit!")
            logger.warning("⚠️ Use /setparallel <number> to increase (e.g., /setparallel 3)")
        
        logger.info("="*80)
        
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
        
        # ============= TEST MODE: Log info =============
        if self.test_mode:
            logger.info(f"🧪 TEST MODE: {num_accounts} accounts × {len(channels_copy)} TEST channels")
            logger.info(f"🧪 Test channels: {self.test_channels}")
            logger.info(f"🧪 Speed limit: {self.test_mode_speed_limit} msg/hour per account")
        else:
            logger.info(f"🚀 SMART MODE: {num_accounts} active accounts (max {MAX_PARALLEL_ACCOUNTS}) × {len(channels_copy)} channels")
        # ============= END TEST MODE =============
        
        # Логирование режима работы
        if self.worker_mode == 'distributed':
            channels_per_worker = len(channels_copy) // num_accounts
            logger.info(f"📊 Mode: DISTRIBUTED - each account gets ~{channels_per_worker} dedicated channels")
            logger.info(f"📊 Total: {num_accounts} accounts × ~{channels_per_worker} channels = {len(channels_copy)} total")
        else:
            logger.info(f"📊 Mode: CYCLIC - each account processes ALL {len(channels_copy)} channels with offset")
        
        logger.info(f"⚡ Rate limit: {self.messages_per_hour} msg/hour per account")
        logger.info(f"🔄 Max cycles per worker: {self.max_cycles_per_worker} (0=infinite)")
        logger.info(f"🛡️ Anti-spam: {MIN_INTERVAL_BETWEEN_OWN_ACCOUNTS}s between own accounts in same chat")
        
        # ============= NEW: Start rotation and health check tasks =============
        rotation_task = asyncio.create_task(self.rotation_worker())
        health_task = asyncio.create_task(self.health_check_worker())
        # ============= END NEW =============
        
        # Create worker tasks for each account
        tasks = []
        self.active_worker_tasks.clear()  # Очищаем старый список
        
        logger.info("="*80)
        logger.info(f"🚀 CREATING {len(accounts_list)} PARALLEL WORKERS")
        logger.info("="*80)
        
        if len(accounts_list) == 1:
            logger.warning("⚠️ WARNING: Only 1 worker will be created!")
            logger.warning("⚠️ Reason: Only 1 active account found or MAX_PARALLEL_ACCOUNTS=1")
            logger.warning("⚠️ Solution: Add more accounts with /auth and set to 'active' status")
            logger.warning("⚠️ Or increase limit with /setparallel")
        
        for i, (phone, data) in enumerate(accounts_list):
            # Give extra channels to first accounts if there's a remainder
            
            logger.info(f"🔧 Creating worker #{i+1}/{len(accounts_list)} for [{data.get('name', phone)}]")
            logger.info(f"   Phone: {phone}")
            logger.info(f"   Status: {data.get('status', 'unknown')}")
            logger.info(f"   Will process: ALL {len(channels_copy)} channels")
            logger.info(f"   Offset: starts from channel #{(i % len(channels_copy)) + 1}")
            
            # Create worker task for this account
            # Create worker task - каждый воркер получает ВСЕ каналы
            task = asyncio.create_task(
                self.account_worker(phone, data, channels_copy, i, len(accounts_list), mode=self.worker_mode)
            )
            tasks.append(task)
            self.active_worker_tasks.append(task)  # Отслеживаем для health check
            
        
        logger.info("="*80)
        logger.info(f"✅ ALL {len(tasks)} WORKERS CREATED AND LAUNCHED")
        logger.info("="*80)
        
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

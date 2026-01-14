import asyncio
import random
import json
import logging
import os
import sqlite3
import requests
from datetime import datetime
from pathlib import Path
from telethon import TelegramClient, events, functions, Button
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest
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

DB_NAME = 'bot_data.json'
SQLITE_DB = 'bot_advanced.db'
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        self.max_parallel_accounts = 2  # Default: 2 accounts work in parallel
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
        self.init_database()
        self.load_stats()
        self.load_data()
    
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
                    reason TEXT
                )
            ''')
            
            # Create comment_history table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS comment_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone TEXT,
                    channel TEXT,
                    comment TEXT,
                    date TEXT
                )
            ''')
            
            # Create parsed_channels table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS parsed_channels (
                    username TEXT PRIMARY KEY,
                    theme TEXT,
                    source TEXT DEFAULT 'parsed',
                    added_date TEXT
                )
            ''')
            
            # Create blocked_channels table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS blocked_channels (
                    username TEXT PRIMARY KEY,
                    block_date TEXT,
                    reason TEXT
                )
            ''')
            
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
    
    async def add_comment_stat(self, phone, success=True):
        self.stats['total_comments'] += 1
        if success:
            self.stats['daily_comments'] += 1
        else:
            self.stats['blocked_accounts'].append(phone)
        if len(self.stats['blocked_accounts']) > 50:
            self.stats['blocked_accounts'] = self.stats['blocked_accounts'][-20:]
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
            
            # Count active accounts
            active_accounts = [p for p, data in self.accounts_data.items() if data.get('active')]
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
        try:
            # Deactivate the banned account
            if phone in self.accounts_data:
                self.accounts_data[phone]['active'] = False
                account_name = self.accounts_data[phone].get('name', phone)
                logger.warning(f"🚫 Account {account_name} ({phone}) deactivated due to: {reason}")
                
                # Find and activate a reserve account (excluding the just-banned account)
                reserve_accounts = [(p, data) for p, data in self.accounts_data.items() 
                                  if not data.get('active', False) and data.get('session') and p != phone]
                
                if reserve_accounts:
                    # Activate the first available reserve account
                    reserve_phone, reserve_data = reserve_accounts[0]
                    self.accounts_data[reserve_phone]['active'] = True
                    reserve_name = reserve_data.get('name', reserve_phone)
                    logger.info(f"✅ Reserve account {reserve_name} ({reserve_phone}) automatically activated!")
                    
                    # Notify bot owner about the switch
                    try:
                        await self.bot_client.send_message(
                            BOT_OWNER_ID,
                            f"⚠️ **Автоматическая замена аккаунта**\n\n"
                            f"🚫 Заблокирован: `{account_name}` ({phone})\n"
                            f"Причина: {reason}\n\n"
                            f"✅ Активирован резервный: `{reserve_name}` ({reserve_phone})"
                        )
                    except Exception as notify_err:
                        logger.error(f"Failed to notify owner: {notify_err}")
                else:
                    logger.error(f"❌ No reserve accounts available to replace {account_name}!")
                    try:
                        await self.bot_client.send_message(
                            BOT_OWNER_ID,
                            f"🚨 **ВНИМАНИЕ: Нет резервных аккаунтов!**\n\n"
                            f"Заблокирован: `{account_name}` ({phone})\n"
                            f"Причина: {reason}\n\n"
                            f"❌ Все резервные аккаунты уже активны или отсутствуют."
                        )
                    except Exception as notify_err:
                        logger.error(f"Failed to notify owner: {notify_err}")
                
                self.save_data()
        except Exception as e:
            logger.error(f"Error handling account ban: {e}")
    
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
    
    async def is_admin(self, user_id):
        return user_id == BOT_OWNER_ID or user_id in self.admins
    
    async def authorize_account(self, phone, proxy=None):
        try:
            client = TelegramClient(StringSession(''), API_ID, API_HASH, proxy=proxy)
            await client.connect()
            if not await client.is_user_authorized():
                await client.send_code_request(phone)
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
            return {
                'session': session, 
                'active': True, 
                'name': me.first_name or 'Без имени',
                'username': getattr(me, 'username', None),
                'phone': phone,
                'proxy': proxy
            }
        except Exception as e:
            logger.error(f"Ошибка авторизации {phone}: {e}")
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
            
            # Parse proxy if exists (format: socks5:host:port:user:pass)
            proxy = None
            if proxy_str:
                try:
                    parts = proxy_str.split(':')
                    if len(parts) >= 5:
                        proxy = (parts[0], parts[1], int(parts[2]), parts[3], parts[4])
                except:
                    logger.warning(f"Failed to parse proxy for ACCOUNT_{n}")
            
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
                    account_data['bio'] = me.about or ''
                    account_data['username'] = me.username or ''
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
`/auth +79123456789 [proxy]` - авторизовать
`/accounts` - управление профилями (аватар, имя, био) 🆕
`/listaccounts` - все аккаунты
`/activeaccounts` - только активные ✅
`/reserveaccounts` - только резервные 🔄
`/blockedaccounts` - заблокированные 🚫
`/delaccount +79123456789` - удалить
`/toggleaccount +79123456789` - переключить активный/резерв

**⚙️ НАСТРОЙКИ:**
`/setparallel 2` - кол-во параллельных аккаунтов
`/getparallel` - текущие настройки

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
`/startmon` - ЗАПУСТИТЬ
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

**🔗 BIO:**
`/addbio t.me/link` - добавить
`/setbio` - применить всем

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
                    if len(proxy_parts) == 5:
                        proxy = (proxy_parts[0], proxy_parts[1], int(proxy_parts[2]), proxy_parts[3], proxy_parts[4])
                await event.respond(f"Авторизуем: `{phone}`\nПроверьте терминал!")
                result = await self.authorize_account(phone, proxy)
                if result:
                    self.accounts_data[phone] = result
                    self.save_data()
                    await event.respond(f"✅ **{result['name']}** авторизован!\n@{result.get('username', 'нет')}\n`{phone}` ✅ АКТИВЕН")
                else:
                    await event.respond("❌ Ошибка авторизации!")
            except Exception as e:
                await event.respond(f"❌ Ошибка: `{str(e)[:50]}`")
        
        @self.bot_client.on(events.NewMessage(pattern='/listaccounts'))
        async def list_accounts(event):
            if not await self.is_admin(event.sender_id): return
            if not self.accounts_data:
                await event.respond("Нет авторизованных аккаунтов")
                return
            
            # Show all accounts, split into multiple messages if needed
            total = len(self.accounts_data)
            accounts_per_msg = 20
            accounts_list = list(self.accounts_data.items())
            
            for batch_num in range(0, total, accounts_per_msg):
                batch_accounts = accounts_list[batch_num:batch_num + accounts_per_msg]
                text = f"АККАУНТЫ ({total}) - Часть {batch_num//accounts_per_msg + 1}:\n\n"
                
                for i, (phone, data) in enumerate(batch_accounts, batch_num + 1):
                    status = "✅" if data.get('active', False) else "❌"
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
                    current_status = self.accounts_data[phone].get('active', False)
                    self.accounts_data[phone]['active'] = not current_status
                    new_status = "✅ АКТИВЕН" if not current_status else "❌ РЕЗЕРВ"
                    account_name = self.accounts_data[phone].get('name', phone)
                    self.save_data()
                    await event.respond(f"Аккаунт `{account_name}` ({phone})\nСтатус изменен: {new_status}")
                else:
                    await event.respond("Аккаунт не найден")
            except:
                await event.respond("Формат: `/toggleaccount +79123456789`\n\n⚠️ Эта команда переключает статус ОДНОГО аккаунта:\n✅ АКТИВЕН → ❌ РЕЗЕРВ\n❌ РЕЗЕРВ → ✅ АКТИВЕН")
        
        @self.bot_client.on(events.NewMessage(pattern='/activeaccounts'))
        async def active_accounts(event):
            """Show only active accounts"""
            if not await self.is_admin(event.sender_id): return
            
            active = {phone: data for phone, data in self.accounts_data.items() if data.get('active', False)}
            
            if not active:
                await event.respond("❌ Нет активных аккаунтов")
                return
            
            text = f"✅ **АКТИВНЫЕ АККАУНТЫ** ({len(active)}):\n\n"
            for i, (phone, data) in enumerate(active.items(), 1):
                name = data.get('name', 'Не авторизован')
                username = data.get('username', 'нет')
                text += f"{i}. `{name}` (@{username})\n   `{phone}`\n"
            
            await event.respond(text)
        
        @self.bot_client.on(events.NewMessage(pattern='/reserveaccounts'))
        async def reserve_accounts(event):
            """Show only reserve accounts"""
            if not await self.is_admin(event.sender_id): return
            
            reserve = {phone: data for phone, data in self.accounts_data.items() 
                      if not data.get('active', False) and data.get('session')}
            
            if not reserve:
                await event.respond("❌ Нет резервных аккаунтов\n\n💡 Используйте `/toggleaccount +номер` чтобы перевести аккаунт в резерв")
                return
            
            text = f"🔄 **РЕЗЕРВНЫЕ АККАУНТЫ** ({len(reserve)}):\n\n"
            for i, (phone, data) in enumerate(reserve.items(), 1):
                name = data.get('name', 'Не авторизован')
                username = data.get('username', 'нет')
                text += f"{i}. `{name}` (@{username})\n   `{phone}`\n"
            
            text += "\n💡 Эти аккаунты автоматически активируются при бане активных"
            await event.respond(text)
        
        @self.bot_client.on(events.NewMessage(pattern='/blockedaccounts'))
        async def blocked_accounts_cmd(event):
            """Show blocked accounts with reasons from database"""
            if not await self.is_admin(event.sender_id): return
            
            if not self.conn:
                await event.respond("❌ БД недоступна")
                return
            
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
            
            active_count = sum(1 for d in self.accounts_data.values() if d.get('active'))
            actual_parallel = min(active_count, self.max_parallel_accounts)
            
            text = f"📊 **НАСТРОЙКИ ПАРАЛЛЕЛЬНОЙ РАБОТЫ:**\n\n"
            text += f"⚙️ Установлено: {self.max_parallel_accounts} аккаунтов\n"
            text += f"✅ Активных аккаунтов: {active_count}\n"
            text += f"🚀 Реально работает: {actual_parallel} аккаунтов\n\n"
            
            if actual_parallel < self.max_parallel_accounts:
                text += f"💡 Для использования {self.max_parallel_accounts} аккаунтов нужно иметь минимум {self.max_parallel_accounts} активных"
            
            await event.respond(text)
        
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
                    if data.get('active') and data.get('session'):
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
            
            active_count = sum(1 for data in self.accounts_data.values() if data.get('active', False))
            text = f"""🚀 АВТОКОММЕНТАРИИ ЗАПУЩЕНЫ (SAFE MODE)!\n\n✅ Активных аккаунтов: `{active_count}`\n⚡ Параллельно работают: `2` (безопасно)\n📢 Каналов: `{len(self.channels)}`\n💬 Шаблонов: `{len(self.templates)}`\n⏱️ Задержка: 50-100 сек между комментариями\n💤 Перерыв: 3-7 мин между циклами\n\n📈 Скорость: ~36-72 комм/час (оптимально)\n🛡️ Защита от бана: АКТИВНА"""
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
        
        @self.bot_client.on(events.NewMessage(pattern='/setbio'))
        async def set_bio(event):
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
            
            text = f"""📊 **СТАТИСТИКА БОТА:**

✅ Всего комментариев: `{self.stats['total_comments']}`
📈 Сегодня комментариев: `{self.stats['daily_comments']}`
"""
            
            # Get blocked accounts from DB
            if self.conn:
                try:
                    cursor = self.conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM blocked_accounts")
                    blocked_count = cursor.fetchone()[0]
                    text += f"🚫 Заблокировано аккаунтов: `{blocked_count}`\n"
                    
                    cursor.execute("SELECT COUNT(*) FROM blocked_channels")
                    blocked_channels_count = cursor.fetchone()[0]
                    text += f"🔇 Каналов без комментариев: `{blocked_channels_count}`\n\n"
                    
                    # Show recent blocks
                    cursor.execute(
                        "SELECT phone, block_date, reason FROM blocked_accounts ORDER BY block_date DESC LIMIT 5"
                    )
                    blocks = cursor.fetchall()
                    if blocks:
                        text += "**Последние блокировки:**\n"
                        for phone, date, reason in blocks:
                            text += f"  🚫 `{phone}` - {reason} ({date[:10]})\n"
                    
                    text += "\n**Последние комментарии:**\n"
                    cursor.execute(
                        "SELECT phone, channel, comment, date FROM comment_history ORDER BY id DESC LIMIT 5"
                    )
                    comments = cursor.fetchall()
                    if comments:
                        for phone, channel, comment, date in comments:
                            short_comment = comment[:30] if len(comment) > 30 else comment
                            text += f"  ✓ `@{channel}` | {short_comment}... ({date[:10]})\n"
                    else:
                        text += "  • Нет\n"
                except Exception as e:
                    logger.error(f"Stats DB error: {e}")
            
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
            if event.sender_id != BOT_OWNER_ID: return
            try:
                admin_id = int(event.text.split(maxsplit=1)[1])
                if admin_id not in self.admins:
                    self.admins.append(admin_id)
                    self.save_data()
                    await event.respond(f"Админ добавлен: `{admin_id}`")
                else:
                    await event.respond("Уже админ")
            except:
                await event.respond("Формат: `/addadmin 123456789`")
        
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
        logger.info(f"[{account_data.get('name', phone)}] Starting worker for {len(channel_subset)} channels")
        
        # Add initial random delay (warmup) to avoid all accounts starting simultaneously
        initial_delay = random.randint(5, 30)
        logger.info(f"[{account_data.get('name', phone)}] Initial warmup delay: {initial_delay}s")
        await asyncio.sleep(initial_delay)
        
        while self.monitoring:
            # Process each channel in the subset
            for channel in channel_subset:
                if not self.monitoring:
                    break
                
                # normalize channel entry
                if isinstance(channel, dict):
                    username = channel.get('username') or channel.get('name')
                else:
                    username = str(channel)
                username = str(username).strip()
                
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
                            await client.send_message(discussion_entity, comment, reply_to_msg_id=reply_id)
                            # Mark this post as commented
                            self.commented_posts[username].add(reply_id)
                        else:
                            await client.send_message(discussion_entity, comment)
                        
                        comment_success = True
                        logger.info(f"[{account_data.get('name', phone)}] ✅ @{username} (post {reply_id}): {comment}")
                        await self.add_comment_stat(phone, True)

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
                                    await client.send_message(discussion_entity, comment, reply_to_msg_id=reply_id)
                                    self.commented_posts[username].add(reply_id)
                                else:
                                    await client.send_message(discussion_entity, comment)
                                
                                comment_success = True
                                logger.info(f"[{account_data.get('name', phone)}] ✅ Joined & commented {username}")
                                await self.add_comment_stat(phone, True)
                                
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
        """Main commenting loop - now runs accounts in parallel with safety limits!"""
        active_accounts = {phone: data for phone, data in self.accounts_data.items()
                         if data.get('active') and data.get('session')}
        
        if not active_accounts:
            logger.error("No active accounts found!")
            return
        
        if not self.channels:
            logger.error("No channels found!")
            return
        
        # Use configured max parallel accounts (can be changed via /setparallel)
        MAX_PARALLEL_ACCOUNTS = self.max_parallel_accounts
        
        # Divide channels among accounts for parallel processing
        accounts_list = list(active_accounts.items())
        num_accounts = min(len(accounts_list), MAX_PARALLEL_ACCOUNTS)
        
        if len(accounts_list) > MAX_PARALLEL_ACCOUNTS:
            logger.warning(f"⚠️ You have {len(accounts_list)} accounts, but only {MAX_PARALLEL_ACCOUNTS} will work in parallel (configured)")
            logger.warning(f"⚠️ Other accounts will be used in rotation if active ones get banned")
        
        accounts_list = accounts_list[:MAX_PARALLEL_ACCOUNTS]  # Use first N accounts
        
        channels_copy = self.channels.copy()
        random.shuffle(channels_copy)
        
        # Calculate channels per account
        channels_per_account = len(channels_copy) // num_accounts
        remainder = len(channels_copy) % num_accounts
        
        logger.info(f"🚀 OPTIMAL MODE: {num_accounts} accounts (max {MAX_PARALLEL_ACCOUNTS}) × {len(channels_copy)} channels")
        logger.info(f"📊 Each account handles ~{channels_per_account} channels")
        logger.info(f"⏱️ Delays: 50-100s between comments, 3-7min between cycles")
        
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
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"Error in parallel workers: {e}")
    
    async def run(self):
        await self.start()
        await self.bot_client.run_until_disconnected()

if __name__ == '__main__':
    bot = UltimateCommentBot()
    asyncio.run(bot.run())

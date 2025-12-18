import asyncio
import random
import json
import logging
import os
import sqlite3
import re
from datetime import datetime
import time
from telethon import TelegramClient, events, functions
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest
from telethon.errors import SessionPasswordNeededError
from telethon.errors.rpcerrorlist import AuthKeyDuplicatedError

API_ID = 36053254
API_HASH = '4c63aee24cbc1be5e593329370712e7f'
BOT_TOKEN = '8233716877:AAFNvAaiHhzEg4HZkcLzMIGa05nIuRuJ8wE'
BOT_OWNER_ID = 6730216440

DB_NAME = 'bot_data.json'
SQLITE_DB = 'bot_advanced.db'
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class UltimateCommentBot:
    def __init__(self):
        self.bot_client = TelegramClient('bot_session', API_ID, API_HASH)
        self.accounts_data = {}
        self.channels = []
        self.templates = [
            'Отличный пост! 👍', 'Интересно! Спасибо!', 'Супер контент! 🔥',
            'Класс! 👌', 'Огонь! 🔥🔥', 'Согласен! 💯', 'Спасибо за контент! 🙌',
            'Супер! 👏', 'Круто! 💎', 'Лучший канал! 👑'
        ]
        self.bio_links = []
        self.admins = []
        self.monitoring = False
        self.stats = {
            'total_comments': 0,
            'blocked_accounts': [],
            'daily_comments': 0
        }
        self.conn = None
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
                # sanitize channels: accept strings or dicts, remove t.me links and leading @
                cleaned = []
                for ch in self.channels:
                    try:
                        if isinstance(ch, dict):
                            username = ch.get('username') or ch.get('name') or ''
                        else:
                            username = str(ch)
                        username = username.strip()
                        # remove full t.me URLs
                        username = re.sub(r'^https?://(www\.)?t\.me/', '', username)
                        username = username.lstrip('@')
                        if username:
                            cleaned.append({'username': username})
                    except Exception:
                        continue
                self.channels = cleaned
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
            client = TelegramClient(StringSession(session_data['session']), API_ID, API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                await client(UpdateProfileRequest(about=bio_text))
                await client.disconnect()
                return True
        except:
            pass
        return False
    
    async def start(self):
        try:
            await self.bot_client.start(bot_token=BOT_TOKEN)
        except AuthKeyDuplicatedError as e:
            logger.warning(f"AuthKeyDuplicatedError: {e} — removing local session files and retrying")
            # attempt to remove obvious local session files
            for fname in ('bot_session.session', 'bot_session.session-journal'):
                try:
                    if os.path.exists(fname):
                        os.remove(fname)
                        logger.info(f"Removed session file: {fname}")
                except Exception:
                    pass
            # create a new uniquely named session to avoid reusing an auth key
            new_session_name = f"bot_session_{int(time.time())}"
            try:
                logger.info(f"Creating new session: {new_session_name}")
                self.bot_client = TelegramClient(new_session_name, API_ID, API_HASH)
                await self.bot_client.start(bot_token=BOT_TOKEN)
            except Exception as e2:
                logger.error(f"Failed to start bot after creating new session: {e2}")
                raise

        self.setup_handlers()
        logger.info("@commentcom_bot ULTIMATE ЗАПУЩЕН!")
    
    def setup_handlers(self):
        @self.bot_client.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            text = f"""**@commentcom_bot ULTIMATE**
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
            text = """**📱 АККАУНТЫ:**
`/auth +79123456789 [proxy]` - авторизовать
`/listaccounts` - список
`/delaccount +79123456789` - удалить

**📢 КАНАЛЫ:**
`/addchannel @username` - добавить
`/listchannels` - список
`/delchannel @username` - удалить
`/searchchannels тема` - поиск по теме

**💬 КОММЕНТАРИИ:**
`/listtemplates` - шаблоны
`/addtemplate Текст!` - новый
`/edittemplate 1 Текст` - изменить
`/del-template 2` - удалить
`/cleartemplates` - очистить

**🤖 АВТО:**
`/startmon` - ЗАПУСТИТЬ
`/stopmon` - остановить

**📊 СТАТИСТИКА:**
`/stats` - подробная статистика
`/listparsed` - спарсенные каналы
`/listbans` - заблокированные аккаунты
`/history` - история комментариев

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
                    if len(proxy_parts) == 4:
                        proxy = (proxy_parts[0], int(proxy_parts[1]), proxy_parts[2], proxy_parts[3])
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
            text = f"АККАУНТЫ ({len(self.accounts_data)})\n\n"
            for i, (phone, data) in enumerate(list(self.accounts_data.items())[:10], 1):
                status = "✅" if data.get('active', False) else "❌"
                name = data.get('name', 'Не авторизован')
                username = data.get('username', 'нет')
                text += f"{i}. {status} `{name}` (@{username})\n`   {phone}`\n"
            await event.respond(text)
        
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
        
        @self.bot_client.on(events.NewMessage(pattern='/addchannel'))
        async def add_channel(event):
            if not await self.is_admin(event.sender_id): return
            try:
                username = event.text.split(maxsplit=1)[1].replace('@', '')
                if username not in [ch['username'] for ch in self.channels]:
                    self.channels.append({'username': username})
                    self.save_data()
                    await event.respond(f"Канал `@{username}` добавлен")
                else:
                    await event.respond("Уже добавлен")
            except:
                await event.respond("Формат: `/addchannel @username`")
        
        @self.bot_client.on(events.NewMessage(pattern='/searchchannels (.+)'))
        async def search_channels(event):
            if not await self.is_admin(event.sender_id): return
            try:
                query = event.pattern_match.group(1).strip()
                await event.respond(f"🔍 Ищу каналы по '{query}'...")
                
                try:
                    result = await self.bot_client(functions.contacts.SearchRequest(q=query, limit=50))
                    channels = []
                    for chat in result.chats:
                        if hasattr(chat, 'username') and chat.username:
                            channels.append(f"@{chat.username}")
                    
                    if channels:
                        msg = f"✅ Найдено {len(channels)} каналов по '{query}':\n\n"
                        for i, ch in enumerate(channels[:10], 1):
                            msg += f"{i}. {ch}\n"
                        
                        if len(channels) > 10:
                            msg += f"\n... и еще {len(channels)-10}"
                        
                        await event.respond(msg)
                        
                        # Auto-add TOP-5 to parsed_channels
                        if self.conn:
                            cursor = self.conn.cursor()
                            for ch in channels[:5]:
                                try:
                                    cursor.execute(
                                        "INSERT OR IGNORE INTO parsed_channels (username, theme, source, added_date) VALUES (?, ?, ?, ?)",
                                        (ch.replace('@', ''), query, 'parsed', datetime.now().isoformat())
                                    )
                                except Exception as e:
                                    logger.error(f"DB insert error: {e}")
                            self.conn.commit()
                            await event.respond(f"✅ Добавлено {min(5, len(channels))} каналов в БД")
                    else:
                        await event.respond("❌ Каналы не найдены")
                except Exception as e:
                    logger.error(f"Search error: {e}")
                    await event.respond(f"❌ Ошибка поиска: {str(e)[:100]}")
            except:
                await event.respond("Формат: `/searchchannels новости`")
        
        @self.bot_client.on(events.NewMessage(pattern='/listchannels'))
        async def list_channels(event):
            if not await self.is_admin(event.sender_id): return
            if not self.channels:
                await event.respond("Нет каналов")
                return
            text = f"КАНАЛЫ ({len(self.channels)})\n\n"
            for i, ch in enumerate(self.channels[:15], 1):
                text += f"{i}. `@{ch['username']}`\n"
            await event.respond(text)
        
        @self.bot_client.on(events.NewMessage(pattern='/delchannel'))
        async def del_channel(event):
            if not await self.is_admin(event.sender_id): return
            try:
                username = event.text.split(maxsplit=1)[1].replace('@', '')
                self.channels = [ch for ch in self.channels if ch['username'] != username]
                self.save_data()
                await event.respond(f"Удален: `@{username}`")
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
            text = f"""АВТОКОММЕНТАРИИ ЗАПУЩЕНЫ!\n\nАктивных: `{sum(1 for data in self.accounts_data.values() if data.get('active', False))}`\nКаналов: `{len(self.channels)}`\nШаблонов: `{len(self.templates)}`"""
            await event.respond(text)
            asyncio.create_task(self.pro_auto_comment())
        
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
                    text += f"🚫 Заблокировано аккаунтов: `{blocked_count}`\n\n"
                    
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
                cursor.execute("SELECT username, theme FROM parsed_channels ORDER BY added_date DESC LIMIT 20")
                parsed = cursor.fetchall()
                
                if parsed:
                    text = f"📋 **СПАРСЕННЫЕ КАНАЛЫ** ({len(parsed)}):\n\n"
                    for username, theme in parsed:
                        text += f"  @{username} ({theme})\n"
                    await event.respond(text)
                else:
                    await event.respond("❌ Нет спарсенных каналов. Используйте /searchchannels")
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
                cursor.execute("SELECT phone, block_date, reason FROM blocked_accounts ORDER BY block_date DESC LIMIT 20")
                bans = cursor.fetchall()
                
                if bans:
                    text = f"🚫 **ЗАБЛОКИРОВАННЫЕ АККАУНТЫ** ({len(bans)}):\n\n"
                    for phone, date, reason in bans:
                        text += f"  `{phone}` | {reason}\n     {date[:19]}\n\n"
                    await event.respond(text)
                else:
                    await event.respond("✅ Нет заблокированных аккаунтов")
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
                cursor.execute(
                    "SELECT phone, channel, comment, date FROM comment_history ORDER BY id DESC LIMIT 20"
                )
                history = cursor.fetchall()
                
                if history:
                    text = f"📝 **ИСТОРИЯ КОММЕНТАРИЕВ** ({len(history)}):\n\n"
                    for phone, channel, comment, date in history:
                        short_comment = comment[:40] if len(comment) > 40 else comment
                        text += f"  `{phone[:12]}...` → @{channel}\n     \"{short_comment}\"\n     {date[:19]}\n\n"
                    await event.respond(text)
                else:
                    await event.respond("❌ История пуста")
            except Exception as e:
                logger.error(f"History error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:50]}")
        
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
    
    async def pro_auto_comment(self):
        while self.monitoring:
            active_accounts = {phone: data for phone, data in self.accounts_data.items() 
                             if data.get('active') and data.get('session')}
            if not active_accounts or not self.channels:
                await asyncio.sleep(60)
                continue
            phone_data = random.choice(list(active_accounts.items()))
            phone, data = phone_data
            channel = random.choice(self.channels)
            comment = random.choice(self.templates)

            # Normalize channel format (dict or string)
            try:
                    if isinstance(channel, dict):
                        username = channel.get('username') or channel.get('name')
                    else:
                        username = channel
                    if not username:
                        logger.error(f"Invalid channel entry: {channel}")
                        await asyncio.sleep(5)
                        continue
                    username = str(username).strip()
                    username = re.sub(r'^https?://(www\.)?t\.me/', '', username)
                    username = username.lstrip('@')

                    client = TelegramClient(StringSession(data['session']), API_ID, API_HASH)
                    await client.connect()
                    try:
                        if not await client.is_user_authorized():
                            logger.warning(f"Account not authorized: {phone}")
                            await client.disconnect()
                            await asyncio.sleep(5)
                            continue

                        # Resolve entity first (safer than passing a string URL)
                        try:
                            entity = await client.get_entity(username)
                        except Exception:
                            # try with @username
                            try:
                                entity = await client.get_entity('@' + username)
                            except Exception as e_res:
                                logger.error(f"Cannot resolve entity for {username}: {e_res}")
                                raise

                        # Fetch latest message id to reply to (comment) if possible
                        try:
                            msgs = await client.get_messages(entity, limit=1)
                            reply_id = msgs[0].id if msgs and len(msgs) > 0 else None
                        except Exception:
                            reply_id = None

                        try:
                            if reply_id:
                                await client.send_message(entity, comment, reply_to=reply_id)
                            else:
                                await client.send_message(entity, comment)
                            logger.info(f"[{data.get('name', phone)}] -> @{username}: {comment}")
                        except Exception as send_exc:
                            err_text = str(send_exc)
                            logger.error(f"Send error for @{username}: {err_text}")
                            if "You can't write in this chat" in err_text:
                                try:
                                    # remove channel from in-memory list and save
                                    self.channels = [ch for ch in self.channels if (ch.get('username') if isinstance(ch, dict) else str(ch).lstrip('@')) != username]
                                    self.save_data()
                                    logger.info(f"Removed unwritable channel: {username}")
                                except Exception as rem_e:
                                    logger.error(f"Failed removing unwritable channel {username}: {rem_e}")
                            raise
                    finally:
                        try:
                            await client.disconnect()
                        except Exception:
                            pass
                    await self.add_comment_stat(phone, True)

                    # Log successful comment to DB
                    if self.conn:
                        try:
                            cursor = self.conn.cursor()
                            cursor.execute(
                                "INSERT INTO comment_history (phone, channel, comment, date) VALUES (?, ?, ?, ?)",
                                (phone, username, comment, datetime.now().isoformat())
                            )
                            self.conn.commit()
                        except Exception as db_err:
                            logger.error(f"DB log error: {db_err}")
                finally:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"Ошибка при комментировании [{phone}] -> {channel}: {e}")
                try:
                    await self.add_comment_stat(phone, False)
                    # Log block to DB (check phrases properly)
                    if self.conn and ("FloodWait" in str(e) or "banned" in str(e).lower()):
                        try:
                            cursor = self.conn.cursor()
                            reason = "FloodWait" if "FloodWait" in str(e) else "Account Ban"
                            cursor.execute(
                                "INSERT OR IGNORE INTO blocked_accounts (phone, block_date, reason) VALUES (?, ?, ?)",
                                (phone, datetime.now().isoformat(), reason)
                            )
                            self.conn.commit()
                            logger.info(f"Blocked account logged: {phone}")
                        except Exception as db_err:
                            logger.error(f"DB block log error: {db_err}")
                except Exception:
                    pass
            await asyncio.sleep(random.randint(120, 300))
    
    async def run(self):
        await self.start()
        await self.bot_client.run_until_disconnected()

if __name__ == '__main__':
    bot = UltimateCommentBot()
    asyncio.run(bot.run())

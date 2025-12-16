import asyncio
import random
import json
import logging
import os
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest
from telethon.errors import SessionPasswordNeededError

# 🔥 ВАШИ ДАННЫЕ (ТОЧНО ВАШИ!)
API_ID = 36053254
API_HASH = '4c63aee24cbc1be5e593329370712e7f'
BOT_TOKEN = '8233716877:AAFNvAaiHhzEg4HZkcLzMIGa05nIuRuJ8wE'
BOT_OWNER_ID = 6730216440

DB_NAME = 'bot_data.json'
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
            'Супер! 👏', 'Круто! 💎', 'Лучший канал! 👑', 'Топ! 🚀',
            'Согласен на 100%! 💪', 'Качество контента огонь! 🔥',
            'Подписан и рекомендую! ✅', 'Всегда интересно читать! 📖'
        ]
        self.bio_links = []
        self.admins = []
        self.monitoring = False
        self.load_data()
    
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
    
    async def is_admin(self, user_id):
        return user_id == BOT_OWNER_ID or user_id in self.admins
    
    async def authorize_account(self, phone, proxy=None):
        """Полная авторизация аккаунта"""
        try:
            client = TelegramClient(StringSession(''), API_ID, API_HASH, proxy=proxy)
            await client.connect()
            
            if not await client.is_user_authorized():
                await client.send_code_request(phone)
                print(f"📱 Код отправлен на {phone}")
                code = input("🔑 Введите код из Telegram: ")
                try:
                    await client.sign_in(phone, code)
                except SessionPasswordNeededError:
                    password = input("🔐 Введите пароль 2FA: ")
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
        """Установить BIO аккаунту"""
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
    
    async def set_account_avatar(self, session_data, photo_path):
        """Установить аватарку аккаунту"""
        try:
            if not os.path.exists(photo_path):
                return False
            client = TelegramClient(StringSession(session_data['session']), API_ID, API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                await client(UploadProfilePhotoRequest(open(photo_path, 'rb')))
                await client.disconnect()
                return True
        except:
            pass
        return False
    
    async def start(self):
        await self.bot_client.start(bot_token=BOT_TOKEN)
        self.setup_handlers()
        logger.info("🚀 @commentcom_bot ULTIMATE ЗАПУЩЕН!")
    
    def setup_handlers(self):
        @self.bot_client.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            await event.respond(
                "🎉 **@commentcom_bot ULTIMATE v2.0**

"
                f"👑 **Владелец:** `{BOT_OWNER_ID}`
"
                f"👥 **Админов:** `{len(self.admins)}`

"
                f"📱 **Аккаунтов:** `{len(self.accounts_data)}`
"
                f"📢 **Каналов:** `{len(self.channels)}`
"
                f"💬 **Шаблонов:** `{len(self.templates)}`

"
                f"**/help** - 👉 все команды с инструкциями"
            )
        
        @self.bot_client.on(events.NewMessage(pattern='/help'))
        async def help_handler(event):
            help_text = (
                "**📱 АККАУНТЫ (только админы):**
"
                "`/auth +79123456789 [ip:port:user:pass]` - 🚀 авторизовать аккаунт
"
                "`/listaccounts` - 📋 список аккаунтов
"
                "`/delaccount +79123456789` - 🗑️ удалить аккаунт

"
                
                "**📢 КАНАЛЫ (только админы):**
"
                "`/addchannel @username` - ➕ добавить канал
"
                "`/listchannels` - 📋 список каналов
"
                "`/delchannel @username` - 🗑️ удалить канал

"
                
                "**💬 КОММЕНТАРИИ (только админы):**
"
                "`/listtemplates` - 📋 все шаблоны
"
                "`/addtemplate Текст!` - ➕ новый шаблон
"
                "`/edittemplate 1 Новый текст` - ✏️ изменить
"
                "`/del-template 2` - 🗑️ удалить №2
"
                "`/cleartemplates` - 🗑️ очистить все

"
                
                "**🤖 АВТОКОММЕНТАРИИ (только админы):**
"
                "`/startmon` - ▶️ ★ ЗАПУСТИТЬ ★
"
                "`/stopmon` - ⏹️ остановить

"
                
                "**🔗 BIO (только админы):**
"
                "`/addbio t.me/link` - ➕ ссылка в био
"
                "`/setbio` - 🎯 применить ко всем

"
                
                "**📸 АВАТАРКИ (только админы):**
"
                "`/setavatar +79123456789` - 📸 сменить аватарку

"
                
                "**👑 АДМИНЫ (только владелец):**
"
                "`/addadmin 123456789` - 👑 новый админ
"
                "`/listadmins` - 📋 список админов"
            )
            await event.respond(help_text, parse_mode='md')
        
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
                
                await event.respond(
                    f"🔄 **Авторизуем:** `{phone}`
"
                    f"🌐 {'✅ с прокси' if proxy else '❌ без прокси'}

"
                    f"📱 **Проверьте терминал Codespaces!**"
                )
                
                result = await self.authorize_account(phone, proxy)
                if result:
                    self.accounts_data[phone] = result
                    self.save_data()
                    await event.respond(
                        f"✅ **{result['name']}** авторизован!
"
                        f"👤 `@{result.get('username', 'нет')}`
"
                        f"📱 `{phone}` ✅ АКТИВЕН"
                    )
                else:
                    await event.respond("❌ **Ошибка авторизации! Проверьте телефон/код**")
            except Exception as e:
                await event.respond(f"❌ **Ошибка:** `{str(e)[:50]}`")
        
        @self.bot_client.on(events.NewMessage(pattern='/listaccounts'))
        async def list_accounts(event):
            if not await self.is_admin(event.sender_id): return
            if not self.accounts_data:
                await event.respond("📭 **Нет авторизованных аккаунтов**")
                return
            text = f"📱 **АККАУНТЫ ({len(self.accounts_data)}):**

"
            for i, (phone, data) in enumerate(list(self.accounts_data.items())[:10], 1):
                status = "✅" if data.get('active', False) else "❌"
                name = data.get('name', 'Не авторизован')
                username = data.get('username', 'нет')
                proxy = "🔒" if data.get('proxy') else ""
                text += f"{i}. {status} `{name}` (@{username}) {proxy}
`   {phone}`
"
            await event.respond(text)
        
        @self.bot_client.on(events.NewMessage(pattern='/delaccount'))
        async def del_account(event):
            if not await self.is_admin(event.sender_id): return
            try:
                phone = event.text.split(maxsplit=1)[1]
                if phone in self.accounts_data:
                    del self.accounts_data[phone]
                    self.save_data()
                    await event.respond(f"🗑️ **Удален:** `{phone}`")
                else:
                    await event.respond("❌ **Аккаунт не найден**")
            except:
                await event.respond("❌ **Формат:** `/delaccount +79123456789`")
        
        @self.bot_client.on(events.NewMessage(pattern='/addchannel'))
        async def add_channel(event):
            if not await self.is_admin(event.sender_id): return
            try:
                username = event.text.split(maxsplit=1)[1].replace('@', '')
                if username not in [ch['username'] for ch in self.channels]:
                    self.channels.append({'username': username})
                    self.save_data()
                    await event.respond(f"✅ **Канал:** `@{username}` **добавлен**")
                else:
                    await event.respond("ℹ️ **Уже добавлен**")
            except:
                await event.respond("❌ **Формат:** `/addchannel @username`")
        
        @self.bot_client.on(events.NewMessage(pattern='/listchannels'))
        async def list_channels(event):
            if not await self.is_admin(event.sender_id): return
            if not self.channels:
                await event.respond("📢 **Нет каналов**")
                return
            text = f"📢 **КАНАЛЫ ({len(self.channels)}):**

"
            for i, ch in enumerate(self.channels[:15], 1):
                text += f"{i}. `@{ch['username']}`
"
            await event.respond(text)
        
        @self.bot_client.on(events.NewMessage(pattern='/delchannel'))
        async def del_channel(event):
            if not await self.is_admin(event.sender_id): return
            try:
                username = event.text.split(maxsplit=1)[1].replace('@', '')
                self.channels = [ch for ch in self.channels if ch['username'] != username]
                self.save_data()
                await event.respond(f"🗑️ **Удален:** `@{username}`")
            except:
                await event.respond("❌ **Формат:** `/delchannel @username`")
        
        @self.bot_client.on(events.NewMessage(pattern='/listtemplates'))
        async def list_templates(event):
            if not await self.is_admin(event.sender_id): return
            if not self.templates:
                await event.respond("💬 **Нет шаблонов**")
                return
            text = f"💬 **Шаблоны ({len(self.templates)}):**

"
            for i, template in enumerate(self.templates, 1):
                text += f"{i}. `{template}`
"
            text += f"
**/addtemplate текст** - ➕
**/edittemplate 1 текст** - ✏️"
            await event.respond(text)
        
        @self.bot_client.on(events.NewMessage(pattern='/addtemplate'))
        async def add_template(event):
            if not await self.is_admin(event.sender_id): return
            try:
                new_template = event.text.replace('/addtemplate ', '').strip()
                if new_template and new_template not in self.templates:
                    self.templates.append(new_template)
                    self.save_data()
                    await event.respond(f"✅ **Добавлен:** `{new_template}`")
                else:
                    await event.respond("❌ **Уже есть или пусто!**")
            except:
                await event.respond("❌ **Формат:** `/addtemplate Крутой пост! 🔥`")
        
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
                    await event.respond(f"✏️ **#{num+1}:**
`{old}` → `{new_text}`")
                else:
                    await event.respond("❌ **Неверный номер!**")
            except:
                await event.respond("❌ **Формат:** `/edittemplate 1 Новый текст!`")
        
        @self.bot_client.on(events.NewMessage(pattern='/del-template'))
        async def del_template(event):
            if not await self.is_admin(event.sender_id): return
            try:
                num = int(event.text.split()[1]) - 1
                if 0 <= num < len(self.templates):
                    deleted = self.templates.pop(num)
                    self.save_data()
                    await event.respond(f"🗑️ **Удален:** `{deleted}`")
                else:
                    await event.respond("❌ **Неверный номер!**")
            except:
                await event.respond("❌ **Формат:** `/del-template 1`")
        
        @self.bot_client.on(events.NewMessage(pattern='/cleartemplates'))
        async def clear_templates(event):
            if not await self.is_admin(event.sender_id): return
            self.templates.clear()
            self.save_data()
            await event.respond("🗑️ **Все шаблоны очищены!**")
        
        @self.bot_client.on(events.NewMessage(pattern='/startmon'))
        async def start_monitor(event):
            if not await self.is_admin(event.sender_id): return
            if self.monitoring:
                await event.respond("⏳ **Уже запущен!**")
                return
            if not self.accounts_data or not any(data.get('active', False) for data in self.accounts_data.values()):
                await event.respond("❌ **Сначала авторизуйте аккаунты! /auth**")
                return
            self.monitoring = True
            await event.respond(
                f"🚀 **АВТОКОММЕНТАРИИ ЗАПУЩЕНЫ!**

"
                f"📱 **Активных:** `{sum(1 for data in self.accounts_data.values() if data.get('active', False))}`
"
                f"📢 **Каналов:** `{len(self.channels)}`
"
                f"💬 **Шаблонов:** `{len(self.templates)}`"
            )
            asyncio.create_task(self.pro_auto_comment())
        
        @self.bot_client.on(events.NewMessage(pattern='/stopmon'))
        async def stop_monitor(event):
            if not await self.is_admin(event.sender_id): return
            self.monitoring = False
            await event.respond("⏹️ **Автокомментарии остановлены**")
        
        @self.bot_client.on(events.NewMessage(pattern='/addbio'))
        async def add_bio(event):
            if not await self.is_admin(event.sender_id): return
            try:
                link = event.text.split(maxsplit=1)[1]
                if 't.me' in link and link not in self.bio_links:
                    self.bio_links.append(link)
                    self.save_data()
                    await event.respond(f"🔗 **BIO добавлен:** `{link}`")
                else:
                    await event.respond("❌ **Новая ссылка t.me!**")
            except:
                await event.respond("❌ **Формат:** `/addbio https://t.me/channel`")
        
        @self.bot_client.on(events.NewMessage(pattern='/setbio'))
        async def set_bio(event):
            if not await self.is_admin(event.sender_id): return
            if not self.bio_links:
                await event.respond("🔗 **Сначала `/addbio`!**")
                return
            bio_text = " | ".join(self.bio_links[:4])
            updated = 0
            for phone, data in self.accounts_data.items():
                if data.get('active') and data.get('session'):
                    if await self.set_account_bio(data, bio_text):
                        updated += 1
            await event.respond(f"✅ **BIO обновлен:** `{bio_text}`
📊 **{updated} аккаунтов**")
        
        @self.bot_client.on(events.NewMessage(pattern='/setavatar'))
        async def set_avatar(event):
            if not await self.is_admin(event.sender_id): return
            try:
                phone = event.text.split(maxsplit=1)[1]
                await event.respond(
                    f"📸 **Смена аватарки:** `{phone}`

"
                    f"📤 **Загрузите фото в чат прямо сейчас!**"
                )
            except:
                await event.respond("❌ **Формат:** `/setavatar +79123456789`")
        
        @self.bot_client.on(events.NewMessage(pattern='/addadmin'))
        async def add_admin(event):
            if event.sender_id != BOT_OWNER_ID: return
            try:
                admin_id = int(event.text.split(maxsplit=1)[1])
                if admin_id not in self.admins:
                    self.admins.append(admin_id)
                    self.save_data()
                    await event.respond(f"👑 **Админ добавлен:** `{admin_id}`")
                else:
                    await event.respond("ℹ️ **Уже админ**")
            except:
                await event.respond("❌ **Формат:** `/addadmin 123456789`")
        
        @self.bot_client.on(events.NewMessage(pattern='/listadmins'))
        async def list_admins(event):
            if not await self.is_admin(event.sender_id): return
            if not self.admins:
                await event.respond("👥 **Нет админов** (только владелец)")
                return
            text = "👥 **Админы:**

"
            for admin_id in self.admins:
                text += f"`{admin_id}`
"
            await event.respond(text)
    
    async def pro_auto_comment(self):
        """ПРОФЕССИОНАЛЬНЫЙ автокомментарий"""
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
            
            try:
                client = TelegramClient(StringSession(data['session']), API_ID, API_HASH)
                await client.connect()
                if await client.is_user_authorized():
                    await client.send_message(channel['username'], comment)
                    logger.info(f"✅ [{data.get('name', phone)}] → @{channel['username']}: {comment}")
                await client.disconnect()
            except Exception as e:
                logger.error(f"Ошибка [{phone}]: {e}")
                if phone in self.accounts_data:
                    self.accounts_data[phone]['active'] = False
                    self.save_data()
            
            await asyncio.sleep(random.randint(120, 300))  # 2-5 мин
    
    async def run(self):
        await self.start()
        await self.bot_client.run_until_disconnected()

if __name__ == '__main__':
    bot = UltimateCommentBot()
    asyncio.run(bot.run())

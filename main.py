def load_data(self):
    try:
        with open(DB_NAME, 'r') as f:
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
    with open(DB_NAME, 'w') as f:
        json.dump(data, f, indent=2)

async def is_admin(self, user_id):
    return user_id == BOT_OWNER_ID or user_id in self.admins

async def authorize_account(self, phone, proxy=None):
    """Полная авторизация аккаунта"""
    try:
        client = TelegramClient(StringSession(''), API_ID, API_HASH, proxy=proxy)
        await client.connect()
        
        if not await client.is_user_authorized():
            await client.send_code_request(phone)
            logger.info(f"Код отправлен на {phone}")
            # В реальности код вводится вручную в логах
            code = input(f"Введите код для {phone}: ")  # В Codespaces
            try:
                await client.sign_in(phone, code)
            except SessionPasswordNeededError:
                password = input("Введите пароль 2FA: ")
                await client.sign_in(password=password)
        
        me = await client.get_me()
        session = client.session.save()
        await client.disconnect()
        
        return {'session': session, 'active': True, 'name': me.first_name, 'username': me.username}
    except Exception as e:
        logger.error(f"Ошибка авторизации {phone}: {e}")
        return None

async def start(self):
    await self.bot_client.start(bot_token=BOT_TOKEN)
    self.setup_handlers()
    logger.info("🚀 @commentcom_bot PRO ЗАПУЩЕН!")

def setup_handlers(self):
    @self.bot_client.on(events.NewMessage(pattern='/start'))
    async def start_handler(event):
        await event.respond(
            "🎉 **@commentcom_bot PRO**

"
            f"👑 Владелец: `{BOT_OWNER_ID}` | 👥 Админов: `{len(self.admins)}`
"
            f"📱 Аккаунтов: `{len(self.accounts_data)}` | 📢 Каналов: `{len(self.channels)}`

"
            "**🚀 /help** - все команды"
        )
    
    @self.bot_client.on(events.NewMessage(pattern='/help'))
    async def help_handler(event):
        await event.respond(
            "**🔥 ПРО-ФУНКЦИИ:**

"
            "**📱 Аккаунты:**
"
            "`/auth +79123456789 [proxy:port:user:pass]`
"
            "`/listaccounts` `/delaccount +79...`

"
            "**📢 Каналы:**
"
            "`/addchannel @username` `/listchannels`

"
            "**🤖 Автокомментарии:**
"
            "`/startmon` `/stopmon`

"
            "**🔗 BIO:**
"
            "`/addbio t.me/link` `/setbio`

"
            "**👑 Админы:**
"
            "`/addadmin 123456` `/listadmins`"
        )
    
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
            
            await event.respond(f"🔄 **Авторизуем:** `{phone}` {'+proxy' if proxy else ''}
📱 Проверьте логи!")
            
            result = await self.authorize_account(phone, proxy)
            if result:
                self.accounts_data[phone] = result
                self.save_data()
                await event.respond(
                    f"✅ **{result['name']}** авторизован!
"
                    f"👤 @{result.get('username', 'нет')}
"
                    f"📱 `{phone}`"
                )
            else:
                await event.respond("❌ **Ошибка авторизации**")
        except Exception as e:
            await event.respond(f"❌ **Ошибка:** `{str(e)[:50]}`")
    
    @self.bot_client.on(events.NewMessage(pattern='/listaccounts'))
    async def list_accounts(event):
        if not await self.is_admin(event.sender_id): return
        if not self.accounts_data:
            await event.respond("📭 **Нет аккаунтов**")
            return
        text = f"📱 **АККАУНТЫ ({len(self.accounts_data)}):**

"
        for i, (phone, data) in enumerate(list(self.accounts_data.items())[:10], 1):
            status = "✅" if data['active'] else "❌"
            name = data.get('name', 'Не авторизован')
            text += f"{i}. {status} `{name}` (@{data.get('username', 'none')})
"
        await event.respond(text)
    
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
    
    @self.bot_client.on(events.NewMessage(pattern='/startmon'))
    async def start_monitor(event):
        if not await self.is_admin(event.sender_id): return
        if self.monitoring:
            await event.respond("⏳ **Уже запущен!**")
            return
        if not self.accounts_data or not any(data['active'] for data in self.accounts_data.values()):
            await event.respond("❌ **Сначала авторизуйте аккаунты! /auth**")
            return
        self.monitoring = True
        await event.respond(
            f"🚀 **АВТОКОММЕНТАРИИ ЗАПУЩЕНЫ!**

"
            f"📱 Активных: `{sum(1 for data in self.accounts_data.values() if data['active'])}`
"
            f"📢 Каналов: `{len(self.channels)}`"
        )
        asyncio.create_task(self.pro_auto_comment())
    
    @self.bot_client.on(events.NewMessage(pattern='/stopmon'))
    async def stop_monitor(event):
        if not await self.is_admin(event.sender_id): return
        self.monitoring = False
        await event.respond("⏹️ **Автокомментарии остановлены**")
    
    @self.bot_client.on(events.NewMessage(pattern='/addadmin'))
    async def add_admin(event):
        if event.sender_id != BOT_OWNER_ID: return
        try:
            admin_id = int(event.text.split(maxsplit=1)[1])
            if admin_id not in self.admins:
                self.admins.append(admin_id)
                self.save_data()
                await event.respond(f"👑 **Админ:** `{admin_id}` **добавлен**")
            else:
                await event.respond("ℹ️ **Уже админ**")
        except:
            await event.respond("❌ **Формат:** `/addadmin 123456789`")
    
    @self.bot_client.on(events.NewMessage(pattern='/addbio'))
    async def add_bio(event):
        if not await self.is_admin(event.sender_id): return
        try:
            link = event.text.split(maxsplit=1)[1]
            if 't.me' in link and link not in self.bio_links:
                self.bio_links.append(link)
                self.save_data()
                await event.respond(f"🔗 **BIO:** `{link}` **добавлен**")
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
                try:
                    client = TelegramClient(StringSession(data['session']), API_ID, API_HASH)
                    await client.connect()
                    if await client.is_user_authorized():
                        await client(UpdateProfileRequest(about=bio_text))
                        updated += 1
                    await client.disconnect()
                except:
                    pass
        await event.respond(f"✅ **BIO обновлен:** `{bio_text}`
📊 **{updated} аккаунтов**")

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
                await event.respond(f"💬 **Комментарий!** `{data.get('name', phone)}` → @{channel['username']}")
            await client.disconnect()
        except Exception as e:
            logger.error(f"Ошибка [{phone}]: {e}")
        
        await asyncio.sleep(random.randint(120, 300))  # 2-5 мин

async def run(self):
    await self.start()
    await self.bot_client.run_until_disconnected()

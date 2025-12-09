API_ID = 36053254
API_HASH = '4c63aee24cbc1be5e593329370712e7f'  
PHONE = '+79299230050'

import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

# ВАШИ ДАННЫЕ (уже правильные!)
API_ID = 36053254
API_HASH = '4c63aee24cbc1be5e593329370712e7f'  
PHONE = '+79299230050'

client = TelegramClient(StringSession(''), API_ID, API_HASH)

async def main():
    await client.start(phone=PHONE)
    print("✅ Бот подключился!")
    me = await client.get_me()
    print(f"👤 Ваш ID: {me.id}")
    print("🔄 Бот работает... (Ctrl+C для выхода)")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())

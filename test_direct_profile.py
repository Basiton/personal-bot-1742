#!/usr/bin/env python3
"""
Прямой тест UpdateProfileRequest
Проверяет работает ли вообще изменение профиля через Telethon
"""

import asyncio
import json
import os
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest

# Hardcoded как в main.py
API_ID = 36053254
API_HASH = "ecd80be4cc92e9cd87e73da31bdedadd"

async def test_profile_update():
    print("🔍 Тест UpdateProfileRequest")
    print("="*60)
    
    # Загружаем аккаунты
    with open('bot_data.json', 'r') as f:
        bot_data = json.load(f)
        accounts_dict = bot_data.get('accounts', {})
    
    # Берем первый аккаунт с сессией
    test_phone = None
    test_data = None
    for phone, data in accounts_dict.items():
        if isinstance(data, dict) and data.get('session'):
            test_phone = phone
            test_data = data
            break
    
    if not test_phone:
        print("❌ Нет аккаунтов с сессией")
        return
    
    print(f"📱 Тестовый аккаунт: {test_phone}")
    print(f"📊 Статус: {test_data.get('status')}")
    print(f"🔑 Session длина: {len(test_data.get('session', ''))}")
    print("="*60)
    
    # Создаем клиент
    print("\n1️⃣ Создаем TelegramClient...")
    client = TelegramClient(
        StringSession(test_data['session']),
        API_ID,
        API_HASH,
        proxy=test_data.get('proxy')
    )
    
    try:
        print("2️⃣ Подключаемся...")
        await client.connect()
        
        print("3️⃣ Проверяем авторизацию...")
        if not await client.is_user_authorized():
            print("❌ Аккаунт не авторизован!")
            return
        
        print("✅ Аккаунт авторизован")
        
        print("\n4️⃣ Получаем текущий профиль...")
        me = await client.get_me()
        print(f"   ID: {me.id}")
        print(f"   Username: {me.username}")
        print(f"   Phone: {me.phone}")
        print(f"   Текущее имя: '{me.first_name}' '{me.last_name}'")
        
        # Генерируем уникальное тестовое имя
        import time
        test_first = f"TestBot"
        test_last = f"{int(time.time() % 10000)}"
        
        print(f"\n5️⃣ Меняем имя на: '{test_first}' '{test_last}'")
        print("   Вызываем UpdateProfileRequest...")
        
        result = await client(UpdateProfileRequest(
            first_name=test_first,
            last_name=test_last
        ))
        
        print(f"   ✅ Запрос выполнен")
        print(f"   Результат: {type(result).__name__}")
        print(f"   Объект: {result}")
        
        print("\n6️⃣ Проверяем изменения...")
        await asyncio.sleep(1)  # Даем время на обновление
        me_after = await client.get_me()
        print(f"   После изменения: '{me_after.first_name}' '{me_after.last_name}'")
        
        if me_after.first_name == test_first and me_after.last_name == test_last:
            print(f"\n✅ УСПЕХ! Имя изменено!")
            print(f"   Было: '{me.first_name}' '{me.last_name}'")
            print(f"   Стало: '{me_after.first_name}' '{me_after.last_name}'")
        else:
            print(f"\n❌ ПРОБЛЕМА! Имя НЕ изменилось!")
            print(f"   Ожидали: '{test_first}' '{test_last}'")
            print(f"   Получили: '{me_after.first_name}' '{me_after.last_name}'")
        
        print(f"\n💡 Проверь в официальном Telegram клиенте аккаунт {test_phone}")
        print(f"   Имя должно быть: {test_first} {test_last}")
        
    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        print(traceback.format_exc())
    finally:
        await client.disconnect()
        print("\n🔌 Отключились")

if __name__ == "__main__":
    asyncio.run(test_profile_update())

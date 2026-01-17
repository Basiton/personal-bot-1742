#!/usr/bin/env python3
"""
Тест всех аккаунтов - ищем который может менять профиль
"""

import asyncio
import json
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest

API_ID = 36053254
API_HASH = "ecd80be4cc92e9cd87e73da31bdedadd"

async def test_all_accounts():
    print("🔍 Проверка всех аккаунтов на возможность изменения профиля")
    print("="*70)
    
    with open('bot_data.json', 'r') as f:
        bot_data = json.load(f)
        accounts_dict = bot_data.get('accounts', {})
    
    results = []
    
    for phone, data in accounts_dict.items():
        if not isinstance(data, dict) or not data.get('session'):
            continue
        
        print(f"\n📱 Тестируем: {phone}")
        print(f"   Статус: {data.get('status', 'unknown')}")
        
        client = TelegramClient(
            StringSession(data['session']),
            API_ID,
            API_HASH,
            proxy=data.get('proxy')
        )
        
        try:
            await client.connect()
            
            if not await client.is_user_authorized():
                print(f"   ❌ Не авторизован")
                results.append((phone, "NOT_AUTH", None))
                continue
            
            me = await client.get_me()
            print(f"   👤 Текущее имя: '{me.first_name}' '{me.last_name}'")
            
            # Пробуем изменить имя
            test_first = me.first_name or "Test"  # Оставляем как есть
            test_last = me.last_name or ""         # Оставляем как есть
            
            try:
                result = await client(UpdateProfileRequest(
                    first_name=test_first,
                    last_name=test_last
                ))
                print(f"   ✅ UpdateProfileRequest РАБОТАЕТ!")
                results.append((phone, "OK", f"{me.id}"))
            except Exception as e:
                error_msg = str(e)
                if "FROZEN" in error_msg:
                    print(f"   ❌ FROZEN - метод заблокирован Telegram")
                    results.append((phone, "FROZEN", error_msg))
                elif "FLOOD" in error_msg:
                    print(f"   ⚠️  FLOOD - нужно подождать")
                    results.append((phone, "FLOOD", error_msg))
                else:
                    print(f"   ❌ Ошибка: {error_msg[:50]}")
                    results.append((phone, "ERROR", error_msg[:50]))
        
        except Exception as e:
            print(f"   ❌ Ошибка подключения: {e}")
            results.append((phone, "CONN_ERROR", str(e)[:50]))
        
        finally:
            await client.disconnect()
    
    print("\n" + "="*70)
    print("📊 ИТОГОВАЯ ТАБЛИЦА:")
    print("="*70)
    
    ok_count = 0
    frozen_count = 0
    
    for phone, status, details in results:
        status_icon = {
            "OK": "✅",
            "FROZEN": "❌",
            "FLOOD": "⚠️ ",
            "ERROR": "⚠️ ",
            "NOT_AUTH": "❓",
            "CONN_ERROR": "❓"
        }.get(status, "?")
        
        print(f"{status_icon} {phone}: {status}")
        
        if status == "OK":
            ok_count += 1
        elif status == "FROZEN":
            frozen_count += 1
    
    print("="*70)
    print(f"\n✅ Рабочих аккаунтов: {ok_count}")
    print(f"❌ Заблокированных (FROZEN): {frozen_count}")
    print(f"📊 Всего проверено: {len(results)}")
    
    if ok_count == 0:
        print("\n" + "!"*70)
        print("⚠️  КРИТИЧЕСКАЯ ПРОБЛЕМА:")
        print("   НИ ОДИН аккаунт не может изменять профиль через API!")
        print("   Telegram заблокировал метод UpdateProfileRequest для всех аккаунтов.")
        print("   ")
        print("   ПРИЧИНЫ:")
        print("   1. Аккаунты куплены/фейковые - Telegram ограничивает их")
        print("   2. Слишком много изменений профиля - флуд контроль")
        print("   3. Аккаунты имеют ограничения из-за подозрительной активности")
        print("!"*70)
    else:
        print(f"\n✅ Хорошие новости: есть {ok_count} рабочих аккаунтов!")
        print("   Используйте их для команд /setname, /setbio, /setavatar")

if __name__ == "__main__":
    asyncio.run(test_all_accounts())

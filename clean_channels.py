#!/usr/bin/env python3
"""
Скрипт для проверки и очистки нерабочих каналов
"""
import asyncio
import json
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = 36053254
API_HASH = '4c63aee24cbc1be5e593329370712e7f'
DB_NAME = 'bot_data.json'

async def check_channels():
    """Check which channels are valid and remove invalid ones"""
    
    # Load data
    with open(DB_NAME, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    accounts = data.get('accounts', {})
    channels = data.get('channels', [])
    
    # Find first active account
    active_account = None
    for phone, acc_data in accounts.items():
        if acc_data.get('session') and acc_data.get('active'):
            active_account = (phone, acc_data)
            break
    
    if not active_account:
        print("❌ Нет активных аккаунтов!")
        return
    
    phone, acc_data = active_account
    print(f"✅ Используем аккаунт: {acc_data.get('name', phone)}")
    print(f"📊 Всего каналов: {len(channels)}\n")
    
    # Connect
    client = TelegramClient(StringSession(acc_data['session']), API_ID, API_HASH)
    await client.connect()
    
    if not await client.is_user_authorized():
        print("❌ Аккаунт не авторизован!")
        await client.disconnect()
        return
    
    valid_channels = []
    invalid_channels = []
    
    for i, channel in enumerate(channels, 1):
        username = channel.get('username') if isinstance(channel, dict) else str(channel)
        username = str(username).strip().lstrip('@')
        
        print(f"[{i}/{len(channels)}] Проверяю @{username}...", end=' ')
        
        try:
            # Try to get entity
            entity = await client.get_entity(username)
            print("✅ OK")
            valid_channels.append(channel)
        except Exception as e:
            error_msg = str(e)
            if "No user has" in error_msg or "username not found" in error_msg.lower():
                print(f"❌ НЕ СУЩЕСТВУЕТ")
                invalid_channels.append(username)
            else:
                print(f"⚠️ ОШИБКА: {error_msg[:50]}")
                # Keep channel if error is not "not found"
                valid_channels.append(channel)
        
        # Small delay to avoid flood
        await asyncio.sleep(0.5)
    
    await client.disconnect()
    
    # Show results
    print(f"\n{'='*60}")
    print(f"📊 РЕЗУЛЬТАТЫ:")
    print(f"✅ Рабочих каналов: {len(valid_channels)}")
    print(f"❌ Нерабочих каналов: {len(invalid_channels)}")
    
    if invalid_channels:
        print(f"\n🗑️ Нерабочие каналы (будут удалены):")
        for username in invalid_channels:
            print(f"   - @{username}")
        
        # Ask for confirmation
        response = input(f"\n❓ Удалить {len(invalid_channels)} нерабочих каналов? (yes/no): ").strip().lower()
        
        if response in ['yes', 'y', 'да', 'д']:
            # Update data
            data['channels'] = valid_channels
            
            # Save
            with open(DB_NAME, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            print(f"✅ Данные обновлены! Осталось {len(valid_channels)} каналов")
        else:
            print("❌ Отменено")
    else:
        print("\n✅ Все каналы рабочие!")

if __name__ == '__main__':
    asyncio.run(check_channels())

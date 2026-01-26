#!/usr/bin/env python3
"""
Ручная авторизация российских номеров (+7) для обхода блокировок Telegram
Создаёт StringSession который потом можно добавить в бота
"""

import asyncio
import json
from telethon import TelegramClient
from telethon.sessions import StringSession

# Из main.py
API_ID = 29857881
API_HASH = '809cdc22d46ccf3b0bbe6854aeff0962'

async def manual_auth():
    """Ручная авторизация с возможностью использования прокси"""
    print("="*60)
    print("🇷🇺 РУЧНАЯ АВТОРИЗАЦИЯ ДЛЯ РОССИЙСКИХ НОМЕРОВ")
    print("="*60)
    
    phone = input("\n📱 Введите номер телефона (с +7): ").strip()
    
    # Опционально: прокси
    use_proxy = input("🌐 Использовать прокси? (y/n): ").strip().lower()
    proxy = None
    
    if use_proxy == 'y':
        print("\n📝 Форматы прокси:")
        print("   socks5://username:password@host:port")
        print("   socks5://host:port")
        print("   http://host:port")
        proxy_str = input("Введите прокси: ").strip()
        
        # Парсим прокси
        if proxy_str.startswith('socks5://'):
            parts = proxy_str.replace('socks5://', '').split('@')
            if len(parts) == 2:
                # С авторизацией
                auth, addr = parts
                username, password = auth.split(':')
                host, port = addr.split(':')
                proxy = ('socks5', host, int(port), True, username, password)
            else:
                # Без авторизации
                host, port = parts[0].split(':')
                proxy = ('socks5', host, int(port))
        elif proxy_str.startswith('http://'):
            host_port = proxy_str.replace('http://', '')
            host, port = host_port.split(':')
            proxy = ('http', host, int(port))
    
    print("\n🔌 Создание Telegram клиента...")
    
    # Создаём клиент с StringSession (для экспорта)
    client = TelegramClient(
        StringSession(),
        API_ID,
        API_HASH,
        proxy=proxy
    )
    
    try:
        await client.connect()
        print("✅ Подключено к Telegram")
        
        # Запрашиваем код
        print(f"\n📨 Отправка кода на {phone}...")
        await client.send_code_request(phone)
        
        # Вводим код
        code = input("📩 Введите код из Telegram: ").strip()
        
        try:
            # Пробуем авторизоваться
            await client.sign_in(phone, code)
            print("✅ Авторизация успешна!")
        except Exception as e:
            # Возможно нужен 2FA пароль
            if 'password' in str(e).lower() or '2fa' in str(e).lower():
                password = input("🔐 Введите 2FA пароль (облачный пароль): ").strip()
                await client.sign_in(password=password)
                print("✅ Авторизация с 2FA успешна!")
            else:
                raise
        
        # Получаем информацию об аккаунте
        me = await client.get_me()
        first_name = me.first_name or ""
        last_name = me.last_name or ""
        username = me.username or ""
        account_name = f"{first_name} {last_name}".strip() or username or phone[-10:]
        
        # Получаем StringSession
        session_string = client.session.save()
        
        print("\n" + "="*60)
        print("✅ АВТОРИЗАЦИЯ ЗАВЕРШЕНА!")
        print("="*60)
        print(f"👤 Аккаунт: {account_name}")
        print(f"📱 Телефон: {phone}")
        print(f"🆔 Username: @{username}" if username else "🆔 Username: нет")
        print("\n📝 StringSession сохранён в файл: session_export.json")
        print("="*60)
        
        # Сохраняем в файл для импорта в бота
        session_data = {
            "phone": phone,
            "session": session_string,
            "name": account_name,
            "username": username,
            "proxy": proxy_str if use_proxy == 'y' else None
        }
        
        with open('session_export.json', 'w', encoding='utf-8') as f:
            json.dump(session_data, f, indent=2, ensure_ascii=False)
        
        print("\n💡 Теперь импортируйте эту сессию в бота:")
        print(f"   1. Скопируйте файл session_export.json на сервер")
        print(f"   2. Запустите: python3 import_session.py")
        print(f"   3. Или добавьте вручную через /addmanual в боте")
        
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.disconnect()
        print("\n🔌 Отключено от Telegram")

if __name__ == '__main__':
    asyncio.run(manual_auth())

#!/usr/bin/env python3
"""
Скрипт для получения StringSession для любого Telegram аккаунта.
Используйте этот скрипт на ВАШЕМ компьютере (Windows/Mac/Linux).
"""

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

# API credentials вашего бота
API_ID = 36053254
API_HASH = '4c63aee24cbc1be5e593329370712e7f'

def main():
    print("=" * 60)
    print("ПОЛУЧЕНИЕ STRING SESSION ДЛЯ TELEGRAM АККАУНТА")
    print("=" * 60)
    print()
    
    phone = input("Введите номер телефона (с +): ").strip()
    
    if not phone.startswith('+'):
        print("⚠️ Номер должен начинаться с +")
        return
    
    print(f"\n📱 Получаю StringSession для {phone}...")
    print()
    print("⚠️  ВАЖНО: Код придет в TELEGRAM приложение, НЕ по SMS!")
    print("    Откройте Telegram на телефоне и проверьте сообщения от Telegram.")
    print()
    
    # Используем StringSession (сессия в памяти)
    with TelegramClient(StringSession(), API_ID, API_HASH) as client:
        client.start(phone=phone, force_sms=False)
        
        # Получаем StringSession
        session_string = client.session.save()
        
        # Получаем информацию о пользователе
        me = client.get_me()
        
        print()
        print("=" * 60)
        print("✅ УСПЕШНО! Вот ваши данные:")
        print("=" * 60)
        print(f"Телефон: {phone}")
        print(f"Имя: {me.first_name or ''} {me.last_name or ''}")
        print(f"Username: @{me.username}" if me.username else "Username: нет")
        print(f"User ID: {me.id}")
        print()
        print("STRING SESSION (скопируйте ЦЕЛИКОМ):")
        print("-" * 60)
        print(session_string)
        print("-" * 60)
        print()
        print("📋 СКОПИРУЙТЕ StringSession выше и используйте команду:")
        print(f"/importsession {phone} {session_string} Имя")
        print()
        print("Где 'Имя' - это имя для аккаунта в боте (любое)")
        print("=" * 60)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Прервано пользователем")
    except Exception as e:
        print(f"\n\n❌ Ошибка: {e}")

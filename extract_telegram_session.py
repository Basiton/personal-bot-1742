#!/usr/bin/env python3
"""
Скрипт для конвертации Telegram Desktop сессии в StringSession
"""

import os
import sys

def main():
    print("=" * 70)
    print("ИЗВЛЕЧЕНИЕ СЕССИИ ИЗ TELEGRAM DESKTOP")
    print("=" * 70)
    print()
    print("Для извлечения сессии нужна библиотека 'opentele'")
    print()
    print("ИНСТРУКЦИЯ:")
    print()
    print("1. Установите opentele:")
    print("   pip install opentele")
    print()
    print("2. Найдите папку tdata на вашем компьютере:")
    print("   Windows: C:\\Users\\ВАШ_ЮЗЕ��\\AppData\\Roaming\\Telegram Desktop\\tdata")
    print("   Mac: ~/Library/Application Support/Telegram Desktop/tdata")
    print("   Linux: ~/.local/share/TelegramDesktop/tdata")
    print()
    print("3. Запустите конвертацию:")
    print()
    print("=" * 70)
    print()
    
    try:
        from opentele.td import TDesktop
        from opentele.api import API, UseCurrentSession
        from telethon.sessions import StringSession
        
        tdata_path = input("Введите путь к папке tdata: ").strip()
        
        if not os.path.exists(tdata_path):
            print(f"❌ Папка не найдена: {tdata_path}")
            return
        
        print(f"\n📂 Читаю сессию из {tdata_path}...")
        
        # Загружаем tdata
        tdesk = TDesktop(tdata_path)
        
        # Проверяем что сессия авторизована
        if not tdesk.isLoaded():
            print("❌ Не удалось загрузить сессию из tdata")
            return
        
        print("✅ Сессия загружена!")
        print(f"📱 Найдено аккаунтов: {len(tdesk.accounts)}")
        print()
        
        # Конвертируем в Telethon
        client = tdesk.ToTelethon(session="tdesk_session", flag=UseCurrentSession, api=API.TelegramDesktop)
        
        # Подключаемся
        client.connect()
        
        if not client.is_user_authorized():
            print("❌ Аккаунт не авторизован")
            return
        
        # Получаем информацию
        me = client.get_me()
        
        # Получаем StringSession
        session_string = StringSession.save(client.session)
        
        print()
        print("=" * 70)
        print("✅ УСПЕШНО! Вот ваши данные:")
        print("=" * 70)
        print(f"Имя: {me.first_name or ''} {me.last_name or ''}")
        print(f"Username: @{me.username}" if me.username else "Username: нет")
        print(f"Телефон: {me.phone}")
        print(f"User ID: {me.id}")
        print()
        print("STRING SESSION (скопируйте ЦЕЛИКОМ):")
        print("-" * 70)
        print(session_string)
        print("-" * 70)
        print()
        print("📋 СКОПИРУЙТЕ StringSession выше и отправьте в бот:")
        print(f"/importsession +{me.phone} {session_string} {me.first_name or 'User'}")
        print("=" * 70)
        
        client.disconnect()
        
    except ImportError:
        print("❌ Библиотека opentele не установлена!")
        print()
        print("Установите её командой:")
        print("   pip install opentele")
        print()
        print("После установки запустите скрипт снова.")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Прервано пользователем")

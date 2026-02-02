#!/usr/bin/env python3
"""
Утилита для конвертации разных типов сессий Telegram в StringSession

Поддерживаемые форматы:
1. Auth Key (HEX) - 512 символов hex строка
2. tdata папка - из Telegram Desktop
3. .session файл - из Telethon/Pyrogram

Использование:
    python3 convert_session.py
"""

import asyncio
import json
import os
import sys
import struct
from pathlib import Path
from telethon import TelegramClient
from telethon.sessions import StringSession, MemorySession

# API credentials (можно заменить на свои или читать из env)
API_ID = int(os.getenv('API_ID', '36053254'))
API_HASH = os.getenv('API_HASH', '4c63aee24cbc1be5e593329370712e7f')


class SessionConverter:
    """Конвертер различных форматов сессий в StringSession"""
    
    @staticmethod
    def hex_to_bytes(hex_string):
        """Конвертирует HEX строку в bytes"""
        hex_string = hex_string.strip().replace(' ', '').replace('\n', '')
        return bytes.fromhex(hex_string)
    
    @staticmethod
    async def from_auth_key(auth_key_hex, dc_id=2, phone=None, proxy=None):
        """
        Создаёт StringSession из Auth Key (HEX)
        
        Args:
            auth_key_hex: Auth Key в формате HEX (512 символов)
            dc_id: ID дата-центра (по умолчанию 2)
            phone: Номер телефона (опционально, для логирования)
            proxy: Прокси (опционально)
        
        Returns:
            StringSession string или None при ошибке
        """
        try:
            print(f"\n🔑 Конвертация Auth Key -> StringSession")
            print(f"   DC ID: {dc_id}")
            if phone:
                print(f"   Телефон: {phone}")
            
            # Убираем пробелы и проверяем длину
            auth_key_hex = auth_key_hex.strip().replace(' ', '').replace('\n', '')
            
            if len(auth_key_hex) != 512:
                print(f"❌ Неверная длина Auth Key: {len(auth_key_hex)} (должно быть 512)")
                return None
            
            # Конвертируем HEX в bytes
            auth_key = SessionConverter.hex_to_bytes(auth_key_hex)
            
            if len(auth_key) != 256:
                print(f"❌ Неверная длина auth_key в bytes: {len(auth_key)} (должно быть 256)")
                return None
            
            print(f"✅ Auth Key успешно декодирован ({len(auth_key)} bytes)")
            
            # Создаём временную сессию в памяти
            session = MemorySession()
            
            # Устанавливаем параметры сессии
            session.set_dc(dc_id, '149.154.167.51', 443)  # DC2 по умолчанию
            session.auth_key = auth_key
            
            # Создаём клиент с этой сессией
            client = TelegramClient(session, API_ID, API_HASH, proxy=proxy)
            
            try:
                await client.connect()
                print("🔌 Подключено к Telegram")
                
                # Проверяем авторизацию
                if await client.is_user_authorized():
                    print("✅ Аккаунт авторизован!")
                    
                    # Получаем информацию
                    me = await client.get_me()
                    print(f"👤 Аккаунт: {me.first_name} {me.last_name or ''}")
                    print(f"📱 Телефон: {me.phone}")
                    print(f"🆔 Username: @{me.username or 'нет'}")
                    
                    # Конвертируем в StringSession
                    string_session = StringSession.save(session)
                    
                    await client.disconnect()
                    
                    return string_session
                else:
                    print("❌ Сессия не авторизована")
                    await client.disconnect()
                    return None
                    
            except Exception as e:
                print(f"❌ Ошибка при подключении: {e}")
                try:
                    await client.disconnect()
                except:
                    pass
                return None
                
        except Exception as e:
            print(f"❌ Ошибка конвертации Auth Key: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    @staticmethod
    async def from_tdata(tdata_path, proxy=None):
        """
        Создаёт StringSession из tdata папки Telegram Desktop
        
        Args:
            tdata_path: Путь к папке tdata
            proxy: Прокси (опционально)
        
        Returns:
            StringSession string или None при ошибке
        """
        try:
            print(f"\n📁 Конвертация tdata -> StringSession")
            print(f"   Путь: {tdata_path}")
            
            # Проверяем что папка существует
            tdata_path = Path(tdata_path)
            if not tdata_path.exists():
                print(f"❌ Папка не найдена: {tdata_path}")
                return None
            
            if not tdata_path.is_dir():
                print(f"❌ Это не папка: {tdata_path}")
                return None
            
            # Импортируем opentele для работы с tdata
            try:
                from opentele.td import TDesktop
                from opentele.api import API, UseCurrentSession
            except ImportError:
                print("❌ Библиотека opentele не установлена!")
                print("   Установите: pip install opentele")
                return None
            
            print("📂 Читаю tdata...")
            
            # Загружаем tdata
            tdesk = TDesktop(str(tdata_path))
            
            # Проверяем есть ли авторизованные аккаунты
            if not tdesk.isLoaded():
                print("❌ tdata не загружена или пуста")
                return None
            
            print(f"✅ Найдено аккаунтов в tdata: {len(tdesk.accounts)}")
            
            # Берём первый аккаунт
            if len(tdesk.accounts) == 0:
                print("❌ В tdata нет авторизованных аккаунтов")
                return None
            
            # Конвертируем в Telethon
            print("🔄 Конвертация в Telethon сессию...")
            
            client = await tdesk.ToTelethon(
                session="memory",
                flag=UseCurrentSession,
                api=API.TelegramDesktop
            )
            
            if client is None:
                print("❌ Не удалось конвертировать tdata")
                return None
            
            try:
                # Подключаемся и проверяем
                if not client.is_connected():
                    await client.connect()
                
                print("🔌 Подключено к Telegram")
                
                if await client.is_user_authorized():
                    print("✅ Аккаунт авторизован!")
                    
                    # Получаем информацию
                    me = await client.get_me()
                    print(f"👤 Аккаунт: {me.first_name} {me.last_name or ''}")
                    print(f"📱 Телефон: {me.phone}")
                    print(f"🆔 Username: @{me.username or 'нет'}")
                    
                    # Получаем StringSession
                    string_session = client.session.save()
                    
                    await client.disconnect()
                    
                    return string_session
                else:
                    print("❌ Сессия не авторизована")
                    await client.disconnect()
                    return None
                    
            except Exception as e:
                print(f"❌ Ошибка при проверке сессии: {e}")
                try:
                    await client.disconnect()
                except:
                    pass
                return None
                
        except Exception as e:
            print(f"❌ Ошибка конвертации tdata: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    @staticmethod
    async def from_session_file(session_file, proxy=None):
        """
        Создаёт StringSession из .session файла
        
        Args:
            session_file: Путь к .session файлу
            proxy: Прокси (опционально)
        
        Returns:
            StringSession string или None при ошибке
        """
        try:
            print(f"\n📄 Конвертация .session -> StringSession")
            print(f"   Файл: {session_file}")
            
            # Проверяем что файл существует
            session_path = Path(session_file)
            if not session_path.exists():
                print(f"❌ Файл не найден: {session_file}")
                return None
            
            # Создаём клиент с этим файлом
            client = TelegramClient(str(session_path.with_suffix('')), API_ID, API_HASH, proxy=proxy)
            
            try:
                await client.connect()
                print("🔌 Подключено к Telegram")
                
                if await client.is_user_authorized():
                    print("✅ Аккаунт авторизован!")
                    
                    # Получаем информацию
                    me = await client.get_me()
                    print(f"👤 Аккаунт: {me.first_name} {me.last_name or ''}")
                    print(f"📱 Телефон: {me.phone}")
                    print(f"🆔 Username: @{me.username or 'нет'}")
                    
                    # Получаем StringSession
                    string_session = client.session.save()
                    
                    await client.disconnect()
                    
                    return string_session
                else:
                    print("❌ Сессия не авторизована")
                    await client.disconnect()
                    return None
                    
            except Exception as e:
                print(f"❌ Ошибка при проверке сессии: {e}")
                try:
                    await client.disconnect()
                except:
                    pass
                return None
                
        except Exception as e:
            print(f"❌ Ошибка конвертации .session файла: {e}")
            import traceback
            traceback.print_exc()
            return None


async def interactive_convert():
    """Интерактивная конвертация сессии"""
    
    print("=" * 70)
    print("🔄 КОНВЕРТЕР TELEGRAM СЕССИЙ")
    print("=" * 70)
    print("\nВыберите тип исходных данных:")
    print("1. Auth Key (HEX) - 512 символов")
    print("2. tdata папка - из Telegram Desktop")
    print("3. .session файл - из Telethon")
    print("=" * 70)
    
    choice = input("\nВаш выбор (1-3): ").strip()
    
    # Опциональный прокси
    use_proxy = input("\n🌐 Использовать прокси? (y/n): ").strip().lower()
    proxy = None
    
    if use_proxy == 'y':
        print("\n📝 Формат прокси: socks5:host:port:user:pass")
        proxy_str = input("Введите прокси: ").strip()
        
        try:
            parts = proxy_str.split(':')
            if len(parts) >= 5:
                proxy = (parts[0], parts[1], int(parts[2]), True, parts[3], parts[4])
                print(f"✅ Прокси настроен: {parts[0]}://{parts[1]}:{parts[2]}")
            else:
                print("⚠️ Неверный формат прокси, продолжаем без прокси")
        except Exception as e:
            print(f"⚠️ Ошибка парсинга прокси: {e}, продолжаем без прокси")
    
    converter = SessionConverter()
    string_session = None
    phone = None
    
    if choice == '1':
        # Auth Key
        print("\n📋 Вставьте Auth Key (HEX, 512 символов):")
        auth_key = input().strip()
        
        dc_id = input("DC ID (по умолчанию 2): ").strip()
        dc_id = int(dc_id) if dc_id else 2
        
        phone = input("Номер телефона (опционально, для логирования): ").strip()
        
        string_session = await converter.from_auth_key(auth_key, dc_id, phone, proxy)
        
    elif choice == '2':
        # tdata
        print("\n📁 Введите путь к папке tdata:")
        tdata_path = input().strip()
        
        string_session = await converter.from_tdata(tdata_path, proxy)
        
    elif choice == '3':
        # .session file
        print("\n📄 Введите путь к .session файлу:")
        session_file = input().strip()
        
        string_session = await converter.from_session_file(session_file, proxy)
    
    else:
        print("❌ Неверный выбор")
        return
    
    # Результат
    if string_session:
        print("\n" + "=" * 70)
        print("✅ КОНВЕРТАЦИЯ УСПЕШНА!")
        print("=" * 70)
        
        # Сохраняем в файл
        output_data = {
            "phone": phone if phone else "unknown",
            "session": string_session,
            "proxy": proxy_str if use_proxy == 'y' and proxy else None,
            "type": ["auth_key", "tdata", "session_file"][int(choice) - 1]
        }
        
        output_file = "session_converted.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        print(f"\n📝 Сохранено в файл: {output_file}")
        print(f"\n🔑 StringSession:\n")
        print(f"{string_session}\n")
        print("=" * 70)
        print("\n💡 Используйте эту сессию в боте:")
        print(f"   /addaccount +номер StringSession Имя")
        print("=" * 70)
    else:
        print("\n❌ Конвертация не удалась")


if __name__ == '__main__':
    asyncio.run(interactive_convert())

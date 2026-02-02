#!/usr/bin/env python3
"""
Пример использования convert_session.py для конвертации Auth Key в StringSession
"""

import asyncio
from convert_session import SessionConverter

# Пример Auth Key (замените на реальный)
EXAMPLE_AUTH_KEY = "0" * 512  # 512 символов HEX

# Пример конфигурации
DC_ID = 2  # Дата-центр (обычно 2 для европейских номеров)
PHONE = "+79991112233"
PROXY = ("socks5", "proxy.example.com", 1080, True, "username", "password")

async def example_convert():
    """Пример конвертации Auth Key"""
    
    print("=" * 70)
    print("ПРИМЕР КОНВЕРТАЦИИ AUTH KEY → STRING SESSION")
    print("=" * 70)
    
    converter = SessionConverter()
    
    # Конвертация БЕЗ прокси
    print("\n1️⃣ Конвертация БЕЗ прокси:")
    session = await converter.from_auth_key(
        auth_key_hex=EXAMPLE_AUTH_KEY,
        dc_id=DC_ID,
        phone=PHONE,
        proxy=None
    )
    
    if session:
        print(f"\n✅ Успешно! StringSession:\n{session}\n")
        print("Используйте в боте:")
        print(f"/addaccount {PHONE} {session} Александр")
    else:
        print("\n❌ Ошибка конвертации")
    
    # Конвертация С прокси
    print("\n" + "=" * 70)
    print("\n2️⃣ Конвертация С прокси:")
    session_with_proxy = await converter.from_auth_key(
        auth_key_hex=EXAMPLE_AUTH_KEY,
        dc_id=DC_ID,
        phone=PHONE,
        proxy=PROXY
    )
    
    if session_with_proxy:
        print(f"\n✅ Успешно! StringSession:\n{session_with_proxy}\n")
        print("Используйте в боте:")
        print(f"/addaccount {PHONE} {session_with_proxy} Александр socks5:proxy.example.com:1080:username:password")
    else:
        print("\n❌ Ошибка конвертации")
    
    print("\n" + "=" * 70)

if __name__ == '__main__':
    print("\n⚠️  ВНИМАНИЕ: Это пример кода, замените EXAMPLE_AUTH_KEY на реальный!\n")
    
    # Раскомментируйте для запуска:
    # asyncio.run(example_convert())
    
    print("Для интерактивной конвертации используйте:")
    print("  python3 convert_session.py")

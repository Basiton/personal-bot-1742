#!/usr/bin/env python3
"""
Импорт вручную созданной сессии в бота
Читает session_export.json и добавляет аккаунт в bot_data.json
"""

import json
import sys

def import_session():
    """Импортирует сессию из session_export.json в bot_data.json"""
    
    # Читаем экспортированную сессию
    try:
        with open('session_export.json', 'r', encoding='utf-8') as f:
            session_data = json.load(f)
    except FileNotFoundError:
        print("❌ Файл session_export.json не найден!")
        print("💡 Сначала создайте сессию через: python3 manual_auth_russia.py")
        return False
    
    phone = session_data['phone']
    
    # Читаем текущие данные бота
    try:
        with open('bot_data.json', 'r', encoding='utf-8') as f:
            bot_data = json.load(f)
    except FileNotFoundError:
        print("❌ Файл bot_data.json не найден!")
        print("💡 Запустите бота хотя бы раз перед импортом")
        return False
    
    # Проверяем что аккаунт еще не добавлен
    if phone in bot_data.get('accounts_data', {}):
        print(f"⚠️ Аккаунт {phone} уже существует в bot_data.json")
        overwrite = input("Перезаписать? (y/n): ").strip().lower()
        if overwrite != 'y':
            print("❌ Импорт отменён")
            return False
    
    # Добавляем аккаунт
    if 'accounts_data' not in bot_data:
        bot_data['accounts_data'] = {}
    
    bot_data['accounts_data'][phone] = {
        'session': session_data['session'],
        'name': session_data['name'],
        'username': session_data['username'],
        'status': 'reserve',  # Начинаем с reserve
        'proxy': session_data.get('proxy')
    }
    
    # Сохраняем
    # Создаём бэкап
    import shutil
    from datetime import datetime
    backup_name = f'bot_data.json.backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    shutil.copy2('bot_data.json', backup_name)
    print(f"💾 Создан бэкап: {backup_name}")
    
    # Сохраняем новые данные
    with open('bot_data.json', 'w', encoding='utf-8') as f:
        json.dump(bot_data, f, indent=2, ensure_ascii=False)
    
    print("\n" + "="*60)
    print("✅ АККАУНТ УСПЕШНО ИМПОРТИРОВАН!")
    print("="*60)
    print(f"👤 Аккаунт: {session_data['name']}")
    print(f"📱 Телефон: {phone}")
    print(f"🔵 Статус: RESERVE (не активен)")
    print("\n💡 Следующие шаги:")
    print("   1. Перезапустите бота: systemctl restart comapc-bot.service")
    print(f"   2. Активируйте аккаунт: /toggleaccount {phone}")
    print("   3. Проверьте: /listaccounts")
    print("="*60)
    
    return True

if __name__ == '__main__':
    success = import_session()
    sys.exit(0 if success else 1)

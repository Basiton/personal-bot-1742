#!/usr/bin/env python3
"""
Проверка доступности методов showcase во время выполнения
"""

import sys
import asyncio

# Импортируем класс
sys.path.insert(0, '/workspaces/personal-bot-1742')
from main import UltimateCommentBot

async def test_methods():
    """Создаём экземпляр и проверяем методы"""
    print("=" * 70)
    print("🧪 ТЕСТ: Проверка методов showcase в runtime")
    print("=" * 70)
    
    print("\n1️⃣ Создаём экземпляр UltimateCommentBot...")
    
    try:
        bot = UltimateCommentBot()
        print("   ✅ Экземпляр создан")
    except Exception as e:
        print(f"   ❌ Ошибка создания: {e}")
        return
    
    print("\n2️⃣ Проверяем наличие методов showcase...")
    
    showcase_methods = [
        '_showcase_create',
        '_showcase_link', 
        '_showcase_unlink',
        '_showcase_list',
        '_showcase_info',
        '_showcase_set'
    ]
    
    all_found = True
    for method_name in showcase_methods:
        has_method = hasattr(bot, method_name)
        if has_method:
            method = getattr(bot, method_name)
            is_callable = callable(method)
            print(f"   ✅ {method_name}: {'callable' if is_callable else 'НЕ callable'}")
        else:
            print(f"   ❌ {method_name}: НЕ НАЙДЕН")
            all_found = False
    
    print("\n3️⃣ Проверяем bot_client...")
    if hasattr(bot, 'bot_client'):
        print(f"   ✅ bot_client: {type(bot.bot_client)}")
    else:
        print(f"   ❌ bot_client: НЕ НАЙДЕН")
    
    print("\n4️⃣ Проверяем метод setup_handlers...")
    if hasattr(bot, 'setup_handlers'):
        print(f"   ✅ setup_handlers: найден")
        print(f"      (вызывается в start() для регистрации обработчиков)")
    else:
        print(f"   ❌ setup_handlers: НЕ НАЙДЕН")
    
    print("\n" + "=" * 70)
    if all_found:
        print("✅ ВСЕ МЕТОДЫ НАЙДЕНЫ - БОТ ДОЛЖЕН РАБОТАТЬ")
    else:
        print("❌ НЕКОТОРЫЕ МЕТОДЫ НЕ НАЙДЕНЫ")
    print("=" * 70)

if __name__ == '__main__':
    asyncio.run(test_methods())

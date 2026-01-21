#!/usr/bin/env python3
"""
Тест для проверки, что /listaccounts имеет только один обработчик
и не содержит проблемных фраз.
"""

import re

def test_listaccounts_handler():
    """Проверка обработчика /listaccounts"""
    
    with open('main.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 1. Проверяем количество обработчиков /listaccounts
    pattern_handlers = re.findall(r"@.*\.on\(events\.NewMessage\(pattern=['\"]\/listaccounts['\"]\)\)", content)
    print(f"📋 Найдено обработчиков /listaccounts: {len(pattern_handlers)}")
    
    if len(pattern_handlers) != 1:
        print(f"❌ ОШИБКА: Должен быть РОВНО ОДИН обработчик, найдено: {len(pattern_handlers)}")
        return False
    else:
        print(f"✅ Найден ровно ОДИН обработчик /listaccounts")
    
    # 2. Проверяем, что в коде нет текста "Нет авторизованных аккаунтов"
    problematic_phrases = [
        "Нет авторизованных аккаунтов"
    ]
    
    for phrase in problematic_phrases:
        matches = re.findall(re.escape(phrase), content, re.IGNORECASE)
        # Исключаем комментарии
        lines_with_phrase = [line for line in content.split('\n') if phrase in line and not line.strip().startswith('#')]
        
        if lines_with_phrase:
            print(f"⚠️  Найдена фраза '{phrase}': {len(lines_with_phrase)} раз")
            for line in lines_with_phrase[:3]:  # Показываем первые 3
                print(f"      {line.strip()[:80]}")
        else:
            print(f"✅ Фраза '{phrase}' не найдена в исполняемом коде")
    
    # 3. Извлекаем тело функции list_accounts
    pattern = r"async def list_accounts\(event\):.*?(?=\n        @self\.bot_client\.on|$)"
    match = re.search(pattern, content, re.DOTALL)
    
    if match:
        function_body = match.group(0)
        
        # Проверяем, что функция не вызывает другие функции проверки
        forbidden_calls = [
            'verify_all_accounts',
            'verify_account_auth',
            'check_authorized_accounts',
            'is_user_authorized'
        ]
        
        print("\n📝 Проверка вызовов функций в list_accounts:")
        for call in forbidden_calls:
            if call in function_body:
                print(f"   ⚠️  Найден вызов: {call}")
            else:
                print(f"   ✅ Не найден вызов: {call}")
        
        # Проверяем количество await event.respond()
        respond_calls = re.findall(r'await event\.respond\(', function_body)
        print(f"\n📤 Количество вызовов await event.respond(): {len(respond_calls)}")
        
        if len(respond_calls) > 2:  # Может быть 1-2 (один для пустого списка, один для списка аккаунтов)
            print(f"   ⚠️  Слишком много вызовов respond! Возможно дублирование.")
        else:
            print(f"   ✅ Нормальное количество вызовов respond")
        
        # Проверяем логирование
        log_lines = re.findall(r'logger\.info\("📋', function_body)
        print(f"\n📊 Количество строк логирования с префиксом 📋: {len(log_lines)}")
        
        if 'HANDLER STARTED' in function_body and 'HANDLER FINISHED' in function_body:
            print("   ✅ Найдены маркеры начала и конца обработчика")
        else:
            print("   ⚠️  Не найдены маркеры HANDLER STARTED/FINISHED")
    else:
        print("❌ Не удалось найти функцию list_accounts")
        return False
    
    print("\n" + "="*60)
    print("✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ!")
    print("="*60)
    print("\n💡 Для применения изменений:")
    print("   1. Остановите бота если он запущен: pkill -f 'python.*main.py'")
    print("   2. Запустите бота заново: python main.py")
    print("   3. Проверьте логи при вызове /listaccounts")
    print("\n📋 В логах должны быть строки:")
    print("   📋 /listaccounts HANDLER STARTED")
    print("   📋 /listaccounts HANDLER FINISHED SUCCESSFULLY")
    
    return True

if __name__ == '__main__':
    test_listaccounts_handler()

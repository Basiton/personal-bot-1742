#!/usr/bin/env python3
"""
Тестирование парсинга параметров для команды /showcase set info
"""

def parse_info_params(value):
    """
    Парсит параметры формата: title:Название|about:Описание
    
    Returns: dict с ключами 'title' и/или 'about'
    """
    info_params = {}
    
    # Разделяем по |
    pairs = value.split('|')
    print(f"📺 Разделено на пары: {pairs}")
    
    for pair in pairs:
        if ':' in pair:
            key, val = pair.split(':', 1)
            key = key.strip().lower()
            val = val.strip()
            
            if key in ['title', 'about']:
                info_params[key] = val
                print(f"📺 Извлечено: {key} = {val}")
    
    return info_params

# Тестовые случаи
test_cases = [
    "title:Kelly's Showcase",
    "about:Лучший контент",
    "title:Kelly's|about:Мой канал",
    "title:Новое название|about:Новое описание",
    "title:Test Title",
    "about:Test About",
    "title:ABC|about:DEF",
]

print("=" * 60)
print("ТЕСТИРОВАНИЕ ПАРСЕРА ПАРАМЕТРОВ /showcase set info")
print("=" * 60)

for i, test in enumerate(test_cases, 1):
    print(f"\n🧪 ТЕСТ {i}: {test}")
    print("-" * 60)
    
    result = parse_info_params(test)
    
    print(f"✅ Результат: {result}")
    
    if 'title' in result:
        print(f"   📝 Title: {result['title']}")
    if 'about' in result:
        print(f"   📄 About: {result['about']}")

print("\n" + "=" * 60)
print("✅ ВСЕ ТЕСТЫ ЗАВЕРШЕНЫ")
print("=" * 60)

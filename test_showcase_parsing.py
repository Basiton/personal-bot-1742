#!/usr/bin/env python3
"""
Тестирование парсинга команд /showcase
"""

import re

def test_showcase_parsing():
    """Тест парсинга команды /showcase"""
    
    test_commands = [
        "/showcase",
        "/showcase list",
        "/showcase info +1",
        "/showcase create +1 Test Channel",
        "/showcase link +1 @testchannel",
        "/showcase unlink +1",
        "/showcase set +1 avatar",
        "/showcase set +1 title New Title",
        "/showcase set +1 about New About",
        "/showcase set +1 info title:Test|about:Desc",
        "/showcase set +1 post Test post",
        "/showcase set +1 post_pin Pinned post",
        "/createshowcase 1",
        "/createshowcase +13434919340",
    ]
    
    # Паттерны
    showcase_pattern = r'^/showcase(?:\s|$)'
    createshowcase_pattern = r'^/createshowcase'
    
    print("=" * 70)
    print("ТЕСТИРОВАНИЕ ПАРСИНГА КОМАНД /showcase")
    print("=" * 70)
    
    for cmd in test_commands:
        print(f"\n🧪 Команда: {cmd}")
        print("-" * 70)
        
        # Проверка паттерна /createshowcase (должен быть проверен первым!)
        if re.match(createshowcase_pattern, cmd):
            print("✅ Совпадение: /createshowcase (более специфичный)")
            parts = cmd.split(maxsplit=2)
            print(f"   Parts: {parts}")
            continue
        
        # Проверка паттерна /showcase
        if re.match(showcase_pattern, cmd):
            print("✅ Совпадение: /showcase")
            
            parts = cmd.split(maxsplit=1)
            
            if len(parts) < 2:
                print("   📋 Действие: Показать справку")
            else:
                args = parts[1].split(maxsplit=1)
                action = args[0].lower()
                
                print(f"   📋 Действие: {action}")
                
                if len(args) > 1:
                    print(f"   📝 Аргументы: {args[1]}")
                    
                    # Специальная обработка для 'set'
                    if action == "set":
                        set_parts = args[1].split(maxsplit=2)
                        if len(set_parts) >= 2:
                            phone = set_parts[0]
                            param = set_parts[1]
                            value = set_parts[2] if len(set_parts) > 2 else ""
                            
                            print(f"      🔸 Phone: {phone}")
                            print(f"      🔸 Param: {param}")
                            if value:
                                print(f"      🔸 Value: {value}")
        else:
            print("❌ Нет совпадения")
    
    print("\n" + "=" * 70)
    print("✅ ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
    print("=" * 70)

if __name__ == "__main__":
    test_showcase_parsing()

#!/usr/bin/env python3
"""Проверка обработчика /testmode"""

import re
import ast

with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Найти определение testmode_command
testmode_start = content.find('async def testmode_command(event):')
if testmode_start == -1:
    print("❌ Функция testmode_command не найдена!")
else:
    print(f"✅ Функция testmode_command найдена на позиции {testmode_start}")
    
    # Найти декоратор перед ней
    decorator_pattern = r'@self\.bot_client\.on\(events\.NewMessage\(pattern=r\'\^/testmode'
    decorator_match = re.search(decorator_pattern, content[:testmode_start])
    
    if decorator_match:
        print(f"✅ Декоратор @self.bot_client.on найден на позиции {decorator_match.start()}")
    else:
        print("❌ Декоратор @self.bot_client.on НЕ найден перед функцией!")
        # Поищем что есть перед функцией
        before_func = content[max(0, testmode_start-500):testmode_start]
        print("\nКод перед функцией:")
        print(before_func[-200:])

# Проверим, закрыта ли функция testmode_command правильно
lines = content.split('\n')
testmode_line = None
for i, line in enumerate(lines):
    if 'async def testmode_command(event):' in line:
        testmode_line = i
        print(f"\n✅ testmode_command начинается на строке {i+1}")
        break

if testmode_line:
    # Найти следующую функцию на том же уровне отступа (8 пробелов)
    indent_level = len(lines[testmode_line]) - len(lines[testmode_line].lstrip())
    print(f"   Уровень отступа: {indent_level} пробелов")
    
    next_function = None
    for i in range(testmode_line + 1, min(testmode_line + 500, len(lines))):
        line = lines[i]
        if line.strip().startswith('async def ') or line.strip().startswith('def '):
            line_indent = len(line) - len(line.lstrip())
            if line_indent <= indent_level:
                next_function = i
                print(f"   Следующая функция на строке {i+1}: {line.strip()[:60]}")
                break
    
    if next_function:
        func_length = next_function - testmode_line
        print(f"   Длина функции: {func_length} строк")
        if func_length > 300:
            print(f"   ⚠️ ВНИМАНИЕ: Функция очень длинная ({func_length} строк)!")

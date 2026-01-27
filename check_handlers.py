#!/usr/bin/env python3
"""
Диагностика проблемы с /testmode
Ищет где в коде может быть проблема
"""

import re

with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()
    lines = content.splitlines()

# Найдём все обработчики команд
pattern = r'@self\.bot_client\.on\(events\.NewMessage\(pattern=[^)]+\)\)'

handlers_found = []
for i, line in enumerate(lines, 1):
    if '@self.bot_client.on(events.NewMessage(' in line:
        # Получим название команды
        if 'pattern=' in line:
            match = re.search(r'pattern=[\'"]([^\'"]+)', line)
            if match:
                command_pattern = match.group(1)
                handlers_found.append((i, command_pattern))
        else:
            handlers_found.append((i, "NO PATTERN (catches all)"))

print("Найденные обработчики команд:\n")
for line_num, pattern in handlers_found:
    print(f"Строка {line_num}: {pattern}")

# Ищем testmode
testmode_handlers = [(ln, pat) for ln, pat in handlers_found if 'testmode' in pat.lower()]

print(f"\n\nОбработчиков /testmode найдено: {len(testmode_handlers)}")
for ln, pat in testmode_handlers:
    print(f"  Строка {ln}: {pat}")

# Проверим, есть ли обработчик без паттерна ПОСЛЕ testmode
testmode_line = testmode_handlers[0][0] if testmode_handlers else 0
catch_all_after = [(ln, pat) for ln, pat in handlers_found if ln > testmode_line and pat == "NO PATTERN (catches all)"]

if catch_all_after:
    print("\n⚠️ ВНИМАНИЕ: После /testmode есть обработчик без паттерна!")
    for ln, pat in catch_all_after:
        print(f"  Строка {ln}: {pat}")
else:
    print("\n✅ После /testmode нет обработчиков без паттерна")

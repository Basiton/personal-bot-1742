#!/usr/bin/env python3
"""Быстрая проверка что бот компилируется и основные функции работают"""
import sys
import ast

print("🔍 БЫСТРАЯ ПРОВЕРКА БОТА")
print("="*50)

# 1. Проверка синтаксиса
print("\n1️⃣ Проверка синтаксиса main.py...")
try:
    with open('main.py', 'r', encoding='utf-8') as f:
        code = f.read()
    ast.parse(code)
    print("   ✅ Синтаксис правильный")
except SyntaxError as e:
    print(f"   ❌ ОШИБКА СИНТАКСИСА: {e}")
    sys.exit(1)

# 2. Проверка импортов
print("\n2️⃣ Проверка основных импортов...")
try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    print("   ✅ Telethon импортируется")
except ImportError as e:
    print(f"   ❌ Ошибка импорта: {e}")

# 3. Проверка ключевых функций в коде
print("\n3️⃣ Проверка ключевых функций...")
checks = {
    'account_worker': 'async def account_worker(',
    'worker_client создание': 'worker_client = TelegramClient(StringSession(',
    'smart delays': '3600 // target_rate',
    'parallel workers': 'asyncio.create_task(',
    'profile commands': 'async def handle_set_name(',
}

for name, pattern in checks.items():
    if pattern in code:
        print(f"   ✅ {name}")
    else:
        print(f"   ❌ {name} НЕ НАЙДЕН")

# 4. Проверка отступов в критической секции
print("\n4️⃣ Проверка отступов в account_worker...")
lines = code.split('\n')
worker_start = None
while_found = False
for i, line in enumerate(lines, 1):
    if 'async def account_worker(' in line:
        worker_start = i
    if worker_start and 'while self.monitoring:' in line:
        while_found = True
        indent = len(line) - len(line.lstrip())
        print(f"   while loop на строке {i}, отступ: {indent} пробелов")
        
        # Проверяем следующие 10 строк
        for j in range(i+1, min(i+11, len(lines))):
            if lines[j-1].strip() and not lines[j-1].strip().startswith('#'):
                next_indent = len(lines[j-1]) - len(lines[j-1].lstrip())
                if next_indent > indent:
                    print(f"   ✅ Код внутри while правильно отступлен ({next_indent} > {indent})")
                    break
                else:
                    print(f"   ❌ ПРОБЛЕМА: код на строке {j} имеет отступ {next_indent}, должен быть > {indent}")
                    break
        break

if not while_found:
    print("   ⚠️ while self.monitoring не найден")

print("\n" + "="*50)
print("✅ БАЗОВАЯ ПРОВЕРКА ЗАВЕРШЕНА")
print("\nДля полного теста запусти бота и отправь /start")

#!/usr/bin/env python3
"""
Скрипт проверки конфигурации RockAPI для защиты от дорогих моделей DeepSeek
"""

import os
import sys

# Цвета для вывода
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
RESET = '\033[0m'

print("="*70)
print("ПРОВЕРКА КОНФИГУРАЦИИ ROCKAPI (ЗАЩИТА ОТ ДОРОГИХ МОДЕЛЕЙ)")
print("="*70)

# Проверяем переменные окружения
rockapi_model = os.getenv('ROCKAPI_MODEL', 'deepseek-chat')
rockapi_key = os.getenv('ROCKAPI_KEY', '')
rockapi_base_url = os.getenv('ROCKAPI_BASE_URL', 'https://api.rockapi.ru/deepseek')

print(f"\n📋 Переменные окружения:")
print(f"   ROCKAPI_MODEL: {rockapi_model}")
print(f"   ROCKAPI_BASE_URL: {rockapi_base_url}")
if rockapi_key:
    print(f"   ROCKAPI_KEY: {rockapi_key[:10]}...{rockapi_key[-5:]} {GREEN}✓{RESET}")
else:
    print(f"   ROCKAPI_KEY: {RED}НЕ УСТАНОВЛЕН{RESET}")

# Список разрешённых экономичных моделей
ALLOWED_MODELS = ['deepseek-chat']

# Список дорогих моделей (для справки)
EXPENSIVE_MODELS = ['deepseek-reasoner', 'deepseek-r1']

print(f"\n✅ Разрешённые модели (экономичные):")
for model in ALLOWED_MODELS:
    print(f"   • {model}")

print(f"\n❌ Запрещённые модели (дорогие):")
for model in EXPENSIVE_MODELS:
    print(f"   • {model}")

print(f"\n🔍 Проверка текущей конфигурации:")

# Проверка модели
if rockapi_model in ALLOWED_MODELS:
    print(f"   {GREEN}✓ Модель '{rockapi_model}' разрешена и экономична{RESET}")
    status = "БЕЗОПАСНО"
    color = GREEN
elif rockapi_model in EXPENSIVE_MODELS:
    print(f"   {RED}✗ ВНИМАНИЕ! Модель '{rockapi_model}' ДОРОГАЯ!{RESET}")
    print(f"   {YELLOW}⚠ Бот автоматически заменит её на 'deepseek-chat'{RESET}")
    status = "ЗАЩИТА АКТИВНА"
    color = YELLOW
else:
    print(f"   {YELLOW}⚠ Неизвестная модель '{rockapi_model}'{RESET}")
    print(f"   {YELLOW}⚠ Бот автоматически заменит её на 'deepseek-chat'{RESET}")
    status = "ЗАЩИТА АКТИВНА"
    color = YELLOW

# Проверка в коде
print(f"\n🔍 Проверка кода main.py:")
try:
    with open('main.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    checks = []
    
    # Проверка 1: Используется переменная ROCKAPI_MODEL
    if '"model": ROCKAPI_MODEL' in content:
        checks.append((True, "Модель берётся из переменной ROCKAPI_MODEL"))
    else:
        checks.append((False, "НЕ найдено использование переменной ROCKAPI_MODEL"))
    
    # Проверка 2: Нет захардкоженных дорогих моделей
    has_expensive = False
    for model in EXPENSIVE_MODELS:
        if f'"{model}"' in content or f"'{model}'" in content:
            # Исключаем упоминания в комментариях и списках запрещённых
            if f"'{model}'" not in "EXPENSIVE_MODELS" and f'"{model}"' not in "EXPENSIVE_MODELS":
                has_expensive = True
                checks.append((False, f"Найдена захардкоженная модель {model}"))
    
    if not has_expensive:
        checks.append((True, "Нет захардкоженных дорогих моделей"))
    
    # Проверка 3: Есть защита через ALLOWED_MODELS
    if 'ALLOWED_MODELS' in content and 'deepseek-chat' in content:
        checks.append((True, "Настроена защита через ALLOWED_MODELS"))
    else:
        checks.append((False, "НЕ найдена защита через ALLOWED_MODELS"))
    
    # Проверка 4: Есть принудительная замена
    if 'not in ALLOWED_MODELS' in content:
        checks.append((True, "Настроена принудительная замена неразрешённых моделей"))
    else:
        checks.append((False, "НЕ найдена принудительная замена"))
    
    for success, message in checks:
        if success:
            print(f"   {GREEN}✓{RESET} {message}")
        else:
            print(f"   {RED}✗{RESET} {message}")
    
    all_passed = all(check[0] for check in checks)
    
except FileNotFoundError:
    print(f"   {RED}✗ Файл main.py не найден{RESET}")
    all_passed = False
except Exception as e:
    print(f"   {RED}✗ Ошибка при проверке: {e}{RESET}")
    all_passed = False

# Итоговый статус
print("\n" + "="*70)
if all_passed and rockapi_model in ALLOWED_MODELS:
    print(f"{GREEN}✓ ВСЁ В ПОРЯДКЕ: Используется только экономичная модель{RESET}")
    print(f"{GREEN}  Модель: {rockapi_model}{RESET}")
    print(f"{GREEN}  Статус: БЕЗОПАСНО{RESET}")
    exit_code = 0
elif all_passed:
    print(f"{YELLOW}⚠ ЗАЩИТА АКТИВНА: Неразрешённая модель будет заменена{RESET}")
    print(f"{YELLOW}  Запрошена: {rockapi_model}{RESET}")
    print(f"{YELLOW}  Будет использована: deepseek-chat{RESET}")
    exit_code = 0
else:
    print(f"{RED}✗ ТРЕБУЕТСЯ ВНИМАНИЕ: Обнаружены проблемы в конфигурации{RESET}")
    exit_code = 1

print("="*70)

# Рекомендации
print(f"\n💡 Рекомендации:")
print(f"   • Всегда используйте ROCKAPI_MODEL=deepseek-chat")
print(f"   • Не меняйте ALLOWED_MODELS = ['deepseek-chat']")
print(f"   • Избегайте моделей: {', '.join(EXPENSIVE_MODELS)}")
print(f"   • Защита в main.py автоматически блокирует дорогие модели")

sys.exit(exit_code)

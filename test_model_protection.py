#!/usr/bin/env python3
"""
Тест автоматической защиты от дорогих моделей в main.py
"""

import os
import sys

print("="*60)
print("ТЕСТ ЗАЩИТЫ ОТ ДОРОГИХ МОДЕЛЕЙ В MAIN.PY")
print("="*60)

# Тест 1: Нормальная конфигурация (deepseek-chat)
print("\n🧪 ТЕСТ 1: Нормальная конфигурация")
print("   Устанавливаем ROCKAPI_MODEL=deepseek-chat")
os.environ['ROCKAPI_MODEL'] = 'deepseek-chat'

# Импортируем после установки переменной
if 'main' in sys.modules:
    del sys.modules['main']
    
from main import ROCKAPI_MODEL as model1

print(f"   ✅ Результат: ROCKAPI_MODEL = '{model1}'")
assert model1 == 'deepseek-chat', "Ожидалась модель deepseek-chat"
print("   ✅ ТЕСТ ПРОЙДЕН: используется deepseek-chat")

# Тест 2: Дорогая модель (должна быть заменена)
print("\n🧪 ТЕСТ 2: Попытка использовать дорогую модель")
print("   Устанавливаем ROCKAPI_MODEL=deepseek-reasoner")
os.environ['ROCKAPI_MODEL'] = 'deepseek-reasoner'

# Перезагружаем модуль
if 'main' in sys.modules:
    del sys.modules['main']

# Захватываем вывод логов (перенаправляем stderr)
import io
import logging
from contextlib import redirect_stderr

stderr_capture = io.StringIO()

with redirect_stderr(stderr_capture):
    from main import ROCKAPI_MODEL as model2

captured_logs = stderr_capture.getvalue()

print(f"   🛡️  Результат: ROCKAPI_MODEL = '{model2}'")

if model2 == 'deepseek-chat':
    print("   ✅ ЗАЩИТА СРАБОТАЛА: модель принудительно заменена на deepseek-chat")
    print("   ✅ ТЕСТ ПРОЙДЕН: дорогая модель заблокирована")
else:
    print(f"   ❌ ОШИБКА: защита не сработала, модель осталась '{model2}'")
    sys.exit(1)

# Тест 3: Неизвестная модель (должна быть заменена)
print("\n🧪 ТЕСТ 3: Неизвестная модель")
print("   Устанавливаем ROCKAPI_MODEL=some-unknown-model")
os.environ['ROCKAPI_MODEL'] = 'some-unknown-model'

# Перезагружаем модуль
if 'main' in sys.modules:
    del sys.modules['main']
    
from main import ROCKAPI_MODEL as model3

print(f"   🛡️  Результат: ROCKAPI_MODEL = '{model3}'")

if model3 == 'deepseek-chat':
    print("   ✅ ЗАЩИТА СРАБОТАЛА: неизвестная модель заменена на deepseek-chat")
    print("   ✅ ТЕСТ ПРОЙДЕН")
else:
    print(f"   ❌ ОШИБКА: защита не сработала, модель осталась '{model3}'")
    sys.exit(1)

# Итоги
print("\n" + "="*60)
print("ИТОГИ ТЕСТИРОВАНИЯ")
print("="*60)
print("✅ Все тесты пройдены успешно!")
print("✅ Защита от дорогих моделей работает корректно")
print("✅ Бот всегда использует только deepseek-chat")
print("\n💡 Заключение:")
print("   - deepseek-chat: ✅ разрешена")
print("   - deepseek-reasoner: ❌ блокируется")
print("   - Любые другие модели: ❌ блокируются")
print("="*60)

#!/usr/bin/env python3
"""
Проверка конфигурации RockAPI модели
Убеждается, что используется только недорогая модель deepseek-chat
"""

import os
import sys

print("="*60)
print("ПРОВЕРКА КОНФИГУРАЦИИ ROCKAPI МОДЕЛИ")
print("="*60)

# Получаем переменную окружения
rockapi_model = os.getenv('ROCKAPI_MODEL', 'deepseek-chat')
print(f"\n📋 Переменная окружения ROCKAPI_MODEL: '{rockapi_model}'")

# Список разрешённых недорогих моделей
ALLOWED_MODELS = ['deepseek-chat']

print(f"\n✅ Разрешённые модели (недорогие):")
for model in ALLOWED_MODELS:
    print(f"   • {model}")

print(f"\n❌ Запрещённые модели (дорогие):")
expensive_models = ['deepseek-reasoner', 'deepseek-r1']
for model in expensive_models:
    print(f"   • {model} — НЕ использовать!")

# Проверка
if rockapi_model in ALLOWED_MODELS:
    print(f"\n✅ ПРОВЕРКА ПРОЙДЕНА")
    print(f"   Модель '{rockapi_model}' разрешена и экономична")
    print(f"   Бот будет использовать именно эту модель")
else:
    print(f"\n⚠️ ПРЕДУПРЕЖДЕНИЕ!")
    print(f"   Модель '{rockapi_model}' НЕ в списке разрешённых")
    print(f"   Это может быть дорогая модель!")
    print(f"\n🛡️ АВТОМАТИЧЕСКАЯ ЗАЩИТА:")
    print(f"   Бот автоматически переключится на 'deepseek-chat'")
    print(f"   и выдаст предупреждение в логах")
    
    print(f"\n💡 РЕКОМЕНДАЦИЯ:")
    print(f"   Установите: export ROCKAPI_MODEL=deepseek-chat")

# Проверка других переменных
print(f"\n{'─'*60}")
print("ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ")
print(f"{'─'*60}")

rockapi_key = os.getenv('ROCKAPI_KEY', '')
if rockapi_key:
    print(f"✅ ROCKAPI_KEY: установлен ({len(rockapi_key)} символов)")
else:
    print(f"❌ ROCKAPI_KEY: НЕ установлен")

rockapi_base_url = os.getenv('ROCKAPI_BASE_URL', 'https://api.rockapi.ru/deepseek')
print(f"✅ ROCKAPI_BASE_URL: {rockapi_base_url}")

comment_provider = os.getenv('COMMENT_PROVIDER', 'rockapi')
print(f"✅ COMMENT_PROVIDER: {comment_provider}")

# Итоги
print(f"\n{'='*60}")
print("ИТОГИ")
print(f"{'='*60}")

if rockapi_model in ALLOWED_MODELS and rockapi_key:
    print("✅ Конфигурация корректна")
    print("✅ Используется недорогая модель deepseek-chat")
    print("✅ Защита от случайного использования дорогих моделей активна")
    sys.exit(0)
elif not rockapi_key:
    print("⚠️ Не установлен ROCKAPI_KEY")
    print("   Установите: export ROCKAPI_KEY=ваш_ключ")
    sys.exit(1)
else:
    print("⚠️ Указана неразрешённая модель")
    print("   Бот автоматически переключится на deepseek-chat")
    print("   Но лучше исправить переменную окружения")
    sys.exit(0)

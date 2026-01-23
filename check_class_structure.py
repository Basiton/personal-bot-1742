#!/usr/bin/env python3
"""
Проверка структуры класса UltimateCommentBot
"""

import sys
import inspect

# Импортируем класс
sys.path.insert(0, '/workspaces/personal-bot-1742')
from main import UltimateCommentBot

print("=" * 70)
print("ПРОВЕРКА СТРУКТУРЫ КЛАССА UltimateCommentBot")
print("=" * 70)
print()

# Получаем все методы класса
methods = [name for name, method in inspect.getmembers(UltimateCommentBot, predicate=inspect.ismethod)]
functions = [name for name, func in inspect.getmembers(UltimateCommentBot, predicate=inspect.isfunction)]

print("📋 Все методы класса:")
print("-" * 70)
all_methods = sorted(set(methods + functions))
for method in all_methods:
    print(f"  • {method}")

print()
print("=" * 70)
print("🔍 ПОИСК МЕТОДОВ SHOWCASE")
print("=" * 70)
print()

showcase_methods = [m for m in all_methods if 'showcase' in m.lower()]

if showcase_methods:
    print(f"✅ Найдено {len(showcase_methods)} методов showcase:")
    print()
    for method in showcase_methods:
        print(f"  ✓ {method}")
else:
    print("❌ НЕ НАЙДЕНО методов showcase!")

print()
print("=" * 70)
print("🎯 ПРОВЕРКА КОНКРЕТНЫХ МЕТОДОВ")
print("=" * 70)
print()

required_methods = [
    '_showcase_create',
    '_showcase_link',
    '_showcase_unlink',
    '_showcase_list',
    '_showcase_info',
    '_showcase_set'
]

all_ok = True
for method_name in required_methods:
    if hasattr(UltimateCommentBot, method_name):
        method = getattr(UltimateCommentBot, method_name)
        print(f"✅ {method_name}: НАЙДЕН")
        
        # Проверяем сигнатуру
        sig = inspect.signature(method)
        params = list(sig.parameters.keys())
        print(f"   Параметры: {params}")
    else:
        print(f"❌ {method_name}: НЕ НАЙДЕН")
        all_ok = False

print()
print("=" * 70)
if all_ok:
    print("✅ ВСЕ МЕТОДЫ НАЙДЕНЫ - СТРУКТУРА КОРРЕКТНА")
else:
    print("❌ МЕТОДЫ НЕ НАЙДЕНЫ - СТРУКТУРА НЕКОРРЕКТНА")
print("=" * 70)

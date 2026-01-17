#!/usr/bin/env python3
"""
Тестирование profile commands
Запускает бот и показывает логи в реальном времени
"""

import subprocess
import time
import sys

print("🚀 Запуск бота для тестирования profile commands...")
print("="*60)

# Останавливаем старые процессы
subprocess.run("pkill -9 -f 'python.*main.py'", shell=True, stderr=subprocess.DEVNULL)
time.sleep(2)

# Запускаем бот в фоне
process = subprocess.Popen(
    ["python3", "-u", "main.py"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    universal_newlines=True,
    bufsize=1
)

print(f"✅ Бот запущен (PID: {process.pid})")
print("="*60)
print("\n📋 ИНСТРУКЦИЯ ПО ТЕСТИРОВАНИЮ:\n")
print("1. Отправь боту команду /setname")
print("2. Выбери аккаунт (например, номер 1)")
print("3. Отправь новое имя (например: 'Test Name 001')")
print("4. Проверь логи ниже - ищи строки 'PROFILE UPDATE:'")
print("5. Проверь в реальном Telegram клиенте что имя изменилось")
print("\n💡 Что искать в логах:")
print("   - 'Account selected - phone=...' - какой аккаунт выбран")
print("   - 'Got user object - id=..., phone=...' - с каким аккаунтом работаем")
print("   - 'VERIFIED - Name change confirmed' - изменения применены")
print("\n" + "="*60)
print("📝 ЛОГИ БОТА:\n")

try:
    # Показываем логи в реальном времени
    for line in process.stdout:
        print(line, end='', flush=True)
        
        # Выделяем важные строки
        if 'PROFILE UPDATE:' in line:
            print(f"\n{'='*60}")
            print(f"⚡ ВАЖНО: {line.strip()}")
            print(f"{'='*60}\n")
            
except KeyboardInterrupt:
    print("\n\n🛑 Остановка бота...")
    process.terminate()
    process.wait()
    print("✅ Бот остановлен")
    sys.exit(0)

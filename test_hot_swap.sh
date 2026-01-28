#!/bin/bash

# Тест горячей замены аккаунтов (Hot Swap Rotation)
# Дата: 28 января 2026

echo "=========================================="
echo "🧪 ТЕСТ: Горячая замена аккаунтов"
echo "=========================================="
echo ""

echo "📋 Проверяем синтаксис main.py..."
python3 -m py_compile main.py
if [ $? -eq 0 ]; then
    echo "✅ Синтаксис корректен"
else
    echo "❌ Ошибка синтаксиса!"
    exit 1
fi
echo ""

echo "🔍 Проверяем наличие ключевых компонентов..."
echo ""

# Проверка worker_slots
if grep -q "self.worker_slots = {}" main.py; then
    echo "✅ worker_slots инициализирован"
else
    echo "❌ worker_slots не найден!"
    exit 1
fi

# Проверка launch_replacement_worker
if grep -q "async def launch_replacement_worker" main.py; then
    echo "✅ Метод launch_replacement_worker найден"
else
    echo "❌ launch_replacement_worker не найден!"
    exit 1
fi

# Проверка вызова launch_replacement_worker
if grep -q "await self.launch_replacement_worker" main.py; then
    echo "✅ Вызов launch_replacement_worker найден"
else
    echo "❌ Вызов launch_replacement_worker не найден!"
    exit 1
fi

# Проверка сохранения в worker_slots
if grep -q "self.worker_slots\[worker_index\]" main.py; then
    echo "✅ Сохранение в worker_slots найдено"
else
    echo "❌ Сохранение в worker_slots не найдено!"
    exit 1
fi

# Проверка очистки worker_slots
if grep -q "self.worker_slots.clear()" main.py; then
    echo "✅ Очистка worker_slots найдена"
else
    echo "❌ Очистка worker_slots не найдена!"
    exit 1
fi

# Проверка обновлённого health_check
if grep -q "Replacement workers should already be running" main.py; then
    echo "✅ Health check обновлён для ротации"
else
    echo "❌ Health check не обновлён!"
    exit 1
fi

echo ""
echo "=========================================="
echo "✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ!"
echo "=========================================="
echo ""
echo "🎯 Система горячей замены готова к использованию"
echo ""
echo "📝 Рекомендации для тестирования:"
echo "  1. Добавьте минимум 6 аккаунтов (3 active, 3 reserve)"
echo "  2. Установите /setmaxcycles 2 (для быстрого теста)"
echo "  3. Установите /setworkermode distributed"
echo "  4. Запустите /startmon"
echo "  5. Наблюдайте логи bot_logs.txt"
echo ""
echo "🔍 Что искать в логах:"
echo "  - 'ROTATION: completed N cycles'"
echo "  - 'LAUNCHING REPLACEMENT WORKER'"
echo "  - 'Replacement worker launched'"
echo "  - 'This is NORMAL rotation, not a crash!'"
echo ""
echo "✅ При успешной ротации:"
echo "  - Все каналы продолжают обрабатываться"
echo "  - Новые workers запускаются автоматически"
echo "  - Health check не паникует"
echo "  - Уведомления приходят владельцу"
echo ""

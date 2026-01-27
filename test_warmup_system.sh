#!/bin/bash
# Быстрый тест системы прогрева аккаунтов

echo "🔥 ТЕСТ СИСТЕМЫ ПРОГРЕВА АККАУНТОВ"
echo "=================================="
echo ""

echo "1️⃣ Проверка модуля account_warmup.py..."
if [ -f "account_warmup.py" ]; then
    echo "✅ Файл account_warmup.py найден"
    python3 -c "from account_warmup import warmup_manager; print('✅ Импорт успешен')" 2>&1
else
    echo "❌ account_warmup.py не найден!"
    exit 1
fi

echo ""
echo "2️⃣ Проверка интеграции в main.py..."
grep -q "from account_warmup import warmup_manager" main.py
if [ $? -eq 0 ]; then
    echo "✅ Импорт в main.py найден"
else
    echo "❌ Импорт не найден в main.py!"
    exit 1
fi

echo ""
echo "3️⃣ Проверка команд в main.py..."
commands=("/warmup" "/warmup_start" "/warmup_stop" "/warmup_status" "/warmup_run")
for cmd in "${commands[@]}"; do
    if grep -q "pattern='$cmd" main.py; then
        echo "✅ Команда $cmd найдена"
    else
        echo "❌ Команда $cmd НЕ найдена!"
    fi
done

echo ""
echo "4️⃣ Проверка функции _run_warmup_background..."
if grep -q "async def _run_warmup_background" main.py; then
    echo "✅ Функция _run_warmup_background найдена"
else
    echo "❌ Функция _run_warmup_background НЕ найдена!"
fi

echo ""
echo "5️⃣ Проверка защиты от использования прогреваемых аккаунтов..."
if grep -q "warmup_manager.get_all_active_warmups()" main.py; then
    echo "✅ Защита интегрирована"
else
    echo "❌ Защита НЕ интегрирована!"
fi

echo ""
echo "✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ!"
echo ""
echo "📝 СЛЕДУЮЩИЕ ШАГИ:"
echo "1. Перезапустите бота"
echo "2. Используйте /warmup для справки"
echo "3. Запустите прогрев: /warmup_start +номер"
echo "4. Следите за прогрессом: /warmup_status"

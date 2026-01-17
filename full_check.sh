#!/bin/bash
# Полная проверка бота после исправления синтаксиса

echo "🔍 ПОЛНАЯ ПРОВЕРКА БОТА" > check_report.txt
echo "======================" >> check_report.txt
echo "" >> check_report.txt

# 1. Проверка синтаксиса
echo "1️⃣ ПРОВЕРКА СИНТАКСИСА" >> check_report.txt
python3 -m py_compile main.py 2>> check_report.txt
if [ $? -eq 0 ]; then
    echo "   ✅ Синтаксис правильный" >> check_report.txt
else
    echo "   ❌ ОШИБКА СИНТАКСИСА" >> check_report.txt
    cat check_report.txt
    exit 1
fi
echo "" >> check_report.txt

# 2. Проверка ключевых функций
echo "2️⃣ КЛЮЧЕВЫЕ ФУНКЦИИ В КОДЕ" >> check_report.txt
if grep -q "worker_client = TelegramClient(StringSession(" main.py; then
    echo "   ✅ worker_client создание (оптимизация)" >> check_report.txt
else
    echo "   ❌ worker_client НЕ НАЙДЕН" >> check_report.txt
fi

if grep -q "3600 // target_rate" main.py; then
    echo "   ✅ Smart delays (умные задержки)" >> check_report.txt
else
    echo "   ❌ Smart delays НЕ НАЙДЕНЫ" >> check_report.txt
fi

if grep -q "async def handle_set_name(" main.py; then
    echo "   ✅ Profile commands (/setname)" >> check_report.txt
else
    echo "   ❌ Profile commands НЕ НАЙДЕНЫ" >> check_report.txt
fi

if grep -q "async def account_worker(" main.py; then
    echo "   ✅ account_worker (параллельные воркеры)" >> check_report.txt
else
    echo "   ❌ account_worker НЕ НАЙДЕН" >> check_report.txt
fi
echo "" >> check_report.txt

# 3. Остановка старого процесса
echo "3️⃣ ПОДГОТОВКА К ЗАПУСКУ" >> check_report.txt
pkill -9 -f "python.*main.py" 2>/dev/null
sleep 2
echo "   ✅ Старые процессы остановлены" >> check_report.txt
echo "" >> check_report.txt

# 4. Запуск бота
echo "4️⃣ ЗАПУСК БОТА" >> check_report.txt
python3 -u main.py > /tmp/bot_live.log 2>&1 &
BOT_PID=$!
echo "   📝 PID: $BOT_PID" >> check_report.txt
sleep 8
echo "" >> check_report.txt

# 5. Проверка что бот запустился
echo "5️⃣ ПРОВЕРКА ЗАПУСКА" >> check_report.txt
if ps -p $BOT_PID > /dev/null; then
    echo "   ✅ Бот работает (PID: $BOT_PID)" >> check_report.txt
else
    echo "   ❌ Бот не запустился" >> check_report.txt
    echo "" >> check_report.txt
    echo "ЛОГИ ОШИБКИ:" >> check_report.txt
    cat /tmp/bot_live.log >> check_report.txt
    cat check_report.txt
    exit 1
fi
echo "" >> check_report.txt

# 6. Анализ логов запуска
echo "6️⃣ ЛОГИ ЗАПУСКА (первые 30 строк)" >> check_report.txt
head -30 /tmp/bot_live.log >> check_report.txt
echo "" >> check_report.txt

# 7. Проверка ключевых событий
echo "7️⃣ КЛЮЧЕВЫЕ СОБЫТИЯ" >> check_report.txt
if grep -q "ULTIMATE ЗАПУЩЕН" /tmp/bot_live.log; then
    echo "   ✅ Бот успешно запущен" >> check_report.txt
else
    echo "   ⚠️ Сообщение о запуске не найдено (возможно еще не успел)" >> check_report.txt
fi

if grep -q "Account statuses initialized" /tmp/bot_live.log; then
    STATS=$(grep "Account statuses initialized" /tmp/bot_live.log | tail -1)
    echo "   ✅ Статусы аккаунтов: $STATS" >> check_report.txt
else
    echo "   ⚠️ Статусы аккаунтов не инициализированы" >> check_report.txt
fi
echo "" >> check_report.txt

# 8. Финальный статус
echo "8️⃣ ФИНАЛЬНЫЙ СТАТУС" >> check_report.txt
echo "   🤖 Бот запущен и работает (PID: $BOT_PID)" >> check_report.txt
echo "   📋 Для проверки параллельных воркеров отправь боту /start" >> check_report.txt
echo "   📝 Логи в реальном времени: tail -f /tmp/bot_live.log" >> check_report.txt
echo "" >> check_report.txt

echo "======================" >> check_report.txt
echo "✅ ПРОВЕРКА ЗАВЕРШЕНА" >> check_report.txt

# Вывод отчета
cat check_report.txt

echo ""
echo "💡 СЛЕДУЮЩИЕ ШАГИ:"
echo "1. Отправь боту /start для активации автокомментирования"
echo "2. Проверь логи: tail -f /tmp/bot_live.log | grep -E 'WORKER|PARALLEL'"
echo "3. Бот работает в фоне, PID: $BOT_PID"

#!/bin/bash
# Быстрый перезапуск бота

echo "🔄 Останавливаю бота..."
pkill -f "python.*main.py"
sleep 2

echo "📋 Копирую обновленный main.py..."
cp /workspaces/personal-bot-1742/main.py /root/bot/main.py
cp /workspaces/personal-bot-1742/config_manager.py /root/bot/config_manager.py 2>/dev/null || true
cp /workspaces/personal-bot-1742/account_warmup.py /root/bot/account_warmup.py 2>/dev/null || true

echo "🚀 Запускаю бота..."
cd /root/bot && nohup python3 main.py >> bot.log 2>&1 &

sleep 1

if ps aux | grep "python.*main.py" | grep -v grep > /dev/null; then
    echo "✅ Бот успешно перезапущен!"
    ps aux | grep "python.*main.py" | grep -v grep
else
    echo "❌ Ошибка запуска, смотрите логи:"
    tail -20 /root/bot/bot.log
fi

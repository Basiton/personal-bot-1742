# ⚡ БЫСТРОЕ ПРИМЕНЕНИЕ ИСПРАВЛЕНИЯ

## 🎯 Что делает это обновление?

Исправляет критический баг из-за которого **0 комментариев за 14 часов**:
- ✅ Автоматическая миграция статусов аккаунтов
- ✅ Исправление hot-swap механизма
- ✅ Воркеры теперь восстанавливаются автоматически

---

## 📋 Команды для сервера (копируй и вставляй):

```bash
# 1. Остановка бота
sudo systemctl stop comapc-bot

# 2. Бэкап данных
sudo cp /root/bot/bot_data.json /root/bot/bot_data.json.backup_$(date +%Y%m%d_%H%M%S)

# 3. Обновление кода
cd /root/bot
sudo git pull origin main

# 4. Запуск бота
sudo systemctl start comapc-bot

# 5. Просмотр логов (Ctrl+C для выхода)
sudo journalctl -u comapc-bot -f
```

---

## ✅ Что должно появиться в логах:

```
⚠️ Loading from OLD structure 'accounts' - will migrate on save
🔄 Удалено старое поле 'active=True' для +447380198512
🔄 Удалено старое поле 'active=True' для +447588477457
...
✅ Account statuses initialized: 1 active, 14 reserve, 3 broken
Data saved successfully
```

---

## 🔍 Проверка после запуска:

**В Telegram боте:**
```
/listaccounts
```

Должны увидеть корректные статусы (active/reserve/broken).

**Если все аккаунты стали reserve (безопасная миграция):**
```
/toggleaccount +447380198512
/toggleaccount +447588477457
/toggleaccount +номер_третьего_аккаунта
```

Это активирует 3 аккаунта вручную.

**Затем запустить комментирование:**
```
/start
```

---

## 📊 Проверка что всё работает:

```bash
# Проверить что воркеры создались
sudo journalctl -u comapc-bot --since "2 minutes ago" | grep "WORKER STARTED"

# Проверить структуру файла
sudo cat /root/bot/bot_data.json | grep -c '"accounts_data"'  # Должно быть 1
sudo cat /root/bot/bot_data.json | grep -c '"accounts":'       # Должно быть 0

# Проверить что старое поле 'active' удалено
sudo grep -c '"active":' /root/bot/bot_data.json  # Должно быть 0
```

---

## ⏱️ Время выполнения: ~2 минуты

**Готово!** 🎉

Подробности в [ROTATION_FIX_COMPLETE.md](ROTATION_FIX_COMPLETE.md)

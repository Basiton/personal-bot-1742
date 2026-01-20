# Восстановление 10 аккаунтов на production сервере

## На production сервере (/root/bot):

```bash
# 1. Проверяем что backup с 10 аккаунтами есть
ls -lh /root/bot/bot_data.json.manual_backup_20260119_160748

# 2. Если файла нет - проверяем другие backups
ls -lh /root/bot/bot_data.json.manual_backup_* | tail -5

# 3. Копируем backup в рабочий файл
cp /root/bot/bot_data.json.manual_backup_20260119_160748 /root/bot/bot_data.json

# 4. Убеждаемся что файл валидный JSON
python3 -c "import json; json.load(open('/root/bot/bot_data.json'))" && echo "✅ JSON валидный"

# 5. Получаем новый код с GitHub
cd /root/bot
git pull

# 6. Деплоим
./deploy.sh

# 7. Проверяем что все 10 аккаунтов загрузились
# В Telegram отправить боту:
# /listaccounts
# Должно показать все 10 аккаунтов
```

## Если backup файла нет на сервере:

Значит нужно найти где он сейчас находится:
- В Codespaces: `/workspaces/personal-bot-1742/`
- На другом сервере
- В локальной копии

И скопировать на production сервер:

```bash
# С локальной машины/Codespaces на сервер:
scp bot_data.json.manual_backup_20260119_160748 root@YOUR_SERVER:/root/bot/bot_data.json

# Потом на сервере:
cd /root/bot
git pull
./deploy.sh
```

## Автоматическая миграция

Новый код автоматически мигрирует старый формат:
- `"active": true` → `"status": "active"`
- `"active": false` → `"status": "reserve"`
- `"18622376920"` → `"+18622376920"` (добавляет + к номерам)

Все сессии сохранятся, ничего не сломается.

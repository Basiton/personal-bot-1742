# Правильный синтаксис Environment в systemd

## ✅ ПРАВИЛЬНО

```ini
[Service]
Environment="PYTHONUNBUFFERED=1"
Environment="YC_API_KEY=AQVN...ваш_ключ_здесь..."
Environment="YC_FOLDER_ID=b1g4or5i5s66hklqfg06"
```

**Почему:** Кавычки охватывают всю пару `NAME=value`. Значение переменной будет чистым, без лишних символов.

## ❌ НЕПРАВИЛЬНО

```ini
[Service]
Environment=YC_API_KEY="AQVN...ваш_ключ_здесь..."
Environment=YC_FOLDER_ID="b1g4or5i5s66hklqfg06"
```

**Почему:** Кавычки вокруг значения станут **частью значения**! 

В Python это будет выглядеть так:
```python
os.getenv('YC_API_KEY')  # Вернёт: "AQVNzbsejh3t..." (С КАВЫЧКАМИ!)
# А YandexGPT ожидает: AQVNzbsejh3t... (БЕЗ кавычек)
```

API будет получать заголовок:
```
Authorization: Api-Key "AQVNzbsejh3t..."  ❌ Неверно!
```

Вместо:
```
Authorization: Api-Key AQVNzbsejh3t...   ✅ Верно!
```

## 🔍 Как проверить

После настройки проверьте что переменные установлены правильно:

```bash
sudo systemctl show comapc-bot -p Environment
```

**Должно показать:**
```
Environment=PYTHONUNBUFFERED=1 YC_API_KEY=AQVNzbsejh3... YC_FOLDER_ID=b1g4or5i5...
```

**НЕ должно быть кавычек внутри значений!**

## 📝 Полный пример правильного unit-файла

```ini
[Unit]
Description=Comapc Telegram Comment Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/bot
ExecStart=/usr/bin/python3 /root/bot/main.py
Restart=always
RestartSec=10

# Переменные окружения (ПРАВИЛЬНЫЙ СИНТАКСИС)
Environment="PYTHONUNBUFFERED=1"
Environment="YC_API_KEY=AQVN...ваш_ключ_здесь..."
Environment="YC_FOLDER_ID=b1g4or5i5s66hklqfg06"

# Логирование
StandardOutput=journal
StandardError=journal
SyslogIdentifier=comapc-bot

[Install]
WantedBy=multi-user.target
```

## 🎯 Правила systemd Environment

1. **Формат:** `Environment="NAME=value"`
2. **Кавычки** охватывают всю пару целиком
3. **Пробелы в значении:** используйте кавычки:
   ```ini
   Environment="MY_VAR=value with spaces"
   ```
4. **Несколько переменных** — каждая на отдельной строке:
   ```ini
   Environment="VAR1=value1"
   Environment="VAR2=value2"
   Environment="VAR3=value3"
   ```
5. **Или через пробел** (если нет пробелов в значениях):
   ```ini
   Environment="VAR1=value1" "VAR2=value2" "VAR3=value3"
   ```

## 🔧 Применение изменений

После редактирования unit-файла:

```bash
# 1. Перезагрузить systemd
sudo systemctl daemon-reload

# 2. Перезапустить бота
sudo systemctl restart comapc-bot

# 3. Проверить статус
sudo systemctl status comapc-bot

# 4. Проверить переменные
sudo systemctl show comapc-bot -p Environment

# 5. Проверить логи инициализации
sudo journalctl -u comapc-bot -n 100 | grep -A 15 "ПРОВЕРКА YANDEX GPT"
```

## 💡 Быстрая проверка правильности

Если в логах бота вы видите:

```
✅ YC_API_KEY найден: AQVNzbse***0p5
✅ YANDEX GPT: ВКЛЮЧЁН
```

Значит синтаксис **правильный** ✅

Если видите:

```
❌ API KEY НЕ НАЙДЕН!
```

Или при запросе к API ошибка 401 — проверьте что нет лишних кавычек в значении.

## 🐛 Отладка проблем с кавычками

Если подозреваете что в переменной есть лишние кавычки:

```bash
# Посмотрите переменные через systemctl
sudo systemctl show comapc-bot -p Environment

# Проверьте в логах бота что именно прочиталось
sudo journalctl -u comapc-bot -n 100 | grep "YC_API_KEY найден"

# Если там показывается ключ с кавычками внутри — исправьте синтаксис!
```


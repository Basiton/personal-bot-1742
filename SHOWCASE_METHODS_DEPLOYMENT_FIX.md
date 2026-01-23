# 🚨 SHOWCASE METHODS - ИНСТРУКЦИЯ ПО РАЗВЁРТЫВАНИЮ

## ✅ ПРОВЕРЕНО В WORKSPACE

Все методы showcase **ЕСТЬ** в файле `/workspaces/personal-bot-1742/main.py`:

```
2095:    async def _showcase_create(self, event, args_str):
2175:    async def _showcase_link(self, event, args_str):
2254:    async def _showcase_unlink(self, event, args_str):
2306:    async def _showcase_list(self, event):
2347:    async def _showcase_info(self, event, args_str):
2408:    async def _showcase_set(self, event, args_str):
```

Runtime проверка: **✅ ВСЕ МЕТОДЫ ДОСТУПНЫ**

## 🎯 ПРОБЛЕМА НА СЕРВЕРЕ

Ошибка: `'UltimateCommentBot' object has no attribute '_showcase_set'`

**Причина:** На сервере запущена **СТАРАЯ версия** main.py без этих методов

## 🔧 РЕШЕНИЕ: 5 ШАГОВ

### 1️⃣ Остановить бота на сервере

```bash
# Если используется systemd
systemctl stop comapc-bot.service

# Или найти и убить процесс
ps aux | grep main.py
kill -9 <PID>

# Или pkill
pkill -f "python.*main.py"
```

### 2️⃣ Проверить версию файла на сервере

```bash
# Проверить наличие методов
grep -n "async def _showcase_set" /root/bot/main.py
grep -n "async def _showcase_create" /root/bot/main.py
grep -n "async def _showcase_list" /root/bot/main.py
```

**Ожидаемый результат:**
```
2408:    async def _showcase_set(self, event, args_str):
2095:    async def _showcase_create(self, event, args_str):
2306:    async def _showcase_list(self, event):
```

**Если методы НЕ НАЙДЕНЫ** → файл устаревший, переходите к шагу 3

### 3️⃣ Обновить файл на сервере

#### Вариант А: Через Git (рекомендуется)

```bash
cd /root/bot
git pull origin main
```

#### Вариант Б: Через scp (если git не настроен)

```bash
# Из workspace
scp /workspaces/personal-bot-1742/main.py root@<server-ip>:/root/bot/main.py
```

#### Вариант В: Через cat/paste (если SSH есть)

```bash
# На сервере создать бэкап старого файла
cp /root/bot/main.py /root/bot/main.py.backup.$(date +%Y%m%d_%H%M%S)

# Затем скопировать новое содержимое
# (используйте nano/vim для вставки)
nano /root/bot/main.py
```

### 4️⃣ Проверить синтаксис обновлённого файла

```bash
cd /root/bot
python3 -m py_compile main.py

# Если ошибок нет - отлично!
# Если есть ошибки - проверьте что файл скопирован полностью
```

### 5️⃣ Запустить бота с новым файлом

```bash
# Через systemd
systemctl start comapc-bot.service

# Или напрямую
cd /root/bot
nohup python3 main.py > bot.log 2>&1 &

# Или через screen/tmux
screen -S bot
python3 main.py
# Ctrl+A+D для detach
```

### 6️⃣ Проверить запуск

```bash
# Подождать 5 секунд для инициализации
sleep 5

# Проверить логи
tail -50 /root/bot/bot.log

# Искать ошибки showcase
grep -i "showcase\|attributeerror" /root/bot/bot.log | tail -20

# Проверить что процесс запущен
ps aux | grep main.py
```

### 7️⃣ Протестировать команду

Откройте Telegram и отправьте боту:

```
/showcase list
```

**Ожидаемый результат:** 
- ✅ Список каналов или сообщение "У ваших аккаунтов пока нет каналов-витрин"
- ❌ **НЕ** должно быть ошибки `AttributeError`

## 🧪 СКРИПТ АВТОМАТИЧЕСКОЙ ПРОВЕРКИ

Создайте на сервере файл `check_showcase_methods.sh`:

```bash
#!/bin/bash

echo "═══════════════════════════════════════════════════════════════"
echo "🔍 ПРОВЕРКА МЕТОДОВ SHOWCASE"
echo "═══════════════════════════════════════════════════════════════"

FILE="/root/bot/main.py"

echo ""
echo "1️⃣ Проверка существования файла..."
if [ -f "$FILE" ]; then
    echo "   ✅ Файл найден: $FILE"
else
    echo "   ❌ Файл НЕ НАЙДЕН: $FILE"
    exit 1
fi

echo ""
echo "2️⃣ Проверка методов showcase..."

METHODS=(
    "_showcase_create"
    "_showcase_link"
    "_showcase_unlink"
    "_showcase_list"
    "_showcase_info"
    "_showcase_set"
)

ALL_FOUND=true

for method in "${METHODS[@]}"; do
    if grep -q "async def $method(self, event" "$FILE"; then
        LINE=$(grep -n "async def $method(self, event" "$FILE" | cut -d: -f1)
        echo "   ✅ $method (строка $LINE)"
    else
        echo "   ❌ $method НЕ НАЙДЕН"
        ALL_FOUND=false
    fi
done

echo ""
echo "3️⃣ Проверка обработчика showcase_command..."
if grep -q "async def showcase_command(event):" "$FILE"; then
    LINE=$(grep -n "async def showcase_command(event):" "$FILE" | cut -d: -f1)
    echo "   ✅ showcase_command найден (строка $LINE)"
else
    echo "   ❌ showcase_command НЕ НАЙДЕН"
    ALL_FOUND=false
fi

echo ""
echo "4️⃣ Проверка вызовов методов в обработчике..."
if grep -q "await self._showcase_set" "$FILE"; then
    echo "   ✅ Вызов self._showcase_set найден"
else
    echo "   ❌ Вызов self._showcase_set НЕ НАЙДЕН"
    ALL_FOUND=false
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"

if [ "$ALL_FOUND" = true ]; then
    echo "✅ ВСЕ МЕТОДЫ НАЙДЕНЫ - ФАЙЛ АКТУАЛЬНЫЙ"
    echo "═══════════════════════════════════════════════════════════════"
    exit 0
else
    echo "❌ НЕКОТОРЫЕ МЕТОДЫ НЕ НАЙДЕНЫ - ТРЕБУЕТСЯ ОБНОВЛЕНИЕ"
    echo "═══════════════════════════════════════════════════════════════"
    exit 1
fi
```

Сделайте его исполняемым и запустите:

```bash
chmod +x check_showcase_methods.sh
./check_showcase_methods.sh
```

## 📊 КОНТРОЛЬНАЯ ТАБЛИЦА

| Проверка | Команда | Ожидаемый результат |
|----------|---------|-------------------|
| Методы в файле | `grep "async def _showcase_set" main.py` | Строка 2408 |
| Обработчик | `grep "async def showcase_command" main.py` | Строка ~6025 |
| Синтаксис | `python3 -m py_compile main.py` | Нет ошибок |
| Процесс запущен | `ps aux \| grep main.py` | Процесс найден |
| Логи без ошибок | `tail -50 bot.log \| grep AttributeError` | Пусто |
| Команда работает | `/showcase list` в Telegram | Нормальный ответ |

## 🎯 ИТОГ

После выполнения всех шагов:

1. ✅ Файл на сервере обновлён
2. ✅ Все методы showcase на месте
3. ✅ Бот перезапущен с новым кодом
4. ✅ Команды `/showcase` работают

Напишите в чат: **✅ SHOWCASE METHODS DEPLOYED**

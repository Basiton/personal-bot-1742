# 🚀 Краткая инструкция: Добавление аккаунтов через Auth Key/tdata

## Что это даёт?

✅ Вход в аккаунты **без SMS кода**  
✅ Поддержка **российских номеров**  
✅ Работа через **прокси**  
✅ Импорт из **Telegram Desktop** (tdata)  
✅ Импорт через **Auth Key** (HEX)

## Быстрый старт

### 1️⃣ Конвертация в StringSession

```bash
python3 convert_session.py
```

Выберите источник:
- `1` - Auth Key (512 символов HEX)
- `2` - tdata папка (из Telegram Desktop)
- `3` - .session файл (из другого бота)

### 2️⃣ Добавление в бота

```
/addaccount +79991112233 1BVtsOHsBu... Имя
```

С прокси:
```
/addaccount +79991112233 1BVtsOHsBu... Имя socks5:host:1080:user:pass
```

### 3️⃣ Активация

```
/toggleaccount +79991112233
```

## Где взять Auth Key?

### Вариант 1: Telegram Desktop → tdata

Папка tdata обычно находится:
- **Windows**: `%APPDATA%\Telegram Desktop\tdata`
- **macOS**: `~/Library/Application Support/Telegram Desktop/tdata`
- **Linux**: `~/.local/share/TelegramDesktop/tdata`

Используйте:
```bash
python3 convert_session.py
# Выберите: 2. tdata папка
```

### Вариант 2: Готовый Auth Key

Если у вас уже есть Auth Key (512 HEX символов):
```bash
python3 convert_session.py
# Выберите: 1. Auth Key
```

## Форматы прокси

```
socks5:host:port:user:pass
socks4:host:port:user:pass
http:host:port:user:pass
```

## Примеры

**Без прокси:**
```
/addaccount +79991112233 1BVtsOHsBu7w9MbxjSg... Александр
```

**С SOCKS5 прокси:**
```
/addaccount +79991112233 1BVtsOHsBu7w9... Александр socks5:proxy.example.com:1080:myuser:mypass
```

**Минимальный (имя подставится автоматически):**
```
/addaccount +79991112233 1BVtsOHsBu7w9MbxjSg...
```

## Проверка

После добавления проверьте:
```
/listaccounts
```

Аккаунт должен появиться со статусом 🔵 **RESERVE**.

Для активации:
```
/toggleaccount +79991112233
```

Статус изменится на ✅ **ACTIVE**.

## Зависимости

Для работы с tdata нужна библиотека:
```bash
pip install opentele
```

## Помощь

Подробная инструкция: [AUTH_KEY_TDATA_GUIDE.md](AUTH_KEY_TDATA_GUIDE.md)

---

**✅ Готово!** Теперь можно добавлять аккаунты без SMS кодов.

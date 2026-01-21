# 🔧 ТЕХНИЧЕСКАЯ ДОКУМЕНТАЦИЯ: Showcase Channels

## 📐 Архитектура

### Основные компоненты

```
UltimateCommentBot
  └── create_showcase_channel()  # Основная функция создания
      ├── Проверка аккаунта
      ├── Генерация username
      ├── Проверка доступности
      ├── Создание канала
      ├── Установка username
      └── Сохранение данных

Bot Commands
  └── /createshowcase  # Команда для пользователей
      └── Вызов create_showcase_channel()
```

---

## 📋 Функция `create_showcase_channel`

### Сигнатура
```python
async def create_showcase_channel(
    self, 
    account_num: Union[int, str], 
    base_username: str = 'showcase'
) -> Tuple[bool, Union[dict, str]]
```

### Параметры

| Параметр | Тип | Описание | По умолчанию |
|----------|-----|----------|--------------|
| `account_num` | `int` or `str` | Номер аккаунта (1-10) или полный номер телефона | - |
| `base_username` | `str` | Базовый username для генерации вариантов | `'showcase'` |

### Возвращаемое значение

**Success (True):**
```python
(True, {
    'username': 'showcase_1',
    'channel_id': 1234567890,
    'phone': '+13434919340',
    'title': 'Showcase John'
})
```

**Failure (False):**
```python
(False, "❌ Описание ошибки")
```

---

## 🔄 Алгоритм работы

### 1. Определение номера телефона

```python
if isinstance(account_num, int) or account_num.isdigit():
    # Это номер аккаунта (1-10)
    account_key = f"ACCOUNT{account_num}_SESSION"
    session_str = os.getenv(account_key)
    
    # Ищем телефон по session
    for phone, data in self.accounts_data.items():
        if data.get('session') == session_str:
            break
else:
    # Это полный номер телефона
    phone = account_num if account_num.startswith('+') else '+' + account_num
```

### 2. Генерация вариантов username

```python
username_variants = [
    base_username,                    # showcase
    f"{base_username}{account_num}",  # showcase1
    f"{base_username}_{account_num}", # showcase_1
]

# Добавляем случайные варианты
for _ in range(7):
    random_suffix = ''.join(random.choices(
        string.ascii_lowercase + string.digits, 
        k=6
    ))
    username_variants.append(f"{base_username}_{random_suffix}")
```

**Итого:** 10 вариантов username

### 3. Проверка доступности

```python
for variant in username_variants:
    try:
        entity = await client.get_entity(variant)
        # Канал существует → username занят
        continue
    except ValueError:
        # Канал не найден → username свободен!
        free_username = variant
        break
```

**Логика:**
- `get_entity()` находит канал → username занят
- `ValueError` → канал не найден → username свободен ✅

### 4. Создание канала

```python
result = await client(CreateChannelRequest(
    title=f"Showcase {account_name}",
    about="",
    broadcast=True,    # Публичный канал
    megagroup=False    # Не мегагруппа
))

created_channel = result.chats[0]
channel_id = created_channel.id
```

### 5. Установка username

```python
await client(UpdateUsernameRequest(
    channel=created_channel,
    username=free_username
))
```

**Обработка ошибок:**
- `UsernameOccupiedError` → username был занят между проверкой и установкой
- `UsernameInvalidError` → некорректный формат username

### 6. Сохранение данных

```python
showcase_info = {
    'username': free_username,
    'channel_id': channel_id,
    'title': channel_title,
    'created': datetime.now().isoformat()
}

account_data['showcase_channel'] = showcase_info
self.save_data()  # Сохраняем в bot_data.json
```

---

## 🎯 Команда `/createshowcase`

### Реализация

```python
@self.bot_client.on(events.NewMessage(pattern='/createshowcase'))
async def createshowcase_command(event):
    # 1. Проверка прав доступа
    if not await self.is_admin(event.sender_id):
        return
    
    # 2. Парсинг аргументов
    parts = event.text.split(maxsplit=2)
    account_identifier = parts[1]
    base_username = parts[2] if len(parts) > 2 else 'showcase'
    
    # 3. Вызов функции создания
    success, result = await self.create_showcase_channel(
        account_identifier, 
        base_username
    )
    
    # 4. Отправка результата
    if success:
        await event.respond(formatted_success_message)
    else:
        await event.respond(result)  # Ошибка
```

### Формат команды

```
/createshowcase <account_num> [base_username]
```

**Примеры:**
- `/createshowcase 1` → `create_showcase_channel(1, 'showcase')`
- `/createshowcase +1234567890` → `create_showcase_channel('+1234567890', 'showcase')`
- `/createshowcase 1 vitrine` → `create_showcase_channel(1, 'vitrine')`

---

## 🗄️ Структура данных

### В bot_data.json

```json
{
  "accounts": {
    "+13434919340": {
      "name": "John",
      "session": "...",
      "status": "active",
      "showcase_channel": {
        "username": "showcase_1",
        "channel_id": 1234567890,
        "title": "Showcase John",
        "created": "2026-01-21T10:30:00.123456"
      }
    }
  }
}
```

### Поля showcase_channel

| Поле | Тип | Описание |
|------|-----|----------|
| `username` | `str` | Username канала (без @) |
| `channel_id` | `int` | ID канала в Telegram |
| `title` | `str` | Название канала |
| `created` | `str` | ISO timestamp создания |

---

## ⚠️ Обработка ошибок

### FloodWaitError

```python
except FloodWaitError as e:
    logger.error(f"FloodWait: нужно подождать {e.seconds} секунд")
    return False, f"❌ Слишком частые запросы. Подождите {e.seconds} секунд"
```

**Причина:** Telegram ограничивает частоту создания каналов  
**Решение:** Подождать указанное время

### UsernameOccupiedError

```python
except UsernameOccupiedError:
    logger.error(f"❌ Username @{free_username} внезапно стал занят")
    return False, f"❌ Username @{free_username} был занят между проверкой и установкой"
```

**Причина:** Username был занят между проверкой и установкой  
**Решение:** Race condition - очень редко, повторить попытку

### UsernameInvalidError

```python
except UsernameInvalidError:
    logger.error(f"❌ Username @{free_username} некорректен")
    return False, f"❌ Username @{free_username} некорректен"
```

**Причина:** Username не соответствует правилам Telegram  
**Решение:** Изменить базовый username

### ValueError (норма!)

```python
try:
    entity = await client.get_entity(variant)
    # Канал найден → занят
except ValueError:
    # Канал НЕ найден → свободен! ✅
    free_username = variant
    break
```

**Это НЕ ошибка!** ValueError означает, что username свободен.

---

## 🔐 Безопасность

### Проверка прав доступа

```python
if not await self.is_admin(event.sender_id):
    return
```

**Только админы** могут создавать showcase-каналы.

### Проверка авторизации

```python
if not await client.is_user_authorized():
    await client.disconnect()
    return False, f"❌ Аккаунт {phone} потерял авторизацию"
```

Перед созданием проверяется, что аккаунт авторизован.

### Проверка дубликатов

```python
if account_data.get('showcase_channel'):
    existing = account_data['showcase_channel']
    return False, f"❌ У аккаунта уже есть showcase-канал: @{existing['username']}"
```

Один аккаунт = один showcase-канал.

---

## 📊 Логирование

### Ключевые события

```python
logger.info(f"🎨 Создание showcase-канала для {phone} с базовым username '{base_username}'")
logger.info(f"🔍 Проверка доступности username: @{variant}")
logger.info(f"✅ Username @{variant} свободен!")
logger.info(f"🎯 Найден свободный username: @{free_username}")
logger.info(f"📺 Создание канала '{channel_title}'...")
logger.info(f"✅ Канал создан с ID: {channel_id}")
logger.info(f"🔧 Установка username @{free_username} для канала...")
logger.info(f"✅ Username @{free_username} установлен")
logger.info(f"✅ Showcase-канал создан: @{free_username} (ID: {channel_id})")
```

### Ошибки

```python
logger.error(f"❌ Username @{free_username} внезапно стал занят")
logger.error(f"❌ Username @{free_username} некорректен")
logger.error(f"❌ Ошибка при установке username: {e}")
logger.error(f"Error creating showcase channel: {e}")
```

---

## 🧪 Тестирование

### Тест-кейсы

1. **Создание с номером аккаунта:**
   ```
   /createshowcase 1
   ```
   Ожидается: канал создан, username = showcase/showcase1/showcase_1

2. **Создание с номером телефона:**
   ```
   /createshowcase +13434919340
   ```
   Ожидается: канал создан для конкретного номера

3. **Создание с кастомным username:**
   ```
   /createshowcase 1 vitrine
   ```
   Ожидается: username начинается с 'vitrine'

4. **Попытка создать второй канал:**
   ```
   /createshowcase 1
   ```
   Ожидается: ошибка "уже есть showcase-канал"

5. **Неавторизованный аккаунт:**
   ```
   /createshowcase 999
   ```
   Ожидается: ошибка "аккаунт не найден" или "не авторизован"

---

## 🔧 Зависимости

### Импорты

```python
from telethon.tl.functions.channels import (
    CreateChannelRequest,
    CheckUsernameRequest,
    UpdateUsernameRequest,
    GetChannelsRequest
)
from telethon.errors import (
    UsernameOccupiedError,
    UsernameInvalidError,
    FloodWaitError
)
from telethon.tl.types import Channel
import string
import random
```

### Telethon методы

- `CreateChannelRequest` - создание канала
- `UpdateUsernameRequest` - установка username
- `GetChannelsRequest` - получение информации о канале
- `client.get_entity()` - проверка существования username
- `client.is_user_authorized()` - проверка авторизации

---

## 📈 Производительность

### Время выполнения

- Проверка 1 username: ~0.5-1 сек
- Создание канала: ~1-2 сек
- Установка username: ~0.5-1 сек
- **Итого:** 2-10 сек (в зависимости от количества проверок)

### Оптимизация

1. **Генерация уникальных username:**
   - Используйте уникальные базовые username
   - Добавьте номер аккаунта в базовый username

2. **Batch операции:**
   - Создавайте каналы последовательно (избегайте FloodWait)
   - Интервал между созданиями: 5-10 сек

---

## 🔄 Будущие улучшения

### 1. Автоматическое добавление в витрину

**Проблема:** Telegram API не предоставляет публичный метод  
**Исследовать:**
- Undocumented API methods
- TDLib (Telegram Database Library)
- Userbot подход

### 2. Batch создание

```python
async def create_showcase_channels_batch(
    self, 
    account_nums: List[int], 
    base_username: str = 'showcase'
) -> List[Tuple[bool, Union[dict, str]]]
```

### 3. Управление showcase-каналами

```python
async def list_showcase_channels(self) -> List[dict]
async def delete_showcase_channel(self, account_num: int) -> Tuple[bool, str]
async def update_showcase_channel(self, account_num: int, **kwargs) -> Tuple[bool, str]
```

---

## 📚 API Reference

### create_showcase_channel

Создаёт уникальный публичный канал для аккаунта.

**Args:**
- `account_num` (int|str): Номер аккаунта или телефон
- `base_username` (str): Базовый username (default: 'showcase')

**Returns:**
- `Tuple[bool, Union[dict, str]]`: (success, result)

**Raises:**
- `FloodWaitError`: Слишком частые запросы
- `ValueError`: Аккаунт не найден (обрабатывается внутри)

**Example:**
```python
success, result = await bot.create_showcase_channel(1, 'shop')
if success:
    print(f"Канал создан: @{result['username']}")
else:
    print(f"Ошибка: {result}")
```

---

## 📝 Changelog

### v1.0.0 (2026-01-21)

**Added:**
- Функция `create_showcase_channel()` для создания уникальных каналов
- Команда `/createshowcase` для пользователей
- Автоматическая генерация и проверка username
- Сохранение информации в `bot_data.json`
- Полная документация и примеры

**Features:**
- 10 вариантов username с автоматической проверкой
- Поддержка номера аккаунта (1-10) и телефона
- Кастомные базовые username
- Обработка всех ошибок Telegram API
- Подробное логирование

---

## 🤝 Contributing

При разработке новых функций:

1. Следуйте существующей структуре кода
2. Добавляйте docstrings к функциям
3. Логируйте важные события
4. Обрабатывайте все возможные ошибки
5. Обновляйте документацию
6. Добавляйте тест-кейсы

---

## 📞 Support

- **Логи:** `bot_logs.txt`
- **Конфигурация:** `bot_data.json`
- **Документация:** `SHOWCASE_CHANNELS_GUIDE.md`
- **Быстрый старт:** `SHOWCASE_QUICK_START.md`

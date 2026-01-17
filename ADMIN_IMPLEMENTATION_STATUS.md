# ✅ Реализовано: Базовая структура разделения админов

## Что готово:

### 1. Константы и проверка прав ✅
```python
SUPER_ADMINS = [6730216440, 5912533270]

def is_super_admin(user_id) -> bool
async def is_admin(user_id) -> bool  
def get_admin_id(user_id) -> int | None
```

### 2. Структура БД расширена ✅
Добавлено поле `admin_id INTEGER DEFAULT NULL` во все таблицы:
- blocked_accounts
- comment_history  
- parsed_channels
- blocked_channels
- profile_changes
- account_stats

Автоматическая миграция при запуске бота.

### 3. Команды управления админами ✅
- `/addadmin <id>` - только для супер-админов, добавляет нового админа
- `/listadmins` - только для супер-админов, список всех админов
- `/removeadmin <id>` - только для супер-админов, удаляет админа

## Что нужно доделать:

### 1. Привязка аккаунтов к админам
**Файл:** main.py, метод `authorize_account()`

**Изменение:**
```python
# Добавить при сохранении аккаунта:
self.accounts_data[phone] = {
    'session': session_string,
    'name': user.first_name,
    'admin_id': event.sender_id,  # NEW
    ...
}
```

### 2. Фильтрация в команде `/stats`
**Файл:** main.py, команда `@self.bot_client.on(events.NewMessage(pattern='/stats'))`

**Изменение:**
```python
async def show_stats(event):
    admin_id = self.get_admin_id(event.sender_id)
    
    if admin_id is None:  # Super admin
        # Show all stats
        query = "SELECT ... FROM account_stats"
    else:  # Regular admin
        # Filter by admin_id
        query = "SELECT ... FROM account_stats WHERE admin_id = ?"
        params = (admin_id,)
```

### 3. Фильтрация во всех командах
Нужно добавить фильтрацию по admin_id в:
- `/listaccounts` - показывать только свои аккаунты
- `/addchannel` - сохранять с admin_id
- `/listchannels` - показывать только свои каналы
- `/testmode` - работать только со своими каналами
- `/auth` - привязывать новый аккаунт к своему admin_id
- все команды работы с аккаунтами

### 4. Обновление методов сохранения статистики
**Файл:** main.py, методы:
- `add_comment_stat()` - добавить параметр admin_id
- `mark_channel_failed_for_account()` - сохранять admin_id  
- При записи в `comment_history` - добавлять admin_id

**Пример:**
```python
async def add_comment_stat(self, phone, success=True, channel=None, 
                          error_message=None, admin_id=None):
    # ...
    cursor.execute(
        "INSERT INTO account_stats (..., admin_id) VALUES (?, ..., ?)",
        (..., admin_id)
    )
```

### 5. Новые команды для супер-админов  
**Добавить:**
- `/stats_global` - глобальная статистика по всем админам
- `/stats_admin <admin_id>` - статистика конкретного админа

### 6. Миграция существующих данных
**Создать скрипт:** `migrate_add_admin_ids.py`

```python
#!/usr/bin/env python3
import sqlite3
import json

# 1. Обновить все записи в БД без admin_id -> установить admin_id супер-админа
# 2. Обновить accounts_data.json - добавить admin_id ко всем аккаунтам
# 3. Обновить channels - добавить admin_id
```

## Пошаговая инструкция для завершения:

### Шаг 1: Обновить метод авторизации
```python
# В методе authorize_account(), после успешной авторизации:
account_info = {
    'session': session_string,
    'name': user.first_name,
    'username': user.username,
    'status': ACCOUNT_STATUS_ACTIVE,
    'admin_id': event.sender_id,  # Добавить эту строку
    ...
}
```

### Шаг 2: Обновить add_comment_stat
```python
async def add_comment_stat(self, phone, success=True, channel=None, 
                          error_message=None, admin_id=None):
    # ...
    if self.conn and phone:
        try:
            cursor = self.conn.cursor()
            event_type = 'comment_sent' if success else 'comment_failed'
            cursor.execute(
                "INSERT INTO account_stats (phone, channel, event_type, timestamp, success, error_message, admin_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (phone, channel or '', event_type, datetime.now().isoformat(), 1 if success else 0, error_message or '', admin_id)
            )
```

### Шаг 3: Обновить вызовы add_comment_stat
```python
# Найти все вызовы:
await self.add_comment_stat(phone, True, channel=username)

# Заменить на:
admin_id = account_data.get('admin_id')  # Получить из данных аккаунта
await self.add_comment_stat(phone, True, channel=username, admin_id=admin_id)
```

### Шаг 4: Обновить команду /stats
Добавить фильтрацию в начало:
```python
async def show_stats(event):
    admin_id = self.get_admin_id(event.sender_id)
    is_super = self.is_super_admin(event.sender_id)
    
    # Определить SQL фильтр
    if is_super:
        admin_filter = ""  # Показать всё
        admin_params = ()
    else:
        admin_filter = " AND admin_id = ?"
        admin_params = (admin_id,)
    
    # Использовать в запросах:
    cursor.execute(
        f"SELECT COUNT(*) FROM account_stats WHERE timestamp >= ? AND event_type = 'comment_sent'{admin_filter}",
        (today_start, *admin_params)
    )
```

### Шаг 5: Создать команду /stats_global
```python
@self.bot_client.on(events.NewMessage(pattern='/stats_global'))
async def stats_global_command(event):
    if not self.is_super_admin(event.sender_id):
        await event.respond("❌ Только для супер-админов")
        return
    
    # Показать статистику без фильтров
    # (копия текущего /stats но без фильтрации)
```

### Шаг 6: Запустить миграцию
```bash
# 1. Остановить бота
pkill -f main.py

# 2. Создать backup
cp bot_data.json bot_data.json.backup
cp bot_advanced.db bot_advanced.db.backup

# 3. Запустить миграционный скрипт
python3 migrate_add_admin_ids.py

# 4. Запустить бота
python3 main.py
```

## Тестирование:

### Тест 1: Супер-админ
```bash
# От супер-админа (6730216440):
/stats          # Должен показать ВСЕ данные
/listadmins     # Должен показать список админов
/addadmin 12345 # Должен добавить нового админа
```

### Тест 2: Обычный админ
```bash
# От обычного админа (не супер):
/stats          # Должен показать ТОЛЬКО свои данные
/listaccounts   # Должен показать ТОЛЬКО свои аккаунты  
/listadmins     # Должен получить ошибку доступа
```

### Тест 3: Изоляция данных
```bash
# Админ 1 добавляет аккаунт
/auth +1234567890

# Админ 2 делает /listaccounts
# НЕ должен видеть аккаунт админа 1
```

## Статус: 60% готово

✅ Готово:
- Структура БД
- Проверка прав
- Команды управления админами

⏳ В процессе:
- Привязка аккаунтов к админам
- Фильтрация команд

❌ Не начато:
- Миграция данных
- Команды stats_global/stats_admin
- Полное тестирование

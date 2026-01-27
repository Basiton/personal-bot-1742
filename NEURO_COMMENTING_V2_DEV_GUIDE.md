# Шпаргалка разработчика: Нейрокомментирование v2.0

## Ключевые методы

### 1. Защита от самокомментирования

```python
# Получить все свои аккаунты
my_accounts = self.get_my_account_ids()
# Возвращает: {phone: {'user_id': int, 'username': str}}

# Проверить, свой ли аккаунт
is_mine, phone = self.is_my_account(user_id=123, username='@user')
# Возвращает: (bool, phone или None)

# Получить авторов последних комментариев
recent_authors = await self.get_recent_thread_authors(client, discussion_entity, limit=5)
# Возвращает: [{'user_id': int, 'username': str, 'is_mine': bool, 'phone': str, 'message_id': int}]

# Проверить, можно ли комментировать
can_comment, reason = self.can_account_comment_on_post(phone, discussion_entity.id, recent_authors)
# Возвращает: (bool, str)
# Reasons: "ok", "account_already_commented_recently", "too_many_own_accounts_in_row", "avoid_own_account_loop"
```

### 2. Дедупликация комментариев

```python
# Проверить на дубликат
is_dup, reason = self.is_comment_duplicate(channel_username, comment_text, min_word_count=5)
# Возвращает: (bool, str)
# Reasons: "ok", "comment_too_short_N_words", "exact_duplicate_from_+phone", "similar_duplicate_N%_from_+phone"

# Добавить комментарий в историю
self.add_comment_to_history(channel_username, comment_text, phone)
```

### 3. Генерация комментариев

```python
# Генерация с выбором типа реакции
comment = generate_neuro_comment(
    post_text="Текст поста",
    channel_theme="технологии",
    temperature=0.8,
    max_tokens=120,
    comment_type="согласие"  # опционально, если None - выбирается случайно
)

# Типы реакций:
# - "согласие"
# - "уточнение"
# - "эмоция"
# - "благодарность"
# - "скептицизм"
# - "опыт"
```

### 4. Пост-обработка

```python
# Очистка и нормализация комментария
final_comment = humanize_comment(raw_comment)
# - Убирает лишние эмодзи (оставляет макс 1)
# - Удаляет формальные фразы
# - Убирает вводные слова
# - Упрощает конструкции
```

---

## Workflow комментирования

```python
# 1. Получить авторов последних комментариев
recent_authors = await self.get_recent_thread_authors(client, discussion_entity, limit=5)

# 2. Проверить, можно ли комментировать (защита от петель)
can_comment, reason = self.can_account_comment_on_post(phone, discussion_entity.id, recent_authors)
if not can_comment:
    logger.warning(f"⛔ Пропускаю: {reason}")
    continue

# 3. Генерировать комментарий (до 3 попыток)
comment = None
for attempt in range(3):
    temp_comment = generate_neuro_comment(post_text=post_text, channel_theme=theme)
    
    # 4. Проверить на дубликат
    is_dup, dup_reason = self.is_comment_duplicate(username, temp_comment, min_word_count=5)
    
    if not is_dup:
        comment = temp_comment
        break
    else:
        logger.warning(f"⚠️ Дубликат: {dup_reason} (попытка {attempt+1}/3)")

# 5. Если не получили уникальный комментарий - пропускаем
if not comment:
    logger.error("❌ Не удалось сгенерировать уникальный комментарий за 3 попытки")
    continue

# 6. Отправить комментарий
await client.send_message(discussion_entity, comment, reply_to=reply_id)

# 7. Сохранить в историю
self.add_comment_to_history(username, comment, phone)
self.register_message_sent(phone, username)
```

---

## Структура данных

### Аккаунт

```python
{
    'session': 'StringSession...',
    'name': 'Account Name',
    'username': '@username',
    'user_id': 123456789,  # <- Обязательно для защиты от самокомментирования
    'status': 'active',    # active / reserve / broken
    'proxy': 'socks5:host:port:user:pass',  # опционально
    'admin_id': 6730216440  # ID админа, который добавил аккаунт
}
```

### История комментариев

```python
self.recent_comments = {
    'channel_username': [
        ('comment_text', timestamp, phone),
        ('another_comment', timestamp, phone),
        # ... до 20 последних
    ]
}
```

### Авторы комментариев

```python
[
    {
        'user_id': 123456789,
        'username': '@user',
        'is_mine': True,
        'phone': '+79123456789',
        'message_id': 42
    },
    # ...
]
```

---

## Настройки

### Константы в коде

```python
# Минимальный интервал между комментариями от своих аккаунтов
MIN_INTERVAL_BETWEEN_OWN_ACCOUNTS = 300  # 5 минут

# Лимит хранимых комментариев на канал
self.recent_comments_limit = 20

# Вероятность использования эмодзи
use_emoji = random.random() < 0.22  # 22%

# Количество попыток генерации уникального комментария
for attempt in range(3):  # 3 попытки
```

### Config.json

```json
{
    "test_mode": false,
    "test_channels": [],
    "max_parallel_accounts": 2,
    "speed": 20,
    "rotation_interval": 14400,
    "worker_mode": "distributed",
    "max_cycles_per_worker": 3,
    "worker_recovery_enabled": true
}
```

---

## Логирование

### Уровни

```python
logger.info("✅ Нормальная работа")
logger.warning("⚠️ Предупреждение (не критично)")
logger.error("❌ Ошибка (требует внимания)")
```

### Ключевые сообщения

```python
# Защита от петель
logger.warning(f"⛔ [Account] Пропускаю @{channel}: {reason}")

# Дедупликация
logger.info(f"✅ [Account] Комментарий уникален (попытка {attempt+1}/3)")
logger.warning(f"⚠️ [Account] Дубликат: {reason} (попытка {attempt+1}/3)")

# Отправка
logger.info("="*80)
logger.info(f"{'🧪 TEST' if test_mode else '🚀 LIVE'} | COMMENT SENT")
logger.info(f"   Channel: @{username}")
logger.info(f"   Account: {account_name} ({phone[-10:]})")
logger.info(f"   Comment: {short_comment}...")
logger.info("="*80)
```

---

## Отладка

### Проверка данных аккаунта

```python
# Проверить наличие user_id
for phone, data in self.accounts_data.items():
    if 'user_id' not in data:
        print(f"❌ {phone}: нет user_id")
    else:
        print(f"✅ {phone}: user_id={data['user_id']}")
```

### Проверка истории комментариев

```python
# Показать последние комментарии в канале
channel = 'example'
if channel in self.recent_comments:
    for text, timestamp, phone in self.recent_comments[channel]:
        print(f"{phone}: {text[:30]}... ({datetime.fromtimestamp(timestamp)})")
```

### Тестирование дедупликации

```python
# Искусственно добавить комментарий
self.add_comment_to_history('test_channel', 'Тестовый комментарий', '+79123456789')

# Проверить дубликат
is_dup, reason = self.is_comment_duplicate('test_channel', 'Тестовый комментарий')
print(f"Дубликат: {is_dup}, причина: {reason}")
```

---

## Тестирование

### Unit-тесты

```python
# Тест защиты от самокомментирования
def test_can_comment():
    bot = UltimateCommentBot()
    
    # Создаем тестовые данные
    recent_authors = [
        {'user_id': 123, 'is_mine': True, 'phone': '+1234567890'},
        {'user_id': 456, 'is_mine': False, 'phone': None},
    ]
    
    # Тест 1: аккаунт не писал - можно
    can, reason = bot.can_account_comment_on_post('+9999999999', 123, recent_authors)
    assert can == True
    
    # Тест 2: аккаунт уже писал - нельзя
    can, reason = bot.can_account_comment_on_post('+1234567890', 123, recent_authors)
    assert can == False
    assert reason == "account_already_commented_recently"
```

### Интеграционные тесты

```python
# Тест полного цикла
async def test_full_cycle():
    bot = UltimateCommentBot()
    
    # 1. Проверить авторизацию
    await bot.verify_all_accounts()
    
    # 2. Активировать аккаунты
    for phone in ['+1111111111', '+2222222222']:
        bot.set_account_status(phone, 'active', 'test')
    
    # 3. Запустить мониторинг (короткий тест)
    bot.test_mode = True
    bot.test_channels = ['test_channel']
    await bot.start_monitoring()
```

---

## Частые проблемы

### Проблема: Нет user_id у аккаунтов

**Решение:**
```bash
/verify_sessions  # В Telegram боте
```

### Проблема: Комментарии повторяются

**Проверка:**
```python
# В логах должно быть
✅ [Account] Комментарий уникален (попытка 1/3)

# Если нет - проверить:
print(self.recent_comments.get('channel_name', []))
```

### Проблема: Все комментарии с эмодзи

**Проверка:**
```python
# В generate_neuro_comment должно быть:
use_emoji = random.random() < 0.22  # ~22%

# В humanize_comment должно быть:
elif emojis and random.random() < 0.75:  # 75% удаляем
```

### Проблема: Аккаунты создают петли

**Проверка:**
```python
# В логах должны быть:
⛔ [Account] Пропускаю @channel: avoid_own_account_loop

# Если нет - проверить:
recent_authors = await self.get_recent_thread_authors(...)
print(f"Recent authors: {recent_authors}")
```

---

## Производительность

### Оптимизация

1. **Кэширование клиентов:**
   ```python
   self.account_clients = {}  # Переиспользование клиентов
   ```

2. **Ограничение истории:**
   ```python
   self.recent_comments_limit = 20  # Не храним больше 20
   ```

3. **Быстрый выход:**
   ```python
   if not can_comment:
       continue  # Не тратим время на генерацию
   ```

---

## Расширение

### Добавить новый тип реакции

```python
# В generate_neuro_comment
reaction_types = [
    # ... существующие
    ("новый_тип", "описание для промпта")
]
```

### Изменить вероятность эмодзи

```python
# В generate_neuro_comment
use_emoji = random.random() < 0.30  # Увеличить до 30%

# В humanize_comment
elif emojis and random.random() < 0.60:  # Уменьшить удаление до 60%
```

### Добавить персональную БД комментариев

```python
def add_comment_to_history(self, channel, text, phone):
    # Сохранение в SQLite
    cursor.execute(
        "INSERT INTO comment_history (channel, text, phone, timestamp) VALUES (?, ?, ?, ?)",
        (channel, text, phone, datetime.now().timestamp())
    )
```

---

Это основные инструменты для работы с обновлённой системой нейрокомментирования v2.0! 🚀

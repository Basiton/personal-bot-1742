# 🔧 ИСПРАВЛЕНИЕ: Проблемы с ротацией и статусами аккаунтов

## Дата: 2026-02-03

## 🔴 Найденные проблемы:

### 1. Неправильная структура данных
**Проблема:** Код использовал старую структуру `"accounts"` вместо `"accounts_data"`

```python
# БЫЛО (НЕПРАВИЛЬНО):
self.accounts_data = data.get('accounts', {})  # Читает из 'accounts'

data = {
    'accounts': self.accounts_data,  # Сохраняет в 'accounts'
    ...
}
```

**Последствия:**
- Файл bot_data.json содержал `"accounts"` вместо `"accounts_data"`
- Смешивание старого формата (`"active": true`) и нового (`"status": "active"`)
- В логах `status=UNKNOWN` для аккаунтов без поля `status`

### 2. Некорректная миграция статусов
**Проблема:** Функция `init_account_statuses()` не обрабатывала аккаунты с одновременно:
- `"active": true` (старое поле)
- `"status": "active"` (новое поле)

**Последствия:**
- Аккаунты оставались с `status=UNKNOWN`
- Система не могла использовать резервные аккаунты
- После падения воркеров не происходила автоматическая замена

### 3. Воркеры не восстанавливались
**Проблема:** При падении аккаунтов система пыталась:
```
11:04 Starting new workers...
11:06 Starting new workers...
11:08 Starting new workers...
```

Но воркеры НЕ создавались потому что:
- Не было аккаунтов со статусом `active`
- Аккаунты со статусом `UNKNOWN` игнорировались
- Резервные аккаунты не активировались автоматически

---

## ✅ Исправления:

### 1. Правильная структура данных

**load_data():**
```python
# Автоматическая миграция из старой структуры
if 'accounts_data' in data and data['accounts_data']:
    self.accounts_data = data['accounts_data']  # Новая структура
    logger.info("✅ Loading from new structure 'accounts_data'")
elif 'accounts' in data and data['accounts']:
    self.accounts_data = data['accounts']  # Старая структура (мигрируем)
    logger.warning("⚠️ Loading from OLD structure 'accounts' - will migrate on save")
```

**save_data():**
```python
data = {
    'accounts_data': self.accounts_data,  # НОВАЯ структура
    'channels': self.channels,
    ...
}
```

### 2. Улучшенная миграция статусов

```python
def init_account_statuses(self):
    for phone, data in list(self.accounts_data.items()):
        # 1. Удаляем старое поле 'active' если есть
        if 'active' in data:
            old_active = data.pop('active')
            logger.info(f"🔄 Удалено старое поле 'active={old_active}'")
        
        # 2. Проверяем статус
        if 'status' not in data or not data['status']:
            # Нет статуса - назначаем reserve/broken
            if data.get('session'):
                data['status'] = ACCOUNT_STATUS_RESERVE
            else:
                data['status'] = ACCOUNT_STATUS_BROKEN
        
        # 3. Валидация статуса
        valid_statuses = ['active', 'reserve', 'broken']
        if data['status'] not in valid_statuses:
            logger.warning(f"⚠️ Неизвестный статус '{data['status']}' → reserve")
            data['status'] = ACCOUNT_STATUS_RESERVE
```

---

## 🎯 Что теперь работает:

### ✅ Правильная структура файла
После первого сохранения `bot_data.json` будет иметь:
```json
{
  "accounts_data": {
    "+447380198512": {
      "status": "reserve",
      "name": "Cxvovxrh",
      ...
    }
  }
}
```

### ✅ Корректные статусы
Все аккаунты получат валидный статус:
- `active` - используется для комментирования
- `reserve` - готов к активации
- `broken` - требует переавторизации

### ✅ Автоматическая ротация
При падении воркера система:
1. Находит резервные аккаунты (`status=reserve`)
2. Автоматически активирует их
3. Создаёт новые воркеры
4. Перераспределяет каналы

---

## 📋 Инструкция по применению:

### На сервере выполните:

1. **Остановите бота:**
```bash
sudo systemctl stop comapc-bot
```

2. **Сделайте бэкап:**
```bash
sudo cp /root/bot/bot_data.json /root/bot/bot_data.json.before_migration_$(date +%Y%m%d_%H%M%S)
```

3. **Обновите код:**
```bash
cd /root/bot
sudo git pull origin main
```

4. **Запустите бота (миграция произойдёт автоматически):**
```bash
sudo systemctl start comapc-bot
```

5. **Проверьте логи:**
```bash
sudo journalctl -u comapc-bot -f
```

Вы должны увидеть:
```
⚠️ Loading from OLD structure 'accounts' - will migrate on save
🔄 Удалено старое поле 'active=True' для ...
🔄 Миграция ...: пустой статус → reserve
✅ Account statuses initialized: 1 active, 14 reserve, 3 broken
Data saved successfully
```

6. **Проверьте статусы аккаунтов в боте:**
```
/listaccounts
```

---

## 🔍 Что проверить после миграции:

### 1. Структура файла
```bash
sudo cat /root/bot/bot_data.json | grep -E '"accounts"|"accounts_data"' | head -5
```

Должно быть только `"accounts_data"`, без `"accounts"`.

### 2. Статусы аккаунтов
```bash
sudo cat /root/bot/bot_data.json | grep -o '"status":[^,}]*' | sort | uniq -c
```

Не должно быть пустых или неизвестных статусов.

### 3. Поле 'active' удалено
```bash
sudo grep -c '"active":' /root/bot/bot_data.json
```

Должно быть `0`.

### 4. Воркеры запускаются
```bash
sudo journalctl -u comapc-bot --since "5 minutes ago" | grep -E "WORKER|worker"
```

Должны быть записи о создании воркеров.

---

## 🚨 Возможные проблемы и решения:

### Проблема: Все аккаунты стали reserve
**Причина:** Безопасная миграция - аккаунты с `active=true` переводятся в `reserve`

**Решение:**
```
/toggleaccount +номер_телефона
```

Активируйте нужные аккаунты вручную.

### Проблема: Воркеры не запускаются
**Причина:** Нет активных аккаунтов

**Решение:**
```
/listaccounts  # Посмотрите статусы
/toggleaccount +номер  # Активируйте 2-3 аккаунта
/start  # Перезапустите комментирование
```

---

## 📊 Результат:

**До исправления:**
```
10:59 - Старт с 3 воркерами
11:00 - Оля забанена
11:00-14:34 - 0 комментариев (воркеры не восстанавливались)
14:34 - Все воркеры умерли
```

**После исправления:**
```
✅ Автоматическая миграция статусов
✅ Правильная структура данных
✅ Автоматическая ротация при падении
✅ Валидация статусов аккаунтов
✅ Работающая hot-swap замена
```

---

**Создано:** 2026-02-03  
**Статус:** ✅ Готово к применению  
**Тестирование:** Требуется на сервере

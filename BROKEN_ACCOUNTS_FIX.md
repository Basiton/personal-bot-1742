# ✅ ИСПРАВЛЕНО: Обработка сломанных аккаунтов Telegram

## 🎯 Проблема

Аккаунты, которые были **удалены**, **деактивированы** или **забанены** в Telegram, не помечались автоматически как `broken`. Это приводило к тому что:

- ❌ Бот пытался использовать сломанные аккаунты для комментирования
- ❌ Воркеры падали с ошибками авторизации
- ❌ Статус `broken` приходилось выставлять вручную

## ✅ Что исправлено

### 1. **Добавлены импорты критических ошибок Telegram** 🔧

```python
from telethon.errors import (
    SessionPasswordNeededError,
    UserDeactivatedBanError,      # Аккаунт забанен/деактивирован
    AuthKeyUnregisteredError,     # Ключ авторизации недействителен
    PhoneNumberBannedError,        # Номер телефона забанен
    SessionRevokedError,           # Сессия отозвана
    UserDeactivatedError           # Аккаунт деактивирован
)
```

### 2. **Улучшена обработка ошибок в `account_worker`** 🔄

Теперь при отправке комментариев обрабатываются критические ошибки:

#### **Специфичные типы ошибок (try/except по типу):**
- `UserDeactivatedBanError` / `UserDeactivatedError` → `handle_account_ban()`
- `AuthKeyUnregisteredError` / `SessionRevokedError` → `handle_account_ban()`
- `PhoneNumberBannedError` → `handle_account_ban()`

#### **Резервная проверка (строковое совпадение):**
Для совместимости также проверяются строковые представления ошибок:
- `"USER_DEACTIVATED"`, `"UserDeactivatedBan"`
- `"AUTH_KEY_UNREGISTERED"`, `"AuthKeyUnregistered"`
- `"SESSION_REVOKED"`
- `"PHONE_NUMBER_BANNED"`

**Что происходит:**
1. ✅ Логируется критическая ошибка
2. ✅ Вызывается `handle_account_ban(phone, reason)`
3. ✅ Аккаунт помечается как `ACCOUNT_STATUS_BROKEN`
4. ✅ Активируется резервный аккаунт (если доступен)
5. ✅ Воркер прерывается (`break`)
6. ✅ Владелец получает уведомление

### 3. **Проверка при подключении клиента** 🔌

При создании и переподключении клиента в `account_worker` теперь:

#### **При создании нового клиента:**
```python
try:
    worker_client = TelegramClient(...)
    await worker_client.connect()
    
    if not await worker_client.is_user_authorized():
        await self.handle_account_ban(phone, "Not authorized (session expired)")
        return
        
except (UserDeactivatedBanError, UserDeactivatedError) as err:
    await self.handle_account_ban(phone, f"Account deactivated: {type(err).__name__}")
    return
    
except (AuthKeyUnregisteredError, SessionRevokedError) as err:
    await self.handle_account_ban(phone, f"Session invalid: {type(err).__name__}")
    return
    
except PhoneNumberBannedError as err:
    await self.handle_account_ban(phone, "Phone number banned")
    return
```

#### **При переподключении существующего клиента:**
Те же проверки применяются при переподключении отключенного клиента.

#### **Резервная проверка (строковая):**
Если ошибка не была поймана по типу, проверяются критические паттерны в строковом виде.

### 4. **Обработка в командах управления профилем** 👤

Команды `/setname`, `/setbio`, `/setavatar` теперь автоматически помечают аккаунты как `broken` при критических ошибках:

#### **Обрабатываемые ошибки:**
- ✅ `UserDeactivatedBanError` / `UserDeactivatedError`
- ✅ `AuthKeyUnregisteredError` / `SessionRevokedError`
- ✅ `PhoneNumberBannedError`
- ✅ Резервная проверка строковых паттернов

**Что происходит:**
1. Пользователь видит понятное сообщение об ошибке
2. Аккаунт автоматически помечается как `broken`
3. Владелец получает уведомление
4. Система активирует резервный аккаунт

**Пример сообщения пользователю:**
```
🚫 Аккаунт +1234567890 деактивирован Telegram

Аккаунт был удален или забанен Telegram.
❌ Статус изменён на: BROKEN

💡 Этот аккаунт больше нельзя использовать.
💡 Используйте /auth +1234567890 если хотите попробовать восстановить
```

## 🎯 Результат

Теперь система **автоматически обнаруживает** сломанные аккаунты и помечает их как `broken` в следующих случаях:

| Ситуация | Обработка | Результат |
|----------|-----------|-----------|
| Аккаунт удален пользователем в Telegram | ✅ Автоматически | `BROKEN` + уведомление |
| Аккаунт деактивирован Telegram | ✅ Автоматически | `BROKEN` + уведомление |
| Номер телефона забанен | ✅ Автоматически | `BROKEN` + уведомление |
| Сессия отозвана/недействительна | ✅ Автоматически | `BROKEN` + уведомление |
| Ключ авторизации невалиден | ✅ Автоматически | `BROKEN` + уведомление |
| Потеряна авторизация | ✅ Автоматически | `BROKEN` + уведомление |

## 🔄 Автоматическая замена

Когда аккаунт помечается как `broken`:
1. 🔄 Статус меняется на `ACCOUNT_STATUS_BROKEN`
2. 🔍 Система ищет резервный аккаунт
3. ✅ Резервный аккаунт активируется (`ACTIVE`)
4. 🚀 Запускается replacement worker на замену
5. 📊 Владелец получает уведомление с новым статусом
6. ♻️ Комментирование продолжается без простоя

## 📝 Логирование

Все критические ошибки теперь логируются с префиксом:
- `🚫` - Account deactivated
- `🔑` - Session invalid
- `⛔` - Phone number banned
- `🚨` - Critical error detected

**Пример лога:**
```
ERROR: 🚫 [Account1] ACCOUNT DEACTIVATED BY TELEGRAM!
ERROR:    Error: UserDeactivatedBanError(...)
ERROR:    This account is permanently banned/deleted
ERROR:    Marking as BROKEN...
```

## ✅ Тестирование

Для проверки работы:

1. **Проверьте текущие аккаунты:**
   ```
   /listaccounts
   ```

2. **Мониторьте логи при работе:**
   ```
   tail -f bot_logs.txt
   ```

3. **Проверьте автопометку при ошибке:**
   - Используйте команду `/setbio` с невалидным аккаунтом
   - Система должна автоматически пометить его как `broken`

## 🛡️ Защита

Теперь система полностью защищена от:
- ❌ Попыток использовать удаленные аккаунты
- ❌ Зависания воркеров из-за невалидных сессий  
- ❌ Повторных попыток подключения к забаненным аккаунтам
- ❌ Потери комментирования из-за сломанных аккаунтов

## 📊 Мониторинг

Используйте команды для проверки статуса:

- `/listaccounts` - посмотреть все аккаунты и их статусы
- `/incidents` - посмотреть историю критических ошибок
- `/stats` - общая статистика работы аккаунтов

---

**Дата исправления:** 8 февраля 2026  
**Статус:** ✅ ГОТОВО К ИСПОЛЬЗОВАНИЮ

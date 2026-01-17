# Быстрая проверка бота - 5 минут

## Шаг 1: Проверка команд профиля (2 мин)

```bash
# 1. В боте выполнить:
/listaccounts
# Запомнить номера и телефоны

# 2. Тест /setname
/setname
# Выбрать любой номер (например, 2)
# Ввести: Test Bot
# Проверить в Telegram - изменилось имя?

# 3. Проверить логи:
grep "PROFILE UPDATE: Account selected.*index=2" bot.log
grep "PROFILE UPDATE: SUCCESS - Name updated" bot.log | tail -1
```

**Ожидание:** Имя изменилось у аккаунта с номером 2 из списка `/listaccounts`

## Шаг 2: Проверка параллельности (3 мин)

```bash
# 1. Подготовка:
/listaccounts
# Убедиться: минимум 2 аккаунта со статусом ✅ active
# Если нет - активировать: /toggleaccount

/setparallel 2
/testmode on
/testchannels @channel1 @channel2  # замените на реальные
/startmon

# 2. Проверить логи:
grep "Total active accounts available:" bot.log | tail -1
grep "CREATING.*PARALLEL WORKERS" bot.log | tail -1
grep "WORKER STARTED:" bot.log | tail -2
grep "Client ready" bot.log | tail -2

# 3. Дождаться комментариев (30-60 сек):
grep "TEST MODE SUCCESS" bot.log | tail -4
```

**Ожидание:**
- `Total active accounts available: 2` (или больше)
- `CREATING 2 PARALLEL WORKERS`
- 2 строки `WORKER STARTED` для разных аккаунтов
- 2 строки `Client ready` для разных аккаунтов
- Комментарии от РАЗНЫХ аккаунтов

## Быстрая диагностика проблем

### ❌ Профиль не меняется
```bash
grep "PROFILE UPDATE.*phone=" bot.log | tail -20
```
Ищите:
- Правильный phone выбран?
- Есть `SUCCESS`?
- Есть ошибки?

### ❌ Только 1 воркер
```bash
grep "Total active accounts available:" bot.log | tail -1
grep "MAX_PARALLEL_ACCOUNTS setting:" bot.log | tail -1
```
- Если `Total active accounts: 1` → активируйте больше через `/toggleaccount`
- Если `MAX_PARALLEL_ACCOUNTS: 1` → увеличьте через `/setparallel 3`

### ❌ Комментарии только от одного аккаунта
```bash
grep "TEST MODE SUCCESS" bot.log | grep "Account:" | tail -10
```
Должны быть РАЗНЫЕ аккаунты. Если только один - проверьте, сколько воркеров создано.

## ✅ Всё работает, если:
1. Профиль меняется у правильного аккаунта
2. Создается N воркеров (N = количество активных или setparallel)
3. Комментарии идут от разных аккаунтов

---

Полная документация: [COMPREHENSIVE_CHECKUP.md](COMPREHENSIVE_CHECKUP.md)

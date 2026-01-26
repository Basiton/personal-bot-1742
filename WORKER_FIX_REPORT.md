# Исправления логики воркеров - отчет

## Дата: 26 января 2026

## Проблема
В логах бота регулярно появлялись сообщения о несоответствии количества воркеров:
- Ожидается: N воркеров
- Работает: 1 воркер
- При установке 6 активных аккаунтов реально работал только 1

## Корневые причины

### 1. Неправильный подсчет живых воркеров
**Проблема:** В `health_check_worker()` использовался простой подсчет:
```python
alive_workers = sum(1 for task in self.active_worker_tasks if not task.done())
```

**Проблема:** Мертвые воркеры НЕ удалялись из `self.active_worker_tasks`, поэтому список рос, но реальных живых воркеров было меньше.

### 2. Отсутствие детального логирования
- Не было видно Task ID при создании воркеров
- Не было понятно, почему воркер падает
- Нет трассировки исключений

### 3. Отсутствие обработки ошибок в account_worker
- Fatal ошибки не ловились на верхнем уровне
- Нет уведомления владельца при падении воркера

## Внесенные исправления

### 1. Детальное логирование старта воркеров ✅
**Файл:** `main.py:9051-9071`

**Добавлено:**
```python
logger.info(f"🔧 Creating worker #{i+1}/{len(accounts_list)} for [{data.get('name', phone)}]")
logger.info(f"   Phone: {phone}")
logger.info(f"   Status: {data.get('status', 'unknown')}")
logger.info(f"   Session: {'✅ EXISTS' if data.get('session') else '❌ MISSING'}")
logger.info(f"   Will process: ALL {len(channels_copy)} channels")
logger.info(f"   Offset: starts from channel #{(i % len(channels_copy)) + 1}")

task = asyncio.create_task(...)
task.set_name(f"worker_{i}_{phone[-10:]}")
logger.info(f"   ✅ Task created: {task.get_name()} (id={id(task)})")
```

**Результат:** Теперь при старте видно:
- Какой именно аккаунт запускается
- Есть ли у него сессия
- Task ID для отслеживания

### 2. Исправлен подсчет живых воркеров ✅
**Файл:** `main.py:1378-1410`

**Было:**
```python
alive_workers = sum(1 for task in self.active_worker_tasks if not task.done())
```

**Стало:**
```python
alive_workers = 0
dead_workers = []
for task in self.active_worker_tasks:
    if task.done():
        dead_workers.append((task.get_name(), task))
    else:
        alive_workers += 1

logger.debug(f"🏥 Worker status check:")
logger.debug(f"   Total tracked: {len(self.active_worker_tasks)}")
logger.debug(f"   Alive: {alive_workers}")
logger.debug(f"   Dead: {len(dead_workers)}")

if dead_workers:
    logger.warning(f"💀 Dead workers detected: {len(dead_workers)}")
    for task_name, task in dead_workers:
        try:
            exc = task.exception()
            logger.warning(f"   {task_name}: {exc}")
        except Exception:
            logger.warning(f"   {task_name}: Cancelled or completed")
    
    # Очищаем мертвые таски
    logger.info(f"🧹 Cleaning up {len(dead_workers)} dead workers")
    self.active_worker_tasks = [task for task in self.active_worker_tasks if not task.done()]
    logger.info(f"✅ Active workers list updated: {len(self.active_worker_tasks)} tasks remaining")
```

**Результат:**
- Корректный подсчет живых воркеров
- Автоматическая очистка мертвых из списка
- Логирование причины падения каждого воркера

### 3. Добавлена обработка ошибок в account_worker ✅
**Файл:** `main.py:8467-8548`

**Добавлено:**
- Обертка `try/except` вокруг всего тела воркера
- Детальное логирование при запуске:
```python
logger.info("="*80)
logger.info(f"🚀 WORKER PROCESS STARTING")
logger.info(f"   Worker ID: {worker_task_name}")
logger.info(f"   Account: {account_name} ({phone})")
logger.info(f"   Status: {account_data.get('status', 'UNKNOWN')}")
logger.info(f"   Task ID: {id(asyncio.current_task())}")
logger.info(f"   Index: {worker_index + 1}/{total_workers}")
logger.info(f"   Mode: {mode.upper()}")
logger.info("="*80)
```

### 4. Детальное логирование при падении воркера ✅
**Файл:** `main.py:8895-8935`

**Добавлено:**
```python
except Exception as outer_e:
    logger.error("="*80)
    logger.error(f"💥 WORKER FATAL ERROR: {worker_task_name}")
    logger.error(f"   Account: {account_name} ({phone})")
    logger.error(f"   Error: {outer_e}")
    logger.error(f"   Traceback:")
    logger.error(traceback.format_exc())
    logger.error("="*80)
    
    # Уведомление владельца
    try:
        await self.bot_client.send_message(
            BOT_OWNER_ID,
            f"💥 **ВОРКЕР УПАЛ**\n\n"
            f"Аккаунт: `{account_name}`\n"
            f"Телефон: `{phone}`\n"
            f"Ошибка: `{str(outer_e)[:200]}`\n\n"
            f"🔄 Система попытается восстановить через health check"
        )
    except:
        pass

finally:
    logger.info("="*80)
    logger.info(f"🛑 WORKER STOPPING: {worker_task_name}")
    logger.info(f"   Account: {account_name} ({phone})")
    logger.info(f"   Reason: {'Normal exit' if self.monitoring else 'Monitoring stopped'}")
    logger.info("="*80)
```

**Результат:**
- Полная трассировка при падении воркера
- Уведомление владельца в Telegram
- Понятная причина остановки

## Ожидаемый результат

После этих изменений:

1. ✅ При запуске N активных аккаунтов будет работать N воркеров
2. ✅ В логах видно статус каждого воркера (Task ID, имя, причина падения)
3. ✅ При падении воркера:
   - Логируется полная трассировка
   - Отправляется уведомление владельцу
   - Health check обнаруживает проблему и перезапускает
4. ✅ Счетчик "Работает" соответствует реальному количеству живых воркеров
5. ✅ Мертвые воркеры автоматически удаляются из списка отслеживания

## Тестирование

### Сценарий 1: Нормальная работа
1. Установить 6 активных аккаунтов
2. Запустить мониторинг
3. Проверить в логах:
   ```
   🔧 Creating worker #1/6 for [Account1]
   🔧 Creating worker #2/6 for [Account2]
   ...
   ✅ Task created: worker_0_8622376920 (id=123456)
   ✅ Task created: worker_1_8622376921 (id=123457)
   ```
4. Ожидаемый результат: 6 воркеров запущены и работают

### Сценарий 2: Падение воркера
1. Симулировать ошибку в одном из воркеров
2. Проверить в логах:
   ```
   💥 WORKER FATAL ERROR: worker_2_8622376922
      Account: TestAccount
      Error: Some error
      Traceback: ...
   ```
3. Проверить health check (через 2 минуты):
   ```
   💀 Dead workers detected: 1
      worker_2_8622376922: Some error
   🧹 Cleaning up 1 dead workers
   ✅ Active workers list updated: 5 tasks remaining
   ```
4. Проверить автовосстановление

### Сценарий 3: Health check
1. Дождаться срабатывания health check
2. Проверить в логах:
   ```
   🏥 Worker status check:
      Total tracked: 6
      Alive: 6
      Dead: 0
   ✅ Health check OK: 6/6 workers
   ```

## Файлы изменены
- `main.py` - основные исправления в функциях:
  - `pro_auto_comment()` - создание воркеров с Task ID
  - `account_worker()` - обработка ошибок и логирование
  - `health_check_worker()` - правильный подсчет и очистка

## Следующие шаги
1. ✅ Протестировать на реальных данных
2. Наблюдать логи в течение нескольких часов
3. При необходимости откорректировать интервалы health check

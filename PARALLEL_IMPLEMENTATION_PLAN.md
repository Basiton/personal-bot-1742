# План реализации параллельного комментирования

## Требования

### Тестовые каналы:
- @AIGIRLSARTS
- @testertesti  
- @testtestista
- @testingmana
- @chiptesterchip

### Логика параллельности:

1. **Параметр /setparallel K** — количество одновременно работающих воркеров

2. **Воркеры:**
   - В любой момент работают `min(K, количество активных аккаунтов)` воркеров
   - Каждый воркер привязан к одному аккаунту (своему Telethon-клиенту)

3. **Обработка каналов:**
   - Каждый аккаунт проходит ВСЕ каналы (не разделяет их с другими)
   - Проход циклический: после завершения всех каналов начинается новый цикл
   - Для распределения нагрузки используется offset: воркер N начинает с канала N

4. **Пример (4 канала, 2 активных аккаунта, K=2):**
   ```
   Каналы: C1, C2, C3, C4
   Аккаунты: A1, A2 (оба активны)
   
   Цикл 1:
   - A1: C1 → C2 → C3 → C4 (начало с offset=0)
   - A2: C2 → C3 → C4 → C1 (начало с offset=1)
   
   Цикл 2:
   - A1: C1 → C2 → C3 → C4
   - A2: C2 → C3 → C4 → C1
   ```

5. **Ротация:**
   - Когда аккаунт отработал цикл → короткая пауза (30-60с) и новый цикл
   - Бесконечный цикл, пока monitoring=True

## Логи (обязательно):

### При старте воркера:
```
WORKER STARTED: account=+XXXXXXXXXXX, parallel_idx=N
```

### При отправке комментария:
```
COMMENT: account=+XXXXXXXXXXX -> channel=@XXXX, cycle=X, step=Y
```

### При завершении цикла:
```
WORKER FINISHED CYCLE: account=+XXXXXXXXXXX, commented_channels=[...]
```

## Изменения в коде:

### 1. Изменить сигнатуру account_worker:
```python
async def account_worker(self, phone, account_data, all_channels, worker_index, total_workers):
```

### 2. Добавить цикл обработки:
```python
cycle_number = 0
while self.monitoring:
    cycle_number += 1
    commented_channels = []
    
    # Offset для распределения
    start_offset = worker_index % len(all_channels)
    
    for step, idx in enumerate(range(len(all_channels)), 1):
        channel_idx = (start_offset + idx) % len(all_channels)
        channel = all_channels[channel_idx]
        
        # ... комментирование ...
        
        commented_channels.append(f"@{username}")
    
    # Лог завершения цикла
    logger.info(f"WORKER FINISHED CYCLE: account={phone}, cycle={cycle_number}")
    logger.info(f"   Commented channels: {commented_channels}")
    
    # Короткая пауза между циклами
    await asyncio.sleep(random.randint(30, 60))
```

### 3. Обновить pro_auto_comment:
```python
# Не делить каналы между аккаунтами — все получают ВСЕ каналы
for i, (phone, data) in enumerate(accounts_list):
    task = asyncio.create_task(
        self.account_worker(phone, data, channels_to_use, i, len(accounts_list))
    )
    tasks.append(task)
```

## Ключевые отличия от текущей реализации:

| Текущая | Новая |
|---------|-------|
| Каналы делятся между аккаунтами | Все аккаунты обрабатывают ВСЕ каналы |
| Один проход по своему subset'у | Бесконечные циклы по всем каналам |
| Нет явных циклов | Чёткое логирование циклов |
| Логи без номеров циклов/шагов | COMMENT с cycle= и step= |


#!/usr/bin/env python3
"""Тест логики подсчета воркеров"""
import asyncio
from unittest.mock import MagicMock

async def test_worker_counting():
    """Симуляция подсчета воркеров"""
    print("=" * 80)
    print("ТЕСТ: Подсчет воркеров")
    print("=" * 80)
    
    # Создаем фейковые таски
    async def fake_worker(name, should_fail=False):
        await asyncio.sleep(0.1)
        if should_fail:
            raise Exception(f"Worker {name} failed!")
        return f"Worker {name} completed"
    
    # Запускаем 6 воркеров (1 должен упасть)
    tasks = []
    for i in range(6):
        task = asyncio.create_task(fake_worker(f"worker_{i}", should_fail=(i == 3)))
        task.set_name(f"worker_{i}_test")
        tasks.append(task)
    
    print(f"\n✅ Создано {len(tasks)} воркеров")
    for task in tasks:
        print(f"   - {task.get_name()} (id={id(task)})")
    
    # Ждем немного
    await asyncio.sleep(0.2)
    
    # Подсчитываем живые/мертвые
    alive_workers = 0
    dead_workers = []
    
    for task in tasks:
        if task.done():
            dead_workers.append((task.get_name(), task))
        else:
            alive_workers += 1
    
    print(f"\n📊 Статус воркеров:")
    print(f"   Total tracked: {len(tasks)}")
    print(f"   Alive: {alive_workers}")
    print(f"   Dead: {len(dead_workers)}")
    
    if dead_workers:
        print(f"\n💀 Мертвые воркеры:")
        for task_name, task in dead_workers:
            try:
                exc = task.exception()
                print(f"   {task_name}: {exc}")
            except Exception as e:
                print(f"   {task_name}: Completed normally")
    
    # Очищаем мертвые таски
    print(f"\n🧹 Очистка мертвых воркеров...")
    tasks = [task for task in tasks if not task.done()]
    print(f"✅ Осталось в списке: {len(tasks)} воркеров")
    
    # Отменяем оставшиеся
    for task in tasks:
        task.cancel()
    
    print("\n" + "=" * 80)
    print("✅ ТЕСТ ЗАВЕРШЕН")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(test_worker_counting())

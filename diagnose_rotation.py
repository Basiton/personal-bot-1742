#!/usr/bin/env python3
"""
Диагностика проблем с ротацией аккаунтов
Проверяет статусы всех аккаунтов и конфигурацию
"""

import sqlite3
import json
import os

DB_FILE = 'bot_data.db'
CONFIG_FILE = 'config.json'

def check_database():
    """Проверить статусы аккаунтов в базе данных"""
    print("="*60)
    print("📊 ПРОВЕРКА БАЗЫ ДАННЫХ")
    print("="*60)
    
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Получаем все аккаунты
        cursor.execute("SELECT phone, name, status FROM accounts ORDER BY status, phone")
        accounts = cursor.fetchall()
        
        if not accounts:
            print("❌ Аккаунтов не найдено в базе данных!")
            conn.close()
            return
        
        # Группируем по статусам
        status_counts = {}
        status_accounts = {}
        
        for phone, name, status in accounts:
            if status not in status_counts:
                status_counts[status] = 0
                status_accounts[status] = []
            status_counts[status] += 1
            status_accounts[status].append((phone, name))
        
        print(f"\n📱 Всего аккаунтов: {len(accounts)}")
        print(f"\n📊 Статусы:")
        for status, count in status_counts.items():
            icon = "✅" if status == "active" else "🔵" if status == "reserve" else "🔴"
            print(f"   {icon} {status.upper()}: {count}")
        
        # Показываем детали
        for status in ['active', 'reserve', 'broken']:
            if status in status_accounts and status_accounts[status]:
                print(f"\n{status.upper()} АККАУНТЫ:")
                for phone, name in status_accounts[status]:
                    print(f"   • {name or 'No name'} ({phone})")
        
        conn.close()
        
        return status_counts
        
    except Exception as e:
        print(f"❌ Ошибка при чтении БД: {e}")
        return None

def check_config():
    """Проверить настройки в config.json"""
    print("\n" + "="*60)
    print("⚙️  ПРОВЕРКА КОНФИГУРАЦИИ")
    print("="*60)
    
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        
        max_parallel = config.get('max_parallel_accounts', 'НЕ УСТАНОВЛЕНО')
        max_cycles = config.get('max_cycles_per_worker', 'НЕ УСТАНОВЛЕНО')
        worker_mode = config.get('worker_mode', 'НЕ УСТАНОВЛЕНО')
        
        print(f"\n📊 Параллельность: {max_parallel}")
        print(f"🔄 Макс циклов: {max_cycles}")
        print(f"🎯 Режим воркеров: {worker_mode}")
        
        if max_parallel == 'НЕ УСТАНОВЛЕНО' or max_parallel == 2:
            print("\n⚠️  ПРОБЛЕМА: MAX_PARALLEL_ACCOUNTS слишком мало или не установлено!")
            print("   Рекомендация: /setparallel 5 (или больше)")
        
        return config
        
    except FileNotFoundError:
        print(f"\n❌ Файл {CONFIG_FILE} не найден!")
        return None
    except Exception as e:
        print(f"\n❌ Ошибка при чтении конфига: {e}")
        return None

def check_rotation_logic(status_counts, config):
    """Проанализировать логику ротации"""
    print("\n" + "="*60)
    print("🔍 АНАЛИЗ РОТАЦИИ")
    print("="*60)
    
    if not status_counts or not config:
        print("\n❌ Недостаточно данных для анализа")
        return
    
    active_count = status_counts.get('active', 0)
    reserve_count = status_counts.get('reserve', 0)
    max_parallel = config.get('max_parallel_accounts', 2)
    max_cycles = config.get('max_cycles_per_worker', 0)
    
    print(f"\n📊 Текущая ситуация:")
    print(f"   ✅ Активных: {active_count}")
    print(f"   🔵 Резервных: {reserve_count}")
    print(f"   ⚙️  Лимит параллельности: {max_parallel}")
    print(f"   🔄 Ротация каждые: {max_cycles} циклов")
    
    print(f"\n🎯 Что произойдет:")
    
    if active_count == 0:
        print("   ❌ НЕТ АКТИВНЫХ АККАУНТОВ!")
        print("   💡 Активируйте аккаунты через /toggleaccount")
    elif active_count > max_parallel:
        print(f"   ⚠️  {active_count} активных, но работать будут только {max_parallel}")
        print(f"   💡 Используйте /setparallel {active_count} чтобы все работали")
    elif active_count < max_parallel:
        print(f"   ✅ {active_count} активных будут работать одновременно")
        if reserve_count > 0:
            print(f"   💡 Можно активировать еще {max_parallel - active_count} из {reserve_count} резервных")
    else:
        print(f"   ✅ Все {active_count} активных будут работать")
    
    if max_cycles > 0:
        print(f"\n🔄 Ротация:")
        if reserve_count == 0:
            print(f"   ⚠️  После {max_cycles} циклов некому заменить активные аккаунты!")
            print(f"   💡 Аккаунты будут переключаться в RESERVE, но новые не активируются")
            print(f"   💡 Рекомендация: добавьте резервные аккаунты или /setmaxcycles 0")
        else:
            print(f"   ✅ После {max_cycles} циклов будет ротация из {reserve_count} резервных")
    else:
        print(f"\n🔄 Ротация: ОТКЛЮЧЕНА (max_cycles=0)")
        print(f"   💡 Аккаунты будут работать бесконечно без смены")

def main():
    print("\n" + "="*60)
    print("🔧 ДИАГНОСТИКА СИСТЕМЫ РОТАЦИИ")
    print("="*60)
    
    status_counts = check_database()
    config = check_config()
    check_rotation_logic(status_counts, config)
    
    print("\n" + "="*60)
    print("💡 РЕКОМЕНДАЦИИ:")
    print("="*60)
    
    if status_counts:
        active = status_counts.get('active', 0)
        reserve = status_counts.get('reserve', 0)
        
        if active == 0:
            print("\n1️⃣ АКТИВИРУЙТЕ АККАУНТЫ:")
            print("   /toggleaccount +номер")
        
        if config and config.get('max_parallel_accounts', 2) < active:
            print(f"\n2️⃣ УВЕЛИЧЬТЕ ЛИМИТ ПАРАЛЛЕЛЬНОСТИ:")
            print(f"   /setparallel {active}")
        
        if reserve == 0 and config and config.get('max_cycles_per_worker', 0) > 0:
            print("\n3️⃣ ЛИБО ДОБАВЬТЕ РЕЗЕРВНЫЕ, ЛИБО ОТКЛЮЧИТЕ РОТАЦИЮ:")
            print("   Вариант А: Добавьте аккаунты и переведите в reserve")
            print("   Вариант Б: /setmaxcycles 0 (отключить ротацию)")
        
        print("\n4️⃣ ПЕРЕЗАПУСТИТЕ МОНИТОРИНГ:")
        print("   /stopmon")
        print("   /startmon")
    
    print("\n" + "="*60)

if __name__ == '__main__':
    main()

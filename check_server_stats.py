#!/usr/bin/env python3
"""
Быстрая проверка статистики на сервере
"""
import json
import os

DB_FILE = 'bot_data.json'
CONFIG_FILE = 'config.json'

print("=" * 80)
print("📊 СТАТИСТИКА СЕРВЕРА comapc-bot")
print("=" * 80)

# Проверка bot_data.json
if os.path.exists(DB_FILE):
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        channels = data.get('channels', [])
        accounts = data.get('accounts_data', {})
        active_accounts = [p for p, a in accounts.items() if a.get('active')]
        commented = data.get('commented_posts', {})
        total_comments = sum(len(posts) for posts in commented.values())
        file_size = os.path.getsize(DB_FILE) / 1024
        
        print(f"\n📁 {DB_FILE}:")
        print(f"   • Размер файла: {file_size:.1f} KB")
        print(f"   • Всего каналов: {len(channels)}")
        print(f"   • Всего аккаунтов: {len(accounts)}")
        print(f"   • Активных аккаунтов: {len(active_accounts)}")
        if active_accounts:
            print(f"   • Список активных: {', '.join([p[-10:] for p in active_accounts[:5]])}")
            if len(active_accounts) > 5:
                print(f"     ... и еще {len(active_accounts) - 5}")
        
        # История commented_posts
        print(f"\n💾 История прокомментированных постов:")
        if commented:
            print(f"   • Каналов с историей: {len(commented)}")
            print(f"   • Всего запомнено постов: {total_comments}")
            avg_posts = total_comments / len(commented) if commented else 0
            print(f"   • В среднем на канал: {avg_posts:.1f} постов")
            
            # Топ-5 каналов
            sorted_channels = sorted(commented.items(), key=lambda x: len(x[1]), reverse=True)[:5]
            print(f"\n   📈 Топ-5 каналов по количеству комментариев:")
            for i, (ch, posts) in enumerate(sorted_channels, 1):
                print(f"      {i}. @{ch}: {len(posts)} постов")
        else:
            print(f"   ⚠️  История пуста (commented_posts отсутствует)")
            print(f"   → Это нормально если бот только запущен")
            print(f"   → После обновления и перезапуска история начнет сохраняться")
        
    except Exception as e:
        print(f"\n❌ Ошибка чтения {DB_FILE}: {e}")
else:
    print(f"\n❌ {DB_FILE} не найден!")

# Проверка config.json
print(f"\n{'=' * 80}")
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        speed = config.get('speed', 20)
        max_accounts = config.get('max_parallel_accounts', 2)
        test_mode = config.get('test_mode', False)
        active_in_config = config.get('active_accounts', [])
        
        print(f"⚙️  {CONFIG_FILE}:")
        print(f"   • Скорость: {speed} комм/час на аккаунт")
        print(f"   • Макс параллельных: {max_accounts}")
        print(f"   • Тест режим: {'🧪 ДА' if test_mode else '🚀 НЕТ (продакшн)'}")
        print(f"   • Активных в конфиге: {len(active_in_config)}")
        
    except Exception as e:
        print(f"\n❌ Ошибка чтения {CONFIG_FILE}: {e}")
else:
    print(f"\n❌ {CONFIG_FILE} не найден!")

# Расчет производительности
print(f"\n{'=' * 80}")
print("📈 РАСЧЕТ ПРОИЗВОДИТЕЛЬНОСТИ:")
print("=" * 80)

if os.path.exists(DB_FILE) and os.path.exists(CONFIG_FILE):
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        channels = data.get('channels', [])
        accounts = data.get('accounts_data', {})
        active_accounts = [p for p, a in accounts.items() if a.get('active')]
        speed = config.get('speed', 20)
        
        if len(channels) > 0 and len(active_accounts) > 0:
            comments_per_hour = len(active_accounts) * speed
            comments_per_day = comments_per_hour * 24
            comments_per_channel_per_day = comments_per_day / len(channels)
            
            print(f"Активных аккаунтов: {len(active_accounts)}")
            print(f"Скорость на аккаунт: {speed} комм/час")
            print(f"Общая скорость: {comments_per_hour} комм/час = {comments_per_day} комм/день")
            print(f"\n➡️  На каждый из {len(channels)} каналов: {comments_per_channel_per_day:.2f} комм/день")
            
            # Оценка
            if comments_per_channel_per_day < 2:
                print(f"\n⚠️  ВНИМАНИЕ: Низкая скорость! Рекомендую:")
                print(f"   • Добавить больше аккаунтов")
                print(f"   • Или увеличить speed в config.json (до 30-40)")
            elif comments_per_channel_per_day < 3:
                print(f"\n⚠️  Скорость низковата при большом количестве каналов")
            else:
                print(f"\n✅ Скорость оптимальна")
            
            # Прогноз при росте
            print(f"\n📊 Прогноз при росте каналов:")
            for future in [500, 600, 800, 1000]:
                if future > len(channels):
                    future_speed = comments_per_day / future
                    status = "✅" if future_speed >= 3 else ("⚠️" if future_speed >= 2 else "🔴")
                    print(f"   {status} {future} каналов → {future_speed:.2f} комм/канал/день")
        
    except:
        pass

print(f"\n{'=' * 80}")

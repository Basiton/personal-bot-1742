#!/usr/bin/env python3
"""
Скрипт оптимизации настроек для 400+ каналов
Анализирует текущую конфигурацию и предлагает улучшения
"""
import json
from pathlib import Path

CONFIG_FILE = 'config.json'
DB_FILE = 'bot_data.json'

def load_config():
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_data():
    with open(DB_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def analyze():
    print("=" * 80)
    print("📊 АНАЛИЗ КОНФИГУРАЦИИ ДЛЯ БОЛЬШОГО ЧИСЛА КАНАЛОВ")
    print("=" * 80)
    
    config = load_config()
    data = load_data()
    
    # Получаем данные
    num_channels = len(data.get('channels', []))
    num_accounts = len([acc for acc in data.get('accounts_data', {}).values() if acc.get('active')])
    speed = config.get('speed', 20)
    commented_posts = data.get('commented_posts', {})
    
    # Расчеты
    comments_per_hour = num_accounts * speed
    comments_per_day = comments_per_hour * 24
    comments_per_channel_per_day = comments_per_day / num_channels if num_channels > 0 else 0
    
    print(f"\n📋 ТЕКУЩЕЕ СОСТОЯНИЕ:")
    print(f"   • Каналов: {num_channels}")
    print(f"   • Активных аккаунтов: {num_accounts}")
    print(f"   • Скорость на аккаунт: {speed} комм/час")
    print(f"   • Общая скорость: {comments_per_hour} комм/час ({comments_per_day} комм/день)")
    print(f"   • На каждый канал: {comments_per_channel_per_day:.2f} комм/день")
    
    if commented_posts:
        total_remembered = sum(len(posts) for posts in commented_posts.values())
        avg_per_channel = total_remembered / len(commented_posts) if commented_posts else 0
        print(f"\n💾 ИСТОРИЯ:")
        print(f"   • Запомнено постов: {total_remembered}")
        print(f"   • В среднем на канал: {avg_per_channel:.1f}")
    
    # Анализ и рекомендации
    print(f"\n" + "=" * 80)
    print("💡 РЕКОМЕНДАЦИИ:")
    print("=" * 80)
    
    issues = []
    recommendations = []
    
    # Проблема 1: Низкая скорость на канал
    if comments_per_channel_per_day < 3:
        issues.append(f"⚠️  Низкая скорость: {comments_per_channel_per_day:.2f} комм/канал/день")
        recommendations.append({
            'title': '1️⃣ Увеличить количество аккаунтов',
            'current': f'{num_accounts} аккаунтов',
            'recommended': f'{num_accounts + 2} аккаунтов',
            'effect': f'→ {comments_per_channel_per_day * (num_accounts + 2) / num_accounts:.2f} комм/канал/день',
            'risk': 'Низкий (если аккаунты прогреты)'
        })
        recommendations.append({
            'title': '2️⃣ Увеличить скорость комментирования',
            'current': f'{speed} комм/час',
            'recommended': f'{min(speed + 10, 40)} комм/час',
            'effect': f'→ {comments_per_channel_per_day * min(speed + 10, 40) / speed:.2f} комм/канал/день',
            'risk': 'Средний (следить за FloodWait)'
        })
    
    # Проблема 2: Много каналов
    if num_channels > 300:
        issues.append(f"⚠️  Большое количество каналов: {num_channels}")
        recommendations.append({
            'title': '3️⃣ Увеличить лимит памяти постов',
            'current': '200 постов/канал',
            'recommended': '500 или 1000 постов/канал',
            'effect': '→ программа запомнит больше истории',
            'implementation': 'В main.py строка ~12655 изменить 200→500'
        })
        recommendations.append({
            'title': '4️⃣ Увеличить глубину проверки',
            'current': 'Проверяет последние 10 постов',
            'recommended': 'Проверять последние 20-30 постов',
            'effect': '→ найдет больше непрокомментированных постов',
            'implementation': 'В main.py строка ~12486 изменить limit=10 → limit=20'
        })
    
    # Проблема 3: Растущее количество
    if num_channels > 350:
        issues.append(f"⚠️  Каналы продолжают расти (сейчас {num_channels})")
        recommendations.append({
            'title': '5️⃣ Добавить приоритизацию каналов',
            'description': 'Комментировать активные каналы чаще',
            'effect': '→ не терять новые посты в быстрых каналах',
            'status': 'Требует разработки'
        })
    
    # Вывод проблем
    if issues:
        print("\n🔴 ОБНАРУЖЕНЫ ПРОБЛЕМЫ:")
        for issue in issues:
            print(f"   {issue}")
    else:
        print("\n✅ Конфигурация оптимальна для текущего числа каналов")
    
    # Вывод рекомендаций
    if recommendations:
        print(f"\n📋 ПРЕДЛАГАЕМЫЕ УЛУЧШЕНИЯ:\n")
        for i, rec in enumerate(recommendations, 1):
            print(f"{rec['title']}")
            for key, value in rec.items():
                if key != 'title':
                    print(f"   • {key.capitalize()}: {value}")
            print()
    
    # Прогноз
    print("=" * 80)
    print("📈 ПРОГНОЗ ПРИ РОСТЕ КАНАЛОВ:")
    print("=" * 80)
    for future_channels in [500, 600, 800, 1000]:
        if future_channels > num_channels:
            future_speed = comments_per_day / future_channels
            print(f"   • {future_channels} каналов → {future_speed:.2f} комм/канал/день", end="")
            if future_speed < 2:
                print(" ⚠️  Критично низко!")
            elif future_speed < 3:
                print(" ⚠️  Низко")
            else:
                print(" ✅")

if __name__ == '__main__':
    analyze()

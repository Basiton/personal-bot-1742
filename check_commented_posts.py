#!/usr/bin/env python3
"""
Скрипт для проверки истории прокомментированных постов
Показывает сколько постов запомнено в каждом канале
"""
import json
from pathlib import Path

DB_NAME = 'bot_data.json'

def main():
    db_path = Path(DB_NAME)
    
    if not db_path.exists():
        print(f"❌ {DB_NAME} не найден")
        return
    
    try:
        with db_path.open('r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Ошибка чтения {DB_NAME}: {e}")
        return
    
    commented_posts = data.get('commented_posts', {})
    
    if not commented_posts:
        print("⚠️  История прокомментированных постов пуста")
        print("   Это нормально если бот только запущен впервые")
        print("   После первых комментариев здесь появятся данные")
        return
    
    print("=" * 80)
    print("📊 ИСТОРИЯ ПРОКОММЕНТИРОВАННЫХ ПОСТОВ")
    print("=" * 80)
    
    total_posts = 0
    channels_sorted = sorted(commented_posts.items(), key=lambda x: len(x[1]), reverse=True)
    
    for i, (channel, post_ids) in enumerate(channels_sorted, 1):
        total_posts += len(post_ids)
        post_ids_sorted = sorted(post_ids)
        
        print(f"\n{i}. @{channel}")
        print(f"   📝 Прокомментировано постов: {len(post_ids)}")
        
        if len(post_ids) <= 10:
            print(f"   🆔 Post IDs: {post_ids_sorted}")
        else:
            print(f"   🆔 Первые посты: {post_ids_sorted[:5]}")
            print(f"   🆔 Последние посты: {post_ids_sorted[-5:]}")
    
    print("\n" + "=" * 80)
    print(f"ИТОГО: {len(commented_posts)} каналов, {total_posts} прокомментированных постов")
    print("=" * 80)
    
    # Дополнительная статистика
    avg_posts = total_posts / len(commented_posts) if commented_posts else 0
    max_channel = max(commented_posts.items(), key=lambda x: len(x[1]))
    min_channel = min(commented_posts.items(), key=lambda x: len(x[1]))
    
    print(f"\n📈 СТАТИСТИКА:")
    print(f"   • Среднее постов на канал: {avg_posts:.1f}")
    print(f"   • Максимум: @{max_channel[0]} ({len(max_channel[1])} постов)")
    print(f"   • Минимум: @{min_channel[0]} ({len(min_channel[1])} постов)")
    
    # Предупреждения
    channels_near_limit = [(ch, len(ids)) for ch, ids in commented_posts.items() if len(ids) > 150]
    if channels_near_limit:
        print(f"\n⚠️  ВНИМАНИЕ: {len(channels_near_limit)} каналов близки к лимиту (200 постов):")
        for ch, count in channels_near_limit:
            print(f"   • @{ch}: {count}/200")

if __name__ == '__main__':
    main()

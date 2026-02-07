#!/usr/bin/env python3
"""
Тестовый скрипт для проверки RockAPI интеграции
Проверяет работу generate_comment_rockapi и сравнивает с YandexGPT
"""

import os
import sys

# Устанавливаем провайдера на RockAPI для теста
os.environ['COMMENT_PROVIDER'] = 'rockapi'

try:
    from main import generate_comment_rockapi, ROCKAPI_KEY, ROCKAPI_MODEL, ROCKAPI_BASE_URL, COMMENT_PROVIDER
    print("✅ Успешно импортирован generate_comment_rockapi")
except ImportError as e:
    print(f"❌ Ошибка импорта: {e}")
    sys.exit(1)

print("\n" + "="*60)
print("ПРОВЕРКА НАСТРОЕК ROCKAPI")
print("="*60)

if not ROCKAPI_KEY:
    print("❌ ROCKAPI_KEY не установлен!")
    print("   Установите переменную окружения ROCKAPI_KEY")
    sys.exit(1)
else:
    print(f"✅ ROCKAPI_KEY: {ROCKAPI_KEY[:10]}...{ROCKAPI_KEY[-5:]}")

print(f"✅ ROCKAPI_MODEL: {ROCKAPI_MODEL}")
print(f"✅ ROCKAPI_BASE_URL: {ROCKAPI_BASE_URL}")
print(f"✅ COMMENT_PROVIDER: {COMMENT_PROVIDER}")

print("\n" + "="*60)
print("ТЕСТИРОВАНИЕ ГЕНЕРАЦИИ КОММЕНТАРИЕВ")
print("="*60)

# Тестовые посты
test_posts = [
    {
        "text": """
🚀 Запустили новый продукт за 3 месяца!
Команда из 5 человек смогла создать MVP, привлечь первых 1000 пользователей
и получить инвестиции в размере $50,000.
Главный урок: начинайте с простого, слушайте пользователей, итерируйте быстро.
        """,
        "theme": "стартапы",
    },
    {
        "text": """
📊 Результаты исследования показали:
- Производительность выросла на 40% после внедрения автоматизации
- Время на рутинные задачи сократилось с 3 часов до 45 минут
- Удовлетворенность команды повысилась на 65%
        """,
        "theme": "бизнес",
    },
    {
        "text": """
🍝 Секрет идеальной пасты карбонара:
1. Используйте гуанчиале, а не бекон
2. Яйца комнатной температуры
3. Никакого чеснока (традиционный рецепт)
4. Готовится за 15 минут
Результат — как в лучших ресторанах Италии!
        """,
        "theme": "кулинария",
    },
]

print(f"\nТестируем {len(test_posts)} постов с разными темами...\n")

for i, post_data in enumerate(test_posts, 1):
    print(f"\n{'─'*60}")
    print(f"ТЕСТ {i}/{len(test_posts)}")
    print(f"Тема: {post_data['theme']}")
    print(f"{'─'*60}")
    
    post_text = post_data["text"].strip()
    print(f"Пост (первые 150 символов):")
    print(f"  {post_text[:150]}...")
    
    try:
        print(f"\n🤖 Генерируем комментарий через RockAPI...")
        comment = generate_comment_rockapi(
            post_text=post_text,
            channel_theme=post_data["theme"]
        )
        
        print(f"\n✅ СГЕНЕРИРОВАННЫЙ КОММЕНТАРИЙ:")
        print(f"   \"{comment}\"")
        print(f"   Длина: {len(comment.split())} слов")
        
        # Проверки качества
        checks = []
        words = comment.split()
        
        if len(words) >= 6 and len(words) <= 15:
            checks.append("✅ Длина в норме (6-15 слов)")
        else:
            checks.append(f"⚠️ Длина не в диапазоне: {len(words)} слов")
        
        # Проверка на женский род (простая)
        female_markers = ['видела', 'читала', 'думала', 'поняла', 'попробовала', 
                         'заметила', 'сталкивалась', 'понравилось', 'была', 'сделала']
        if any(marker in comment.lower() for marker in female_markers):
            checks.append("✅ Женский род")
        
        # Проверка на отсутствие шаблонных начал
        template_starts = ['Интересно', 'Круто', 'Классно', 'Отлично', 'Супер', 'Ого', 'Вау']
        has_template = any(comment.startswith(word) for word in template_starts)
        if not has_template:
            checks.append("✅ Без шаблонных начал")
        else:
            checks.append("⚠️ Есть шаблонное начало")
        
        # Проверка на эмодзи
        emoji_count = sum(1 for char in comment if ord(char) > 0x1F300)
        if emoji_count <= 1:
            checks.append(f"✅ Эмодзи: {emoji_count}")
        else:
            checks.append(f"⚠️ Много эмодзи: {emoji_count}")
        
        print(f"\n   Проверки качества:")
        for check in checks:
            print(f"     {check}")
            
    except Exception as e:
        print(f"\n❌ Ошибка при генерации комментария: {e}")
        import traceback
        print(f"   Traceback: {traceback.format_exc()}")

print("\n" + "="*60)
print("ИТОГИ ТЕСТИРОВАНИЯ")
print("="*60)
print("✅ Если вы видите сгенерированные комментарии выше, RockAPI работает!")
print("⚠️ Если видите fallback комментарии, проверьте:")
print("   - API ключ ROCKAPI_KEY")
print("   - Доступность сервиса RockAPI")
print("   - Наличие средств на балансе")
print("\n💡 Для переключения обратно на YandexGPT:")
print("   export COMMENT_PROVIDER=yandex")
print("\n💡 Текущий провайдер можно изменить в переменной окружения COMMENT_PROVIDER")
print("   Доступные значения: 'rockapi' (по умолчанию) или 'yandex'")
print("="*60)

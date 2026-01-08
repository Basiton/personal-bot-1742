#!/usr/bin/env python3
"""
Простой скрипт для поиска подходящих каналов
Отредактируйте список MY_CHANNELS и запустите
"""
import asyncio
from search_channels import ChannelSearcher

# ========================================
# ВСТАВЬТЕ СЮДА СВОЙ СПИСОК КАНАЛОВ
# ========================================
MY_CHANNELS = [
    'breakingmash',
    'rbc_news',
    'meduzalive',
    'bbcrussian',
    'rian_ru',
    'tass_agency',
    # Добавьте свои каналы здесь...
]

async def main():
    print("🔍 Начинаем поиск подходящих каналов...")
    print(f"📊 Будет проверено каналов: {len(MY_CHANNELS)}\n")
    
    searcher = ChannelSearcher()
    results = await searcher.search_channels(MY_CHANNELS)
    
    # Выводим результаты
    searcher.print_results()
    
    # Опционально - сохранить в файл
    if results:
        save = input("\n💾 Сохранить результаты в файл found_channels.json? (y/n): ").lower()
        if save == 'y':
            searcher.save_results()
            print("✅ Результаты сохранены!")

if __name__ == '__main__':
    asyncio.run(main())

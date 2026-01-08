#!/usr/bin/env python3
"""
Скрипт для поиска каналов с критериями:
- От 50,000 подписчиков
- Доступны комментарии без вступления в канал
- Без необходимости подачи заявки на вступление
"""
import asyncio
import json
import logging
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import Channel
from telethon.errors import ChannelPrivateError, UsernameInvalidError, FloodWaitError
from datetime import datetime

# Настройки из main.py
API_ID = 36053254
API_HASH = '4c63aee24cbc1be5e593329370712e7f'
DB_NAME = 'bot_data.json'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ChannelSearcher:
    def __init__(self):
        self.accounts_data = {}
        self.found_channels = []
        self.load_accounts()
        
    def load_accounts(self):
        """Загрузить данные аккаунтов из bot_data.json"""
        try:
            with open(DB_NAME, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.accounts_data = data.get('accounts', {})
                logger.info(f"Загружено {len(self.accounts_data)} аккаунтов")
        except Exception as e:
            logger.error(f"Ошибка загрузки аккаунтов: {e}")
            
    def get_active_account(self):
        """Получить первый активный аккаунт для поиска"""
        for phone, data in self.accounts_data.items():
            if data.get('active') and data.get('session'):
                return phone, data
        return None, None
    
    async def check_channel(self, client, channel_username):
        """
        Проверить канал на соответствие критериям:
        - Минимум 50,000 подписчиков
        - Публичный канал (не требует вступления)
        - Доступны комментарии
        """
        try:
            # Убираем @ если есть
            username = channel_username.lstrip('@')
            
            # Получаем информацию о канале
            entity = await client.get_entity(username)
            
            # Проверяем что это канал
            if not isinstance(entity, Channel):
                return None
            
            # Получаем полную информацию
            full_channel = await client.get_entity(entity)
            
            # Проверяем количество подписчиков через participants_count
            participants_count = getattr(full_channel, 'participants_count', 0)
            
            # Если нет в атрибутах, пробуем получить из dialog
            if participants_count == 0:
                try:
                    dialogs = await client.get_dialogs()
                    for dialog in dialogs:
                        if hasattr(dialog.entity, 'id') and dialog.entity.id == entity.id:
                            if hasattr(dialog, 'entity') and hasattr(dialog.entity, 'participants_count'):
                                participants_count = dialog.entity.participants_count
                            break
                except:
                    pass
            
            # Проверяем минимальное количество подписчиков
            if participants_count < 50000:
                logger.info(f"❌ {username}: только {participants_count} подписчиков (нужно >= 50,000)")
                return None
            
            # Проверяем что канал публичный (не приватный, не закрытый)
            if entity.broadcast and not entity.megagroup:
                # Это канал (не группа)
                
                # Проверяем доступ - если мы можем получить сообщения без вступления
                is_public = not getattr(entity, 'restricted', False)
                join_request = getattr(entity, 'join_request', False)
                
                if join_request:
                    logger.info(f"❌ {username}: требуется заявка на вступление")
                    return None
                    
                if not is_public:
                    logger.info(f"❌ {username}: ограниченный доступ")
                    return None
                
                # Проверяем, включены ли комментарии в канале
                try:
                    # Получаем последние сообщения
                    messages = await client.get_messages(entity, limit=5)
                    
                    has_comments = False
                    for msg in messages:
                        # Проверяем, есть ли у сообщения обсуждение (комментарии)
                        if hasattr(msg, 'replies') and msg.replies:
                            # Если есть replies и они не None - значит комментарии доступны
                            has_comments = True
                            
                            # Дополнительно проверяем, можно ли комментировать без вступления
                            if hasattr(msg.replies, 'comments') and msg.replies.comments:
                                logger.info(f"✅ {username}: {participants_count:,} подписчиков, комментарии доступны")
                                return {
                                    'username': username,
                                    'title': entity.title,
                                    'subscribers': participants_count,
                                    'link': f"https://t.me/{username}",
                                    'checked_at': datetime.now().isoformat()
                                }
                    
                    if not has_comments:
                        logger.info(f"❌ {username}: комментарии отключены или недоступны")
                        return None
                        
                except ChannelPrivateError:
                    logger.info(f"❌ {username}: приватный канал")
                    return None
            else:
                logger.info(f"❌ {username}: это группа, а не канал")
                return None
                
        except UsernameInvalidError:
            logger.error(f"❌ {channel_username}: неверное имя пользователя")
            return None
        except ChannelPrivateError:
            logger.info(f"❌ {channel_username}: приватный канал")
            return None
        except FloodWaitError as e:
            logger.warning(f"⏳ Flood wait {e.seconds} секунд")
            await asyncio.sleep(e.seconds)
            return None
        except Exception as e:
            logger.error(f"❌ {channel_username}: ошибка - {e}")
            return None
    
    async def search_channels(self, channel_list):
        """
        Поиск каналов из предоставленного списка
        
        Args:
            channel_list: список юзернеймов каналов для проверки
        """
        phone, account_data = self.get_active_account()
        
        if not phone:
            logger.error("❌ Нет активных аккаунтов для поиска!")
            return []
        
        logger.info(f"🔍 Начинаем поиск с аккаунта: {account_data.get('name', phone)}")
        
        client = TelegramClient(
            StringSession(account_data['session']), 
            API_ID, 
            API_HASH
        )
        
        try:
            await client.connect()
            
            if not await client.is_user_authorized():
                logger.error("❌ Аккаунт не авторизован!")
                return []
            
            logger.info(f"📋 Проверяем {len(channel_list)} каналов...")
            
            for i, channel in enumerate(channel_list, 1):
                logger.info(f"[{i}/{len(channel_list)}] Проверяем: {channel}")
                
                result = await self.check_channel(client, channel)
                
                if result:
                    self.found_channels.append(result)
                    logger.info(f"✅ Найден подходящий канал! Всего найдено: {len(self.found_channels)}")
                
                # Небольшая задержка между проверками
                await asyncio.sleep(2)
            
            logger.info(f"\n{'='*60}")
            logger.info(f"🎉 Поиск завершен! Найдено подходящих каналов: {len(self.found_channels)}")
            logger.info(f"{'='*60}\n")
            
            return self.found_channels
            
        except Exception as e:
            logger.error(f"Ошибка при поиске: {e}")
            return []
        finally:
            await client.disconnect()
    
    def print_results(self):
        """Вывести результаты поиска в удобном формате"""
        if not self.found_channels:
            print("\n❌ Подходящих каналов не найдено.\n")
            return
        
        print(f"\n{'='*80}")
        print(f"✅ НАЙДЕНО ПОДХОДЯЩИХ КАНАЛОВ: {len(self.found_channels)}")
        print(f"{'='*80}\n")
        
        for i, channel in enumerate(self.found_channels, 1):
            print(f"{i}. @{channel['username']}")
            print(f"   Название: {channel['title']}")
            print(f"   Подписчиков: {channel['subscribers']:,}")
            print(f"   Ссылка: {channel['link']}")
            print(f"   Проверено: {channel['checked_at']}")
            print()
        
        print(f"{'='*80}\n")
        
        # Список для быстрого копирования
        print("📋 СПИСОК ДЛЯ КОПИРОВАНИЯ:")
        print("-" * 80)
        for channel in self.found_channels:
            print(f"@{channel['username']}")
        print()
    
    def save_results(self, filename='found_channels.json'):
        """Сохранить результаты в файл (опционально)"""
        if not self.found_channels:
            return
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.found_channels, f, indent=2, ensure_ascii=False)
            logger.info(f"💾 Результаты сохранены в {filename}")
        except Exception as e:
            logger.error(f"Ошибка сохранения результатов: {e}")


async def main():
    """
    Главная функция для запуска поиска
    """
    print("""
╔════════════════════════════════════════════════════════════════╗
║          ПОИСК КАНАЛОВ С ОТКРЫТЫМИ КОММЕНТАРИЯМИ               ║
║                                                                 ║
║  Критерии поиска:                                              ║
║  ✓ От 50,000 подписчиков                                       ║
║  ✓ Публичные каналы (без вступления)                          ║
║  ✓ Открытые комментарии                                        ║
╚════════════════════════════════════════════════════════════════╝
    """)
    
    # Пример списка каналов для проверки
    # ЗАМЕНИТЕ ЭТОТ СПИСОК НА СВОЙ!
    test_channels = [
        'breakingmash',      # Breaking Mash
        'rbc_news',          # РБК
        'meduzalive',        # Медуза
        'bbcrussian',        # BBC Russian
        'rian_ru',           # РИА Новости
        'tass_agency',       # ТАСС
        'lentachold',        # Лента.ру
        'kommersant',        # Коммерсантъ
        'vedomosti',         # Ведомости
        'izvestia',          # Известия
        'rt_russian',        # RT на русском
        'interfaxonline',    # Интерфакс
        'gazeta_ru',         # Газета.Ру
        'business_gazeta',   # Деловая газета
        'forbes_ru',         # Forbes Russia
    ]
    
    print("\n⚠️  ВНИМАНИЕ!")
    print("Отредактируйте список каналов в файле search_channels.py")
    print("перед запуском или передайте свой список.\n")
    
    choice = input("Использовать тестовый список каналов? (y/n): ").lower()
    
    if choice != 'y':
        print("\n📝 Введите юзернеймы каналов (по одному на строку).")
        print("Для завершения ввода нажмите Enter на пустой строке:\n")
        
        custom_channels = []
        while True:
            channel = input("Канал: ").strip()
            if not channel:
                break
            custom_channels.append(channel)
        
        if custom_channels:
            test_channels = custom_channels
        else:
            print("\n❌ Список каналов пуст. Выход.")
            return
    
    searcher = ChannelSearcher()
    results = await searcher.search_channels(test_channels)
    
    # Выводим результаты
    searcher.print_results()
    
    # Опционально сохраняем результаты
    if results:
        save = input("Сохранить результаты в файл? (y/n): ").lower()
        if save == 'y':
            searcher.save_results()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Поиск прерван пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")

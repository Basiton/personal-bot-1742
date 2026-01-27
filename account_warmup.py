"""
Модуль для прогрева Telegram аккаунтов
Быстрая программа: 4 дня до полной готовности
"""

import asyncio
import random
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from telethon import TelegramClient, functions
from telethon.tl.types import InputPeerChannel, InputPeerUser
from telethon.errors import FloodWaitError, ChatWriteForbiddenError, UserBannedInChannelError

logger = logging.getLogger(__name__)


class AccountWarmup:
    """Класс для прогрева Telegram аккаунтов (4 дня)"""
    
    # Публичные каналы для прогрева (безопасные, популярные)
    WARMUP_CHANNELS = [
        '@telegram',
        '@durov',
        '@TelegramTips',
        '@WebogramNews',
    ]
    
    # Эмодзи для реакций
    REACTION_EMOJIS = ['👍', '❤️', '🔥', '😊', '👏', '🎉', '💯', '⚡']
    
    # Простые универсальные комментарии для прогрева
    WARMUP_COMMENTS = [
        'Интересно!',
        'Спасибо за информацию',
        'Полезно 👍',
        'Хорошо написано',
        'Согласен',
        'Отлично!',
        'Познавательно',
        'Благодарю ❤️',
    ]
    
    def __init__(self, db_path: str = 'bot_advanced.db'):
        """Инициализация модуля прогрева"""
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        """Создание таблицы для отслеживания прогрева"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS account_warmup (
                phone TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                start_date TEXT NOT NULL,
                current_day INTEGER DEFAULT 1,
                actions_today INTEGER DEFAULT 0,
                total_actions INTEGER DEFAULT 0,
                last_action TEXT,
                completed_date TEXT,
                notes TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("✅ Таблица account_warmup инициализирована")
    
    def get_warmup_status(self, phone: str) -> Optional[Dict]:
        """Получить статус прогрева аккаунта"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT status, start_date, current_day, actions_today, 
                   total_actions, last_action, completed_date
            FROM account_warmup WHERE phone = ?
        ''', (phone,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'status': row[0],
                'start_date': row[1],
                'current_day': row[2],
                'actions_today': row[3],
                'total_actions': row[4],
                'last_action': row[5],
                'completed_date': row[6]
            }
        return None
    
    def start_warmup(self, phone: str) -> bool:
        """Начать прогрев аккаунта"""
        import sqlite3
        
        # Проверяем, не прогревается ли уже
        status = self.get_warmup_status(phone)
        if status and status['status'] == 'active':
            logger.warning(f"⚠️ {phone} уже прогревается")
            return False
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        now = datetime.now().isoformat()
        
        cursor.execute('''
            INSERT OR REPLACE INTO account_warmup 
            (phone, status, start_date, current_day, actions_today, total_actions, last_action)
            VALUES (?, 'active', ?, 1, 0, 0, ?)
        ''', (phone, now, now))
        
        conn.commit()
        conn.close()
        
        logger.info(f"🔥 Начат прогрев аккаунта {phone}")
        return True
    
    def stop_warmup(self, phone: str, reason: str = 'manual_stop'):
        """Остановить прогрев аккаунта"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE account_warmup 
            SET status = 'stopped', notes = ?
            WHERE phone = ?
        ''', (reason, phone))
        
        conn.commit()
        conn.close()
        logger.info(f"⏸️ Прогрев {phone} остановлен: {reason}")
    
    def complete_warmup(self, phone: str):
        """Отметить прогрев как завершенный"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        now = datetime.now().isoformat()
        
        cursor.execute('''
            UPDATE account_warmup 
            SET status = 'completed', completed_date = ?
            WHERE phone = ?
        ''', (now, phone))
        
        conn.commit()
        conn.close()
        logger.info(f"✅ Прогрев {phone} завершен!")
    
    def update_progress(self, phone: str, action_type: str):
        """Обновить прогресс прогрева после действия"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        now = datetime.now().isoformat()
        
        cursor.execute('''
            UPDATE account_warmup 
            SET actions_today = actions_today + 1,
                total_actions = total_actions + 1,
                last_action = ?
            WHERE phone = ?
        ''', (now, phone))
        
        conn.commit()
        conn.close()
    
    def advance_day(self, phone: str):
        """Перейти к следующему дню прогрева"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE account_warmup 
            SET current_day = current_day + 1,
                actions_today = 0
            WHERE phone = ?
        ''', (phone,))
        
        conn.commit()
        conn.close()
        logger.info(f"📅 {phone} перешел на следующий день прогрева")
    
    def get_all_active_warmups(self) -> List[str]:
        """Получить список всех аккаунтов в процессе прогрева"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT phone FROM account_warmup 
            WHERE status = 'active'
        ''')
        
        phones = [row[0] for row in cursor.fetchall()]
        conn.close()
        return phones
    
    async def run_warmup_cycle(self, client: TelegramClient, phone: str):
        """
        Выполнить один цикл прогрева для аккаунта
        Автоматически определяет действия в зависимости от дня
        """
        status = self.get_warmup_status(phone)
        if not status or status['status'] != 'active':
            logger.warning(f"⚠️ {phone} не активен для прогрева")
            return
        
        current_day = status['current_day']
        
        try:
            if current_day == 1:
                await self._day1_warmup(client, phone)
            elif current_day == 2:
                await self._day2_warmup(client, phone)
            elif current_day == 3:
                await self._day3_warmup(client, phone)
            elif current_day == 4:
                await self._day4_warmup(client, phone)
            else:
                # Прогрев завершен
                self.complete_warmup(phone)
                logger.info(f"🎉 {phone} завершил прогрев!")
                
        except FloodWaitError as e:
            logger.warning(f"⏳ FloodWait для {phone}: {e.seconds}с")
            await asyncio.sleep(e.seconds)
        except Exception as e:
            logger.error(f"❌ Ошибка прогрева {phone}: {e}")
    
    async def _day1_warmup(self, client: TelegramClient, phone: str):
        """
        День 1: Минимальная активность
        - Просмотр каналов: 5-8
        - Подписки: 2-3
        - Задержки: 8-15 мин между действиями
        """
        logger.info(f"📅 {phone} - День 1: Просмотр и подписки")
        
        channels_to_view = random.sample(self.WARMUP_CHANNELS, min(3, len(self.WARMUP_CHANNELS)))
        
        for channel in channels_to_view:
            try:
                # Получаем канал
                entity = await client.get_entity(channel)
                
                # Читаем последние сообщения
                messages = await client.get_messages(entity, limit=5)
                logger.info(f"👁️ {phone} просмотрел {len(messages)} сообщений в {channel}")
                
                # Задержка между просмотрами
                await asyncio.sleep(random.randint(10, 20))
                
                # Подписываемся (50% шанс)
                if random.random() > 0.5:
                    await client(functions.channels.JoinChannelRequest(entity))
                    logger.info(f"✅ {phone} подписался на {channel}")
                    await asyncio.sleep(random.randint(5, 10))
                
                self.update_progress(phone, 'view_channel')
                
            except Exception as e:
                logger.error(f"❌ Ошибка при работе с {channel}: {e}")
            
            # Большая задержка между каналами
            await asyncio.sleep(random.randint(480, 900))  # 8-15 минут
    
    async def _day2_warmup(self, client: TelegramClient, phone: str):
        """
        День 2: Реакции на посты
        - Реакции: 10-15 в день
        - Задержки: 5-10 мин
        """
        logger.info(f"📅 {phone} - День 2: Реакции на посты")
        
        reactions_count = random.randint(10, 15)
        channels = self.WARMUP_CHANNELS
        
        for i in range(reactions_count):
            try:
                channel = random.choice(channels)
                entity = await client.get_entity(channel)
                
                # Получаем случайное сообщение
                messages = await client.get_messages(entity, limit=20)
                if messages:
                    msg = random.choice(messages)
                    emoji = random.choice(self.REACTION_EMOJIS)
                    
                    # Ставим реакцию
                    await client.send_reaction(entity, msg.id, emoji)
                    logger.info(f"❤️ {phone} поставил {emoji} на пост в {channel}")
                    
                    self.update_progress(phone, 'reaction')
                    
                    # Задержка
                    await asyncio.sleep(random.randint(300, 600))  # 5-10 минут
                    
            except Exception as e:
                logger.error(f"❌ Ошибка реакции: {e}")
                await asyncio.sleep(60)
    
    async def _day3_warmup(self, client: TelegramClient, phone: str):
        """
        День 3: Первые комментарии
        - Комментарии: 3-5 в день
        - Реакции: 10-12
        - Задержки: 4-8 мин
        """
        logger.info(f"📅 {phone} - День 3: Комментарии")
        
        # Сначала реакции
        for i in range(random.randint(10, 12)):
            try:
                channel = random.choice(self.WARMUP_CHANNELS)
                entity = await client.get_entity(channel)
                messages = await client.get_messages(entity, limit=20)
                
                if messages:
                    msg = random.choice(messages)
                    emoji = random.choice(self.REACTION_EMOJIS)
                    await client.send_reaction(entity, msg.id, emoji)
                    
                    self.update_progress(phone, 'reaction')
                    await asyncio.sleep(random.randint(180, 300))  # 3-5 минут
                    
            except Exception as e:
                logger.error(f"❌ Ошибка реакции: {e}")
        
        # Теперь комментарии
        comments_count = random.randint(3, 5)
        
        for i in range(comments_count):
            try:
                channel = random.choice(self.WARMUP_CHANNELS)
                entity = await client.get_entity(channel)
                messages = await client.get_messages(entity, limit=10)
                
                if messages:
                    msg = random.choice(messages)
                    comment_text = random.choice(self.WARMUP_COMMENTS)
                    
                    # Отправляем комментарий
                    await client.send_message(entity, comment_text, comment_to=msg.id)
                    logger.info(f"💬 {phone} оставил комментарий в {channel}")
                    
                    self.update_progress(phone, 'comment')
                    
                    # Большая задержка после комментария
                    await asyncio.sleep(random.randint(240, 480))  # 4-8 минут
                    
            except ChatWriteForbiddenError:
                logger.warning(f"⚠️ Комментарии запрещены в канале")
            except UserBannedInChannelError:
                logger.warning(f"⚠️ Пользователь забанен в канале")
            except Exception as e:
                logger.error(f"❌ Ошибка комментария: {e}")
                await asyncio.sleep(120)
    
    async def _day4_warmup(self, client: TelegramClient, phone: str):
        """
        День 4: Полная активность
        - Комментарии: 8-10
        - Реакции: 15-20
        - Задержки: 3-6 мин
        """
        logger.info(f"📅 {phone} - День 4: Полная активность")
        
        # Интенсивные реакции
        for i in range(random.randint(15, 20)):
            try:
                channel = random.choice(self.WARMUP_CHANNELS)
                entity = await client.get_entity(channel)
                messages = await client.get_messages(entity, limit=30)
                
                if messages:
                    msg = random.choice(messages)
                    emoji = random.choice(self.REACTION_EMOJIS)
                    await client.send_reaction(entity, msg.id, emoji)
                    
                    self.update_progress(phone, 'reaction')
                    await asyncio.sleep(random.randint(120, 240))  # 2-4 минуты
                    
            except Exception as e:
                logger.error(f"❌ Ошибка реакции: {e}")
        
        # Активные комментарии
        comments_count = random.randint(8, 10)
        
        for i in range(comments_count):
            try:
                channel = random.choice(self.WARMUP_CHANNELS)
                entity = await client.get_entity(channel)
                messages = await client.get_messages(entity, limit=15)
                
                if messages:
                    msg = random.choice(messages)
                    comment_text = random.choice(self.WARMUP_COMMENTS)
                    
                    await client.send_message(entity, comment_text, comment_to=msg.id)
                    logger.info(f"💬 {phone} оставил комментарий в {channel}")
                    
                    self.update_progress(phone, 'comment')
                    await asyncio.sleep(random.randint(180, 360))  # 3-6 минут
                    
            except (ChatWriteForbiddenError, UserBannedInChannelError):
                logger.warning(f"⚠️ Не удалось оставить комментарий")
            except Exception as e:
                logger.error(f"❌ Ошибка комментария: {e}")
                await asyncio.sleep(120)
        
        # День завершен
        logger.info(f"✅ {phone} завершил День 4 прогрева")
    
    def get_warmup_report(self) -> str:
        """Получить отчет по всем прогреваемым аккаунтам"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT phone, status, start_date, current_day, 
                   total_actions, last_action
            FROM account_warmup
            ORDER BY start_date DESC
        ''')
        
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return "📊 Нет аккаунтов в процессе прогрева"
        
        report = "📊 **ОТЧЕТ ПО ПРОГРЕВУ АККАУНТОВ**\n\n"
        
        for row in rows:
            phone, status, start_date, current_day, total_actions, last_action = row
            
            status_emoji = {
                'active': '🔥',
                'completed': '✅',
                'stopped': '⏸️'
            }.get(status, '❓')
            
            start = datetime.fromisoformat(start_date)
            days_elapsed = (datetime.now() - start).days
            
            report += f"{status_emoji} **{phone}**\n"
            report += f"   Статус: `{status}`\n"
            report += f"   День: `{current_day}/4`\n"
            report += f"   Действий: `{total_actions}`\n"
            report += f"   Прошло дней: `{days_elapsed}`\n\n"
        
        return report


# Глобальный экземпляр для использования в main.py
warmup_manager = AccountWarmup()

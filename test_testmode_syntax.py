#!/usr/bin/env python3
"""Извлечение и проверка только обработчика testmode"""

with open('main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Извлечь функцию testmode_command (строки 6627-6856)
testmode_code = ''.join(lines[6626:6857])  # Индексы с 0

# Создать минимальный тестовый файл
test_code = '''
import asyncio
from telethon import TelegramClient, events

class TestBot:
    def __init__(self):
        self.bot_client = None
        self.test_mode = False
        self.test_channels = []
        self.test_mode_speed_limit = 10
        self.channels = []
        
    async def is_admin(self, user_id):
        return True
    
    def save_data(self):
        pass
    
    def save_config_value(self, key, value):
        pass
    
    async def test_mode_bulk_channels(self, event, channels):
        pass
    
    def _normalize_channel_username(self, username):
        return username.lstrip('@').lower()
    
    def setup_handlers(self):
''' + testmode_code + '''
        
bot = TestBot()
print("✅ Код testmode_command синтаксически корректен")
'''

# Попробовать скомпилировать
try:
    compile(test_code, '<string>', 'exec')
    print("✅ Обработчик testmode_command компилируется без ошибок")
except SyntaxError as e:
    print(f"❌ Синтаксическая ошибка в testmode_command:")
    print(f"   Строка {e.lineno}: {e.msg}")
    print(f"   Текст: {e.text}")

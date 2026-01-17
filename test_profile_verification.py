#!/usr/bin/env python3
"""
ПОЛНАЯ ВЕРИФИКАЦИЯ PROFILE OPERATIONS
Проверяем не только отсутствие ошибок, но и РЕАЛЬНЫЕ изменения в Telegram
"""
import asyncio
import json
import os
import sys
from datetime import datetime
from telethon import TelegramClient
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest
from telethon.tl.functions.users import GetFullUserRequest
from PIL import Image

class ProfileVerificationTest:
    def __init__(self):
        self.results = []
        self.detailed_logs = []
        
    def log(self, msg, level="INFO"):
        """Логирование с сохранением"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        log_entry = f"[{timestamp}] [{level}] {msg}"
        print(log_entry)
        self.detailed_logs.append(log_entry)
    
    async def get_current_profile(self, client):
        """Читаем текущее состояние профиля"""
        try:
            me = await client.get_me()
            full_user = await client(GetFullUserRequest(me.id))
            
            return {
                'first_name': me.first_name or '',
                'last_name': me.last_name or '',
                'bio': full_user.full_user.about or '',
                'user_id': me.id,
                'username': me.username or ''
            }
        except Exception as e:
            self.log(f"❌ Ошибка чтения профиля: {e}", "ERROR")
            return None
    
    async def test_bio_with_verification(self, client, phone, test_bio):
        """Тест BIO с проверкой реального изменения"""
        self.log(f"\n{'='*70}")
        self.log(f"📝 ТЕСТ BIO для {phone}")
        self.log(f"{'='*70}")
        
        # 1. Читаем ТЕКУЩЕЕ состояние
        self.log("1️⃣ Читаем текущий профиль...")
        before = await self.get_current_profile(client)
        if not before:
            return {'status': 'ERROR', 'reason': 'Не удалось прочитать профиль'}
        
        old_bio = before['bio']
        self.log(f"   Текущее БИО: '{old_bio[:50]}...'")
        self.log(f"   Новое БИО: '{test_bio}'")
        
        # 2. Вызываем API
        self.log("2️⃣ Вызываем UpdateProfileRequest(about=...)...")
        try:
            result = await client(UpdateProfileRequest(about=test_bio))
            result_type = type(result).__name__
            self.log(f"   ✅ API вызов успешен, тип ответа: {result_type}")
            
            # Логируем детали ответа
            if hasattr(result, 'user'):
                self.log(f"   📊 Ответ содержит user: ID={result.user.id}")
            
        except Exception as e:
            error_msg = str(e)
            self.log(f"   ❌ API вызов FAILED: {type(e).__name__}", "ERROR")
            self.log(f"   ❌ Сообщение: {error_msg}", "ERROR")
            
            if "FROZEN" in error_msg:
                return {
                    'status': 'FROZEN',
                    'api_error': error_msg,
                    'reason': 'Telegram вернул FROZEN_METHOD_INVALID'
                }
            else:
                return {
                    'status': 'API_ERROR',
                    'api_error': error_msg,
                    'reason': f'API error: {type(e).__name__}'
                }
        
        # 3. Читаем профиль ПОСЛЕ изменения
        self.log("3️⃣ Перечитываем профиль для проверки...")
        await asyncio.sleep(0.5)  # Небольшая пауза для синхронизации
        after = await self.get_current_profile(client)
        
        if not after:
            return {
                'status': 'VERIFICATION_FAILED',
                'reason': 'Не удалось перечитать профиль после изменения'
            }
        
        new_bio = after['bio']
        self.log(f"   Профиль после операции: '{new_bio[:50]}...'")
        
        # 4. ПРОВЕРЯЕМ реальное изменение
        self.log("4️⃣ Проверка реального изменения...")
        if new_bio == test_bio:
            self.log(f"   ✅ УСПЕХ! БИО реально изменилось в Telegram!", "SUCCESS")
            self.log(f"   ✅ Было: '{old_bio[:30]}...'")
            self.log(f"   ✅ Стало: '{new_bio[:30]}...'")
            return {
                'status': 'SUCCESS',
                'old_value': old_bio,
                'new_value': new_bio,
                'verified': True,
                'api_result_type': result_type
            }
        else:
            self.log(f"   ⚠️ ПРОВАЛ! API вернул success, но БИО НЕ ИЗМЕНИЛОСЬ!", "WARNING")
            self.log(f"   ⚠️ Ожидали: '{test_bio}'", "WARNING")
            self.log(f"   ⚠️ Получили: '{new_bio}'", "WARNING")
            return {
                'status': 'FALSE_SUCCESS',
                'reason': 'API вернул success, но профиль не изменился',
                'expected': test_bio,
                'actual': new_bio,
                'old_value': old_bio,
                'api_result_type': result_type
            }
    
    async def test_name_with_verification(self, client, phone, first_name, last_name):
        """Тест NAME с проверкой реального изменения"""
        self.log(f"\n{'='*70}")
        self.log(f"👤 ТЕСТ NAME для {phone}")
        self.log(f"{'='*70}")
        
        # 1. Читаем ТЕКУЩЕЕ
        self.log("1️⃣ Читаем текущий профиль...")
        before = await self.get_current_profile(client)
        if not before:
            return {'status': 'ERROR', 'reason': 'Не удалось прочитать профиль'}
        
        old_first = before['first_name']
        old_last = before['last_name']
        self.log(f"   Текущее имя: '{old_first}' '{old_last}'")
        self.log(f"   Новое имя: '{first_name}' '{last_name}'")
        
        # 2. Вызываем API
        self.log("2️⃣ Вызываем UpdateProfileRequest(first_name=..., last_name=...)...")
        try:
            result = await client(UpdateProfileRequest(
                first_name=first_name,
                last_name=last_name
            ))
            result_type = type(result).__name__
            self.log(f"   ✅ API вызов успешен, тип ответа: {result_type}")
            
        except Exception as e:
            error_msg = str(e)
            self.log(f"   ❌ API вызов FAILED: {type(e).__name__}", "ERROR")
            self.log(f"   ❌ Сообщение: {error_msg}", "ERROR")
            
            if "FROZEN" in error_msg:
                return {
                    'status': 'FROZEN',
                    'api_error': error_msg,
                    'reason': 'Telegram вернул FROZEN_METHOD_INVALID'
                }
            else:
                return {
                    'status': 'API_ERROR',
                    'api_error': error_msg,
                    'reason': f'API error: {type(e).__name__}'
                }
        
        # 3. Читаем ПОСЛЕ
        self.log("3️⃣ Перечитываем профиль для проверки...")
        await asyncio.sleep(0.5)
        after = await self.get_current_profile(client)
        
        if not after:
            return {
                'status': 'VERIFICATION_FAILED',
                'reason': 'Не удалось перечитать профиль'
            }
        
        new_first = after['first_name']
        new_last = after['last_name']
        self.log(f"   Профиль после: '{new_first}' '{new_last}'")
        
        # 4. ПРОВЕРЯЕМ
        self.log("4️⃣ Проверка реального изменения...")
        if new_first == first_name and new_last == last_name:
            self.log(f"   ✅ УСПЕХ! ИМЯ реально изменилось!", "SUCCESS")
            self.log(f"   ✅ Было: '{old_first}' '{old_last}'")
            self.log(f"   ✅ Стало: '{new_first}' '{new_last}'")
            return {
                'status': 'SUCCESS',
                'old_value': f"{old_first} {old_last}",
                'new_value': f"{new_first} {new_last}",
                'verified': True,
                'api_result_type': result_type
            }
        else:
            self.log(f"   ⚠️ ПРОВАЛ! API success, но ИМЯ НЕ ИЗМЕНИЛОСЬ!", "WARNING")
            return {
                'status': 'FALSE_SUCCESS',
                'reason': 'API success, но профиль не изменился',
                'expected': f"{first_name} {last_name}",
                'actual': f"{new_first} {new_last}",
                'old_value': f"{old_first} {old_last}",
                'api_result_type': result_type
            }
    
    async def test_avatar_with_verification(self, client, phone):
        """Тест AVATAR с проверкой"""
        self.log(f"\n{'='*70}")
        self.log(f"🖼️  ТЕСТ AVATAR для {phone}")
        self.log(f"{'='*70}")
        
        # 1. Создаём уникальное изображение
        import random
        color = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
        img = Image.new('RGB', (512, 512), color=color)
        temp_file = f'/tmp/test_avatar_{phone.replace("+", "")}.jpg'
        img.save(temp_file, 'JPEG', quality=95)
        self.log(f"1️⃣ Создано изображение: {temp_file}, цвет RGB{color}")
        
        # 2. Читаем текущие фото
        self.log("2️⃣ Читаем текущие фото профиля...")
        me = await client.get_me()
        photos_before = await client.get_profile_photos('me')
        photos_count_before = len(photos_before)
        self.log(f"   Текущее количество фото: {photos_count_before}")
        
        # 3. Вызываем API
        self.log("3️⃣ Вызываем UploadProfilePhotoRequest...")
        try:
            uploaded_file = await client.upload_file(temp_file)
            result = await client(UploadProfilePhotoRequest(file=uploaded_file))
            result_type = type(result).__name__
            self.log(f"   ✅ API вызов успешен, тип ответа: {result_type}")
            
            if hasattr(result, 'photo'):
                self.log(f"   📊 Ответ содержит photo объект")
            
        except Exception as e:
            error_msg = str(e)
            self.log(f"   ❌ API FAILED: {type(e).__name__}", "ERROR")
            self.log(f"   ❌ Сообщение: {error_msg}", "ERROR")
            
            # Удаляем временный файл
            if os.path.exists(temp_file):
                os.remove(temp_file)
            
            if "FROZEN" in error_msg:
                return {
                    'status': 'FROZEN',
                    'api_error': error_msg,
                    'reason': 'FROZEN_METHOD_INVALID'
                }
            else:
                return {
                    'status': 'API_ERROR',
                    'api_error': error_msg,
                    'reason': f'{type(e).__name__}'
                }
        
        # 4. Проверяем ПОСЛЕ
        self.log("4️⃣ Перечитываем список фото...")
        await asyncio.sleep(1)  # Пауза для синхронизации
        photos_after = await client.get_profile_photos('me')
        photos_count_after = len(photos_after)
        self.log(f"   Количество фото после: {photos_count_after}")
        
        # Удаляем временный файл
        if os.path.exists(temp_file):
            os.remove(temp_file)
        
        # 5. ПРОВЕРЯЕМ
        self.log("5️⃣ Проверка реального изменения...")
        if photos_count_after > photos_count_before:
            self.log(f"   ✅ УСПЕХ! Аватарка реально загружена!", "SUCCESS")
            self.log(f"   ✅ Было фото: {photos_count_before}")
            self.log(f"   ✅ Стало фото: {photos_count_after}")
            return {
                'status': 'SUCCESS',
                'photos_before': photos_count_before,
                'photos_after': photos_count_after,
                'verified': True,
                'api_result_type': result_type
            }
        else:
            self.log(f"   ⚠️ ПРОВАЛ! API success, но аватарка НЕ загружена!", "WARNING")
            return {
                'status': 'FALSE_SUCCESS',
                'reason': 'API success, но количество фото не изменилось',
                'photos_before': photos_count_before,
                'photos_after': photos_count_after,
                'api_result_type': result_type
            }
    
    async def test_account(self, phone, session_string, api_id, api_hash):
        """Тестируем один аккаунт"""
        self.log(f"\n\n{'#'*70}")
        self.log(f"📱 АККАУНТ: {phone}")
        self.log(f"{'#'*70}")
        
        result = {
            'phone': phone,
            'bio': None,
            'name': None,
            'avatar': None,
            'authorized': False
        }
        
        # Используем StringSession
        from telethon.sessions import StringSession
        client = None
        
        try:
            client = TelegramClient(StringSession(session_string), api_id, api_hash)
            await client.connect()
            
            if not await client.is_user_authorized():
                self.log(f"❌ Аккаунт НЕ авторизован", "ERROR")
                result['authorized'] = False
                return result
            
            result['authorized'] = True
            me = await client.get_me()
            self.log(f"✅ Авторизован: ID={me.id}, username={me.username}")
            
            # Генерируем уникальные значения
            import random
            test_suffix = random.randint(1000, 9999)
            
            # Тест BIO
            result['bio'] = await self.test_bio_with_verification(
                client, phone, f"Test Bio {test_suffix}"
            )
            
            # Тест NAME
            result['name'] = await self.test_name_with_verification(
                client, phone, me.first_name or "Test", f"Bot{test_suffix}"
            )
            
            # Тест AVATAR
            result['avatar'] = await self.test_avatar_with_verification(
                client, phone
            )
            
        except Exception as e:
            self.log(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}", "ERROR")
            import traceback
            self.log(traceback.format_exc(), "ERROR")
        
        finally:
            if client and client.is_connected():
                await client.disconnect()
        
        return result
    
    async def run_full_test(self):
        """Запуск полного теста всех аккаунтов"""
        self.log("🚀 СТАРТ ПОЛНОЙ ВЕРИФИКАЦИИ PROFILE OPERATIONS")
        self.log(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Загружаем bot_data.json
        try:
            with open('bot_data.json', 'r') as f:
                bot_data = json.load(f)
        except Exception as e:
            self.log(f"❌ Ошибка чтения bot_data.json: {e}", "ERROR")
            return
        
        accounts = bot_data.get('accounts', {})
        
        # API credentials из main.py
        api_id = 36053254
        api_hash = '4c63aee24cbc1be5e593329370712e7f'
        
        self.log(f"\n📊 Найдено аккаунтов: {len(accounts)}")
        
        # Тестируем каждый аккаунт
        for phone, acc_data in accounts.items():
            if not isinstance(acc_data, dict):
                continue
            
            result = await self.test_account(
                phone,
                acc_data.get('session', ''),
                api_id,
                api_hash
            )
            self.results.append(result)
        
        # Формируем итоговый отчёт
        self.generate_report()
    
    def generate_report(self):
        """Генерация итогового отчёта"""
        self.log(f"\n\n{'='*70}")
        self.log("📊 ИТОГОВЫЙ ОТЧЁТ")
        self.log(f"{'='*70}\n")
        
        # Таблица результатов
        self.log(f"{'Телефон':<18} {'BIO':<20} {'NAME':<20} {'AVATAR':<20}")
        self.log("-" * 78)
        
        for r in self.results:
            phone = r['phone']
            
            # BIO
            bio_status = self._format_status(r.get('bio'))
            name_status = self._format_status(r.get('name'))
            avatar_status = self._format_status(r.get('avatar'))
            
            self.log(f"{phone:<18} {bio_status:<20} {name_status:<20} {avatar_status:<20}")
        
        # Детальная статистика
        self.log(f"\n{'='*70}")
        self.log("📈 ДЕТАЛЬНАЯ СТАТИСТИКА")
        self.log(f"{'='*70}\n")
        
        for r in self.results:
            self.log(f"\n📱 {r['phone']}:")
            if not r['authorized']:
                self.log("   ❌ НЕ АВТОРИЗОВАН")
                continue
            
            for op_name, op_data in [('BIO', r.get('bio')), ('NAME', r.get('name')), ('AVATAR', r.get('avatar'))]:
                if not op_data:
                    continue
                
                status = op_data.get('status', 'UNKNOWN')
                self.log(f"\n   {op_name}:")
                self.log(f"      Статус: {status}")
                
                if status == 'SUCCESS':
                    self.log(f"      ✅ РЕАЛЬНО ИЗМЕНИЛОСЬ В TELEGRAM")
                    if 'old_value' in op_data:
                        self.log(f"      Было: {op_data['old_value'][:40]}")
                    if 'new_value' in op_data:
                        self.log(f"      Стало: {op_data['new_value'][:40]}")
                    if 'api_result_type' in op_data:
                        self.log(f"      API ответ: {op_data['api_result_type']}")
                
                elif status == 'FALSE_SUCCESS':
                    self.log(f"      ⚠️ API ВЕРНУЛ SUCCESS, НО ПРОФИЛЬ НЕ ИЗМЕНИЛСЯ!")
                    self.log(f"      Причина: {op_data.get('reason', 'Unknown')}")
                    if 'expected' in op_data:
                        self.log(f"      Ожидали: {op_data['expected'][:40]}")
                    if 'actual' in op_data:
                        self.log(f"      Получили: {op_data['actual'][:40]}")
                
                elif status == 'FROZEN':
                    self.log(f"      ❌ TELEGRAM ВЕРНУЛ FROZEN_METHOD_INVALID")
                    if 'api_error' in op_data:
                        self.log(f"      Ошибка: {op_data['api_error'][:60]}")
                
                elif status == 'API_ERROR':
                    self.log(f"      ❌ ОШИБКА API")
                    if 'api_error' in op_data:
                        self.log(f"      Ошибка: {op_data['api_error'][:60]}")
        
        # Сохраняем результаты
        report_data = {
            'timestamp': datetime.now().isoformat(),
            'results': self.results,
            'logs': self.detailed_logs
        }
        
        with open('profile_verification_report.json', 'w') as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)
        
        self.log(f"\n💾 Полный отчёт сохранён: profile_verification_report.json")
        self.log(f"💾 Подробные логи доступны в JSON файле")
    
    def _format_status(self, op_data):
        """Форматирование статуса для таблицы"""
        if not op_data:
            return "❓ NO_DATA"
        
        status = op_data.get('status', 'UNKNOWN')
        
        if status == 'SUCCESS':
            return "✅ ИЗМЕНЯЕТСЯ"
        elif status == 'FALSE_SUCCESS':
            return "⚠️ ЛОЖНЫЙ УСПЕХ"
        elif status == 'FROZEN':
            return "❌ FROZEN"
        elif status == 'API_ERROR':
            return "❌ API_ERROR"
        elif status == 'VERIFICATION_FAILED':
            return "⚠️ НЕТ ВЕРИФИКАЦИИ"
        else:
            return f"❓ {status}"

async def main():
    tester = ProfileVerificationTest()
    await tester.run_full_test()

if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
ПРОДВИНУТАЯ ДИАГНОСТИКА И ПОПЫТКИ ОБХОДА ОГРАНИЧЕНИЙ
Тестируем разные подходы для разблокировки аккаунтов
"""
import asyncio
import json
import os
import time
from datetime import datetime
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.errors import FloodWaitError, FloodError
from PIL import Image

API_ID = 36053254
API_HASH = '4c63aee24cbc1be5e593329370712e7f'

class AdvancedProfileDiagnostics:
    def __init__(self):
        self.results = {}
        self.strategies = []
    
    def log(self, msg, level="INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] [{level}] {msg}")
    
    async def check_account_health(self, client, phone):
        """Проверка общего здоровья аккаунта"""
        self.log(f"\n{'='*70}")
        self.log(f"🏥 HEALTH CHECK для {phone}")
        self.log(f"{'='*70}")
        
        health = {
            'authorized': False,
            'user_id': None,
            'username': None,
            'is_bot': False,
            'is_restricted': False,
            'restrictions': [],
            'phone_verified': False,
            'has_password': False,
            'account_age_days': None
        }
        
        try:
            me = await client.get_me()
            health['authorized'] = True
            health['user_id'] = me.id
            health['username'] = me.username
            health['is_bot'] = me.bot
            health['phone_verified'] = me.verified
            
            # Получаем полную информацию
            full = await client(GetFullUserRequest(me.id))
            
            # Проверяем ограничения
            if hasattr(me, 'restricted'):
                health['is_restricted'] = me.restricted
            
            if hasattr(me, 'restriction_reason'):
                health['restrictions'] = me.restriction_reason
            
            # Проверяем двухфакторку
            # Note: полную проверку пароля сложно сделать без попытки логина
            
            self.log(f"✅ User ID: {health['user_id']}")
            self.log(f"✅ Username: {health['username'] or 'не задан'}")
            self.log(f"✅ Phone verified: {health['phone_verified']}")
            self.log(f"✅ Is restricted: {health['is_restricted']}")
            
            if health['restrictions']:
                self.log(f"⚠️ Restrictions: {health['restrictions']}", "WARNING")
            
        except Exception as e:
            self.log(f"❌ Health check failed: {e}", "ERROR")
        
        return health
    
    async def test_with_delay(self, client, phone, operation_name, operation_func, delay=2):
        """Тест с задержкой между запросами"""
        self.log(f"\n📝 ТЕСТ: {operation_name} (с задержкой {delay}s)")
        
        try:
            # Задержка перед операцией
            self.log(f"⏱️ Ждём {delay}s перед операцией...")
            await asyncio.sleep(delay)
            
            result = await operation_func(client)
            
            self.log(f"✅ {operation_name} выполнено успешно")
            return {'status': 'SUCCESS', 'result': result}
            
        except FloodWaitError as e:
            wait_time = e.seconds
            self.log(f"⏳ FloodWait: нужно ждать {wait_time}s", "WARNING")
            return {'status': 'FLOOD_WAIT', 'wait_seconds': wait_time}
        
        except FloodError as e:
            error_msg = str(e)
            if "FROZEN" in error_msg:
                self.log(f"❌ FROZEN: {error_msg}", "ERROR")
                return {'status': 'FROZEN', 'error': error_msg}
            else:
                self.log(f"❌ FloodError: {error_msg}", "ERROR")
                return {'status': 'FLOOD_ERROR', 'error': error_msg}
        
        except Exception as e:
            self.log(f"❌ Ошибка: {type(e).__name__}: {e}", "ERROR")
            return {'status': 'ERROR', 'error': str(e)}
    
    async def test_bio_strategies(self, client, phone):
        """Тестируем разные стратегии изменения био"""
        self.log(f"\n{'#'*70}")
        self.log(f"📝 ТЕСТИРОВАНИЕ СТРАТЕГИЙ ДЛЯ BIO: {phone}")
        self.log(f"{'#'*70}")
        
        strategies_results = {}
        
        # Стратегия 1: Простое изменение
        self.log(f"\n🔸 СТРАТЕГИЯ 1: Простое изменение")
        async def simple_bio(c):
            return await c(UpdateProfileRequest(about="Test 1"))
        
        strategies_results['simple'] = await self.test_with_delay(
            client, phone, "Simple bio update", simple_bio, delay=1
        )
        
        # Если успешно - верифицируем
        if strategies_results['simple']['status'] == 'SUCCESS':
            await asyncio.sleep(0.5)
            me = await client.get_me()
            full = await client(GetFullUserRequest(me.id))
            actual_bio = full.full_user.about or ''
            verified = (actual_bio == "Test 1")
            strategies_results['simple']['verified'] = verified
            self.log(f"{'✅' if verified else '⚠️'} Верификация: {verified}")
        
        # Стратегия 2: Очистка перед изменением
        if strategies_results['simple']['status'] != 'SUCCESS':
            self.log(f"\n🔸 СТРАТЕГИЯ 2: Сначала очистка, потом установка")
            
            # Сначала очищаем
            async def clear_bio(c):
                return await c(UpdateProfileRequest(about=""))
            
            clear_result = await self.test_with_delay(
                client, phone, "Clear bio", clear_bio, delay=2
            )
            
            if clear_result['status'] == 'SUCCESS':
                # Потом устанавливаем
                async def set_bio(c):
                    return await c(UpdateProfileRequest(about="Test 2"))
                
                set_result = await self.test_with_delay(
                    client, phone, "Set bio after clear", set_bio, delay=2
                )
                
                strategies_results['clear_then_set'] = set_result
                
                if set_result['status'] == 'SUCCESS':
                    await asyncio.sleep(0.5)
                    me = await client.get_me()
                    full = await client(GetFullUserRequest(me.id))
                    actual_bio = full.full_user.about or ''
                    verified = (actual_bio == "Test 2")
                    strategies_results['clear_then_set']['verified'] = verified
                    self.log(f"{'✅' if verified else '⚠️'} Верификация: {verified}")
            else:
                strategies_results['clear_then_set'] = clear_result
        
        # Стратегия 3: Маленькое изменение (1 символ)
        if strategies_results['simple']['status'] != 'SUCCESS':
            self.log(f"\n🔸 СТРАТЕГИЯ 3: Минимальное био (1 символ)")
            
            async def minimal_bio(c):
                return await c(UpdateProfileRequest(about="x"))
            
            strategies_results['minimal'] = await self.test_with_delay(
                client, phone, "Minimal bio (1 char)", minimal_bio, delay=2
            )
            
            if strategies_results['minimal']['status'] == 'SUCCESS':
                await asyncio.sleep(0.5)
                me = await client.get_me()
                full = await client(GetFullUserRequest(me.id))
                actual_bio = full.full_user.about or ''
                verified = (actual_bio == "x")
                strategies_results['minimal']['verified'] = verified
                self.log(f"{'✅' if verified else '⚠️'} Верификация: {verified}")
        
        # Стратегия 4: Большая задержка (5 секунд)
        if strategies_results['simple']['status'] == 'FLOOD_WAIT':
            self.log(f"\n🔸 СТРАТЕГИЯ 4: Большая задержка (5s)")
            
            async def delayed_bio(c):
                return await c(UpdateProfileRequest(about="Test 4"))
            
            strategies_results['long_delay'] = await self.test_with_delay(
                client, phone, "Bio with 5s delay", delayed_bio, delay=5
            )
            
            if strategies_results['long_delay']['status'] == 'SUCCESS':
                await asyncio.sleep(0.5)
                me = await client.get_me()
                full = await client(GetFullUserRequest(me.id))
                actual_bio = full.full_user.about or ''
                verified = (actual_bio == "Test 4")
                strategies_results['long_delay']['verified'] = verified
                self.log(f"{'✅' if verified else '⚠️'} Верификация: {verified}")
        
        return strategies_results
    
    async def test_name_strategies(self, client, phone):
        """Тестируем разные стратегии изменения имени"""
        self.log(f"\n{'#'*70}")
        self.log(f"👤 ТЕСТИРОВАНИЕ СТРАТЕГИЙ ДЛЯ NAME: {phone}")
        self.log(f"{'#'*70}")
        
        strategies_results = {}
        me = await client.get_me()
        original_first = me.first_name or "Test"
        original_last = me.last_name or "User"
        
        # Стратегия 1: Только изменение фамилии
        self.log(f"\n🔸 СТРАТЕГИЯ 1: Только изменение фамилии")
        
        async def change_lastname(c):
            return await c(UpdateProfileRequest(
                first_name=original_first,
                last_name="Test1"
            ))
        
        strategies_results['lastname_only'] = await self.test_with_delay(
            client, phone, "Change lastname only", change_lastname, delay=1
        )
        
        if strategies_results['lastname_only']['status'] == 'SUCCESS':
            await asyncio.sleep(0.5)
            me_after = await client.get_me()
            verified = (me_after.last_name == "Test1")
            strategies_results['lastname_only']['verified'] = verified
            self.log(f"{'✅' if verified else '⚠️'} Верификация: {verified}")
        
        # Стратегия 2: Только изменение имени
        if strategies_results['lastname_only']['status'] != 'SUCCESS':
            self.log(f"\n🔸 СТРАТЕГИЯ 2: Только изменение имени")
            
            async def change_firstname(c):
                return await c(UpdateProfileRequest(
                    first_name="Test2",
                    last_name=original_last
                ))
            
            strategies_results['firstname_only'] = await self.test_with_delay(
                client, phone, "Change firstname only", change_firstname, delay=2
            )
            
            if strategies_results['firstname_only']['status'] == 'SUCCESS':
                await asyncio.sleep(0.5)
                me_after = await client.get_me()
                verified = (me_after.first_name == "Test2")
                strategies_results['firstname_only']['verified'] = verified
                self.log(f"{'✅' if verified else '⚠️'} Верификация: {verified}")
        
        # Стратегия 3: Минимальное имя (1 буква)
        if strategies_results['lastname_only']['status'] != 'SUCCESS':
            self.log(f"\n🔸 СТРАТЕГИЯ 3: Минимальное имя (1 буква)")
            
            async def minimal_name(c):
                return await c(UpdateProfileRequest(
                    first_name="A",
                    last_name="B"
                ))
            
            strategies_results['minimal_name'] = await self.test_with_delay(
                client, phone, "Minimal name (1 letter)", minimal_name, delay=2
            )
            
            if strategies_results['minimal_name']['status'] == 'SUCCESS':
                await asyncio.sleep(0.5)
                me_after = await client.get_me()
                verified = (me_after.first_name == "A" and me_after.last_name == "B")
                strategies_results['minimal_name']['verified'] = verified
                self.log(f"{'✅' if verified else '⚠️'} Верификация: {verified}")
        
        return strategies_results
    
    async def test_avatar_strategies(self, client, phone):
        """Тестируем разные стратегии загрузки аватара"""
        self.log(f"\n{'#'*70}")
        self.log(f"🖼️  ТЕСТИРОВАНИЕ СТРАТЕГИЙ ДЛЯ AVATAR: {phone}")
        self.log(f"{'#'*70}")
        
        strategies_results = {}
        
        # Стратегия 1: Стандартный размер 512x512
        self.log(f"\n🔸 СТРАТЕГИЯ 1: Стандартный 512x512")
        
        img = Image.new('RGB', (512, 512), color=(100, 150, 200))
        temp1 = '/tmp/avatar_512.jpg'
        img.save(temp1, 'JPEG', quality=95)
        
        async def upload_512(c):
            uploaded = await c.upload_file(temp1)
            return await c(UploadProfilePhotoRequest(file=uploaded))
        
        strategies_results['size_512'] = await self.test_with_delay(
            client, phone, "Avatar 512x512", upload_512, delay=1
        )
        
        if strategies_results['size_512']['status'] == 'SUCCESS':
            await asyncio.sleep(1)
            photos = await client.get_profile_photos('me')
            strategies_results['size_512']['verified'] = len(photos) > 0
        
        os.remove(temp1)
        
        # Стратегия 2: Маленький размер 160x160 (минимум)
        if strategies_results['size_512']['status'] != 'SUCCESS':
            self.log(f"\n🔸 СТРАТЕГИЯ 2: Минимальный 160x160")
            
            img = Image.new('RGB', (160, 160), color=(200, 100, 150))
            temp2 = '/tmp/avatar_160.jpg'
            img.save(temp2, 'JPEG', quality=90)
            
            async def upload_160(c):
                uploaded = await c.upload_file(temp2)
                return await c(UploadProfilePhotoRequest(file=uploaded))
            
            strategies_results['size_160'] = await self.test_with_delay(
                client, phone, "Avatar 160x160", upload_160, delay=2
            )
            
            if strategies_results['size_160']['status'] == 'SUCCESS':
                await asyncio.sleep(1)
                photos = await client.get_profile_photos('me')
                strategies_results['size_160']['verified'] = len(photos) > 0
            
            os.remove(temp2)
        
        # Стратегия 3: Большой размер 1024x1024
        if strategies_results['size_512']['status'] != 'SUCCESS':
            self.log(f"\n🔸 СТРАТЕГИЯ 3: Большой 1024x1024")
            
            img = Image.new('RGB', (1024, 1024), color=(150, 200, 100))
            temp3 = '/tmp/avatar_1024.jpg'
            img.save(temp3, 'JPEG', quality=85)
            
            async def upload_1024(c):
                uploaded = await c.upload_file(temp3)
                return await c(UploadProfilePhotoRequest(file=uploaded))
            
            strategies_results['size_1024'] = await self.test_with_delay(
                client, phone, "Avatar 1024x1024", upload_1024, delay=2
            )
            
            if strategies_results['size_1024']['status'] == 'SUCCESS':
                await asyncio.sleep(1)
                photos = await client.get_profile_photos('me')
                strategies_results['size_1024']['verified'] = len(photos) > 0
            
            os.remove(temp3)
        
        return strategies_results
    
    async def analyze_account(self, phone, session_string):
        """Полный анализ одного аккаунта"""
        self.log(f"\n\n{'='*70}")
        self.log(f"🔍 ПОЛНЫЙ АНАЛИЗ АККАУНТА: {phone}")
        self.log(f"{'='*70}")
        
        client = None
        result = {
            'phone': phone,
            'health': None,
            'bio_strategies': None,
            'name_strategies': None,
            'avatar_strategies': None,
            'recommendations': []
        }
        
        try:
            client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
            await client.connect()
            
            if not await client.is_user_authorized():
                self.log(f"❌ Аккаунт не авторизован", "ERROR")
                result['recommendations'].append("⚠️ Требуется повторная авторизация")
                return result
            
            # 1. Health check
            result['health'] = await self.check_account_health(client, phone)
            
            # 2. Тестируем стратегии для BIO
            result['bio_strategies'] = await self.test_bio_strategies(client, phone)
            
            # 3. Тестируем стратегии для NAME
            result['name_strategies'] = await self.test_name_strategies(client, phone)
            
            # 4. Тестируем стратегии для AVATAR
            result['avatar_strategies'] = await self.test_avatar_strategies(client, phone)
            
            # 5. Генерируем рекомендации
            result['recommendations'] = self.generate_recommendations(result)
            
        except Exception as e:
            self.log(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}", "ERROR")
            import traceback
            self.log(traceback.format_exc(), "ERROR")
        
        finally:
            if client and client.is_connected():
                await client.disconnect()
        
        return result
    
    def generate_recommendations(self, result):
        """Генерация рекомендаций на основе результатов"""
        recommendations = []
        
        # Анализ BIO
        bio_strats = result.get('bio_strategies', {})
        bio_working = any(s.get('status') == 'SUCCESS' and s.get('verified') for s in bio_strats.values())
        
        if bio_working:
            # Находим рабочую стратегию
            working = [name for name, data in bio_strats.items() if data.get('status') == 'SUCCESS' and data.get('verified')]
            recommendations.append(f"✅ BIO: Используйте стратегию '{working[0]}'")
        else:
            # Проверяем тип ошибки
            frozen = any('FROZEN' in s.get('error', '') for s in bio_strats.values())
            if frozen:
                recommendations.append("❌ BIO: Telegram заблокировал UpdateProfileRequest(about) - обход невозможен")
            else:
                recommendations.append("⚠️ BIO: Попробуйте подождать 24-48 часов и повторить")
        
        # Анализ NAME
        name_strats = result.get('name_strategies', {})
        name_working = any(s.get('status') == 'SUCCESS' and s.get('verified') for s in name_strats.values())
        
        if name_working:
            working = [name for name, data in name_strats.items() if data.get('status') == 'SUCCESS' and data.get('verified')]
            recommendations.append(f"✅ NAME: Используйте стратегию '{working[0]}'")
        else:
            frozen = any('FROZEN' in s.get('error', '') for s in name_strats.values())
            if frozen:
                recommendations.append("❌ NAME: Telegram заблокировал UpdateProfileRequest(name) - обход невозможен")
            else:
                recommendations.append("⚠️ NAME: Попробуйте подождать 24-48 часов и повторить")
        
        # Анализ AVATAR
        avatar_strats = result.get('avatar_strategies', {})
        avatar_working = any(s.get('status') == 'SUCCESS' and s.get('verified') for s in avatar_strats.values())
        
        if avatar_working:
            working = [name for name, data in avatar_strats.items() if data.get('status') == 'SUCCESS' and data.get('verified')]
            recommendations.append(f"✅ AVATAR: Используйте стратегию '{working[0]}'")
        else:
            frozen = any('FROZEN' in s.get('error', '') for s in avatar_strats.values())
            if frozen:
                recommendations.append("❌ AVATAR: Telegram заблокировал UploadProfilePhotoRequest - обход невозможен")
            else:
                recommendations.append("⚠️ AVATAR: Попробуйте подождать 24-48 часов и повторить")
        
        # Общие рекомендации
        if result.get('health', {}).get('is_restricted'):
            recommendations.append("⚠️ АККАУНТ ИМЕЕТ ОГРАНИЧЕНИЯ: свяжитесь с поддержкой Telegram")
        
        return recommendations
    
    async def run_full_analysis(self):
        """Запуск полного анализа всех аккаунтов"""
        self.log("🚀 ЗАПУСК ПРОДВИНУТОЙ ДИАГНОСТИКИ")
        self.log(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        # Загружаем аккаунты
        with open('bot_data.json', 'r') as f:
            bot_data = json.load(f)
        
        accounts = bot_data.get('accounts', {})
        
        for phone, acc_data in accounts.items():
            if not isinstance(acc_data, dict):
                continue
            
            session = acc_data.get('session', '')
            if not session:
                self.log(f"⚠️ Пропускаем {phone} - нет сессии", "WARNING")
                continue
            
            result = await self.analyze_account(phone, session)
            self.results[phone] = result
        
        # Генерируем финальный отчёт
        self.generate_final_report()
    
    def generate_final_report(self):
        """Генерация финального отчёта"""
        self.log(f"\n\n{'='*70}")
        self.log("📊 ФИНАЛЬНЫЙ ОТЧЁТ")
        self.log(f"{'='*70}\n")
        
        for phone, data in self.results.items():
            if data is None:
                continue
            
            self.log(f"\n{'#'*70}")
            self.log(f"📱 {phone}")
            self.log(f"{'#'*70}")
            
            health = data.get('health') or {}
            if not health.get('authorized'):
                self.log("❌ НЕ АВТОРИЗОВАН\n")
                continue
            
            # Выводим результаты по стратегиям
            bio_strats = data.get('bio_strategies', {})
            name_strats = data.get('name_strategies', {})
            avatar_strats = data.get('avatar_strategies', {})
            
            self.log("\n📝 BIO стратегии:")
            for strat_name, strat_data in bio_strats.items():
                status = strat_data.get('status', 'UNKNOWN')
                verified = strat_data.get('verified', False)
                icon = "✅" if (status == 'SUCCESS' and verified) else "❌"
                self.log(f"   {icon} {strat_name}: {status}" + (f" (verified: {verified})" if status == 'SUCCESS' else ""))
            
            self.log("\n👤 NAME стратегии:")
            for strat_name, strat_data in name_strats.items():
                status = strat_data.get('status', 'UNKNOWN')
                verified = strat_data.get('verified', False)
                icon = "✅" if (status == 'SUCCESS' and verified) else "❌"
                self.log(f"   {icon} {strat_name}: {status}" + (f" (verified: {verified})" if status == 'SUCCESS' else ""))
            
            self.log("\n🖼️  AVATAR стратегии:")
            for strat_name, strat_data in avatar_strats.items():
                status = strat_data.get('status', 'UNKNOWN')
                verified = strat_data.get('verified', False)
                icon = "✅" if (status == 'SUCCESS' and verified) else "❌"
                self.log(f"   {icon} {strat_name}: {status}" + (f" (verified: {verified})" if status == 'SUCCESS' else ""))
            
            # Рекомендации
            self.log("\n💡 РЕКОМЕНДАЦИИ:")
            for rec in data.get('recommendations', []):
                self.log(f"   {rec}")
        
        # Сохраняем в JSON
        with open('advanced_diagnostics_report.json', 'w') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'results': self.results
            }, f, indent=2, ensure_ascii=False)
        
        self.log(f"\n💾 Полный отчёт сохранён: advanced_diagnostics_report.json")

async def main():
    diag = AdvancedProfileDiagnostics()
    await diag.run_full_analysis()

if __name__ == "__main__":
    asyncio.run(main())

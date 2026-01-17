#!/usr/bin/env python3
"""
Диагностический скрипт для проверки возможности изменения BIO для всех аккаунтов
Тестирует каждый аккаунт и создаёт детальный отчёт
"""

import asyncio
import json
import sys
from datetime import datetime
from telethon import TelegramClient, functions
from telethon.sessions import StringSession
from telethon.errors import *

# Загружаем конфигурацию из main.py
sys.path.insert(0, '/workspaces/personal-bot-1742')

try:
    from main import API_ID, API_HASH, ACCOUNT_STATUS_ACTIVE, ACCOUNT_STATUS_RESERVE, ACCOUNT_STATUS_BROKEN
except ImportError:
    print("❌ Не удалось импортировать настройки из main.py")
    print("Убедитесь, что файл main.py существует и содержит API_ID, API_HASH")
    sys.exit(1)

# Тестовые био для проверки
TEST_BIOS = [
    "Test bio 1",  # Короткое
    "Investor | Trader | Crypto enthusiast 🚀",  # Среднее с emoji
    "Bitcoin maximalist. HODL forever. Not financial advice.",  # Длинное (68 символов)
]

class BioTester:
    def __init__(self):
        self.results = []
        self.report_file = f"bio_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        
    def load_accounts(self):
        """Загружает аккаунты из bot_data.json"""
        try:
            with open('bot_data.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('accounts', {})
        except Exception as e:
            print(f"❌ Ошибка загрузки bot_data.json: {e}")
            return {}
    
    async def test_account_bio(self, phone, account_data):
        """Тестирует возможность изменения BIO для одного аккаунта"""
        result = {
            'phone': phone,
            'status': account_data.get('status', 'unknown'),
            'has_session': bool(account_data.get('session')),
            'tests': [],
            'can_change_bio': False,
            'errors': [],
            'recommendations': []
        }
        
        if not account_data.get('session'):
            result['errors'].append("Нет сессии")
            result['recommendations'].append("Требуется авторизация через /auth")
            return result
        
        client = None
        try:
            print(f"\\n🔍 Тестирую {phone}...")
            
            # Создаём клиента
            client = TelegramClient(
                StringSession(account_data['session']),
                API_ID,
                API_HASH,
                proxy=account_data.get('proxy')
            )
            
            await client.connect()
            
            # Проверка авторизации
            if not await client.is_user_authorized():
                result['errors'].append("Аккаунт не авторизован")
                result['recommendations'].append("Сессия устарела, нужна переавторизация")
                return result
            
            # Получаем текущий профиль
            me = await client.get_me()
            result['user_id'] = me.id
            result['username'] = me.username
            
            try:
                full = await client(functions.users.GetFullUserRequest(me))
                result['current_bio'] = full.full_user.about or ''
                print(f"  Текущее био: '{result['current_bio'][:50]}...'")
            except Exception as e:
                result['errors'].append(f"Не удалось получить текущее био: {str(e)}")
            
            # Тестируем изменение bio
            for i, test_bio in enumerate(TEST_BIOS, 1):
                test_result = {
                    'test_number': i,
                    'bio_text': test_bio,
                    'bio_length': len(test_bio),
                    'success': False,
                    'error': None,
                    'verified': False
                }
                
                print(f"  Тест {i}/{len(TEST_BIOS)}: '{test_bio[:30]}...'")
                
                try:
                    # Пытаемся изменить bio
                    update_result = await client(functions.account.UpdateProfileRequest(
                        about=test_bio
                    ))
                    
                    # Даём время на синхронизацию
                    await asyncio.sleep(0.5)
                    
                    # Проверяем, действительно ли изменилось
                    full_after = await client(functions.users.GetFullUserRequest(me))
                    actual_bio = full_after.full_user.about or ''
                    
                    if actual_bio == test_bio:
                        test_result['success'] = True
                        test_result['verified'] = True
                        result['can_change_bio'] = True
                        print(f"    ✅ Успешно изменено и проверено")
                    else:
                        test_result['success'] = True
                        test_result['verified'] = False
                        test_result['error'] = f"API ответил OK, но био не изменилось (ожидали '{test_bio}', получили '{actual_bio}')"
                        print(f"    ⚠️ API OK, но bio не изменилось")
                    
                except FloodWaitError as e:
                    test_result['error'] = f"FloodWait: {e.seconds} секунд"
                    result['errors'].append(test_result['error'])
                    result['recommendations'].append(f"Нужно подождать {e.seconds//60} минут перед следующей попыткой")
                    print(f"    ⏰ FloodWait: {e.seconds}s")
                    break  # Прерываем дальнейшие тесты для этого аккаунта
                    
                except AboutTooLongError as e:
                    test_result['error'] = f"Био слишком длинное (макс 70 символов)"
                    print(f"    ❌ Слишком длинное")
                    
                except UserDeactivatedError as e:
                    test_result['error'] = "Аккаунт деактивирован Telegram"
                    result['errors'].append("КРИТИЧНО: Аккаунт деактивирован")
                    result['recommendations'].append("Аккаунт нельзя использовать, пометить как BROKEN")
                    print(f"    🚫 Деактивирован")
                    break
                    
                except AuthKeyUnregisteredError as e:
                    test_result['error'] = "Сессия недействительна (AUTH_KEY_UNREGISTERED)"
                    result['errors'].append("Сессия недействительна")
                    result['recommendations'].append("Требуется переавторизация через /auth")
                    print(f"    🔑 Сессия недействительна")
                    break
                    
                except PhoneNumberBannedError as e:
                    test_result['error'] = "Номер забанен в Telegram"
                    result['errors'].append("КРИТИЧНО: Номер забанен")
                    result['recommendations'].append("Аккаунт навсегда забанен, пометить как BROKEN")
                    print(f"    ⛔ Номер забанен")
                    break
                    
                except Exception as e:
                    error_type = type(e).__name__
                    error_msg = str(e)
                    test_result['error'] = f"{error_type}: {error_msg}"
                    result['errors'].append(test_result['error'])
                    print(f"    ❌ {error_type}: {error_msg[:50]}")
                    
                    # Для неизвестных ошибок не прерываем
                    if "FROZEN" in error_msg or "420" in error_msg:
                        result['recommendations'].append("Аккаунт заморожен, нужно подождать")
                        break
                
                result['tests'].append(test_result)
                
                # Небольшая пауза между тестами
                await asyncio.sleep(2)
            
            # Возвращаем оригинальное bio, если было
            if result.get('current_bio') and result['can_change_bio']:
                try:
                    await client(functions.account.UpdateProfileRequest(
                        about=result['current_bio']
                    ))
                    print(f"  🔄 Восстановлено оригинальное био")
                except:
                    pass
            
        except Exception as e:
            result['errors'].append(f"Критическая ошибка: {type(e).__name__}: {str(e)}")
            print(f"  ❌ Критическая ошибка: {e}")
            
        finally:
            if client and client.is_connected():
                await client.disconnect()
        
        return result
    
    async def test_all_accounts(self):
        """Тестирует все аккаунты"""
        accounts = self.load_accounts()
        
        if not accounts:
            print("❌ Нет аккаунтов для тестирования")
            return
        
        print(f"\\n📊 Найдено аккаунтов: {len(accounts)}")
        print(f"🧪 Будет протестировано {len(TEST_BIOS)} вариантов био на каждом аккаунте\\n")
        print("="*80)
        
        for phone, account_data in accounts.items():
            result = await self.test_account_bio(phone, account_data)
            self.results.append(result)
            
            # Пауза между аккаунтами
            await asyncio.sleep(3)
        
        print("\\n" + "="*80)
        print("✅ Тестирование завершено\\n")
    
    def generate_report(self):
        """Генерирует MD-отчёт"""
        report = []
        report.append("# 🔍 Отчёт о проверке /setbio для всех аккаунтов\\n")
        report.append(f"**Дата:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\\n")
        report.append(f"**Протестировано аккаунтов:** {len(self.results)}\\n")
        
        # Статистика
        working = sum(1 for r in self.results if r['can_change_bio'])
        broken = sum(1 for r in self.results if 'КРИТИЧНО' in ' '.join(r['errors']))
        need_auth = sum(1 for r in self.results if not r['has_session'] or 'авторизован' in ' '.join(r['errors']).lower())
        
        report.append("\\n## 📊 Статистика\\n")
        report.append(f"- ✅ **Работающих:** {working}\\n")
        report.append(f"- ❌ **Сломанных:** {broken}\\n")
        report.append(f"- 🔑 **Требуют авторизации:** {need_auth}\\n")
        
        # Таблица результатов
        report.append("\\n## 📋 Детальные результаты\\n")
        report.append("| Аккаунт | Статус | /setbio | Ошибки | Рекомендации |\\n")
        report.append("|---------|--------|---------|--------|--------------|\\n")
        
        for r in self.results:
            phone_masked = r['phone'][-10:]
            status_emoji = {
                ACCOUNT_STATUS_ACTIVE: "✅",
                ACCOUNT_STATUS_RESERVE: "🔵",
                ACCOUNT_STATUS_BROKEN: "🔴"
            }.get(r['status'], "❓")
            
            bio_status = "✅ Работает" if r['can_change_bio'] else "❌ Не работает"
            errors = "<br>".join(r['errors'][:2]) if r['errors'] else "-"
            recommendations = "<br>".join(r['recommendations'][:2]) if r['recommendations'] else "-"
            
            report.append(f"| `...{phone_masked}` | {status_emoji} | {bio_status} | {errors} | {recommendations} |\\n")
        
        # Детали по каждому аккаунту
        report.append("\\n## 🔬 Подробные результаты тестов\\n")
        
        for r in self.results:
            report.append(f"\\n### Аккаунт: `{r['phone']}`\\n")
            report.append(f"- **Статус:** {r['status']}\\n")
            report.append(f"- **User ID:** {r.get('user_id', 'N/A')}\\n")
            report.append(f"- **Username:** @{r.get('username', 'N/A')}\\n")
            report.append(f"- **Текущее био:** `{r.get('current_bio', 'N/A')}`\\n")
            report.append(f"- **Может менять био:** {'✅ Да' if r['can_change_bio'] else '❌ Нет'}\\n")
            
            if r['tests']:
                report.append(f"\\n**Результаты тестов:**\\n")
                for test in r['tests']:
                    status_icon = "✅" if test['success'] and test['verified'] else ("⚠️" if test['success'] else "❌")
                    report.append(f"- {status_icon} Тест {test['test_number']}: `{test['bio_text'][:50]}` ({test['bio_length']} символов)\\n")
                    if test['error']:
                        report.append(f"  - ❌ Ошибка: {test['error']}\\n")
            
            if r['errors']:
                report.append(f"\\n**Ошибки:**\\n")
                for error in r['errors']:
                    report.append(f"- ⚠️ {error}\\n")
            
            if r['recommendations']:
                report.append(f"\\n**Рекомендации:**\\n")
                for rec in r['recommendations']:
                    report.append(f"- 💡 {rec}\\n")
        
        # Общие рекомендации
        report.append("\\n## 💡 Общие рекомендации\\n")
        report.append("\\n### Рабочие аккаунты\\n")
        working_accounts = [r for r in self.results if r['can_change_bio']]
        if working_accounts:
            for r in working_accounts:
                report.append(f"- ✅ `{r['phone']}` - можно использовать\\n")
        else:
            report.append("- ⚠️ Нет полностью рабочих аккаунтов!\\n")
        
        report.append("\\n### Требуют внимания\\n")
        problem_accounts = [r for r in self.results if not r['can_change_bio']]
        if problem_accounts:
            for r in problem_accounts:
                main_issue = r['errors'][0] if r['errors'] else "Неизвестная проблема"
                report.append(f"- ❌ `{r['phone']}` - {main_issue}\\n")
        
        report.append("\\n### Лимиты и ограничения\\n")
        report.append("- 📏 **Максимальная длина bio:** 70 символов\\n")
        report.append("- ⏰ **Рекомендуемый интервал между изменениями:** 1 час\\n")
        report.append("- 🛡️ **Флуд-контроль Telegram:** может потребовать ожидания 15-60 минут\\n")
        report.append("- 🚫 **Замороженные аккаунты:** не могут менять профиль временно или постоянно\\n")
        
        # Сохраняем отчёт
        report_text = ''.join(report)
        with open(self.report_file, 'w', encoding='utf-8') as f:
            f.write(report_text)
        
        print(f"📄 Отчёт сохранён: {self.report_file}\\n")
        
        # Краткая сводка в консоль
        print("\\n" + "="*80)
        print("📊 КРАТКАЯ СВОДКА")
        print("="*80)
        print(f"✅ Работающих: {working}/{len(self.results)}")
        print(f"❌ Сломанных: {broken}/{len(self.results)}")
        print(f"🔑 Требуют авторизации: {need_auth}/{len(self.results)}")
        print("="*80 + "\\n")
        
        return report_text

async def main():
    """Главная функция"""
    print("\\n" + "="*80)
    print("🔍 ДИАГНОСТИКА /setbio ДЛЯ ВСЕХ АККАУНТОВ")
    print("="*80)
    
    tester = BioTester()
    
    try:
        await tester.test_all_accounts()
        tester.generate_report()
        
        print("\\n✅ Диагностика завершена успешно!")
        print(f"📄 Смотрите подробный отчёт: {tester.report_file}\\n")
        
    except KeyboardInterrupt:
        print("\\n\\n⚠️ Прервано пользователем")
    except Exception as e:
        print(f"\\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
ПАТЧ ДЛЯ MAIN.PY: Автоматический выбор рабочих аккаунтов + Rate Limiting
"""

CODE_TO_ADD_AFTER_IMPORTS = '''
# ============= PROFILE OPERATIONS PROTECTION =============
from datetime import datetime, timedelta

# Список проверенных рабочих аккаунтов (обновляется по результатам тестов)
WORKING_ACCOUNTS = [
    '+13434919340'  # Проверено: BIO ✅, NAME ✅, AVATAR ✅
]

# Аккаунты с FROZEN блокировкой (не использовать для profile operations)
FROZEN_ACCOUNTS = [
    '+13435909132',  # FROZEN: все методы заблокированы
    '+15482373234'   # FROZEN: все методы заблокированы
]

# Лог операций с профилем для rate limiting
profile_operations_log = {}  # {f"{phone}:{operation}": datetime}

# Лимиты операций (защита от блокировки)
PROFILE_OPERATION_LIMITS = {
    'bio': timedelta(hours=1),      # BIO: макс 1 раз в час
    'name': timedelta(hours=1),     # NAME: макс 1 раз в час
    'avatar': timedelta(hours=24)   # AVATAR: макс 1 раз в день
}
'''

FUNCTION_TO_ADD = '''
async def can_do_profile_operation(self, phone, operation_type):
    """
    Проверяет можно ли выполнить операцию с профилем (rate limiting)
    
    Args:
        phone: Номер телефона аккаунта
        operation_type: Тип операции ('bio', 'name', 'avatar')
    
    Returns:
        (can_do: bool, wait_time: timedelta|None)
    """
    now = datetime.now()
    key = f"{phone}:{operation_type}"
    
    # Проверяем не заморожен ли аккаунт
    if phone in FROZEN_ACCOUNTS:
        logger.warning(f"PROFILE: Account {phone} is FROZEN, operation denied")
        return False, None
    
    # Проверяем лимиты
    if key in profile_operations_log:
        last_op = profile_operations_log[key]
        limit = PROFILE_OPERATION_LIMITS.get(operation_type, timedelta(hours=1))
        
        if now - last_op < limit:
            wait_time = (last_op + limit) - now
            logger.info(f"PROFILE: Rate limit for {phone}:{operation_type}, wait {wait_time}")
            return False, wait_time
    
    # Операция разрешена
    profile_operations_log[key] = now
    logger.info(f"PROFILE: Operation {operation_type} allowed for {phone}")
    return True, None

async def get_working_account_for_profile(self, current_accounts):
    """
    Выбирает первый доступный рабочий аккаунт из списка
    
    Args:
        current_accounts: dict аккаунтов из bot_data
    
    Returns:
        phone номер рабочего аккаунта или None
    """
    for phone in WORKING_ACCOUNTS:
        if phone in current_accounts:
            status = current_accounts[phone].get('status')
            if status == 'active':
                logger.info(f"PROFILE: Selected working account {phone}")
                return phone
    
    logger.warning("PROFILE: No working accounts available!")
    return None
'''

USAGE_EXAMPLE_SETBIO = '''
# В команде /setbio ПОСЛЕ получения phone добавить:

# Проверка rate limit
can_do, wait_time = await self.can_do_profile_operation(phone, 'bio')
if not can_do:
    if wait_time:
        wait_minutes = int(wait_time.total_seconds() / 60)
        await event.respond(
            f"⏰ **Слишком частые операции с профилем!**\\n\\n"
            f"Аккаунт `{phone}` использовался недавно.\\n"
            f"Подождите: {wait_minutes} минут\\n\\n"
            f"⚠️ Это защищает аккаунт от блокировки Telegram."
        )
    else:
        await event.respond(
            f"❌ **Аккаунт `{phone}` заблокирован**\\n\\n"
            f"Этот аккаунт имеет FROZEN блокировку от Telegram.\\n"
            f"Используйте другой аккаунт.\\n\\n"
            f"Рабочие аккаунты: {', '.join(WORKING_ACCOUNTS)}"
        )
    return
'''

MENU_FILTER_EXAMPLE = '''
# В меню выбора аккаунта добавить фильтрацию:

# Показываем только рабочие аккаунты
available_accounts = []
for phone, data in accounts.items():
    if phone in FROZEN_ACCOUNTS:
        continue  # Пропускаем замороженные
    if phone not in WORKING_ACCOUNTS:
        continue  # Показываем только проверенные
    available_accounts.append((phone, data))

if not available_accounts:
    await event.respond(
        "❌ **Нет доступных рабочих аккаунтов!**\\n\\n"
        "Все аккаунты либо заморожены, либо не проверены.\\n"
        "Обратитесь к администратору."
    )
    return
'''

print("="*70)
print("ПАТЧ ДЛЯ MAIN.PY")
print("="*70)
print()
print("1. Добавьте после импортов:")
print("-" * 70)
print(CODE_TO_ADD_AFTER_IMPORTS)
print()
print("2. Добавьте в класс TelegramChannelBot:")
print("-" * 70)
print(FUNCTION_TO_ADD)
print()
print("3. В каждой команде (/setbio, /setname, /setavatar):")
print("-" * 70)
print(USAGE_EXAMPLE_SETBIO)
print()
print("4. В меню выбора аккаунта:")
print("-" * 70)
print(MENU_FILTER_EXAMPLE)
print()
print("="*70)
print("ФАЙЛ: apply_profile_protection.py")
print("Сохраните этот вывод и примените изменения в main.py")
print("="*70)

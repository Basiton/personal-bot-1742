#!/bin/bash

# Скрипт проверки готовности системы управления профилями
# Автоматически проверяет все компоненты

echo "============================================================"
echo "  🔍 ПРОВЕРКА СИСТЕМЫ УПРАВЛЕНИЯ ПРОФИЛЯМИ"
echo "============================================================"
echo ""

ERRORS=0
WARNINGS=0

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Функция для проверки
check() {
    local name="$1"
    local command="$2"
    
    echo -n "Проверка: $name... "
    
    if eval "$command" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ OK${NC}"
        return 0
    else
        echo -e "${RED}❌ FAIL${NC}"
        ERRORS=$((ERRORS + 1))
        return 1
    fi
}

# Функция для предупреждений
warn() {
    local name="$1"
    local command="$2"
    
    echo -n "Проверка: $name... "
    
    if eval "$command" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ OK${NC}"
        return 0
    else
        echo -e "${YELLOW}⚠️  WARNING${NC}"
        WARNINGS=$((WARNINGS + 1))
        return 1
    fi
}

echo "1️⃣  ПРОВЕРКА ОСНОВНЫХ ФАЙЛОВ"
echo "============================================================"

check "main.py существует" "test -f main.py"
check "demo_profiles.py существует" "test -f demo_profiles.py"

echo ""
echo "2️⃣  ПРОВЕРКА ДОКУМЕНТАЦИИ"
echo "============================================================"

check "ACCOUNTS_PROFILES_GUIDE.md" "test -f ACCOUNTS_PROFILES_GUIDE.md"
check "QUICK_PROFILES.md" "test -f QUICK_PROFILES.md"
check "ACCOUNTS_PROFILES_README.md" "test -f ACCOUNTS_PROFILES_README.md"
check "ARCHITECTURE_DIAGRAM.md" "test -f ARCHITECTURE_DIAGRAM.md"
check "CHECKLIST.md" "test -f CHECKLIST.md"

echo ""
echo "3️⃣  ПРОВЕРКА СИНТАКСИСА PYTHON"
echo "============================================================"

check "main.py компилируется" "python3 -m py_compile main.py"
check "demo_profiles.py компилируется" "python3 -m py_compile demo_profiles.py"

echo ""
echo "4️⃣  ПРОВЕРКА ИМПОРТОВ"
echo "============================================================"

check "Telethon установлен" "python3 -c 'import telethon'"
check "Button доступен" "python3 -c 'from telethon import Button'"
check "asyncio доступен" "python3 -c 'import asyncio'"
check "pathlib доступен" "python3 -c 'from pathlib import Path'"

echo ""
echo "5️⃣  ПРОВЕРКА ФУНКЦИЙ В main.py"
echo "============================================================"

check "get_all_accounts_from_env определена" "grep -q 'def get_all_accounts_from_env' main.py"
check "create_accounts_keyboard определена" "grep -q 'def create_accounts_keyboard' main.py"
check "create_account_menu_keyboard определена" "grep -q 'def create_account_menu_keyboard' main.py"
check "get_account_info определена" "grep -q 'async def get_account_info' main.py"
check "apply_account_changes определена" "grep -q 'async def apply_account_changes' main.py"
check "clear_user_state определена" "grep -q 'async def clear_user_state' main.py"
check "save_temp_avatar определена" "grep -q 'async def save_temp_avatar' main.py"

echo ""
echo "6️⃣  ПРОВЕРКА ОБРАБОТЧИКОВ"
echo "============================================================"

check "/accounts команда определена" "grep -q \"pattern='/accounts'\" main.py"
check "CallbackQuery обработчик есть" "grep -q 'events.CallbackQuery' main.py"
check "Photo обработчик есть" "grep -q 'func=lambda e: e.photo' main.py"
check "Text обработчик есть" "grep -q \"func=lambda e: e.text and not e.text.startswith('/')\" main.py"

echo ""
echo "7️⃣  ПРОВЕРКА STATE MANAGEMENT"
echo "============================================================"

check "user_states инициализирован" "grep -q 'self.user_states' main.py"
check "account_cache инициализирован" "grep -q 'self.account_cache' main.py"

echo ""
echo "8️⃣  ПРОВЕРКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ (ОПЦИОНАЛЬНО)"
echo "============================================================"

warn "ACCOUNT_1_PHONE настроен" "test -n \"\$ACCOUNT_1_PHONE\""
warn "ACCOUNT_1_SESSION настроен" "test -n \"\$ACCOUNT_1_SESSION\""

echo ""
echo "9️⃣  ПРОВЕРКА ДЕМО-СКРИПТА"
echo "============================================================"

echo "Запуск demo_profiles.py..."
if python3 demo_profiles.py | grep -q "ДЕМОНСТРАЦИЯ ЗАВЕРШЕНА"; then
    echo -e "${GREEN}✅ Демо-скрипт работает${NC}"
else
    echo -e "${RED}❌ Демо-скрипт не работает${NC}"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "🔟  ПРОВЕРКА ДИРЕКТОРИЙ"
echo "============================================================"

check "/tmp доступна для записи" "test -w /tmp"

# Создаём директорию для аватарок если её нет
if [ ! -d "/tmp/bot_avatars" ]; then
    echo "Создание /tmp/bot_avatars..."
    mkdir -p /tmp/bot_avatars
    chmod 755 /tmp/bot_avatars
    echo -e "${GREEN}✅ Директория создана${NC}"
else
    check "/tmp/bot_avatars существует" "test -d /tmp/bot_avatars"
fi

check "/tmp/bot_avatars доступна для записи" "test -w /tmp/bot_avatars"

echo ""
echo "============================================================"
echo "  📊 РЕЗУЛЬТАТЫ ПРОВЕРКИ"
echo "============================================================"
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}🎉 ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ!${NC}"
    echo ""
    echo "Система полностью готова к использованию."
    echo ""
    echo "Запустите бота:"
    echo "  python3 main.py"
    echo ""
    echo "Используйте команду в боте:"
    echo "  /accounts"
    echo ""
    EXIT_CODE=0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠️  ЕСТЬ ПРЕДУПРЕЖДЕНИЯ${NC}"
    echo ""
    echo "Предупреждений: $WARNINGS"
    echo ""
    echo "Основные компоненты работают, но некоторые"
    echo "опциональные проверки не прошли."
    echo ""
    echo "Вы можете запустить бота:"
    echo "  python3 main.py"
    echo ""
    EXIT_CODE=0
else
    echo -e "${RED}❌ ОБНАРУЖЕНЫ ОШИБКИ${NC}"
    echo ""
    echo "Ошибок: $ERRORS"
    echo "Предупреждений: $WARNINGS"
    echo ""
    echo "Исправьте ошибки перед запуском бота."
    echo ""
    EXIT_CODE=1
fi

echo "============================================================"
echo ""

exit $EXIT_CODE

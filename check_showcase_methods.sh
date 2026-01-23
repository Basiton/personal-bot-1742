#!/bin/bash
# Скрипт проверки наличия методов showcase в main.py

echo "═══════════════════════════════════════════════════════════════"
echo "🔍 ПРОВЕРКА МЕТОДОВ SHOWCASE"
echo "═══════════════════════════════════════════════════════════════"

FILE="${1:-main.py}"

echo ""
echo "1️⃣ Проверка существования файла..."
if [ -f "$FILE" ]; then
    echo "   ✅ Файл найден: $FILE"
else
    echo "   ❌ Файл НЕ НАЙДЕН: $FILE"
    exit 1
fi

echo ""
echo "2️⃣ Проверка методов showcase..."

METHODS=(
    "_showcase_create"
    "_showcase_link"
    "_showcase_unlink"
    "_showcase_list"
    "_showcase_info"
    "_showcase_set"
)

ALL_FOUND=true

for method in "${METHODS[@]}"; do
    if grep -q "async def $method(self, event" "$FILE"; then
        LINE=$(grep -n "async def $method(self, event" "$FILE" | cut -d: -f1)
        echo "   ✅ $method (строка $LINE)"
    else
        echo "   ❌ $method НЕ НАЙДЕН"
        ALL_FOUND=false
    fi
done

echo ""
echo "3️⃣ Проверка обработчика showcase_command..."
if grep -q "async def showcase_command(event):" "$FILE"; then
    LINE=$(grep -n "async def showcase_command(event):" "$FILE" | cut -d: -f1)
    echo "   ✅ showcase_command найден (строка $LINE)"
else
    echo "   ❌ showcase_command НЕ НАЙДЕН"
    ALL_FOUND=false
fi

echo ""
echo "4️⃣ Проверка вызовов методов в обработчике..."
if grep -q "await self._showcase_set" "$FILE"; then
    echo "   ✅ Вызов self._showcase_set найден"
else
    echo "   ❌ Вызов self._showcase_set НЕ НАЙДЕН"
    ALL_FOUND=false
fi

echo ""
echo "5️⃣ Проверка регистрации обработчика..."
if grep -q "@self.bot_client.on(events.NewMessage(pattern=r'^/showcase" "$FILE"; then
    echo "   ✅ Регистрация @self.bot_client.on найдена"
else
    echo "   ❌ Регистрация обработчика НЕ НАЙДЕНА"
    ALL_FOUND=false
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"

if [ "$ALL_FOUND" = true ]; then
    echo "✅ ВСЕ МЕТОДЫ НАЙДЕНЫ - ФАЙЛ АКТУАЛЬНЫЙ"
    echo "═══════════════════════════════════════════════════════════════"
    echo ""
    echo "Можно запускать бота:"
    echo "  python3 $FILE"
    exit 0
else
    echo "❌ НЕКОТОРЫЕ МЕТОДЫ НЕ НАЙДЕНЫ - ТРЕБУЕТСЯ ОБНОВЛЕНИЕ"
    echo "═══════════════════════════════════════════════════════════════"
    exit 1
fi

#!/usr/bin/env python3
"""
Быстрая диагностика test mode - проверка фильтрации каналов
"""

import json

def check_test_mode():
    """Проверяет логику test mode"""
    
    # Загружаем данные бота
    try:
        with open('bot_data.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Ошибка загрузки bot_data.json: {e}")
        return
    
    channels = data.get('channels', [])
    test_mode = data.get('test_mode', False)
    test_channels = data.get('test_channels', [])
    
    print("="*80)
    print("🔍 ДИАГНОСТИКА TEST MODE")
    print("="*80)
    print(f"\n📊 Текущие настройки:")
    print(f"   Test mode: {'🟢 ВКЛЮЧЕН' if test_mode else '🔴 ВЫКЛЮЧЕН'}")
    print(f"   Test channels: {test_channels}")
    print(f"   Всего каналов в системе: {len(channels)}")
    
    if not test_mode:
        print("\n⚠️ Test mode выключен - будут использоваться ВСЕ каналы")
        return
    
    if not test_channels:
        print("\n⚠️ Test channels не указаны - будут использоваться ВСЕ каналы")
        return
    
    # Нормализуем test channels
    normalized_test_channels = []
    for tc in test_channels:
        if not tc.startswith('@'):
            normalized_test_channels.append('@' + tc)
        else:
            normalized_test_channels.append(tc)
    
    print(f"\n🔧 Нормализованные test channels: {normalized_test_channels}")
    
    # Проверяем фильтрацию
    print(f"\n🔍 Проверка каналов:")
    print("-"*80)
    
    matched_channels = []
    
    for ch in channels:
        ch_username = ch.get('username') if isinstance(ch, dict) else ch
        if not ch_username.startswith('@'):
            ch_username = '@' + ch_username
        
        # Case-insensitive сравнение
        if ch_username.lower() in [tc.lower() for tc in normalized_test_channels]:
            print(f"✅ MATCH: {ch_username}")
            matched_channels.append(ch_username)
        else:
            print(f"❌ SKIP:  {ch_username}")
    
    print("-"*80)
    print(f"\n📊 Результат фильтрации:")
    print(f"   Найдено совпадений: {len(matched_channels)}/{len(normalized_test_channels)}")
    print(f"   Будет использовано: {len(matched_channels)} каналов")
    
    if matched_channels:
        print(f"\n✅ Отфильтрованные каналы:")
        for ch in matched_channels:
            print(f"   • {ch}")
    
    # Проверяем отсутствующие
    missing = []
    for tc in normalized_test_channels:
        if tc.lower() not in [ch.lower() for ch in matched_channels]:
            missing.append(tc)
    
    if missing:
        print(f"\n⚠️ НЕ НАЙДЕНЫ в системе:")
        for m in missing:
            print(f"   ❌ {m}")
        print(f"\n💡 Добавьте их через:")
        for m in missing:
            print(f"   /addchannel {m}")
    
    # Итоговая рекомендация
    print("\n" + "="*80)
    if len(matched_channels) == 0:
        print("❌ ПРОБЛЕМА: Ни один test channel не найден!")
        print("   Мониторинг НЕ ЗАПУСТИТСЯ!")
        print("\n💡 Решение:")
        print("   1. Проверьте правильность имён каналов")
        print("   2. Добавьте каналы через /addchannel")
        print("   3. Или используйте /listchannels чтобы увидеть доступные")
    elif len(matched_channels) < len(normalized_test_channels):
        print("⚠️ ВНИМАНИЕ: Не все test channels найдены")
        print(f"   Будет использовано только {len(matched_channels)} из {len(normalized_test_channels)}")
    else:
        print("✅ ВСЁ ХОРОШО: Все test channels найдены и будут использованы")
    
    print("="*80)

if __name__ == "__main__":
    check_test_mode()

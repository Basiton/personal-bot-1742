#!/usr/bin/env python3
"""
Детальный тест profile operations
Проверяет ДЛЯ КАЖДОГО аккаунта ТРИ операции отдельно:
1. UpdateProfileRequest(about=...) - BIO
2. UpdateProfileRequest(first_name=..., last_name=...) - NAME  
3. UploadProfilePhotoRequest - AVATAR
"""

import asyncio
import json
import time
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest
from telethon.tl.functions.users import GetFullUserRequest
import os

API_ID = 36053254
API_HASH = "ecd80be4cc92e9cd87e73da31bdedadd"

async def test_bio(client, phone):
    """Тест изменения BIO"""
    try:
        # Получаем текущее био
        me = await client.get_me()
        full = await client(GetFullUserRequest(me))
        old_bio = full.full_user.about or ''
        
        # Создаем уникальное тестовое био
        test_bio = f"Test Bio {int(time.time() % 1000)}"
        
        print(f"   📝 Текущее био: '{old_bio[:30]}...'")
        print(f"   📝 Тестовое био: '{test_bio}'")
        print(f"   ⚡ Вызываем UpdateProfileRequest(about=...)")
        
        result = await client(UpdateProfileRequest(about=test_bio))
        
        # Проверяем изменения
        await asyncio.sleep(1)
        full_after = await client(GetFullUserRequest(me))
        new_bio = full_after.full_user.about or ''
        
        if new_bio == test_bio:
            print(f"   ✅ BIO изменено успешно!")
            return "OK", test_bio, new_bio
        else:
            print(f"   ⚠️  UpdateProfileRequest прошел, но био не изменилось")
            print(f"      Ожидали: '{test_bio}'")
            print(f"      Получили: '{new_bio}'")
            return "NOT_APPLIED", test_bio, new_bio
            
    except Exception as e:
        error = str(e)
        if "FROZEN" in error or "420" in error:
            print(f"   ❌ FROZEN: {error}")
            return "FROZEN", None, error
        else:
            print(f"   ❌ ERROR: {error}")
            return "ERROR", None, error

async def test_name(client, phone):
    """Тест изменения NAME"""
    try:
        # Получаем текущее имя
        me = await client.get_me()
        old_first = me.first_name or ''
        old_last = me.last_name or ''
        
        # Создаем уникальное тестовое имя (оставляем first как есть, меняем last)
        test_first = old_first if old_first else "Test"
        test_last = f"Bot{int(time.time() % 1000)}"
        
        print(f"   👤 Текущее имя: '{old_first}' '{old_last}'")
        print(f"   👤 Тестовое имя: '{test_first}' '{test_last}'")
        print(f"   ⚡ Вызываем UpdateProfileRequest(first_name=..., last_name=...)")
        
        result = await client(UpdateProfileRequest(
            first_name=test_first,
            last_name=test_last
        ))
        
        # Проверяем изменения
        await asyncio.sleep(1)
        me_after = await client.get_me()
        
        if me_after.first_name == test_first and me_after.last_name == test_last:
            print(f"   ✅ NAME изменено успешно!")
            return "OK", f"{test_first} {test_last}", f"{me_after.first_name} {me_after.last_name}"
        else:
            print(f"   ⚠️  UpdateProfileRequest прошел, но имя не изменилось")
            print(f"      Ожидали: '{test_first}' '{test_last}'")
            print(f"      Получили: '{me_after.first_name}' '{me_after.last_name}'")
            return "NOT_APPLIED", f"{test_first} {test_last}", f"{me_after.first_name} {me_after.last_name}"
            
    except Exception as e:
        error = str(e)
        if "FROZEN" in error or "420" in error:
            print(f"   ❌ FROZEN: {error}")
            return "FROZEN", None, error
        else:
            print(f"   ❌ ERROR: {error}")
            return "ERROR", None, error

async def test_avatar(client, phone):
    """Тест загрузки AVATAR"""
    # Создаем тестовое изображение 1x1 пиксель
    test_image_path = f"/tmp/test_avatar_{int(time.time())}.jpg"
    
    try:
        # Создаем изображение 512x512 (рекомендуемый Telegram)
        from PIL import Image
        img = Image.new('RGB', (512, 512), color='red')
        img.save(test_image_path, 'JPEG', quality=95)
        
        file_size = os.path.getsize(test_image_path)
        print(f"   📷 Создано тестовое изображение: {test_image_path}")
        print(f"   📦 Размер: 512x512, {file_size} bytes")
        print(f"   ⚡ Вызываем UploadProfilePhotoRequest")
        
        # Загружаем файл
        uploaded_file = await client.upload_file(test_image_path)
        
        # Устанавливаем как аватар
        result = await client(UploadProfilePhotoRequest(file=uploaded_file))
        
        print(f"   ✅ AVATAR загружен успешно!")
        return "OK", "uploaded", str(type(result).__name__)
            
    except Exception as e:
        error = str(e)
        if "FROZEN" in error or "420" in error:
            print(f"   ❌ FROZEN: {error}")
            return "FROZEN", None, error
        else:
            print(f"   ❌ ERROR: {error}")
            return "ERROR", None, error
    finally:
        # Удаляем тестовое изображение
        try:
            if os.path.exists(test_image_path):
                os.remove(test_image_path)
        except:
            pass

async def test_account_full(phone, data):
    """Полный тест всех операций для одного аккаунта"""
    print(f"\n{'='*70}")
    print(f"📱 ТЕСТИРУЕМ: {phone}")
    print(f"   Статус: {data.get('status', 'unknown')}")
    print(f"{'='*70}")
    
    client = TelegramClient(
        StringSession(data['session']),
        API_ID,
        API_HASH,
        proxy=data.get('proxy')
    )
    
    results = {
        'phone': phone,
        'status': data.get('status', 'unknown'),
        'bio': None,
        'name': None,
        'avatar': None
    }
    
    try:
        await client.connect()
        
        if not await client.is_user_authorized():
            print("   ❌ Аккаунт не авторизован")
            results['bio'] = ('NOT_AUTH', None, None)
            results['name'] = ('NOT_AUTH', None, None)
            results['avatar'] = ('NOT_AUTH', None, None)
            return results
        
        me = await client.get_me()
        print(f"   ✅ Авторизован: ID={me.id}, username={me.username}")
        
        # Тест 1: BIO
        print(f"\n   🔸 ТЕСТ 1/3: BIO (about)")
        results['bio'] = await test_bio(client, phone)
        await asyncio.sleep(2)
        
        # Тест 2: NAME
        print(f"\n   🔸 ТЕСТ 2/3: NAME (first_name, last_name)")
        results['name'] = await test_name(client, phone)
        await asyncio.sleep(2)
        
        # Тест 3: AVATAR
        print(f"\n   🔸 ТЕСТ 3/3: AVATAR (photo)")
        results['avatar'] = await test_avatar(client, phone)
        
    except Exception as e:
        print(f"   ❌ Ошибка подключения: {e}")
        results['bio'] = ('CONN_ERROR', None, str(e))
        results['name'] = ('CONN_ERROR', None, str(e))
        results['avatar'] = ('CONN_ERROR', None, str(e))
    
    finally:
        await client.disconnect()
    
    return results

async def main():
    print("🔍 ДЕТАЛЬНЫЙ ТЕСТ PROFILE OPERATIONS")
    print("="*70)
    print("Проверяем для каждого аккаунта:")
    print("  1. BIO (UpdateProfileRequest with about)")
    print("  2. NAME (UpdateProfileRequest with first_name, last_name)")
    print("  3. AVATAR (UploadProfilePhotoRequest)")
    print("="*70)
    
    # Загружаем аккаунты
    with open('bot_data.json', 'r') as f:
        bot_data = json.load(f)
        accounts_dict = bot_data.get('accounts', {})
    
    # Тестируем каждый аккаунт
    all_results = []
    
    for phone, data in accounts_dict.items():
        if not isinstance(data, dict) or not data.get('session'):
            continue
        
        result = await test_account_full(phone, data)
        all_results.append(result)
        
        # Задержка между аккаунтами
        await asyncio.sleep(3)
    
    # Итоговая таблица
    print("\n\n" + "="*70)
    print("📊 ИТОГОВАЯ ТАБЛИЦА РЕЗУЛЬТАТОВ")
    print("="*70)
    print(f"{'Телефон':<20} {'BIO':<12} {'NAME':<12} {'AVATAR':<12}")
    print("-"*70)
    
    for r in all_results:
        phone = r['phone']
        bio_status = r['bio'][0] if r['bio'] else 'N/A'
        name_status = r['name'][0] if r['name'] else 'N/A'
        avatar_status = r['avatar'][0] if r['avatar'] else 'N/A'
        
        # Иконки
        bio_icon = {'OK': '✅', 'FROZEN': '❌', 'NOT_APPLIED': '⚠️', 'ERROR': '❓', 'NOT_AUTH': '❓', 'CONN_ERROR': '❓'}.get(bio_status, '?')
        name_icon = {'OK': '✅', 'FROZEN': '❌', 'NOT_APPLIED': '⚠️', 'ERROR': '❓', 'NOT_AUTH': '❓', 'CONN_ERROR': '❓'}.get(name_status, '?')
        avatar_icon = {'OK': '✅', 'FROZEN': '❌', 'NOT_APPLIED': '⚠️', 'ERROR': '❓', 'NOT_AUTH': '❓', 'CONN_ERROR': '❓'}.get(avatar_status, '?')
        
        print(f"{phone:<20} {bio_icon} {bio_status:<10} {name_icon} {name_status:<10} {avatar_icon} {avatar_status:<10}")
    
    # Детальная статистика
    print("\n" + "="*70)
    print("📈 СТАТИСТИКА:")
    print("="*70)
    
    bio_ok = sum(1 for r in all_results if r['bio'] and r['bio'][0] == 'OK')
    name_ok = sum(1 for r in all_results if r['name'] and r['name'][0] == 'OK')
    avatar_ok = sum(1 for r in all_results if r['avatar'] and r['avatar'][0] == 'OK')
    
    bio_frozen = sum(1 for r in all_results if r['bio'] and r['bio'][0] == 'FROZEN')
    name_frozen = sum(1 for r in all_results if r['name'] and r['name'][0] == 'FROZEN')
    avatar_frozen = sum(1 for r in all_results if r['avatar'] and r['avatar'][0] == 'FROZEN')
    
    print(f"BIO:    ✅ Работает: {bio_ok}    ❌ FROZEN: {bio_frozen}")
    print(f"NAME:   ✅ Работает: {name_ok}    ❌ FROZEN: {name_frozen}")
    print(f"AVATAR: ✅ Работает: {avatar_ok}    ❌ FROZEN: {avatar_frozen}")
    
    # Рекомендации
    print("\n" + "="*70)
    print("💡 РЕКОМЕНДАЦИИ:")
    print("="*70)
    
    if bio_ok > 0:
        print(f"✅ /setbio работает на {bio_ok} аккаунтах - ИСПОЛЬЗУЙ ЭТО!")
    else:
        print("❌ /setbio не работает ни на одном аккаунте")
    
    if name_ok > 0:
        print(f"✅ /setname работает на {name_ok} аккаунтах")
        for r in all_results:
            if r['name'] and r['name'][0] == 'OK':
                print(f"   → {r['phone']}")
    else:
        print("❌ /setname заблокирован на всех аккаунтах")
    
    if avatar_ok > 0:
        print(f"✅ /setavatar работает на {avatar_ok} аккаунтах")
        for r in all_results:
            if r['avatar'] and r['avatar'][0] == 'OK':
                print(f"   → {r['phone']}")
    else:
        print("❌ /setavatar заблокирован на всех аккаунтах")
    
    # Сохраняем результаты в JSON
    with open('profile_test_results.json', 'w') as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    
    print(f"\n📄 Результаты сохранены в: profile_test_results.json")

if __name__ == "__main__":
    asyncio.run(main())

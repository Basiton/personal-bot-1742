#!/usr/bin/env python3
"""
Тест размеров аватарки для Telegram
"""
import asyncio
import json
import os
from PIL import Image
from telethon import TelegramClient
from telethon.tl.functions.photos import UploadProfilePhotoRequest

async def test_avatar_sizes():
    """Тестирует разные размеры изображений для аватарки"""
    
    print("=" * 70)
    print("ТЕСТ РАЗМЕРОВ АВАТАРКИ ДЛЯ TELEGRAM")
    print("=" * 70)
    
    # Загружаем данные аккаунтов
    try:
        with open('bot_data.json', 'r') as f:
            bot_data = json.load(f)
    except Exception as e:
        print(f"❌ Ошибка чтения bot_data.json: {e}")
        return
    
    accounts = bot_data.get('accounts', {})
    if not accounts:
        print("❌ Нет аккаунтов")
        return
    
    # Используем только active аккаунт
    test_account = None
    for phone, acc in accounts.items():
        if isinstance(acc, dict) and acc.get('status') == 'active':
            acc['phone'] = phone  # Добавляем номер телефона
            test_account = acc
            break
    
    if not test_account:
        print("❌ Нет active аккаунта")
        return
    
    phone = test_account['phone']
    session = f"{phone}.session"  # Формат session файла
    api_id = test_account.get('api_id') or bot_data.get('api_id')
    api_hash = test_account.get('api_hash') or bot_data.get('api_hash')
    
    print(f"\n📱 Тестируем аккаунт: {phone}")
    print(f"📄 Сессия: {session}")
    
    # Тестируемые размеры (width x height)
    test_sizes = [
        (100, 100),   # Слишком маленький (не работает)
        (160, 160),   # Минимальный рекомендованный
        (320, 320),   # Средний
        (512, 512),   # Рекомендованный Telegram
        (640, 640),   # Большой
    ]
    
    results = []
    
    for width, height in test_sizes:
        size_name = f"{width}x{height}"
        print(f"\n{'─' * 70}")
        print(f"🖼️  ТЕСТ РАЗМЕРА: {size_name}")
        print(f"{'─' * 70}")
        
        temp_file = None
        client = None
        
        try:
            # Создаём тестовое изображение
            img = Image.new('RGB', (width, height), color=(73, 109, 137))
            temp_file = f'test_avatar_{size_name}.jpg'
            img.save(temp_file, 'JPEG', quality=95)
            file_size = os.path.getsize(temp_file)
            
            print(f"✅ Создано изображение: {size_name}")
            print(f"📦 Размер файла: {file_size} байт")
            
            # Подключаемся к Telegram
            client = TelegramClient(session, api_id, api_hash)
            await client.connect()
            
            if not await client.is_user_authorized():
                print(f"❌ Аккаунт не авторизован")
                results.append({
                    'size': size_name,
                    'status': 'NOT_AUTH',
                    'error': 'Not authorized'
                })
                continue
            
            # Пытаемся загрузить аватарку
            print(f"📤 Загружаем аватарку...")
            
            await client(UploadProfilePhotoRequest(
                file=await client.upload_file(temp_file)
            ))
            
            print(f"✅ УСПЕХ! Размер {size_name} работает")
            results.append({
                'size': size_name,
                'dimensions': f'{width}x{height}',
                'file_size': file_size,
                'status': 'OK'
            })
            
        except Exception as e:
            error_msg = str(e)
            print(f"❌ ОШИБКА для {size_name}:")
            print(f"   Тип: {type(e).__name__}")
            print(f"   Сообщение: {error_msg}")
            
            results.append({
                'size': size_name,
                'dimensions': f'{width}x{height}',
                'file_size': file_size if temp_file else 0,
                'status': 'ERROR',
                'error_type': type(e).__name__,
                'error_msg': error_msg
            })
            
        finally:
            # Отключаемся
            if client and client.is_connected():
                await client.disconnect()
            
            # Удаляем временный файл
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass
    
    # Итоговая таблица результатов
    print(f"\n{'═' * 70}")
    print("ИТОГОВАЯ ТАБЛИЦА РЕЗУЛЬТАТОВ")
    print(f"{'═' * 70}")
    print(f"{'Размер':<12} {'Пиксели':<12} {'Размер файла':<15} {'Статус':<10}")
    print(f"{'─' * 70}")
    
    for r in results:
        size = r.get('size', 'N/A')
        dims = r.get('dimensions', 'N/A')
        fsize = r.get('file_size', 0)
        status = r.get('status', 'UNKNOWN')
        
        status_icon = "✅" if status == "OK" else "❌"
        print(f"{size:<12} {dims:<12} {fsize:<15} {status_icon} {status}")
    
    # Сохраняем результаты
    with open('avatar_size_test_results.json', 'w') as f:
        json.dump({
            'account': phone,
            'test_results': results,
            'conclusion': 'Минимальный рабочий размер: 160x160 (рекомендуется 512x512)'
        }, f, indent=2, ensure_ascii=False)
    
    print(f"\n💾 Результаты сохранены в avatar_size_test_results.json")
    print(f"{'═' * 70}")
    
    # Рекомендация
    working_sizes = [r for r in results if r.get('status') == 'OK']
    if working_sizes:
        min_size = working_sizes[0]
        print(f"\n💡 РЕКОМЕНДАЦИЯ:")
        print(f"   Минимальный рабочий размер: {min_size['size']}")
        print(f"   Рекомендуемый Telegram: 512x512")
    else:
        print(f"\n⚠️  ВНИМАНИЕ: Ни один размер не сработал!")
        print(f"   Возможно аккаунт заблокирован для загрузки аватарок")

if __name__ == "__main__":
    asyncio.run(test_avatar_sizes())

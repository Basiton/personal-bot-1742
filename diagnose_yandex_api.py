#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Диагностика YandexGPT API
"""

import os
import requests
import json
import sys
from dotenv import load_dotenv

load_dotenv()

# Проверяем переменные окружения (YC_API_KEY и YC_FOLDER_ID или старые названия)
YANDEX_API_KEY = os.getenv('YC_API_KEY') or os.getenv('YANDEX_API_KEY', '')
YANDEX_FOLDER_ID = os.getenv('YC_FOLDER_ID') or os.getenv('YANDEX_FOLDER_ID', '')

print("="*70)
print("🔍 ДИАГНОСТИКА YANDEX GPT API")
print("="*70)

# Проверяем, что ключи заданы
if not YANDEX_API_KEY or not YANDEX_FOLDER_ID:
    print("\n❌ ОШИБКА: Переменные окружения не заданы")
    print("\nНеобходимо установить:")
    print("  - YC_API_KEY (или YANDEX_API_KEY)")
    print("  - YC_FOLDER_ID (или YANDEX_FOLDER_ID)")
    print("\nПример для .env файла:")
    print("  YC_API_KEY=AQVNxxxxxxxxxx")
    print("  YC_FOLDER_ID=b1gxxxxxxxxxx")
    print("\nИли экспортировать в shell:")
    print("  export YC_API_KEY='...'")
    print("  export YC_FOLDER_ID='...'")
    sys.exit(1)

print(f"\n✅ API KEY: {YANDEX_API_KEY[:15]}...{YANDEX_API_KEY[-10:]}")
print(f"✅ FOLDER ID: {YANDEX_FOLDER_ID}")

# Тест 1: Базовый запрос без system role
print("\n" + "="*70)
print("ТЕСТ 1: Простой запрос (только user role)")
print("="*70)

url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

headers = {
    "Authorization": f"Api-Key {YANDEX_API_KEY}",
    "Content-Type": "application/json",
}

payload1 = {
    "modelUri": f"gpt://{YANDEX_FOLDER_ID}/yandexgpt/latest",
    "completionOptions": {
        "stream": False,
        "temperature": 0.7,
        "maxTokens": 100,
    },
    "messages": [
        {
            "role": "user",
            "text": "Напиши короткий комментарий к посту: 'Сегодня отличная погода!'"
        }
    ],
}

print(f"\n📤 Отправляем запрос...")
print(f"URL: {url}")
print(f"Headers: {json.dumps({k: v[:30] + '...' if len(v) > 30 else v for k, v in headers.items()}, indent=2, ensure_ascii=False)}")
print(f"Payload: {json.dumps(payload1, indent=2, ensure_ascii=False)}")

try:
    response = requests.post(url, headers=headers, json=payload1, timeout=30)
    print(f"\n📥 Ответ сервера:")
    print(f"Status Code: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        if "result" in data and "alternatives" in data["result"]:
            text = data["result"]["alternatives"][0]["message"]["text"]
            print(f"\n✅ УСПЕХ! Сгенерированный текст:")
            print(f"   {text}")
        else:
            print(f"\n⚠️ Неожиданный формат ответа")
            print(f"Response: {response.text[:300]}")
    else:
        print(f"\n❌ ОШИБКА {response.status_code}")
        print(f"Response: {response.text[:400]}")
        
        if response.status_code == 401:
            print("\n💡 Проверьте:")
            print("   • API ключ актуален в Yandex Cloud Console")
            print("   • Сервисный аккаунт имеет роль: ai.languageModels.user")
            print("   • Folder ID указан верно")
        
except Exception as e:
    print(f"\n❌ ИСКЛЮЧЕНИЕ: {e}")

# Тест 2: С system role (может не работать)
# Тест 2: С system role (опционально)
print("\n" + "="*70)
print("ТЕСТ 2: Запрос с system role (экспериментальный)")
print("="*70)

payload2 = {
    "modelUri": f"gpt://{YANDEX_FOLDER_ID}/yandexgpt/latest",
    "completionOptions": {
        "stream": False,
        "temperature": 0.7,
        "maxTokens": 100,
    },
    "messages": [
        {
            "role": "system",
            "text": "Ты пишешь комментарии к постам."
        },
        {
            "role": "user",
            "text": "Напиши комментарий к: 'Сегодня отличная погода!'"
        }
    ],
}

print(f"\n📤 Отправляем запрос с system role...")

try:
    response = requests.post(url, headers=headers, json=payload2, timeout=30)
    print(f"Status Code: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        if "result" in data and "alternatives" in data["result"]:
            text = data["result"]["alternatives"][0]["message"]["text"]
            print(f"✅ System role поддерживается!")
            print(f"   Ответ: {text}")
        else:
            print("⚠️ Неожиданный формат ответа")
    else:
        print(f"⚠️ System role может не поддерживаться (код {response.status_code})")
        
except Exception as e:
    print(f"❌ Ошибка: {e}")

print("\n" + "="*70)
print("✅ ДИАГНОСТИКА ЗАВЕРШЕНА")
print("="*70)

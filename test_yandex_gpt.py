#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test script for YandexGPT integration
Run this to verify your YandexGPT API is working correctly
"""

import os
import sys

# Try to load .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✅ Loaded .env file")
except ImportError:
    print("⚠️  python-dotenv not installed, using system environment variables")

# Check environment variables
YANDEX_API_KEY = os.getenv('YANDEX_API_KEY', '')
YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID', '')

print("\n" + "="*50)
print("🔍 Checking Configuration")
print("="*50)

if not YANDEX_API_KEY:
    print("❌ YANDEX_API_KEY not set!")
    print("   Please add it to your .env file")
    sys.exit(1)
else:
    print(f"✅ YANDEX_API_KEY: {YANDEX_API_KEY[:10]}...{YANDEX_API_KEY[-5:]}")

if not YANDEX_FOLDER_ID:
    print("❌ YANDEX_FOLDER_ID not set!")
    print("   Please add it to your .env file")
    sys.exit(1)
else:
    print(f"✅ YANDEX_FOLDER_ID: {YANDEX_FOLDER_ID}")

# Try to import the function
print("\n" + "="*50)
print("📦 Testing Import")
print("="*50)

try:
    from main import generate_neuro_comment
    print("✅ Successfully imported generate_neuro_comment")
except Exception as e:
    print(f"❌ Failed to import: {e}")
    sys.exit(1)

# Test the function with sample data
print("\n" + "="*50)
print("🧪 Testing Comment Generation")
print("="*50)

test_cases = [
    {
        "post_text": "Сегодня отличная погода! Солнце светит, птицы поют. Прекрасный день для прогулки.",
        "channel_theme": "общение"
    },
    {
        "post_text": "Новая версия Python 3.12 вышла с улучшенной производительностью и новыми возможностями!",
        "channel_theme": "программирование"
    },
    {
        "post_text": "Лучший рецепт пасты карбонара: яйца, бекон, пармезан и черный перец. Просто и вкусно!",
        "channel_theme": "кулинария"
    }
]

for i, test_case in enumerate(test_cases, 1):
    print(f"\n📝 Test {i}:")
    print(f"   Post: {test_case['post_text'][:50]}...")
    print(f"   Theme: {test_case['channel_theme']}")
    
    try:
        comment = generate_neuro_comment(
            post_text=test_case['post_text'],
            channel_theme=test_case['channel_theme']
        )
        print(f"   ✅ Generated: {comment}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
        continue

print("\n" + "="*50)
print("✨ Testing Complete!")
print("="*50)
print("\nIf you see generated comments above, YandexGPT is working!")
print("If you see fallback comments, check your API key and Yandex Cloud settings.")

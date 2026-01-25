#!/usr/bin/env python3
"""Тест паттерна команды /testmode"""
import re

# Старый паттерн
old_pattern = r'^/testmode(?:@comapc_bot)?(\\s.*)?$'
# Новый паттерн
new_pattern = r'^/testmode(?:@\w+)?(\s.*)?$'

test_cases = [
    "/testmode",
    "/testmode on",
    "/testmode off",
    "/testmode on @channel1",
    "/testmode@comapc_bot",
    "/testmode@comapc_bot on",
    "/testmode 1",
    "/testmode speed 10",
]

print("Старый паттерн:", old_pattern)
print("-" * 60)
for test in test_cases:
    match = re.match(old_pattern, test)
    print(f"{test:30} -> {'✅ MATCH' if match else '❌ NO MATCH'}")

print("\n" + "=" * 60 + "\n")

print("Новый паттерн:", new_pattern)
print("-" * 60)
for test in test_cases:
    match = re.match(new_pattern, test)
    print(f"{test:30} -> {'✅ MATCH' if match else '❌ NO MATCH'}")

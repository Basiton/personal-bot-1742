#!/usr/bin/env python3
"""Проверка работоспособности команды /testmode"""

import re

pattern = r'^/testmode(?:@\w+)?(\s.*)?$'

test_commands = [
    "/testmode",
    "/testmode on @channel1 @channel2",
    "/testmode off",
    "/testmode 1",
    "/testmode @mychannel",
    "/testmode speed 10",
    "/testmode@mybot",
    "/testmode@mybot on @channel1",
]

print("Тестирование regex паттерна для /testmode:")
print(f"Паттерн: {pattern}\n")

for cmd in test_commands:
    match = re.match(pattern, cmd)
    if match:
        print(f"✅ '{cmd}' - МАТЧ (groups: {match.groups()})")
    else:
        print(f"❌ '{cmd}' - НЕ МАТЧ")

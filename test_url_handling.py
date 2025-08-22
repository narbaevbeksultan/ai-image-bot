#!/usr/bin/env python3
"""
Тест обработки URL для понимания проблемы
"""
import os
from dotenv import load_dotenv

# Загружаем переменные
load_dotenv()

# Симулируем ответ от Seedream-3
class MockOutput:
    def __init__(self, url):
        self.url = url
    
    def __str__(self):
        return self.url

# Тестируем разные сценарии
test_url = "https://replicate.delivery/xezq/HOYWY53aqmL8NtN2phtB6dnw5AJxAoqCge31zTkHdf129eaqA/tmpvltbaxka.jpg"

print(f"🔍 Тестовый URL: {test_url}")
print(f"🔍 Длина URL: {len(test_url)}")

# Сценарий 1: как в боте
output = MockOutput(test_url)
print(f"\n🔍 Сценарий 1 - как в боте:")
print(f"   output.url: {output.url}")
print(f"   тип output.url: {type(output.url)}")
print(f"   длина output.url: {len(str(output.url))}")

# Сценарий 2: проверяем hasattr
print(f"\n🔍 Сценарий 2 - проверка атрибутов:")
print(f"   hasattr(output, 'url'): {hasattr(output, 'url')}")
print(f"   hasattr(output, '__getitem__'): {hasattr(output, '__getitem__')}")
print(f"   isinstance(output, (list, tuple)): {isinstance(output, (list, tuple))}")

# Сценарий 3: симулируем логику бота
print(f"\n🔍 Сценарий 3 - логика бота:")
if hasattr(output, 'url'):
    image_url = output.url
    print(f"   ✅ Используем output.url: {image_url}")
elif hasattr(output, '__getitem__'):
    image_url = output[0] if output else None
    print(f"   ✅ Используем output[0]: {image_url}")
elif isinstance(output, (list, tuple)) and len(output) > 0:
    image_url = output[0]
    print(f"   ✅ Используем output[0] из списка: {image_url}")
else:
    image_url = str(output) if output else None
    print(f"   ✅ Используем str(output): {image_url}")

print(f"   Итоговый image_url: {image_url}")
print(f"   Длина image_url: {len(str(image_url)) if image_url else 'None'}")

# Сценарий 4: проверяем возможные проблемы
print(f"\n🔍 Сценарий 4 - возможные проблемы:")
print(f"   str(output)[:1]: {str(output)[:1]}")  # Первый символ
print(f"   str(output)[:5]: {str(output)[:5]}")  # Первые 5 символов
print(f"   str(output)[-5:]: {str(output)[-5:]}")  # Последние 5 символов


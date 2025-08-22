#!/usr/bin/env python3
"""
Тестовый скрипт для отладки проблемы с Seedream-3
"""
import os
import replicate
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# Настраиваем API токен
replicate_token = os.getenv('REPLICATE_API_TOKEN')
if not replicate_token:
    print("❌ REPLICATE_API_TOKEN не установлен")
    exit(1)

print(f"✅ REPLICATE_API_TOKEN найден: {replicate_token[:20]}...")

print("🚀 Тестируем Seedream-3...")

try:
    # Генерируем тестовое изображение
    output = replicate.run(
        "bytedance/seedream-3",
        input={
            "prompt": "beautiful woman in red dress, photorealistic, high quality",
            "aspect_ratio": "1:1"
        }
    )
    
    print(f"🔍 Output тип: {type(output)}")
    print(f"🔍 Output значение: {output}")
    print(f"🔍 Output dir(): {dir(output) if hasattr(output, '__dict__') else 'Нет атрибутов'}")
    
    # Пробуем разные способы получения URL
    if hasattr(output, 'url'):
        print(f"🔍 output.url: {output.url}")
        print(f"🔍 Тип output.url: {type(output.url)}")
        
        # Попробуем вызвать как функцию
        try:
            url_result = output.url()
            print(f"🔍 output.url(): {url_result}")
        except Exception as e:
            print(f"🔍 output.url() ошибка: {e}")
    
    if hasattr(output, '__getitem__'):
        try:
            print(f"🔍 output[0]: {output[0]}")
        except Exception as e:
            print(f"🔍 output[0] ошибка: {e}")
    
    if isinstance(output, (list, tuple)):
        print(f"🔍 output как список/кортеж: {len(output)} элементов")
        for i, item in enumerate(output):
            print(f"🔍 output[{i}]: {item} (тип: {type(item)})")
    
    # Пробуем str()
    str_output = str(output)
    print(f"🔍 str(output): {str_output}")
    print(f"🔍 Длина str(output): {len(str_output)}")
    
except Exception as e:
    print(f"❌ Ошибка: {e}")
    import traceback
    traceback.print_exc()

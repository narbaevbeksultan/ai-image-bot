#!/usr/bin/env python3
"""
Тест для проверки блокировки при одновременной генерации изображений
"""

import asyncio
import time
import logging
from bot import generate_single_image_async, USER_STATE

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_concurrent_generation():
    """Тестирует параллельную генерацию изображений"""
    
    print("🔧 Тест параллельной генерации изображений")
    print("=" * 50)
    
    # Создаем состояние для теста
    state = {
        'image_gen_model': 'Ideogram',
        'image_gen_style': 'Фотореализм',
        'format': '1:1'
    }
    
    # Тестовые промпты
    prompts = [
        "A beautiful sunset over the ocean",
        "A cute cat sitting on a windowsill", 
        "A modern city skyline at night"
    ]
    
    print(f"📝 Тестовые промпты: {prompts}")
    
    # Создаем задачи для параллельной генерации
    tasks = []
    for idx, prompt in enumerate(prompts, 1):
        task = generate_single_image_async(idx, prompt, state)
        tasks.append(task)
    
    print(f"🚀 Создано {len(tasks)} задач для параллельной генерации")
    
    # Засекаем время
    start_time = time.time()
    
    try:
        # Запускаем все задачи параллельно
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Время выполнения
        execution_time = time.time() - start_time
        print(f"⏱️ Время выполнения: {execution_time:.2f} секунд")
        
        # Обрабатываем результаты
        success_count = 0
        error_count = 0
        
        for result in results:
            if isinstance(result, Exception):
                print(f"❌ Ошибка: {result}")
                error_count += 1
            else:
                idx, success, image_url, caption, error = result
                if success:
                    print(f"✅ Задача {idx}: Успешно - {caption}")
                    success_count += 1
                else:
                    print(f"❌ Задача {idx}: Ошибка - {error}")
                    error_count += 1
        
        print(f"\n📊 Результаты:")
        print(f"   ✅ Успешно: {success_count}")
        print(f"   ❌ Ошибок: {error_count}")
        print(f"   📈 Общий результат: {success_count}/{len(tasks)}")
        
        if success_count == len(tasks):
            print("🎉 Тест пройден! Параллельная генерация работает корректно.")
            print("💡 Теперь несколько пользователей могут генерировать изображения одновременно!")
        else:
            print("⚠️ Тест не пройден. Есть проблемы с параллельной генерацией.")
            
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        logger.exception("Ошибка в тесте")

if __name__ == "__main__":
    asyncio.run(test_concurrent_generation())

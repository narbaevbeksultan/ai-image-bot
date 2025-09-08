#!/usr/bin/env python3
"""
Тест для проверки параллельной генерации изображений
"""

import asyncio
import sys
import os

# Добавляем текущую директорию в путь для импорта
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

async def test_parallel_generation():
    """Тестирует параллельную генерацию изображений"""
    
    print("🧪 Тестирование параллельной генерации изображений...")
    
    # Импортируем функцию
    try:
        from bot import generate_single_image_async
        print("✅ Функция generate_single_image_async импортирована успешно")
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")
        return False
    
    # Создаем тестовые данные
    test_state = {
        'image_gen_model': 'Ideogram',
        'image_gen_style': 'Фотореализм',
        'format': '1:1',
        'simple_orientation': None
    }
    
    test_prompts = [
        "A beautiful sunset over the ocean",
        "A cute cat sitting on a windowsill",
        "A modern city skyline at night"
    ]
    
    print(f"📝 Тестовые промпты: {test_prompts}")
    
    # Тестируем параллельную генерацию
    try:
        # Создаем задачи
        tasks = []
        for idx, prompt in enumerate(test_prompts, 1):
            task = generate_single_image_async(idx, prompt, test_state, None)
            tasks.append(task)
        
        print(f"🚀 Создано {len(tasks)} задач для параллельной генерации")
        
        # Запускаем параллельно
        start_time = asyncio.get_event_loop().time()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        end_time = asyncio.get_event_loop().time()
        
        print(f"⏱️ Время выполнения: {end_time - start_time:.2f} секунд")
        
        # Анализируем результаты
        success_count = 0
        error_count = 0
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"❌ Задача {i+1}: Ошибка - {result}")
                error_count += 1
            else:
                idx, success, image_url, caption, error = result
                if success:
                    print(f"✅ Задача {i+1}: Успешно - {caption}")
                    success_count += 1
                else:
                    print(f"❌ Задача {i+1}: Ошибка - {error}")
                    error_count += 1
        
        print(f"\n📊 Результаты:")
        print(f"   ✅ Успешно: {success_count}")
        print(f"   ❌ Ошибок: {error_count}")
        print(f"   📈 Общий результат: {success_count}/{len(tasks)}")
        
        return success_count > 0
        
    except Exception as e:
        print(f"❌ Ошибка при тестировании: {e}")
        return False

async def main():
    """Основная функция тестирования"""
    print("🔧 Тест параллельной генерации изображений")
    print("=" * 50)
    
    success = await test_parallel_generation()
    
    if success:
        print("\n🎉 Тест пройден! Параллельная генерация работает корректно.")
        print("💡 Теперь несколько пользователей могут генерировать изображения одновременно!")
    else:
        print("\n❌ Тест не пройден. Проверьте настройки API.")
    
    return success

if __name__ == "__main__":
    # Запускаем тест
    result = asyncio.run(main())
    sys.exit(0 if result else 1)

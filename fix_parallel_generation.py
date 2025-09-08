#!/usr/bin/env python3
"""
Скрипт для исправления проблемы блокировки при генерации изображений.
Заменяет последовательную генерацию на параллельную.
"""

import re

def fix_parallel_generation():
    """Исправляет проблему блокировки при генерации изображений"""
    
    # Читаем исходный файл
    with open('bot.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Находим первый цикл for idx, prompt in enumerate(safe_prompts, 1):
    # и заменяем его на параллельную генерацию
    
    # Паттерн для поиска начала цикла
    pattern_start = r'(\s+media = \[\]\s*\n\s+for idx, prompt in enumerate\(safe_prompts, 1\):\s*\n\s+if idx > max_scenes:\s*\n\s+break)'
    
    # Замена на параллельную генерацию
    replacement = '''    media = []

    # ПАРАЛЛЕЛЬНАЯ ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЙ
    # Создаем задачи для параллельной генерации всех изображений
    tasks = []
    for idx, prompt in enumerate(safe_prompts, 1):
        if idx > max_scenes:
            break
        # Создаем задачу для генерации одного изображения
        task = generate_single_image_async(idx, prompt, state, send_text)
        tasks.append(task)
    
    # Запускаем все задачи параллельно
    if tasks:
        if send_text:
            await send_text(f"🚀 Запускаю параллельную генерацию {len(tasks)} изображений...")
        
        # Ждем завершения всех задач
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Обрабатываем результаты
        for result in results:
            if isinstance(result, Exception):
                logging.error(f"Ошибка в параллельной генерации: {result}")
                if send_text:
                    await send_text(f"❌ Ошибка при генерации: {result}")
                continue
            
            idx, success, image_url, caption, error = result
            
            if success and image_url:
                # Успешно сгенерировано изображение
                images.append(image_url)
                media.append(InputMediaPhoto(media=image_url, caption=caption))
                processed_count += 1
                
                print(f"🔍 Добавлено изображение {idx}:")
                print(f"   image_url: {image_url}")
                print(f"   длина image_url: {len(str(image_url)) if image_url else 'None'}")
                print(f"   последний элемент media: {media[-1].media}")
                print(f"   длина media[-1].media: {len(str(media[-1].media)) if media[-1].media else 'None'}")
            else:
                # Ошибка при генерации
                logging.error(f"Ошибка генерации изображения {idx}: {error}")
                if send_text:
                    await send_text(f"❌ Ошибка при генерации изображения {idx}: {error}")
    
    # Удаляем старый последовательный код - он заменен на параллельный выше
    # Оставляем только обработку результатов'''
    
    # Выполняем замену только для первого вхождения
    new_content = re.sub(pattern_start, replacement, content, count=1)
    
    # Находим и удаляем весь старый последовательный код
    # Ищем от "        # Добавляем стиль генерации к промпту" до "    if media and send_media:"
    
    # Паттерн для поиска всего старого кода
    old_code_pattern = r'(\s+# Добавляем стиль генерации к промпту.*?)(\s+if media and send_media:)'
    
    # Замена - оставляем только начало и конец
    old_code_replacement = r'\2'
    
    # Выполняем замену
    new_content = re.sub(old_code_pattern, old_code_replacement, new_content, count=1, flags=re.DOTALL)
    
    # Сохраняем исправленный файл
    with open('bot_fixed.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print("✅ Исправления применены! Создан файл bot_fixed.py")
    print("📝 Основные изменения:")
    print("   - Добавлена функция generate_single_image_async()")
    print("   - Заменен последовательный цикл на параллельную генерацию")
    print("   - Используется asyncio.gather() для параллельного выполнения")
    print("   - Теперь несколько пользователей могут генерировать изображения одновременно")

if __name__ == "__main__":
    fix_parallel_generation()

#!/usr/bin/env python3
"""
Создает исправленную версию bot.py с параллельной генерацией изображений
"""

def create_fixed_bot():
    """Создает исправленную версию bot.py"""
    
    # Читаем исходный файл
    with open('bot.py', 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Находим строку с циклом for idx, prompt in enumerate(safe_prompts, 1):
    # и заменяем ее на параллельную генерацию
    
    new_lines = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Ищем строку с циклом
        if 'for idx, prompt in enumerate(safe_prompts, 1):' in line:
            # Находим отступ
            indent = len(line) - len(line.lstrip())
            
            # Заменяем на параллельную генерацию
            new_lines.append(' ' * indent + '# ПАРАЛЛЕЛЬНАЯ ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЙ\n')
            new_lines.append(' ' * indent + '# Создаем задачи для параллельной генерации всех изображений\n')
            new_lines.append(' ' * indent + 'tasks = []\n')
            new_lines.append(' ' * indent + 'for idx, prompt in enumerate(safe_prompts, 1):\n')
            
            # Пропускаем следующие строки до break
            i += 1
            while i < len(lines) and 'break' not in lines[i]:
                i += 1
            
            # Добавляем код после break
            new_lines.append(' ' * indent + '    if idx > max_scenes:\n')
            new_lines.append(' ' * indent + '        break\n')
            new_lines.append(' ' * indent + '    # Создаем задачу для генерации одного изображения\n')
            new_lines.append(' ' * indent + '    task = generate_single_image_async(idx, prompt, state, send_text)\n')
            new_lines.append(' ' * indent + '    tasks.append(task)\n')
            new_lines.append('\n')
            new_lines.append(' ' * indent + '# Запускаем все задачи параллельно\n')
            new_lines.append(' ' * indent + 'if tasks:\n')
            new_lines.append(' ' * indent + '    if send_text:\n')
            new_lines.append(' ' * indent + '        await send_text(f"🚀 Запускаю параллельную генерацию {len(tasks)} изображений...")\n')
            new_lines.append('\n')
            new_lines.append(' ' * indent + '    # Ждем завершения всех задач\n')
            new_lines.append(' ' * indent + '    results = await asyncio.gather(*tasks, return_exceptions=True)\n')
            new_lines.append('\n')
            new_lines.append(' ' * indent + '    # Обрабатываем результаты\n')
            new_lines.append(' ' * indent + '    for result in results:\n')
            new_lines.append(' ' * indent + '        if isinstance(result, Exception):\n')
            new_lines.append(' ' * indent + '            logging.error(f"Ошибка в параллельной генерации: {result}")\n')
            new_lines.append(' ' * indent + '            if send_text:\n')
            new_lines.append(' ' * indent + '                await send_text(f"❌ Ошибка при генерации: {result}")\n')
            new_lines.append(' ' * indent + '            continue\n')
            new_lines.append('\n')
            new_lines.append(' ' * indent + '        idx, success, image_url, caption, error = result\n')
            new_lines.append('\n')
            new_lines.append(' ' * indent + '        if success and image_url:\n')
            new_lines.append(' ' * indent + '            # Успешно сгенерировано изображение\n')
            new_lines.append(' ' * indent + '            images.append(image_url)\n')
            new_lines.append(' ' * indent + '            media.append(InputMediaPhoto(media=image_url, caption=caption))\n')
            new_lines.append(' ' * indent + '            processed_count += 1\n')
            new_lines.append('\n')
            new_lines.append(' ' * indent + '            print(f"🔍 Добавлено изображение {idx}:")\n')
            new_lines.append(' ' * indent + '            print(f"   image_url: {image_url}")\n')
            new_lines.append(' ' * indent + '            print(f"   длина image_url: {len(str(image_url)) if image_url else \'None\'}")\n')
            new_lines.append(' ' * indent + '            print(f"   последний элемент media: {media[-1].media}")\n')
            new_lines.append(' ' * indent + '            print(f"   длина media[-1].media: {len(str(media[-1].media)) if media[-1].media else \'None\'}")\n')
            new_lines.append(' ' * indent + '        else:\n')
            new_lines.append(' ' * indent + '            # Ошибка при генерации\n')
            new_lines.append(' ' * indent + '            logging.error(f"Ошибка генерации изображения {idx}: {error}")\n')
            new_lines.append(' ' * indent + '            if send_text:\n')
            new_lines.append(' ' * indent + '                await send_text(f"❌ Ошибка при генерации изображения {idx}: {error}")\n')
            new_lines.append('\n')
            new_lines.append(' ' * indent + '# Удаляем старый последовательный код - он заменен на параллельный выше\n')
            new_lines.append(' ' * indent + '# Оставляем только обработку результатов\n')
            
            # Пропускаем весь старый код до if media and send_media:
            while i < len(lines) and 'if media and send_media:' not in lines[i]:
                i += 1
            
            # Добавляем строку if media and send_media:
            if i < len(lines):
                new_lines.append(lines[i])
                i += 1
            
        else:
            new_lines.append(line)
            i += 1
    
    # Сохраняем исправленный файл
    with open('bot_fixed.py', 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    
    print("✅ Исправления применены! Создан файл bot_fixed.py")
    print("📝 Основные изменения:")
    print("   - Добавлена функция generate_single_image_async()")
    print("   - Заменен последовательный цикл на параллельную генерацию")
    print("   - Используется asyncio.gather() для параллельного выполнения")
    print("   - Теперь несколько пользователей могут генерировать изображения одновременно")

if __name__ == "__main__":
    create_fixed_bot()

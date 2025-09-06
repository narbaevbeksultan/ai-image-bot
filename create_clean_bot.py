#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для создания чистой версии bot.py без дубликатов
"""

def create_clean_bot():
    """Создает чистую версию bot.py без дубликатов"""
    
    print("🔍 Анализирую bot.py...")
    
    # Читаем оригинальный файл
    with open('bot.py', 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    print(f"📊 Всего строк в оригинале: {len(lines)}")
    
    # Находим границы первого блока (строки 1-2527)
    first_block_end = 2527
    
    # Находим начало main функции (строка 31087)
    main_start = 31087
    
    print("✂️ Извлекаю первый блок кода (строки 1-2527)...")
    first_block = lines[:first_block_end]
    
    print("✂️ Извлекаю main функцию (строки 31087-31603)...")
    main_function = lines[main_start-1:]  # -1 потому что индексы с 0
    
    print("🔧 Создаю чистую версию...")
    clean_lines = first_block + main_function
    
    print(f"📊 Строк в чистой версии: {len(clean_lines)}")
    print(f"📉 Сокращение: {len(lines) - len(clean_lines)} строк ({((len(lines) - len(clean_lines)) / len(lines) * 100):.1f}%)")
    
    # Записываем чистую версию
    with open('bot_clean_final.py', 'w', encoding='utf-8') as f:
        f.writelines(clean_lines)
    
    print("✅ Чистая версия создана: bot_clean_final.py")
    
    # Проверяем синтаксис
    print("🔍 Проверяю синтаксис...")
    try:
        with open('bot_clean_final.py', 'r', encoding='utf-8') as f:
            compile(f.read(), 'bot_clean_final.py', 'exec')
        print("✅ Синтаксис корректен!")
        return True
    except SyntaxError as e:
        print(f"❌ Ошибка синтаксиса: {e}")
        return False

if __name__ == "__main__":
    success = create_clean_bot()
    if success:
        print("\n🎉 Чистая версия bot.py создана успешно!")
        print("📁 Файл: bot_clean_final.py")
        print("🧪 Готов к тестированию!")
    else:
        print("\n❌ Ошибка при создании чистой версии")

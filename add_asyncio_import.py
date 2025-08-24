#!/usr/bin/env python3
"""
Добавляет импорт asyncio в начало файла bot.py
"""

def add_asyncio_import():
    with open('bot.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Проверяем, есть ли глобальный импорт asyncio
    if not content.startswith('import logging\nimport asyncio'):
        # Добавляем asyncio после import logging
        content = content.replace(
            'import logging\n',
            'import logging\nimport asyncio\n'
        )
        
        with open('bot.py', 'w', encoding='utf-8') as f:
            f.write(content)
        
        print("✅ Глобальный импорт asyncio добавлен!")
    else:
        print("✅ Глобальный импорт asyncio уже есть!")

if __name__ == "__main__":
    add_asyncio_import()

#!/usr/bin/env python3
"""
Удаляет все локальные импорты asyncio, оставляя только глобальный
"""

def remove_local_asyncio():
    with open('bot.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Удаляем все локальные импорты asyncio, кроме первого (глобального)
    lines = content.split('\n')
    new_lines = []
    asyncio_import_count = 0
    
    for line in lines:
        if line.strip() == 'import asyncio':
            asyncio_import_count += 1
            # Оставляем только первый импорт (глобальный)
            if asyncio_import_count == 1:
                new_lines.append(line)
        else:
            new_lines.append(line)
    
    content = '\n'.join(new_lines)
    
    with open('bot.py', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"✅ Удалено {asyncio_import_count - 1} локальных импортов asyncio!")

if __name__ == "__main__":
    remove_local_asyncio()

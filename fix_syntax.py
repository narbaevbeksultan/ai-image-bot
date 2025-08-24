#!/usr/bin/env python3
"""
Исправляет синтаксическую ошибку в bot.py
"""

def fix_syntax_error():
    with open('bot.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Исправляем слипшийся комментарий и код
    content = content.replace(
        '# Генерируем простое изображение через Ideogramoutput = replicate.run(',
        '# Генерируем простое изображение через Ideogram\n        output = replicate.run('
    )
    
    with open('bot.py', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✅ Синтаксическая ошибка исправлена!")

if __name__ == "__main__":
    fix_syntax_error()

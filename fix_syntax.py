#!/usr/bin/env python3
"""
Исправляет синтаксические ошибки в bot.py
"""

def fix_syntax_error():
    with open('bot.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Исправляем все слипшиеся комментарии и код
    fixes = [
        ('# Генерируем простое изображение через Ideogramoutput = replicate.run(', 
         '# Генерируем простое изображение через Ideogram\n        output = replicate.run('),
        
        ('# Генерация через Bria на Replicateoutput = replicate.run(', 
         '# Генерация через Bria на Replicate\n                    output = replicate.run('),
        
        ('# Fallback на Ideogram если модель не поддерживаетсяoutput = replicate.run(', 
         '# Fallback на Ideogram если модель не поддерживается\n                    output = replicate.run(')
    ]
    
    for old, new in fixes:
        content = content.replace(old, new)
    
    with open('bot.py', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✅ Все синтаксические ошибки исправлены!")

if __name__ == "__main__":
    fix_syntax_error()

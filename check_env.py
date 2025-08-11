#!/usr/bin/env python3
"""
Простая проверка переменных окружения
"""

import os

def main():
    print("🔍 Проверка переменных окружения...")
    print("=" * 50)
    
    # Проверяем основные переменные
    required_vars = [
        'TELEGRAM_BOT_TOKEN',
        'REPLICATE_API_TOKEN', 
        'OPENAI_API_KEY'
    ]
    
    missing_vars = []
    for var in required_vars:
        value = os.environ.get(var)
        if value:
            # Скрываем значение, показываем только первые 10 символов
            masked_value = value[:10] + "..." if len(value) > 10 else value
            print(f"✅ {var}: {masked_value}")
        else:
            print(f"❌ {var}: НЕ НАЙДЕН")
            missing_vars.append(var)
    
    print("\n" + "=" * 50)
    
    if missing_vars:
        print(f"⚠️ Отсутствуют переменные: {', '.join(missing_vars)}")
        print("\n💡 Решение:")
        print("1. Создайте файл .env в корне проекта")
        print("2. Или установите переменные в Railway Dashboard")
        print("3. Или установите переменные окружения в системе")
        
        print("\n📝 Пример содержимого .env файла:")
        print("TELEGRAM_BOT_TOKEN=your_token_here")
        print("REPLICATE_API_TOKEN=your_token_here")
        print("OPENAI_API_KEY=your_key_here")
        
    else:
        print("✅ Все переменные окружения найдены!")
        print("\n💡 Теперь можно запустить основной бот:")
        print("python bot.py")

if __name__ == "__main__":
    main()




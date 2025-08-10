#!/usr/bin/env python3
"""
Тестовый скрипт для проверки API ключей и их работоспособности
"""

import os
import replicate
import openai
from dotenv import load_dotenv

def test_environment_variables():
    """Проверяет наличие всех необходимых переменных окружения"""
    print("🔍 Проверка переменных окружения...")
    
    # Загружаем .env файл если он существует
    load_dotenv()
    
    required_vars = [
        'TELEGRAM_BOT_TOKEN',
        'REPLICATE_API_TOKEN', 
        'OPENAI_API_KEY'
    ]
    
    missing_vars = []
    for var in required_vars:
        value = os.getenv(var)
        if value:
            # Скрываем значение, показываем только первые 10 символов
            masked_value = value[:10] + "..." if len(value) > 10 else value
            print(f"✅ {var}: {masked_value}")
        else:
            print(f"❌ {var}: НЕ НАЙДЕН")
            missing_vars.append(var)
    
    if missing_vars:
        print(f"\n⚠️ Отсутствуют переменные: {', '.join(missing_vars)}")
        return False
    else:
        print("\n✅ Все переменные окружения найдены")
        return True

def test_replicate_api():
    """Тестирует Replicate API"""
    print("\n🧪 Тестирование Replicate API...")
    
    try:
        api_token = os.getenv('REPLICATE_API_TOKEN')
        if not api_token:
            print("❌ REPLICATE_API_TOKEN не найден")
            return False
        
        # Создаем клиент
        client = replicate.Client(api_token=api_token)
        print("✅ Клиент Replicate создан")
        
        # Тестируем простую модель
        print("🔄 Тестирую простую модель...")
        output = replicate.run(
            "replicate/hello-world",
            input={"text": "test"}
        )
        print(f"✅ Тестовая модель работает: {output}")
        
        # Тестируем Ideogram
        print("🔄 Тестирую Ideogram...")
        try:
            ideogram_output = replicate.run(
                "ideogram-ai/ideogram-v3-turbo",
                input={"prompt": "simple test image"}
            )
            print(f"✅ Ideogram работает: {ideogram_output}")
        except Exception as e:
            print(f"⚠️ Ideogram недоступен: {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка Replicate API: {e}")
        return False

def test_openai_api():
    """Тестирует OpenAI API"""
    print("\n🧪 Тестирование OpenAI API...")
    
    try:
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            print("❌ OPENAI_API_KEY не найден")
            return False
        
        # Создаем клиент
        client = openai.OpenAI(api_key=api_key)
        print("✅ Клиент OpenAI создан")
        
        # Тестируем простой запрос
        print("🔄 Тестирую OpenAI API...")
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": "Привет! Ответь одним словом."}
            ],
            max_tokens=10
        )
        
        reply = response.choices[0].message.content
        print(f"✅ OpenAI API работает: {reply}")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка OpenAI API: {e}")
        return False

def test_telegram_bot():
    """Тестирует Telegram Bot Token"""
    print("\n🧪 Тестирование Telegram Bot Token...")
    
    try:
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not token:
            print("❌ TELEGRAM_BOT_TOKEN не найден")
            return False
        
        # Проверяем формат токена
        if not token.startswith('5') or len(token) < 40:
            print("❌ Неверный формат Telegram Bot Token")
            return False
        
        print("✅ Формат Telegram Bot Token корректен")
        
        # Можно добавить проверку через Telegram API
        # Но для этого нужно делать HTTP запрос
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка проверки Telegram Bot Token: {e}")
        return False

def main():
    """Основная функция тестирования"""
    print("🚀 Тестирование API ключей и их работоспособности")
    print("=" * 60)
    
    # Проверяем переменные окружения
    env_ok = test_environment_variables()
    
    if not env_ok:
        print("\n❌ Не все переменные окружения найдены")
        print("💡 Убедитесь, что файл .env существует или переменные установлены в Railway")
        return
    
    # Тестируем API
    replicate_ok = test_replicate_api()
    openai_ok = test_openai_api()
    telegram_ok = test_telegram_bot()
    
    print("\n" + "=" * 60)
    print("📊 Результаты тестирования:")
    print(f"🔑 Переменные окружения: {'✅' if env_ok else '❌'}")
    print(f"🤖 Replicate API: {'✅' if replicate_ok else '❌'}")
    print(f"🧠 OpenAI API: {'✅' if openai_ok else '❌'}")
    print(f"📱 Telegram Bot: {'✅' if telegram_ok else '❌'}")
    
    if all([env_ok, replicate_ok, openai_ok, telegram_ok]):
        print("\n🎉 Все тесты пройдены! Бот должен работать корректно.")
    else:
        print("\n⚠️ Некоторые тесты не пройдены. Проверьте настройки.")
        
        if not replicate_ok:
            print("\n💡 Для Replicate API:")
            print("   - Проверьте баланс на https://replicate.com/account/billing")
            print("   - Убедитесь, что токен действителен")
            
        if not openai_ok:
            print("\n💡 Для OpenAI API:")
            print("   - Проверьте баланс на https://platform.openai.com/account/billing")
            print("   - Убедитесь, что токен действителен")

if __name__ == "__main__":
    main()

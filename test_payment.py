#!/usr/bin/env python3
"""
Тест платежной системы AI Image Generator Bot
"""

import os
import sys
from dotenv import load_dotenv

    # Загружаем переменные окружения
    load_dotenv()
    
def test_betatransfer_api():
    """Тестирует API Betatransfer"""
    print("🧪 Тестируем API Betatransfer...")
    
    try:
        from betatransfer_api import betatransfer_api
        
        # Проверяем подключение
        print("🔍 Проверяем подключение к API...")
        connection_test = betatransfer_api.test_connection()
        print(f"📡 Результат подключения: {connection_test}")
        
        # Тестируем создание платежа
        print("\n🔍 Тестируем создание платежа...")
        payment_result = betatransfer_api.create_payment(
            amount=14.0,
            currency="UAH",
            description="Тестовый платеж для 2000 кредитов",
            payer_id="test_user_123"
        )
        print(f"📝 Результат создания платежа: {payment_result}")
        
        if 'payment_id' in payment_result:
            payment_id = payment_result['payment_id']
            print(f"✅ Платеж создан успешно! ID: {payment_id}")
            
            # Получаем URL для оплаты
            payment_url = betatransfer_api.get_payment_url(payment_id)
            print(f"🔗 URL для оплаты: {payment_url}")
            
            # Проверяем статус платежа
            print("\n🔍 Проверяем статус платежа...")
            status_result = betatransfer_api.get_payment_status(payment_id)
            print(f"📊 Статус платежа: {status_result}")
            
        else:
            print(f"❌ Ошибка создания платежа: {payment_result}")
            
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")
    except Exception as e:
        print(f"❌ Ошибка тестирования: {e}")

def test_database():
    """Тестирует базу данных"""
    print("\n🧪 Тестируем базу данных...")
    
    try:
        from database import analytics_db
        
        # Тестируем создание пользователя
        test_user_id = 999999
        print(f"🔍 Создаем тестового пользователя {test_user_id}...")
        analytics_db.add_user(test_user_id, "test_user", "Test", "User")
        
        # Инициализируем кредиты
        print("🔍 Инициализируем кредиты...")
        analytics_db.init_user_credits(test_user_id)
        
        # Проверяем кредиты
        print("🔍 Проверяем кредиты...")
        credits = analytics_db.get_user_credits(test_user_id)
        print(f"📊 Кредиты пользователя: {credits}")
        
        # Добавляем кредиты
        print("🔍 Добавляем тестовые кредиты...")
        success = analytics_db.add_credits(test_user_id, 1000, description="Тестовые кредиты")
        print(f"✅ Добавление кредитов: {'успешно' if success else 'ошибка'}")
        
        # Проверяем обновленные кредиты
        credits = analytics_db.get_user_credits(test_user_id)
        print(f"📊 Обновленные кредиты: {credits}")
        
        # Тестируем использование кредитов
        print("🔍 Тестируем использование кредитов...")
        success = analytics_db.use_credits(test_user_id, 100, description="Тестовое использование")
        print(f"✅ Использование кредитов: {'успешно' if success else 'ошибка'}")
        
        # Проверяем финальные кредиты
        credits = analytics_db.get_user_credits(test_user_id)
        print(f"📊 Финальные кредиты: {credits}")
        
        # Тестируем бесплатные генерации
        print("🔍 Тестируем бесплатные генерации...")
        free_left = analytics_db.get_free_generations_left(test_user_id)
        print(f"🆓 Бесплатных генераций осталось: {free_left}")
        
        # Увеличиваем счетчик бесплатных генераций
        print("🔍 Увеличиваем счетчик бесплатных генераций...")
        success = analytics_db.increment_free_generations(test_user_id)
        print(f"✅ Увеличение счетчика: {'успешно' if success else 'ошибка'}")
        
        # Проверяем обновленные бесплатные генерации
        free_left = analytics_db.get_free_generations_left(test_user_id)
        print(f"🆓 Обновленные бесплатные генерации: {free_left}")
        
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")
    except Exception as e:
        print(f"❌ Ошибка тестирования: {e}")

def test_pricing_config():
    """Тестирует конфигурацию цен"""
    print("\n🧪 Тестируем конфигурацию цен...")
    
    try:
        from pricing_config import (
            CREDIT_PACKAGES, 
            get_generation_cost, 
            format_price,
            get_available_credit_packages
        )
        
        # Проверяем пакеты кредитов
        print("🔍 Пакеты кредитов:")
        packages = get_available_credit_packages()
        for package in packages:
            print(f"  📦 {package['name']}: {package['credits']} кредитов за {format_price(package['price'], package['currency'])}")
        
        # Тестируем расчет стоимости генераций
        print("\n🔍 Стоимость генераций:")
        models = ['Ideogram', 'Bytedance (Seedream-3)', 'Google Imagen 4 Ultra', 'FLUX.1 Kontext Pro']
        for model in models:
            cost = get_generation_cost(model)
            print(f"  🎨 {model}: {cost} кредитов")
        
        # Тестируем форматирование цен
        print("\n🔍 Форматирование цен:")
        test_amounts = [14.0, 30.0, 50.0]
        currencies = ['UAH', 'USD', 'RUB', 'EUR']
        for amount in test_amounts:
            for currency in currencies:
                formatted = format_price(amount, currency)
                print(f"  💰 {amount} {currency}: {formatted}")
                
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")
    except Exception as e:
        print(f"❌ Ошибка тестирования: {e}")

def main():
    """Основная функция тестирования"""
    print("🚀 Запуск тестов платежной системы AI Image Generator Bot")
    print("=" * 60)
    
    # Проверяем переменные окружения
    print("🔍 Проверяем переменные окружения...")
    required_vars = [
        'BETATRANSFER_API_KEY',
        'BETATRANSFER_SECRET_KEY',
        'WEBHOOK_BASE_URL'
    ]
    
    for var in required_vars:
        value = os.getenv(var)
        if value:
            print(f"  ✅ {var}: {value[:20]}..." if len(value) > 20 else f"  ✅ {var}: {value}")
        else:
            print(f"  ❌ {var}: не установлен")
    
    print("\n" + "=" * 60)
    
    # Запускаем тесты
    test_betatransfer_api()
    test_database()
    test_pricing_config()
    
    print("\n" + "=" * 60)
    print("🎉 Тестирование завершено!")

if __name__ == "__main__":
    main()

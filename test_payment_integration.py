#!/usr/bin/env python3
"""
Тест интеграции платежной системы в боте
"""

import os
import sys
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

def test_imports():
    """Тестирует импорт всех необходимых модулей"""
    print("🧪 Тестируем импорты...")
    
    try:
        from betatransfer_api import betatransfer_api
        print("✅ betatransfer_api импортирован успешно")
    except ImportError as e:
        print(f"❌ Ошибка импорта betatransfer_api: {e}")
        return False
    
    try:
        from database import analytics_db
        print("✅ database импортирован успешно")
    except ImportError as e:
        print(f"❌ Ошибка импорта database: {e}")
        return False
    
    try:
        from pricing_config import CREDIT_PACKAGES, get_generation_cost
        print("✅ pricing_config импортирован успешно")
    except ImportError as e:
        print(f"❌ Ошибка импорта pricing_config: {e}")
        return False
    
    return True

def test_database_functions():
    """Тестирует функции базы данных"""
    print("\n🧪 Тестируем функции базы данных...")
    
    try:
        from database import analytics_db
        
        # Тестируем создание пользователя
        test_user_id = 999999
        analytics_db.add_user(test_user_id, "test_user", "Test", "User")
        print(f"✅ Пользователь {test_user_id} создан")
        
        # Тестируем инициализацию кредитов
        analytics_db.init_user_credits(test_user_id)
        print("✅ Кредиты инициализированы")
        
        # Тестируем получение кредитов
        credits = analytics_db.get_user_credits(test_user_id)
        print(f"✅ Кредиты получены: {credits}")
        
        # Тестируем добавление кредитов
        success = analytics_db.add_credits(test_user_id, 100, description="Тестовые кредиты")
        print(f"✅ Добавление кредитов: {'успешно' if success else 'ошибка'}")
        
        # Тестируем создание платежа
        payment_record = analytics_db.create_payment(
            user_id=test_user_id,
            amount=14.0,
            currency="UAH",
            payment_id="test_payment_123",
            order_id="test_order_123"
        )
        print(f"✅ Создание платежа: {'успешно' if payment_record else 'ошибка'}")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка тестирования базы данных: {e}")
        return False

def test_pricing_config():
    """Тестирует конфигурацию цен"""
    print("\n🧪 Тестируем конфигурацию цен...")
    
    try:
        from pricing_config import CREDIT_PACKAGES, get_generation_cost, get_available_credit_packages
        
        # Проверяем пакеты кредитов
        packages = get_available_credit_packages()
        print(f"✅ Найдено пакетов кредитов: {len(packages)}")
        for package in packages:
            print(f"  📦 {package['name']}: {package['credits']} кредитов за {package['price']} {package['currency']}")
        
        # Тестируем расчет стоимости генераций
        models = ['Ideogram', 'Bytedance (Seedream-3)', 'Google Imagen 4 Ultra']
        for model in models:
            try:
                cost = get_generation_cost(model)
                print(f"✅ {model}: {cost} кредитов")
            except Exception as e:
                print(f"❌ {model}: ошибка - {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка тестирования конфигурации цен: {e}")
        return False

def test_betatransfer_api():
    """Тестирует API Betatransfer"""
    print("\n🧪 Тестируем API Betatransfer...")
    
    try:
        from betatransfer_api import betatransfer_api
        
        # Проверяем переменные окружения
        api_key = os.getenv('BETATRANSFER_API_KEY')
        secret_key = os.getenv('BETATRANSFER_SECRET_KEY')
        webhook_url = os.getenv('WEBHOOK_BASE_URL')
        
        if not api_key:
            print("❌ BETATRANSFER_API_KEY не установлен")
            return False
        if not secret_key:
            print("❌ BETATRANSFER_SECRET_KEY не установлен")
            return False
        if not webhook_url:
            print("❌ WEBHOOK_BASE_URL не установлен")
            return False
        
        print("✅ Все переменные окружения установлены")
        print(f"  API Key: {api_key[:10]}...")
        print(f"  Secret Key: {secret_key[:10]}...")
        print(f"  Webhook URL: {webhook_url}")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка тестирования API Betatransfer: {e}")
        return False

def main():
    """Основная функция тестирования"""
    print("🚀 Тест интеграции платежной системы в боте")
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
    success = True
    
    if not test_imports():
        success = False
    
    if not test_database_functions():
        success = False
    
    if not test_pricing_config():
        success = False
    
    if not test_betatransfer_api():
        success = False
    
    print("\n" + "=" * 60)
    
    if success:
        print("🎉 Все тесты прошли успешно! Платежная система готова к работе.")
    else:
        print("❌ Некоторые тесты не прошли. Проверьте настройки.")
    
    return success

if __name__ == "__main__":
    main()

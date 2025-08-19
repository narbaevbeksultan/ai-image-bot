#!/usr/bin/env python3
"""
Тест создания платежа через Betatransfer API
"""

import os
import logging
from dotenv import load_dotenv
from betatransfer_api import BetatransferAPI
import json

# Настраиваем детальное логирование HTTP запросов
logging.basicConfig(level=logging.DEBUG)
# Включаем логирование для requests
logging.getLogger("urllib3").setLevel(logging.DEBUG)
logging.getLogger("requests").setLevel(logging.DEBUG)

def main():
    # Загружаем переменные окружения
    load_dotenv()
    
    print("🚀 Тестируем создание платежа через Betatransfer API...")
    print("=" * 60)
    
    # Создаем экземпляр API
    api = BetatransferAPI()
    
    # Тестовые данные пользователя
    test_user = {
        'email': 'test@example.com',
        'name': 'Test User',
        'id': 'user_123'
    }
    
    print(f"💰 Создаем тестовый платеж на 0.007$ (1 кредит)...")
    print(f"👤 Пользователь: {test_user['name']} ({test_user['email']})")
    
    try:
        # Создаем платеж
        result = api.create_payment(
            amount=0.007,
            currency="UAH",
            description="Покупка 1 кредита",
            payer_email=test_user['email'],
            payer_name=test_user['name'],
            payer_id=test_user['id']
        )
        
        if "error" in result:
            print(f"❌ Ошибка создания платежа: {result['error']}")
        else:
            print(f"✅ Платеж создан успешно!")
            print(f"📊 Результат: {json.dumps(result, indent=2, ensure_ascii=False)}")
            
            # Если есть payment_id, показываем URL для оплаты
            if 'payment_id' in result:
                payment_url = api.get_payment_url(result['payment_id'])
                print(f"🌐 URL для оплаты: {payment_url}")
    
    except Exception as e:
        print(f"❌ Ошибка: {str(e)}")
    
    print("\n" + "=" * 60)
    print("🎯 Следующие шаги:")
    print("1. Проверить логи в терминале с callback сервером")
    print("2. Настроить callback URL в Betatransfer")
    print("3. Протестировать реальный платеж")

if __name__ == "__main__":
    main()

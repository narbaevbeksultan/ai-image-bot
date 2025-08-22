#!/usr/bin/env python3
"""
Прямой тест создания платежа через Betatransfer API
"""

from betatransfer_api import BetatransferAPI
import time

def test_payment_creation():
    print("🧪 Тестируем создание платежа через Betatransfer API...")
    
    # Создаем экземпляр API
    api = BetatransferAPI()
    
    # Тестовые данные для платежа
    test_payment = {
        'amount': 14.0,
        'currency': 'UAH',
        'order_id': f'test_order_{int(time.time())}',
        'payer_id': '7735323051'  # ID пользователя из предыдущих логов
    }
    
    print(f"🔍 Тестовые данные платежа:")
    print(f"   Сумма: {test_payment['amount']} {test_payment['currency']}")
    print(f"   Order ID: {test_payment['order_id']}")
    print(f"   Payer ID: {test_payment['payer_id']}")
    print()
    
    # Создаем платеж
    result = api.create_payment(
        amount=test_payment['amount'],
        currency=test_payment['currency'],
        order_id=test_payment['order_id'],
        payer_id=test_payment['payer_id']
    )
    
    print(f"🔍 Результат создания платежа:")
    print(f"   {result}")
    
    if 'error' in result:
        print(f"❌ Ошибка создания платежа: {result['error']}")
        return False
    else:
        print(f"✅ Платеж создан успешно!")
        if 'id' in result:
            print(f"   Payment ID: {result['id']}")
        if 'url' in result:
            print(f"   Payment URL: {result['url']}")
        return True

if __name__ == "__main__":
    test_payment_creation()



#!/usr/bin/env python3
"""
Тестовый файл для симуляции callback уведомления от Betatransfer
"""

import requests
import hashlib
import time

def test_callback():
    print("🧪 Тестируем callback систему...")
    print("=" * 50)
    
    # Тестовые данные (как в примере Betatransfer)
    test_data = {
        'id': 'test_payment_123',
        'paymentSystem': 'card',
        'type': 'deposit',
        'orderId': f'test_order_{int(time.time())}',
        'orderAmount': '0.007',
        'paidAmount': '0.007',
        'amount': '0.007',
        'currency': 'UAH',
        'commission': '0.00',
        'createdAt': str(int(time.time())),
        'updatedAt': str(int(time.time())),
        'status': 'completed',
        'exchangeRate': '1.0',
        'receiverWallet': 'test_wallet',
        'beneficiaryName': 'Test User',
        'beneficiaryBank': 'test_bank'
    }
    
    # Создаем подпись (MD5 от всех параметров + секретный ключ)
    secret_key = "853d593cf0696f846edd26b079009c75"  # Ваш секретный ключ
    
    # Сортируем параметры и создаем строку для подписи
    sorted_params = sorted(test_data.items())
    signature_string = ''.join(str(v) for _, v in sorted_params) + secret_key
    
    # Создаем MD5 подпись
    signature = hashlib.md5(signature_string.encode('utf-8')).hexdigest()
    
    # Добавляем подпись к данным
    test_data['sign'] = signature
    
    print(f"📝 Тестовые данные: {test_data}")
    print(f"🔐 Подпись: {signature}")
    print()
    
    # Отправляем POST запрос на callback endpoint
    callback_url = "https://3e73a8bfe0ff.ngrok-free.app/payment/callback"
    
    try:
        print(f"🌐 Отправляем callback на: {callback_url}")
        response = requests.post(callback_url, data=test_data)
        
        print(f"📊 Статус ответа: {response.status_code}")
        print(f"📝 Ответ: {response.text}")
        
        if response.status_code == 200:
            print("✅ Callback обработан успешно!")
        else:
            print("❌ Ошибка обработки callback")
            
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")
    
    print("\n" + "=" * 50)
    print("🎯 Следующие шаги:")
    print("1. Проверьте логи в терминале с callback сервером")
    print("2. Дождитесь ответов от Betatransfer")
    print("3. Протестируем создание реального платежа")

if __name__ == "__main__":
    test_callback()




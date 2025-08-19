#!/usr/bin/env python3
"""
Тестовый файл для проверки подключения к Betatransfer API
"""

import os
from dotenv import load_dotenv
from betatransfer_api import BetatransferAPI

def main():
    print("🚀 Тестируем подключение к Betatransfer API...")
    print("=" * 50)
    
    # Загружаем переменные окружения
    load_dotenv()
    
    # Проверяем наличие API ключей
    api_key = os.getenv('BETATRANSFER_API_KEY')
    secret_key = os.getenv('BETATRANSFER_SECRET_KEY')
    
    if not api_key or not secret_key:
        print("❌ Ошибка: API ключи не найдены в .env файле!")
        print("📝 Убедитесь, что файл .env создан и содержит:")
        print("   BETATRANSFER_API_KEY=ваш_ключ")
        print("   BETATRANSFER_SECRET_KEY=ваш_секрет")
        return
    
    print(f"✅ API Key: {api_key[:10]}...")
    print(f"✅ Secret Key: {secret_key[:10]}...")
    print()
    
    # Создаем экземпляр API
    try:
        api = BetatransferAPI()
        print("✅ BetatransferAPI создан успешно")
    except Exception as e:
        print(f"❌ Ошибка создания API: {e}")
        return
    
    # Тестируем подключение
    print("\n🔍 Тестируем подключение к API...")
    try:
        result = api.test_connection()
        
        if result.get("success"):
            print("✅ Подключение успешно!")
            print(f"📝 Сообщение: {result.get('message')}")
        else:
            print("❌ Ошибка подключения!")
            print(f"📝 Сообщение: {result.get('message')}")
            
    except Exception as e:
        print(f"❌ Ошибка тестирования: {e}")
    
    print("\n" + "=" * 50)
    print("🎯 Следующие шаги:")
    print("1. Установить ngrok")
    print("2. Запустить callback сервер")
    print("3. Получить ngrok URL")
    print("4. Настроить callback URL в Betatransfer")

if __name__ == "__main__":
    main()




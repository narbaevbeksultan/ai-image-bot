#!/usr/bin/env python3
"""
Тестовый скрипт для проверки сохранения данных пользователей
"""

import os
import sys
from database import AnalyticsDB

def test_database_persistence():
    """Тестирует, что данные пользователей сохраняются правильно"""
    
    print("🧪 Тестирование сохранения данных пользователей...")
    print("=" * 60)
    
    # Создаем тестовую базу данных
    test_db_path = "test_bot_analytics.db"
    
    # Удаляем тестовую базу, если она существует
    if os.path.exists(test_db_path):
        os.remove(test_db_path)
    
    try:
        # Создаем экземпляр базы данных
        db = AnalyticsDB(test_db_path)
        
        test_user_id = 12345
        
        print(f"👤 Тестируем с пользователем ID: {test_user_id}")
        
        # 1. Тест: Получение лимитов для нового пользователя
        print("\n1️⃣ Тест получения лимитов для нового пользователя...")
        limits = db.get_user_limits(test_user_id)
        print(f"   Лимиты: {limits}")
        
        # Проверяем, что запись НЕ создалась автоматически
        import sqlite3
        with sqlite3.connect(db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM user_limits WHERE user_id = ?", (test_user_id,))
            count = cursor.fetchone()[0]
            print(f"   Записей в user_limits: {count} (должно быть 0)")
            
        if count == 0:
            print("   ✅ ПРОЙДЕН: Запись не создалась автоматически")
        else:
            print("   ❌ ОШИБКА: Запись создалась автоматически!")
            return False
        
        # 2. Тест: Получение кредитов для нового пользователя
        print("\n2️⃣ Тест получения кредитов для нового пользователя...")
        credits = db.get_user_credits(test_user_id)
        print(f"   Кредиты: {credits}")
        
        # Проверяем, что запись НЕ создалась автоматически
        with sqlite3.connect(db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM user_credits WHERE user_id = ?", (test_user_id,))
            count = cursor.fetchone()[0]
            print(f"   Записей в user_credits: {count} (должно быть 0)")
            
        if count == 0:
            print("   ✅ ПРОЙДЕН: Запись не создалась автоматически")
        else:
            print("   ❌ ОШИБКА: Запись создалась автоматически!")
            return False
        
        # 3. Тест: Использование бесплатной генерации
        print("\n3️⃣ Тест использования бесплатной генерации...")
        result = db.increment_free_generations(test_user_id)
        print(f"   Результат: {result}")
        
        # Небольшая задержка для освобождения блокировки
        import time
        time.sleep(0.1)
        
        # Проверяем, что запись создалась
        with sqlite3.connect(db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM user_limits WHERE user_id = ?", (test_user_id,))
            count = cursor.fetchone()[0]
            print(f"   Записей в user_limits: {count} (должно быть 1)")
            
        if count == 1:
            print("   ✅ ПРОЙДЕН: Запись создалась при использовании")
        else:
            print("   ❌ ОШИБКА: Запись не создалась при использовании!")
            return False
        
        # 4. Тест: Добавление кредитов
        print("\n4️⃣ Тест добавления кредитов...")
        result = db.add_credits(test_user_id, 100, description="Тестовая покупка")
        print(f"   Результат: {result}")
        
        # Небольшая задержка для освобождения блокировки
        time.sleep(0.1)
        
        # Проверяем, что запись создалась
        with sqlite3.connect(db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM user_credits WHERE user_id = ?", (test_user_id,))
            count = cursor.fetchone()[0]
            print(f"   Записей в user_credits: {count} (должно быть 1)")
            
        if count == 1:
            print("   ✅ ПРОЙДЕН: Запись создалась при добавлении кредитов")
        else:
            print("   ❌ ОШИБКА: Запись не создалась при добавлении кредитов!")
            return False
        
        # 5. Тест: Использование кредитов
        print("\n5️⃣ Тест использования кредитов...")
        result = db.use_credits(test_user_id, 10, description="Тестовое использование")
        print(f"   Результат: {result}")
        
        # Проверяем баланс
        credits = db.get_user_credits(test_user_id)
        print(f"   Баланс после использования: {credits['balance']} (должно быть 90)")
        
        if credits['balance'] == 90:
            print("   ✅ ПРОЙДЕН: Кредиты списались правильно")
        else:
            print("   ❌ ОШИБКА: Кредиты списались неправильно!")
            return False
        
        # 6. Тест: Перезапуск (симуляция)
        print("\n6️⃣ Тест симуляции перезапуска...")
        
        # Создаем новый экземпляр базы данных (как при перезапуске)
        db2 = AnalyticsDB(test_db_path)
        
        # Проверяем, что данные сохранились
        limits2 = db2.get_user_limits(test_user_id)
        credits2 = db2.get_user_credits(test_user_id)
        
        print(f"   Лимиты после перезапуска: {limits2}")
        print(f"   Кредиты после перезапуска: {credits2}")
        
        if (limits2['free_generations_used'] == 1 and 
            limits2['total_free_generations'] == 3 and
            credits2['balance'] == 90):
            print("   ✅ ПРОЙДЕН: Данные сохранились после перезапуска")
        else:
            print("   ❌ ОШИБКА: Данные не сохранились после перезапуска!")
            return False
        
        print("\n🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
        print("   Теперь кредиты и лимиты пользователей будут сохраняться при перезапуске бота")
        
        return True
        
    except Exception as e:
        print(f"\n❌ ОШИБКА ВО ВРЕМЯ ТЕСТИРОВАНИЯ: {e}")
        return False
        
    finally:
        # Удаляем тестовую базу данных
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
            print(f"\n🧹 Тестовая база данных {test_db_path} удалена")

if __name__ == "__main__":
    success = test_database_persistence()
    sys.exit(0 if success else 1)

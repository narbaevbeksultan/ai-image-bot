#!/usr/bin/env python3
"""
Тестовый скрипт для проверки системы аналитики
"""

from database import analytics_db
import time

def test_analytics():
    """Тестирует систему аналитики"""
    print("🧪 Тестирование системы аналитики...")
    
    # Тестируем добавление пользователя
    print("1. Добавление тестового пользователя...")
    analytics_db.add_user(
        user_id=123456789,
        username="test_user",
        first_name="Test",
        last_name="User"
    )
    
    # Тестируем обновление активности
    print("2. Обновление активности пользователя...")
    analytics_db.update_user_activity(123456789)
    
    # Тестируем логирование действий
    print("3. Логирование действий...")
    analytics_db.log_action(123456789, "test_action", "test_data")
    
    # Тестируем логирование генерации
    print("4. Логирование успешной генерации...")
    analytics_db.log_generation(
        user_id=123456789,
        model_name="Ideogram",
        format_type="Instagram Post",
        prompt="test prompt",
        image_count=2,
        success=True,
        generation_time=15.5
    )
    
    # Тестируем логирование ошибки
    print("5. Логирование ошибки...")
    analytics_db.log_error(
        user_id=123456789,
        error_type="test_error",
        error_message="Test error message"
    )
    
    # Тестируем получение статистики пользователя
    print("6. Получение статистики пользователя...")
    user_stats = analytics_db.get_user_stats(123456789)
    print(f"   Статистика пользователя: {user_stats}")
    
    # Тестируем получение глобальной статистики
    print("7. Получение глобальной статистики...")
    global_stats = analytics_db.get_global_stats(7)
    print(f"   Глобальная статистика: {global_stats}")
    
    print("✅ Тестирование завершено!")
    print("\n📊 Для просмотра статистики запустите: python view_stats.py")

if __name__ == "__main__":
    test_analytics()


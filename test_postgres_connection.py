#!/usr/bin/env python3
"""
Скрипт для проверки подключения к PostgreSQL
Использование: python test_postgres_connection.py
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def test_postgres_connection():
    """Тестирует подключение к PostgreSQL"""
    try:
        # Получаем DATABASE_URL
        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            logging.error("❌ DATABASE_URL не установлен!")
            logging.info("💡 Установите переменную окружения: export DATABASE_URL='postgresql://...'")
            return False
        
        logging.info("🔌 Подключаемся к PostgreSQL...")
        
        # Подключаемся к базе
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Тестируем подключение
        cursor.execute("SELECT 1 as test")
        result = cursor.fetchone()
        
        if result and result['test'] == 1:
            logging.info("✅ Подключение к PostgreSQL успешно!")
            
            # Проверяем версию PostgreSQL
            cursor.execute("SELECT version()")
            version = cursor.fetchone()['version']
            logging.info(f"📊 Версия PostgreSQL: {version}")
            
            # Проверяем существующие таблицы
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
                ORDER BY table_name
            """)
            tables = cursor.fetchall()
            
            if tables:
                logging.info("📋 Найденные таблицы:")
                for table in tables:
                    logging.info(f"  - {table['table_name']}")
            else:
                logging.info("📋 Таблицы не найдены (база пуста)")
            
            conn.close()
            return True
        else:
            logging.error("❌ Неожиданный результат теста")
            return False
            
    except psycopg2.Error as e:
        logging.error(f"❌ Ошибка PostgreSQL: {e}")
        return False
    except Exception as e:
        logging.error(f"❌ Общая ошибка: {e}")
        return False

def test_database_operations():
    """Тестирует основные операции с базой данных"""
    try:
        from database_postgres import analytics_db
        
        logging.info("🧪 Тестируем операции с базой данных...")
        
        # Тест 1: Добавление пользователя
        test_user_id = 999999999
        analytics_db.add_user(test_user_id, "test_user", "Test", "User")
        logging.info("✅ Тест добавления пользователя пройден")
        
        # Тест 2: Получение лимитов
        limits = analytics_db.get_user_limits(test_user_id)
        logging.info(f"✅ Тест получения лимитов: {limits}")
        
        # Тест 3: Получение кредитов
        credits = analytics_db.get_user_credits(test_user_id)
        logging.info(f"✅ Тест получения кредитов: {credits}")
        
        # Тест 4: Добавление кредитов
        analytics_db.add_credits(test_user_id, 10, description="Тестовые кредиты")
        updated_credits = analytics_db.get_user_credits(test_user_id)
        logging.info(f"✅ Тест добавления кредитов: {updated_credits}")
        
        # Тест 5: Логирование действия
        analytics_db.log_action(test_user_id, "test_action", "Тестовые данные")
        logging.info("✅ Тест логирования действия пройден")
        
        # Очистка тестовых данных
        with analytics_db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE user_id = %s", (test_user_id,))
            conn.commit()
        
        logging.info("🧹 Тестовые данные очищены")
        logging.info("🎉 Все тесты базы данных пройдены успешно!")
        
        return True
        
    except Exception as e:
        logging.error(f"❌ Ошибка тестирования операций: {e}")
        return False

def main():
    """Основная функция тестирования"""
    logging.info("🚀 Начинаем тестирование PostgreSQL подключения")
    
    # Тест 1: Подключение
    if not test_postgres_connection():
        logging.error("❌ Тест подключения не пройден")
        return
    
    # Тест 2: Операции с базой данных
    if not test_database_operations():
        logging.error("❌ Тест операций не пройден")
        return
    
    logging.info("🎉 Все тесты пройдены! PostgreSQL готов к работе!")

if __name__ == "__main__":
    main()

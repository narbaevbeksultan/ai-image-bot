#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для очистки PostgreSQL базы данных
Удаляет все данные и сбрасывает счетчики ID
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def clear_database():
    """Очищает базу данных и сбрасывает счетчики ID"""
    
    # Получаем URL базы данных
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        logger.error("❌ DATABASE_URL не найден в переменных окружения")
        return False
    
    try:
        # Подключаемся к базе данных
        logger.info("🔌 Подключаемся к PostgreSQL...")
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        
        # Отключаем проверку внешних ключей
        logger.info("🔓 Отключаем проверку внешних ключей...")
        cursor.execute("SET session_replication_role = replica;")
        
        # Очищаем таблицы в правильном порядке (с учетом зависимостей)
        tables_to_clear = [
            'user_actions',
            'credit_transactions', 
            'user_credits',
            'user_limits',
            'payments',
            'errors',
            'generations',
            'users'
        ]
        
        logger.info("🧹 Очищаем таблицы...")
        for table in tables_to_clear:
            try:
                cursor.execute(f"DELETE FROM {table};")
                logger.info(f"✅ Очищена таблица {table}")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка очистки таблицы {table}: {e}")
        
        # Сбрасываем счетчики ID
        logger.info("🔄 Сбрасываем счетчики ID...")
        sequences_to_reset = [
            'user_actions_id_seq',
            'credit_transactions_id_seq',
            'errors_id_seq',
            'generations_id_seq'
        ]
        
        for sequence in sequences_to_reset:
            try:
                cursor.execute(f"ALTER SEQUENCE {sequence} RESTART WITH 1;")
                logger.info(f"✅ Сброшен счетчик {sequence}")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка сброса счетчика {sequence}: {e}")
        
        # Включаем проверку внешних ключей обратно
        logger.info("🔒 Включаем проверку внешних ключей...")
        cursor.execute("SET session_replication_role = DEFAULT;")
        
        # Подтверждаем изменения
        conn.commit()
        
        logger.info("🎉 База данных успешно очищена!")
        logger.info("💡 Теперь можно перезапустить бота")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка очистки базы данных: {e}")
        return False
        
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    logger.info("🚀 Начинаем очистку базы данных...")
    
    # Проверяем, что мы в правильной директории
    if not os.path.exists('database.py'):
        logger.error("❌ Файл database.py не найден. Запустите скрипт из корневой директории проекта")
        exit(1)
    
    success = clear_database()
    
    if success:
        logger.info("✅ Очистка завершена успешно!")
        logger.info("🔄 Теперь перезапустите бота на Railway")
    else:
        logger.error("❌ Очистка не удалась. Проверьте логи выше")
        exit(1)

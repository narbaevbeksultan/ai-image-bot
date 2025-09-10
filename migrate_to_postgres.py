#!/usr/bin/env python3
"""
Скрипт миграции данных из SQLite в PostgreSQL
Использование: python migrate_to_postgres.py
"""

import os
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
from datetime import datetime

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_sqlite_connection():
    """Подключение к SQLite базе"""
    return sqlite3.connect("bot_analytics.db")

def get_postgres_connection():
    """Подключение к PostgreSQL базе"""
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        raise ValueError("DATABASE_URL не установлен. Установите переменную окружения DATABASE_URL")
    return psycopg2.connect(db_url)

def migrate_table(sqlite_conn, postgres_conn, table_name, columns, transform_func=None):
    """Миграция таблицы из SQLite в PostgreSQL"""
    try:
        # Получаем данные из SQLite
        sqlite_cursor = sqlite_conn.cursor()
        sqlite_cursor.execute(f"SELECT * FROM {table_name}")
        rows = sqlite_cursor.fetchall()
        
        if not rows:
            logging.info(f"Таблица {table_name} пуста, пропускаем")
            return
        
        # Получаем названия колонок
        column_names = [description[0] for description in sqlite_cursor.description]
        
        # Подготавливаем данные для PostgreSQL
        postgres_cursor = postgres_conn.cursor()
        
        # Создаем плейсхолдеры для INSERT
        placeholders = ', '.join(['%s'] * len(column_names))
        columns_str = ', '.join(column_names)
        
        insert_query = f"INSERT INTO {table_name} ({columns_str}) VALUES ({placeholders})"
        
        migrated_count = 0
        for row in rows:
            try:
                # Применяем трансформацию если есть
                if transform_func:
                    row = transform_func(row, column_names)
                
                postgres_cursor.execute(insert_query, row)
                migrated_count += 1
            except Exception as e:
                logging.warning(f"Ошибка при миграции строки в таблице {table_name}: {e}")
                continue
        
        postgres_conn.commit()
        logging.info(f"✅ Таблица {table_name}: мигрировано {migrated_count} записей")
        
    except Exception as e:
        logging.error(f"Ошибка миграции таблицы {table_name}: {e}")
        postgres_conn.rollback()

def transform_users(row, columns):
    """Трансформация данных пользователей"""
    # Преобразуем user_id в BIGINT для PostgreSQL
    row = list(row)
    if 'user_id' in columns:
        user_id_idx = columns.index('user_id')
        row[user_id_idx] = int(row[user_id_idx])
    return row

def transform_generations(row, columns):
    """Трансформация данных генераций"""
    row = list(row)
    if 'user_id' in columns:
        user_id_idx = columns.index('user_id')
        row[user_id_idx] = int(row[user_id_idx])
    return row

def transform_payments(row, columns):
    """Трансформация данных платежей"""
    row = list(row)
    if 'user_id' in columns:
        user_id_idx = columns.index('user_id')
        row[user_id_idx] = int(row[user_id_idx])
    return row

def transform_credits(row, columns):
    """Трансформация данных кредитов"""
    row = list(row)
    if 'user_id' in columns:
        user_id_idx = columns.index('user_id')
        row[user_id_idx] = int(row[user_id_idx])
    return row

def transform_limits(row, columns):
    """Трансформация данных лимитов"""
    row = list(row)
    if 'user_id' in columns:
        user_id_idx = columns.index('user_id')
        row[user_id_idx] = int(row[user_id_idx])
    return row

def transform_transactions(row, columns):
    """Трансформация данных транзакций"""
    row = list(row)
    if 'user_id' in columns:
        user_id_idx = columns.index('user_id')
        row[user_id_idx] = int(row[user_id_idx])
    return row

def check_sqlite_exists():
    """Проверяем, существует ли SQLite файл"""
    if not os.path.exists("bot_analytics.db"):
        logging.error("Файл bot_analytics.db не найден!")
        return False
    return True

def check_postgres_connection():
    """Проверяем подключение к PostgreSQL"""
    try:
        conn = get_postgres_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        conn.close()
        logging.info("✅ Подключение к PostgreSQL успешно")
        return True
    except Exception as e:
        logging.error(f"Ошибка подключения к PostgreSQL: {e}")
        return False

def get_table_stats(sqlite_conn, table_name):
    """Получаем статистику по таблице"""
    try:
        cursor = sqlite_conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        return count
    except:
        return 0

def main():
    """Основная функция миграции"""
    logging.info("🚀 Начинаем миграцию данных из SQLite в PostgreSQL")
    
    # Проверяем наличие SQLite файла
    if not check_sqlite_exists():
        return
    
    # Проверяем подключение к PostgreSQL
    if not check_postgres_connection():
        return
    
    # Подключаемся к базам данных
    try:
        sqlite_conn = get_sqlite_connection()
        postgres_conn = get_postgres_connection()
        
        logging.info("📊 Статистика SQLite базы данных:")
        
        # Получаем статистику по таблицам
        tables_stats = {}
        tables = ['users', 'generations', 'errors', 'user_actions', 'payments', 
                 'user_limits', 'user_credits', 'credit_transactions']
        
        for table in tables:
            count = get_table_stats(sqlite_conn, table)
            tables_stats[table] = count
            logging.info(f"  {table}: {count} записей")
        
        # Спрашиваем подтверждение
        total_records = sum(tables_stats.values())
        if total_records == 0:
            logging.warning("В SQLite базе нет данных для миграции")
            return
        
        print(f"\n📋 Найдено {total_records} записей для миграции")
        confirm = input("Продолжить миграцию? (y/N): ").lower().strip()
        
        if confirm != 'y':
            logging.info("Миграция отменена")
            return
        
        # Начинаем миграцию
        logging.info("🔄 Начинаем миграцию...")
        
        # Мигрируем таблицы в правильном порядке (с учетом внешних ключей)
        migration_order = [
            ('users', transform_users),
            ('generations', transform_generations),
            ('errors', None),
            ('user_actions', None),
            ('payments', transform_payments),
            ('user_limits', transform_limits),
            ('user_credits', transform_credits),
            ('credit_transactions', transform_transactions)
        ]
        
        for table_name, transform_func in migration_order:
            if tables_stats.get(table_name, 0) > 0:
                logging.info(f"🔄 Мигрируем таблицу {table_name}...")
                migrate_table(sqlite_conn, postgres_conn, table_name, None, transform_func)
            else:
                logging.info(f"⏭️  Таблица {table_name} пуста, пропускаем")
        
        # Проверяем результат
        logging.info("🔍 Проверяем результат миграции...")
        postgres_cursor = postgres_conn.cursor()
        
        for table in tables:
            postgres_cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = postgres_cursor.fetchone()[0]
            original_count = tables_stats.get(table, 0)
            status = "✅" if count == original_count else "⚠️"
            logging.info(f"  {status} {table}: {count}/{original_count} записей")
        
        logging.info("🎉 Миграция завершена!")
        logging.info("💡 Теперь можно безопасно обновлять бота на Railway")
        
    except Exception as e:
        logging.error(f"Критическая ошибка миграции: {e}")
    finally:
        try:
            sqlite_conn.close()
            postgres_conn.close()
        except:
            pass

if __name__ == "__main__":
    main()

import sqlite3
import logging
from datetime import datetime, timedelta
import os
from typing import Dict, List, Optional, Tuple

class AnalyticsDB:
    def __init__(self, db_path: str = "bot_analytics.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Инициализация базы данных и создание таблиц"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Таблица пользователей
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        last_name TEXT,
                        first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        total_generations INTEGER DEFAULT 0,
                        total_errors INTEGER DEFAULT 0,
                        is_premium BOOLEAN DEFAULT FALSE
                    )
                ''')
                
                # Таблица генераций
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS generations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        model_name TEXT,
                        format_type TEXT,
                        prompt TEXT,
                        image_count INTEGER,
                        success BOOLEAN,
                        error_message TEXT,
                        generation_time REAL,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users (user_id)
                    )
                ''')
                
                # Таблица ошибок
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS errors (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        error_type TEXT,
                        error_message TEXT,
                        stack_trace TEXT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users (user_id)
                    )
                ''')
                
                # Таблица действий пользователей
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS user_actions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        action_type TEXT,
                        action_data TEXT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users (user_id)
                    )
                ''')
                
                # НОВЫЕ ТАБЛИЦЫ ДЛЯ ПЛАТЕЖНОЙ СИСТЕМЫ
                
                # Таблица платежей
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS payments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        amount DECIMAL(10,2) NOT NULL,
                        currency TEXT DEFAULT 'UAH',
                        status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'completed', 'failed'
                        betatransfer_id TEXT,
                        order_id TEXT,
                        credit_amount INTEGER,
                        payment_method TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        completed_at TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users (user_id)
                    )
                ''')
                
                # Таблица лимитов пользователей (упрощенная)
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS user_limits (
                        user_id INTEGER PRIMARY KEY,
                        free_generations_used INTEGER DEFAULT 0,
                        total_free_generations INTEGER DEFAULT 3,
                        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users (user_id)
                    )
                ''')
                
                # Таблица кредитов (для pay-per-use модели)
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS user_credits (
                        user_id INTEGER PRIMARY KEY,
                        credits_balance INTEGER DEFAULT 0,
                        total_purchased INTEGER DEFAULT 0,
                        total_used INTEGER DEFAULT 0,
                        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users (user_id)
                    )
                ''')
                
                # Таблица транзакций кредитов
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS credit_transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        transaction_type TEXT NOT NULL, -- 'purchase', 'usage', 'refund'
                        amount INTEGER NOT NULL,
                        description TEXT,
                        payment_id INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users (user_id),
                        FOREIGN KEY (payment_id) REFERENCES payments (id)
                    )
                ''')
                
                # Миграция: добавляем недостающие колонки в таблицу payments
                self._migrate_payments_table(cursor)
                
                # Миграция: добавляем недостающие колонки в таблицу user_limits
                self._migrate_user_limits_table(cursor)
                
                conn.commit()
                logging.info("База данных успешно инициализирована")
                
        except Exception as e:
            logging.error(f"Ошибка инициализации базы данных: {e}")
    
    def _migrate_payments_table(self, cursor):
        """Миграция таблицы payments для добавления недостающих колонок"""
        try:
            # Проверяем, есть ли колонка order_id
            cursor.execute("PRAGMA table_info(payments)")
            columns = [column[1] for column in cursor.fetchall()]
            
            # Добавляем колонку order_id если её нет
            if 'order_id' not in columns:
                cursor.execute("ALTER TABLE payments ADD COLUMN order_id TEXT")
                logging.info("Добавлена колонка order_id в таблицу payments")
            
            # Добавляем колонку credit_amount если её нет
            if 'credit_amount' not in columns:
                cursor.execute("ALTER TABLE payments ADD COLUMN credit_amount INTEGER")
                logging.info("Добавлена колонка credit_amount в таблицу payments")
                
        except Exception as e:
            logging.error(f"Ошибка миграции таблицы payments: {e}")
    
    def _migrate_user_limits_table(self, cursor):
        """Миграция таблицы user_limits для добавления недостающих колонок"""
        try:
            # Проверяем, есть ли таблица user_limits
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_limits'")
            if not cursor.fetchone():
                # Создаем таблицу если её нет
                cursor.execute('''
                    CREATE TABLE user_limits (
                        user_id INTEGER PRIMARY KEY,
                        free_generations_used INTEGER DEFAULT 0,
                        total_free_generations INTEGER DEFAULT 3,
                        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users (user_id)
                    )
                ''')
                logging.info("Создана таблица user_limits")
                return
            
            # Проверяем структуру существующей таблицы
            cursor.execute("PRAGMA table_info(user_limits)")
            columns = [column[1] for column in cursor.fetchall()]
            required_columns = ['free_generations_used', 'total_free_generations', 'last_updated']
            
            # Если отсутствуют важные колонки, пересоздаем таблицу
            missing_columns = [col for col in required_columns if col not in columns]
            if missing_columns:
                logging.info(f"Отсутствуют колонки: {missing_columns}, пересоздаем таблицу")
                
                # Сохраняем существующие данные
                cursor.execute("SELECT user_id, free_generations_used, total_free_generations FROM user_limits")
                existing_data = cursor.fetchall()
                
                # Удаляем старую таблицу
                cursor.execute("DROP TABLE user_limits")
                
                # Создаем новую таблицу
                cursor.execute('''
                    CREATE TABLE user_limits (
                        user_id INTEGER PRIMARY KEY,
                        free_generations_used INTEGER DEFAULT 0,
                        total_free_generations INTEGER DEFAULT 3,
                        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users (user_id)
                    )
                ''')
                
                # Восстанавливаем данные
                for user_id, free_used, total_free in existing_data:
                    cursor.execute('''
                        INSERT INTO user_limits (user_id, free_generations_used, total_free_generations)
                        VALUES (?, ?, ?)
                    ''', (user_id, free_used or 0, total_free or 3))
                
                logging.info("Таблица user_limits пересоздана с сохранением данных")
                return
            
            # Если все колонки есть, просто добавляем недостающие
            if 'free_generations_used' not in columns:
                cursor.execute("ALTER TABLE user_limits ADD COLUMN free_generations_used INTEGER DEFAULT 0")
                logging.info("Добавлена колонка free_generations_used в таблицу user_limits")
            
            if 'total_free_generations' not in columns:
                cursor.execute("ALTER TABLE user_limits ADD COLUMN total_free_generations INTEGER DEFAULT 3")
                logging.info("Добавлена колонка total_free_generations в таблицу user_limits")
                
            if 'last_updated' not in columns:
                cursor.execute("ALTER TABLE user_limits ADD COLUMN last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
                logging.info("Добавлена колонка last_updated в таблицу user_limits")
                
        except Exception as e:
            logging.error(f"Ошибка миграции таблицы user_limits: {e}")
            # В случае ошибки пытаемся создать таблицу заново
            try:
                cursor.execute("DROP TABLE IF EXISTS user_limits")
                cursor.execute('''
                    CREATE TABLE user_limits (
                        user_id INTEGER PRIMARY KEY,
                        free_generations_used INTEGER DEFAULT 0,
                        total_free_generations INTEGER DEFAULT 3,
                        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users (user_id)
                    )
                ''')
                logging.info("Таблица user_limits создана заново после ошибки")
            except Exception as recreate_error:
                logging.error(f"Критическая ошибка при создании таблицы user_limits: {recreate_error}")
    
    def add_user(self, user_id: int, username: str = None, first_name: str = None, last_name: str = None):
        """Добавление нового пользователя"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR IGNORE INTO users (user_id, username, first_name, last_name)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, username, first_name, last_name))
                conn.commit()
        except Exception as e:
            logging.error(f"Ошибка добавления пользователя: {e}")
    
    def update_user_activity(self, user_id: int):
        """Обновление времени последней активности пользователя"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE users SET last_activity = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                ''', (user_id,))
                conn.commit()
        except Exception as e:
            logging.error(f"Ошибка обновления активности пользователя: {e}")
    
    def log_generation(self, user_id: int, model_name: str, format_type: str, 
                      prompt: str, image_count: int, success: bool, 
                      error_message: str = None, generation_time: float = None):
        """Логирование генерации изображения"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Добавляем запись о генерации
                cursor.execute('''
                    INSERT INTO generations (user_id, model_name, format_type, prompt, 
                                           image_count, success, error_message, generation_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, model_name, format_type, prompt, image_count, success, error_message, generation_time))
                
                # Обновляем счетчики пользователя
                if success:
                    cursor.execute('''
                        UPDATE users SET total_generations = total_generations + 1
                        WHERE user_id = ?
                    ''', (user_id,))
                else:
                    cursor.execute('''
                        UPDATE users SET total_errors = total_errors + 1
                        WHERE user_id = ?
                    ''', (user_id,))
                
                conn.commit()
        except Exception as e:
            logging.error(f"Ошибка логирования генерации: {e}")
    
    def log_error(self, user_id: int, error_type: str, error_message: str, stack_trace: str = None):
        """Логирование ошибки"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO errors (user_id, error_type, error_message, stack_trace)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, error_type, error_message, stack_trace))
                conn.commit()
        except Exception as e:
            logging.error(f"Ошибка логирования ошибки: {e}")
    
    def log_action(self, user_id: int, action_type: str, action_data: str = None):
        """Логирование действия пользователя"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO user_actions (user_id, action_type, action_data)
                    VALUES (?, ?, ?)
                ''', (user_id, action_type, action_data))
                conn.commit()
        except Exception as e:
            logging.error(f"Ошибка логирования действия: {e}")
    
    def get_user_stats(self, user_id: int) -> Dict:
        """Получение статистики пользователя"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Основная статистика пользователя
                cursor.execute('''
                    SELECT total_generations, total_errors, first_seen, last_activity
                    FROM users WHERE user_id = ?
                ''', (user_id,))
                user_data = cursor.fetchone()
                
                if not user_data:
                    return {}
                
                # Статистика по моделям
                cursor.execute('''
                    SELECT model_name, COUNT(*) as count, 
                           AVG(generation_time) as avg_time,
                           SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful
                    FROM generations 
                    WHERE user_id = ? 
                    GROUP BY model_name
                    ORDER BY count DESC
                ''', (user_id,))
                models_stats = cursor.fetchall()
                
                # Статистика по форматам
                cursor.execute('''
                    SELECT format_type, COUNT(*) as count
                    FROM generations 
                    WHERE user_id = ? 
                    GROUP BY format_type
                    ORDER BY count DESC
                ''', (user_id,))
                formats_stats = cursor.fetchall()
                
                return {
                    'total_generations': user_data[0],
                    'total_errors': user_data[1],
                    'first_seen': user_data[2],
                    'last_activity': user_data[3],
                    'models_stats': models_stats,
                    'formats_stats': formats_stats
                }
        except Exception as e:
            logging.error(f"Ошибка получения статистики пользователя: {e}")
            return {}
    
    def get_global_stats(self, days: int = 30) -> Dict:
        """Получение глобальной статистики"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Общая статистика
                cursor.execute('''
                    SELECT COUNT(DISTINCT user_id) as total_users,
                           SUM(total_generations) as total_generations,
                           SUM(total_errors) as total_errors
                    FROM users
                ''')
                global_data = cursor.fetchone()
                
                # Статистика за последние N дней
                date_limit = datetime.now() - timedelta(days=days)
                cursor.execute('''
                    SELECT COUNT(DISTINCT user_id) as active_users,
                           COUNT(*) as generations_count,
                           AVG(generation_time) as avg_generation_time
                    FROM generations 
                    WHERE timestamp >= ?
                ''', (date_limit,))
                recent_data = cursor.fetchone()
                
                # Популярные модели
                cursor.execute('''
                    SELECT model_name, COUNT(*) as count
                    FROM generations 
                    WHERE timestamp >= ? AND success = 1
                    GROUP BY model_name
                    ORDER BY count DESC
                    LIMIT 5
                ''', (date_limit,))
                popular_models = cursor.fetchall()
                
                # Популярные форматы
                cursor.execute('''
                    SELECT format_type, COUNT(*) as count
                    FROM generations 
                    WHERE timestamp >= ? AND success = 1
                    GROUP BY format_type
                    ORDER BY count DESC
                    LIMIT 5
                ''', (date_limit,))
                popular_formats = cursor.fetchall()
                
                return {
                    'total_users': global_data[0] or 0,
                    'total_generations': global_data[1] or 0,
                    'total_errors': global_data[2] or 0,
                    'active_users_30d': recent_data[0] or 0,
                    'generations_30d': recent_data[1] or 0,
                    'avg_generation_time': recent_data[2] or 0,
                    'popular_models': popular_models,
                    'popular_formats': popular_formats
                }
        except Exception as e:
            logging.error(f"Ошибка получения глобальной статистики: {e}")
            return {}
    
    def get_daily_stats(self, days: int = 7) -> List[Tuple]:
        """Получение ежедневной статистики"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT DATE(timestamp) as date,
                           COUNT(*) as generations,
                           COUNT(DISTINCT user_id) as users,
                           AVG(generation_time) as avg_time
                    FROM generations 
                    WHERE timestamp >= DATE('now', '-{} days')
                    GROUP BY DATE(timestamp)
                    ORDER BY date DESC
                '''.format(days))
                return cursor.fetchall()
        except Exception as e:
            logging.error(f"Ошибка получения ежедневной статистики: {e}")
            return []

    # НОВЫЕ МЕТОДЫ ДЛЯ ПЛАТЕЖНОЙ СИСТЕМЫ
    
    def get_user_subscription(self, user_id: int) -> Optional[Dict]:
        """Получение активной подписки пользователя"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, plan_type, status, start_date, end_date, 
                           monthly_generations, used_generations
                    FROM subscriptions 
                    WHERE user_id = ? AND status = 'active' AND end_date > CURRENT_TIMESTAMP
                    ORDER BY created_at DESC
                    LIMIT 1
                ''', (user_id,))
                result = cursor.fetchone()
                
                if result:
                    return {
                        'id': result[0],
                        'plan_type': result[1],
                        'status': result[2],
                        'start_date': result[3],
                        'end_date': result[4],
                        'monthly_generations': result[5],
                        'used_generations': result[6]
                    }
                return None
        except Exception as e:
            logging.error(f"Ошибка получения подписки пользователя: {e}")
            return None
    
    def get_user_limits(self, user_id: int) -> Dict:
        """Получение лимитов пользователя"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT free_generations_used, total_free_generations, last_updated
                    FROM user_limits 
                    WHERE user_id = ?
                ''', (user_id,))
                result = cursor.fetchone()
                
                if result:
                    return {
                        'free_generations_used': result[0],
                        'total_free_generations': result[1],
                        'last_updated': result[2]
                    }
                else:
                    # Создаем запись по умолчанию
                    self.init_user_limits(user_id)
                    return {
                        'free_generations_used': 0,
                        'total_free_generations': 3,
                        'last_updated': datetime.now().isoformat()
                    }
        except Exception as e:
            logging.error(f"Ошибка получения лимитов пользователя: {e}")
            return {}
    
    def init_user_limits(self, user_id: int):
        """Инициализация лимитов пользователя"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR IGNORE INTO user_limits 
                    (user_id, free_generations_used, total_free_generations, last_updated)
                    VALUES (?, 0, 3, CURRENT_TIMESTAMP)
                ''', (user_id,))
                conn.commit()
        except Exception as e:
            logging.error(f"Ошибка инициализации лимитов пользователя: {e}")
    
    def check_generation_limit(self, user_id: int) -> bool:
        """Проверка лимита генераций для пользователя"""
        try:
            limits = self.get_user_limits(user_id)
            if not limits:
                return False
            
            # Проверяем, есть ли еще бесплатные генерации
            if limits['free_generations_used'] < limits['total_free_generations']:
                return True
            
            # Проверяем, есть ли кредиты
            credits = self.get_user_credits(user_id)
            if credits['balance'] > 0:
                return True
            
            # Нет ни бесплатных генераций, ни кредитов
            return False
            
        except Exception as e:
            logging.error(f"Ошибка проверки лимита генераций: {e}")
            return False
    
    def increment_generation_count(self, user_id: int):
        """Увеличение счетчика генераций пользователя"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Сначала пытаемся использовать бесплатные генерации
                cursor.execute('''
                    UPDATE user_limits 
                    SET free_generations_used = free_generations_used + 1
                    WHERE user_id = ? AND free_generations_used < total_free_generations
                ''', (user_id,))
                
                if cursor.rowcount == 0:
                    # Бесплатные генерации закончились, используем кредиты
                    cursor.execute('''
                        UPDATE user_credits 
                        SET credits_balance = credits_balance - 1, total_used = total_used + 1
                        WHERE user_id = ? AND credits_balance > 0
                    ''', (user_id,))
                    
                    if cursor.rowcount > 0:
                        # Логируем использование кредита
                        cursor.execute('''
                            INSERT INTO credit_transactions 
                            (user_id, transaction_type, amount, description)
                            VALUES (?, 'usage', 1, 'Генерация изображения')
                        ''', (user_id,))
                
                conn.commit()
        except Exception as e:
            logging.error(f"Ошибка увеличения счетчика генераций: {e}")
    
    def get_free_generations_left(self, user_id: int) -> int:
        """Получение количества оставшихся бесплатных генераций"""
        try:
            limits = self.get_user_limits(user_id)
            if not limits:
                return 0
            
            return max(0, limits['total_free_generations'] - limits['free_generations_used'])
        except Exception as e:
            logging.error(f"Ошибка получения бесплатных генераций: {e}")
            return 0
    
    def increment_free_generations(self, user_id: int):
        """Увеличивает счетчик использованных бесплатных генераций"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE user_limits 
                    SET free_generations_used = free_generations_used + 1
                    WHERE user_id = ?
                ''', (user_id,))
                conn.commit()
                return True
        except Exception as e:
            logging.error(f"Ошибка увеличения счетчика бесплатных генераций: {e}")
            return False
    
    def reset_daily_limit(self, user_id: int):
        """Сброс дневного лимита"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE user_limits 
                    SET used_daily = 0, last_daily_reset = CURRENT_DATE
                    WHERE user_id = ?
                ''', (user_id,))
                conn.commit()
        except Exception as e:
            logging.error(f"Ошибка сброса дневного лимита: {e}")
    
    def reset_monthly_limit(self, user_id: int):
        """Сброс месячного лимита"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE user_limits 
                    SET used_monthly = 0, last_monthly_reset = CURRENT_DATE
                    WHERE user_id = ?
                ''', (user_id,))
                conn.commit()
        except Exception as e:
            logging.error(f"Ошибка сброса месячного лимита: {e}")
    
    def create_subscription(self, user_id: int, plan_type: str, monthly_generations: int, 
                           payment_id: str = None) -> bool:
        """Создание новой подписки"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Деактивируем старые подписки
                cursor.execute('''
                    UPDATE subscriptions 
                    SET status = 'expired' 
                    WHERE user_id = ? AND status = 'active'
                ''', (user_id,))
                
                # Создаем новую подписку
                end_date = datetime.now() + timedelta(days=30)
                cursor.execute('''
                    INSERT INTO subscriptions 
                    (user_id, plan_type, status, start_date, end_date, monthly_generations, payment_id)
                    VALUES (?, ?, 'active', CURRENT_TIMESTAMP, ?, ?, ?)
                ''', (user_id, plan_type, end_date, monthly_generations, payment_id))
                
                # Обновляем лимиты пользователя
                cursor.execute('''
                    UPDATE user_limits 
                    SET monthly_generations = ?, is_premium = TRUE
                    WHERE user_id = ?
                ''', (user_id,))
                
                conn.commit()
                return True
        except Exception as e:
            logging.error(f"Ошибка создания подписки: {e}")
            return False
    
    def get_user_credits(self, user_id: int) -> Dict:
        """Получение баланса кредитов пользователя"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT credits_balance, total_purchased, total_used
                    FROM user_credits 
                    WHERE user_id = ?
                ''', (user_id,))
                result = cursor.fetchone()
                
                if result:
                    return {
                        'balance': result[0],
                        'total_purchased': result[1],
                        'total_used': result[2]
                    }
                else:
                    # Создаем запись по умолчанию
                    self.init_user_credits(user_id)
                    return {'balance': 0, 'total_purchased': 0, 'total_used': 0}
        except Exception as e:
            logging.error(f"Ошибка получения кредитов пользователя: {e}")
            return {'balance': 0, 'total_purchased': 0, 'total_used': 0}
    
    def init_user_credits(self, user_id: int):
        """Инициализация кредитов пользователя"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR IGNORE INTO user_credits 
                    (user_id, credits_balance, total_purchased, total_used)
                    VALUES (?, 0, 0, 0)
                ''', (user_id,))
                conn.commit()
        except Exception as e:
            logging.error(f"Ошибка инициализации кредитов пользователя: {e}")
    
    def add_credits(self, user_id: int, amount: int, payment_id: int = None, 
                    description: str = "Покупка кредитов"):
        """Добавление кредитов пользователю"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Добавляем кредиты
                cursor.execute('''
                    UPDATE user_credits 
                    SET credits_balance = credits_balance + ?, total_purchased = total_purchased + ?
                    WHERE user_id = ?
                ''', (amount, amount, user_id))
                
                # Логируем транзакцию
                cursor.execute('''
                    INSERT INTO credit_transactions 
                    (user_id, transaction_type, amount, description, payment_id)
                    VALUES (?, 'purchase', ?, ?, ?)
                ''', (user_id, amount, description, payment_id))
                
                conn.commit()
                return True
        except Exception as e:
            logging.error(f"Ошибка добавления кредитов: {e}")
            return False
    
    def use_credits(self, user_id: int, amount: int, description: str = "Использование кредитов"):
        """Использование кредитов пользователем"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Проверяем баланс
                cursor.execute('SELECT credits_balance FROM user_credits WHERE user_id = ?', (user_id,))
                result = cursor.fetchone()
                
                if not result or result[0] < amount:
                    return False
                
                # Списываем кредиты
                cursor.execute('''
                    UPDATE user_credits 
                    SET credits_balance = credits_balance - ?, total_used = total_used + ?
                    WHERE user_id = ?
                ''', (amount, amount, user_id))
                
                # Логируем транзакцию
                cursor.execute('''
                    INSERT INTO credit_transactions 
                    (user_id, transaction_type, amount, description)
                    VALUES (?, 'usage', ?, ?)
                ''', (user_id, amount, description))
                
                conn.commit()
                return True
        except Exception as e:
            logging.error(f"Ошибка использования кредитов: {e}")
            return False

    def create_payment(self, user_id: int, amount: float, currency: str = "UAH", 
                      payment_id: str = None, order_id: str = None, 
                      credit_amount: int = None) -> bool:
        """
        Создает запись о платеже в базе данных
        
        Args:
            user_id: ID пользователя
            amount: Сумма платежа
            currency: Валюта
            payment_id: ID платежа в Betatransfer
            order_id: Уникальный ID заказа
            credit_amount: Количество кредитов
            
        Returns:
            True если создание успешно, False иначе
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO payments 
                    (user_id, amount, currency, status, betatransfer_id, order_id, credit_amount, created_at)
                    VALUES (?, ?, ?, 'pending', ?, ?, ?, CURRENT_TIMESTAMP)
                """, (user_id, amount, currency, payment_id, order_id or '', credit_amount or 0))
                
                conn.commit()
                return True
                
        except Exception as e:
            logging.error(f"Ошибка создания платежа: {e}")
            return False

    def get_payment_by_order_id(self, order_id: str) -> Optional[Dict]:
        """
        Получает информацию о платеже по order_id
        
        Args:
            order_id: Уникальный ID заказа
            
        Returns:
            Dict с информацией о платеже или None
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM payments 
                    WHERE order_id = ?
                """, (order_id,))
                
                row = cursor.fetchone()
                if row:
                    columns = [description[0] for description in cursor.description]
                    return dict(zip(columns, row))
                return None
            
        except Exception as e:
            logging.error(f"Ошибка получения платежа по order_id: {e}")
            return None

    def update_payment_status(self, payment_id: str, status: str) -> bool:
        """
        Обновляет статус платежа
        
        Args:
            payment_id: ID платежа в Betatransfer
            status: Новый статус
            
        Returns:
            True если обновление успешно, False иначе
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE payments 
                    SET status = ?, completed_at = CURRENT_TIMESTAMP
                    WHERE betatransfer_id = ?
                """, (status, payment_id))
                
                conn.commit()
                return cursor.rowcount > 0
            
        except Exception as e:
            logging.error(f"Ошибка обновления статуса платежа: {e}")
            return False

    def get_total_credits_statistics(self) -> Dict:
        """
        Получает общую статистику по кредитам всех пользователей
        
        Returns:
            Dict с общей статистикой:
            - total_purchased: общее количество купленных кредитов
            - total_used: общее количество использованных кредитов
            - total_balance: общий баланс кредитов
            - total_users: количество пользователей с кредитами
            - total_payments: общее количество платежей
            - total_revenue: общая выручка
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Общая статистика по кредитам
                cursor.execute("""
                    SELECT 
                        SUM(total_purchased) as total_purchased,
                        SUM(total_used) as total_used,
                        SUM(credits_balance) as total_balance,
                        COUNT(*) as total_users
                    FROM user_credits
                """)
                
                credits_stats = cursor.fetchone()
                
                # Статистика по платежам
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_payments,
                        SUM(amount) as total_revenue,
                        COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_payments,
                        SUM(CASE WHEN status = 'completed' THEN amount ELSE 0 END) as completed_revenue
                    FROM payments
                """)
                
                payment_stats = cursor.fetchone()
                
                # Статистика по транзакциям
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_transactions,
                        SUM(CASE WHEN transaction_type = 'purchase' THEN amount ELSE 0 END) as total_purchased_transactions,
                        SUM(CASE WHEN transaction_type = 'usage' THEN amount ELSE 0 END) as total_used_transactions
                    FROM credit_transactions
                """)
                
                transaction_stats = cursor.fetchone()
                
                return {
                    'total_purchased': credits_stats[0] or 0,
                    'total_used': credits_stats[1] or 0,
                    'total_balance': credits_stats[2] or 0,
                    'total_users': credits_stats[3] or 0,
                    'total_payments': payment_stats[0] or 0,
                    'total_revenue': payment_stats[1] or 0,
                    'completed_payments': payment_stats[2] or 0,
                    'completed_revenue': payment_stats[3] or 0,
                    'total_transactions': transaction_stats[0] or 0,
                    'total_purchased_transactions': transaction_stats[1] or 0,
                    'total_used_transactions': transaction_stats[2] or 0
                }
                
        except Exception as e:
            logging.error(f"Ошибка получения общей статистики кредитов: {e}")
            return {
                'total_purchased': 0,
                'total_used': 0,
                'total_balance': 0,
                'total_users': 0,
                'total_payments': 0,
                'total_revenue': 0,
                'completed_payments': 0,
                'completed_revenue': 0,
                'total_transactions': 0,
                'total_purchased_transactions': 0,
                'total_used_transactions': 0
            }

    def get_user_credits_list(self) -> List[Dict]:
        """
        Получает список всех пользователей с их кредитами
        
        Returns:
            List[Dict] с информацией о пользователях и их кредитах
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT 
                        uc.user_id,
                        u.username,
                        u.first_name,
                        u.last_name,
                        uc.credits_balance,
                        uc.total_purchased,
                        uc.total_used,
                        uc.last_updated
                    FROM user_credits uc
                    LEFT JOIN users u ON uc.user_id = u.user_id
                    ORDER BY uc.total_purchased DESC
                """)
                
                rows = cursor.fetchall()
                columns = [description[0] for description in cursor.description]
                
                return [dict(zip(columns, row)) for row in rows]
                
        except Exception as e:
            logging.error(f"Ошибка получения списка пользователей с кредитами: {e}")
            return []

    def get_payment_history(self, limit: int = 100) -> List[Dict]:
        """
        Получает историю платежей
        
        Args:
            limit: Максимальное количество записей
            
        Returns:
            List[Dict] с историей платежей
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT 
                        p.*,
                        u.username,
                        u.first_name,
                        u.last_name
                    FROM payments p
                    LEFT JOIN users u ON p.user_id = u.user_id
                    ORDER BY p.created_at DESC
                    LIMIT ?
                """, (limit,))
                
                rows = cursor.fetchall()
                columns = [description[0] for description in cursor.description]
                
                return [dict(zip(columns, row)) for row in rows]
                
        except Exception as e:
            logging.error(f"Ошибка получения истории платежей: {e}")
            return []

    def create_payment_with_credits(self, user_id: int, amount: float, currency: str = "UAH", 
                                   payment_id: str = None, order_id: str = None, 
                                   credit_amount: int = None) -> bool:
        """
        Создает запись о платеже с указанием количества кредитов
        
        Args:
            user_id: ID пользователя
            amount: Сумма платежа
            currency: Валюта
            payment_id: ID платежа в Betatransfer
            order_id: Уникальный ID заказа
            credit_amount: Количество кредитов
            
        Returns:
            True если создание успешно, False иначе
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO payments 
                    (user_id, amount, currency, status, betatransfer_id, order_id, credit_amount, created_at)
                    VALUES (?, ?, ?, 'pending', ?, ?, ?, CURRENT_TIMESTAMP)
                """, (user_id, amount, currency, payment_id, order_id or '', credit_amount or 0))
                
                conn.commit()
                return True
                
        except Exception as e:
            logging.error(f"Ошибка создания платежа с кредитами: {e}")
            return False

# Глобальный экземпляр базы данных
analytics_db = AnalyticsDB()


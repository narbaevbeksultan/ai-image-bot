import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import sql
import sqlite3

class AnalyticsDB:
    def __init__(self, db_url: str = None):
        """
        Инициализация базы данных PostgreSQL
        
        Args:
            db_url: URL подключения к PostgreSQL (DATABASE_URL из переменных окружения)
        """
        self.db_url = db_url or os.getenv('DATABASE_URL')
        if not self.db_url:
            # Fallback на SQLite для локальной разработки
            self.db_url = "sqlite:///bot_analytics.db"
            self.db_type = "sqlite"
        else:
            self.db_type = "postgresql"
        
        self.init_database()
    
    def get_connection(self):
        """Получение подключения к базе данных"""
        if self.db_type == "sqlite":
            return sqlite3.connect("bot_analytics.db")
        else:
            return psycopg2.connect(self.db_url)
    
    def init_database(self):
        """Инициализация базы данных и создание таблиц"""
        try:
            if self.db_type == "sqlite":
                self._init_sqlite()
            else:
                self._init_postgresql()
            logging.info("База данных успешно инициализирована")
        except Exception as e:
            logging.error(f"Ошибка инициализации базы данных: {e}")
    
    def _init_sqlite(self):
        """Инициализация SQLite базы данных"""
        with sqlite3.connect("bot_analytics.db") as conn:
            cursor = conn.cursor()
            self._create_tables_sqlite(cursor)
            conn.commit()
    
    def _init_postgresql(self):
        """Инициализация PostgreSQL базы данных"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            self._create_tables_postgresql(cursor)
            conn.commit()
    
    def _create_tables_sqlite(self, cursor):
        """Создание таблиц для SQLite"""
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
        
        # Таблица платежей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount DECIMAL(10,2) NOT NULL,
                currency TEXT DEFAULT 'UAH',
                status TEXT NOT NULL DEFAULT 'pending',
                betatransfer_id TEXT,
                order_id TEXT,
                credit_amount INTEGER,
                payment_method TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица лимитов пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_limits (
                user_id INTEGER PRIMARY KEY,
                free_generations_used INTEGER DEFAULT 0,
                total_free_generations INTEGER DEFAULT 3,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица кредитов
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
                transaction_type TEXT NOT NULL,
                amount INTEGER NOT NULL,
                description TEXT,
                payment_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id),
                FOREIGN KEY (payment_id) REFERENCES payments (id)
            )
        ''')
    
    def _create_tables_postgresql(self, cursor):
        """Создание таблиц для PostgreSQL"""
        # Таблица пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username VARCHAR(255),
                first_name VARCHAR(255),
                last_name VARCHAR(255),
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
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                model_name VARCHAR(255),
                format_type VARCHAR(255),
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
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                error_type VARCHAR(255),
                error_message TEXT,
                stack_trace TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица действий пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_actions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                action_type VARCHAR(255),
                action_data TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица платежей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                amount DECIMAL(10,2) NOT NULL,
                currency VARCHAR(10) DEFAULT 'UAH',
                status VARCHAR(50) NOT NULL DEFAULT 'pending',
                betatransfer_id VARCHAR(255),
                order_id VARCHAR(255),
                credit_amount INTEGER,
                payment_method VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица лимитов пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_limits (
                user_id BIGINT PRIMARY KEY,
                free_generations_used INTEGER DEFAULT 0,
                total_free_generations INTEGER DEFAULT 3,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица кредитов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_credits (
                user_id BIGINT PRIMARY KEY,
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
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                transaction_type VARCHAR(50) NOT NULL,
                amount INTEGER NOT NULL,
                description TEXT,
                payment_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id),
                FOREIGN KEY (payment_id) REFERENCES payments (id)
            )
        ''')
    
    def execute_query(self, query, params=None, fetch_one=False, fetch_all=False):
        """Универсальный метод выполнения запросов"""
        try:
            with self.get_connection() as conn:
                if self.db_type == "sqlite":
                    cursor = conn.cursor()
                    cursor.execute(query, params or ())
                else:
                    cursor = conn.cursor(cursor_factory=RealDictCursor)
                    cursor.execute(query, params or ())
                
                if fetch_one:
                    result = cursor.fetchone()
                    if self.db_type == "postgresql" and result:
                        return dict(result)
                    return result
                elif fetch_all:
                    result = cursor.fetchall()
                    if self.db_type == "postgresql" and result:
                        return [dict(row) for row in result]
                    return result
                else:
                    conn.commit()
                    return True
        except Exception as e:
            logging.error(f"Ошибка выполнения запроса: {e}")
            return None
    
    # Методы для работы с пользователями
    def add_user(self, user_id: int, username: str = None, first_name: str = None, last_name: str = None):
        """Добавление нового пользователя"""
        query = '''
            INSERT INTO users (user_id, username, first_name, last_name)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id) DO NOTHING
        ''' if self.db_type == "postgresql" else '''
            INSERT OR IGNORE INTO users (user_id, username, first_name, last_name)
            VALUES (?, ?, ?, ?)
        '''
        return self.execute_query(query, (user_id, username, first_name, last_name))
    
    def update_user_activity(self, user_id: int):
        """Обновление времени последней активности пользователя"""
        query = '''
            UPDATE users SET last_activity = CURRENT_TIMESTAMP
            WHERE user_id = %s
        ''' if self.db_type == "postgresql" else '''
            UPDATE users SET last_activity = CURRENT_TIMESTAMP
            WHERE user_id = ?
        '''
        return self.execute_query(query, (user_id,))
    
    def log_generation(self, user_id: int, model_name: str, format_type: str, 
                      prompt: str, image_count: int, success: bool, 
                      error_message: str = None, generation_time: float = None):
        """Логирование генерации изображения"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Добавляем запись о генерации
                if self.db_type == "postgresql":
                    cursor.execute('''
                        INSERT INTO generations (user_id, model_name, format_type, prompt, 
                                               image_count, success, error_message, generation_time)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (user_id, model_name, format_type, prompt, image_count, success, error_message, generation_time))
                else:
                    cursor.execute('''
                        INSERT INTO generations (user_id, model_name, format_type, prompt, 
                                               image_count, success, error_message, generation_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (user_id, model_name, format_type, prompt, image_count, success, error_message, generation_time))
                
                # Обновляем счетчики пользователя
                if success:
                    if self.db_type == "postgresql":
                        cursor.execute('''
                            UPDATE users SET total_generations = total_generations + 1
                            WHERE user_id = %s
                        ''', (user_id,))
                    else:
                        cursor.execute('''
                            UPDATE users SET total_generations = total_generations + 1
                            WHERE user_id = ?
                        ''', (user_id,))
                else:
                    if self.db_type == "postgresql":
                        cursor.execute('''
                            UPDATE users SET total_errors = total_errors + 1
                            WHERE user_id = %s
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
        query = '''
            INSERT INTO errors (user_id, error_type, error_message, stack_trace)
            VALUES (%s, %s, %s, %s)
        ''' if self.db_type == "postgresql" else '''
            INSERT INTO errors (user_id, error_type, error_message, stack_trace)
            VALUES (?, ?, ?, ?)
        '''
        return self.execute_query(query, (user_id, error_type, error_message, stack_trace))
    
    def log_action(self, user_id: int, action_type: str, action_data: str = None):
        """Логирование действия пользователя"""
        query = '''
            INSERT INTO user_actions (user_id, action_type, action_data)
            VALUES (%s, %s, %s)
        ''' if self.db_type == "postgresql" else '''
            INSERT INTO user_actions (user_id, action_type, action_data)
            VALUES (?, ?, ?)
        '''
        return self.execute_query(query, (user_id, action_type, action_data))
    
    # Методы для работы с лимитами
    def get_user_limits(self, user_id: int) -> Dict:
        """Получение лимитов пользователя"""
        query = '''
            SELECT free_generations_used, total_free_generations, last_updated
            FROM user_limits 
            WHERE user_id = %s
        ''' if self.db_type == "postgresql" else '''
            SELECT free_generations_used, total_free_generations, last_updated
            FROM user_limits 
            WHERE user_id = ?
        '''
        result = self.execute_query(query, (user_id,), fetch_one=True)
        
        if result:
            if self.db_type == "postgresql":
                return {
                    'free_generations_used': result['free_generations_used'],
                    'total_free_generations': result['total_free_generations'],
                    'last_updated': result['last_updated']
                }
            else:
                return {
                    'free_generations_used': result[0],
                    'total_free_generations': result[1],
                    'last_updated': result[2]
                }
        else:
            return {
                'free_generations_used': 0,
                'total_free_generations': 3,
                'last_updated': datetime.now().isoformat()
            }
    
    def init_user_limits(self, user_id: int):
        """Инициализация лимитов пользователя"""
        query = '''
            INSERT INTO user_limits 
            (user_id, free_generations_used, total_free_generations, last_updated)
            VALUES (%s, 0, 3, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id) DO NOTHING
        ''' if self.db_type == "postgresql" else '''
            INSERT OR IGNORE INTO user_limits 
            (user_id, free_generations_used, total_free_generations, last_updated)
            VALUES (?, 0, 3, CURRENT_TIMESTAMP)
        '''
        return self.execute_query(query, (user_id,))
    
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
            
            return False
        except Exception as e:
            logging.error(f"Ошибка проверки лимита генераций: {e}")
            return False
    
    def increment_generation_count(self, user_id: int):
        """Увеличение счетчика генераций пользователя"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Сначала пытаемся использовать бесплатные генерации
                if self.db_type == "postgresql":
                    cursor.execute('''
                        UPDATE user_limits 
                        SET free_generations_used = free_generations_used + 1
                        WHERE user_id = %s AND free_generations_used < total_free_generations
                    ''', (user_id,))
                else:
                    cursor.execute('''
                        UPDATE user_limits 
                        SET free_generations_used = free_generations_used + 1
                        WHERE user_id = ? AND free_generations_used < total_free_generations
                    ''', (user_id,))
                
                if cursor.rowcount == 0:
                    # Бесплатные генерации закончились, используем кредиты
                    if self.db_type == "postgresql":
                        cursor.execute('''
                            UPDATE user_credits 
                            SET credits_balance = credits_balance - 1, total_used = total_used + 1
                            WHERE user_id = %s AND credits_balance > 0
                        ''', (user_id,))
                        
                        if cursor.rowcount > 0:
                            cursor.execute('''
                                INSERT INTO credit_transactions 
                                (user_id, transaction_type, amount, description)
                                VALUES (%s, 'usage', 1, 'Генерация изображения')
                            ''', (user_id,))
                    else:
                        cursor.execute('''
                            UPDATE user_credits 
                            SET credits_balance = credits_balance - 1, total_used = total_used + 1
                            WHERE user_id = ? AND credits_balance > 0
                        ''', (user_id,))
                        
                        if cursor.rowcount > 0:
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
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Сначала проверяем, есть ли еще бесплатные генерации
                if self.db_type == "postgresql":
                    cursor.execute('''
                        SELECT free_generations_used, total_free_generations
                        FROM user_limits 
                        WHERE user_id = %s
                    ''', (user_id,))
                else:
                    cursor.execute('''
                        SELECT free_generations_used, total_free_generations
                        FROM user_limits 
                        WHERE user_id = ?
                    ''', (user_id,))
                
                result = cursor.fetchone()
                
                if result:
                    used, total = result[0], result[1]
                    if used >= total:
                        # Бесплатные генерации закончились
                        return False
                else:
                    # Если записи нет, создаем новую с 1 использованной генерацией
                    if self.db_type == "postgresql":
                        cursor.execute('''
                            INSERT INTO user_limits 
                            (user_id, free_generations_used, total_free_generations, last_updated)
                            VALUES (%s, 1, 3, CURRENT_TIMESTAMP)
                        ''', (user_id,))
                    else:
                        cursor.execute('''
                            INSERT INTO user_limits 
                            (user_id, free_generations_used, total_free_generations, last_updated)
                            VALUES (?, 1, 3, CURRENT_TIMESTAMP)
                        ''', (user_id,))
                    
                    conn.commit()
                    return True
                
                # Обновляем счетчик использованных генераций
                if self.db_type == "postgresql":
                    cursor.execute('''
                        UPDATE user_limits 
                        SET free_generations_used = free_generations_used + 1
                        WHERE user_id = %s AND free_generations_used < total_free_generations
                    ''', (user_id,))
                else:
                    cursor.execute('''
                        UPDATE user_limits 
                        SET free_generations_used = free_generations_used + 1
                        WHERE user_id = ? AND free_generations_used < total_free_generations
                    ''', (user_id,))
                
                if cursor.rowcount == 0:
                    # Не удалось обновить - возможно, лимит исчерпан
                    return False
                
                conn.commit()
                return True
        except Exception as e:
            logging.error(f"Ошибка увеличения счетчика бесплатных генераций: {e}")
            return False
    
    # Методы для работы с кредитами
    def get_user_credits(self, user_id: int) -> Dict:
        """Получение баланса кредитов пользователя"""
        query = '''
            SELECT credits_balance, total_purchased, total_used
            FROM user_credits 
            WHERE user_id = %s
        ''' if self.db_type == "postgresql" else '''
            SELECT credits_balance, total_purchased, total_used
            FROM user_credits 
            WHERE user_id = ?
        '''
        result = self.execute_query(query, (user_id,), fetch_one=True)
        
        if result:
            if self.db_type == "postgresql":
                return {
                    'balance': result['credits_balance'],
                    'total_purchased': result['total_purchased'],
                    'total_used': result['total_used']
                }
            else:
                return {
                    'balance': result[0],
                    'total_purchased': result[1],
                    'total_used': result[2]
                }
        else:
            return {'balance': 0, 'total_purchased': 0, 'total_used': 0}
    
    def init_user_credits(self, user_id: int):
        """Инициализация кредитов пользователя"""
        query = '''
            INSERT INTO user_credits 
            (user_id, credits_balance, total_purchased, total_used)
            VALUES (%s, 0, 0, 0)
            ON CONFLICT (user_id) DO NOTHING
        ''' if self.db_type == "postgresql" else '''
            INSERT OR IGNORE INTO user_credits 
            (user_id, credits_balance, total_purchased, total_used)
            VALUES (?, 0, 0, 0)
        '''
        return self.execute_query(query, (user_id,))
    
    def add_credits(self, user_id: int, amount: int, payment_id: int = None, 
                    description: str = "Покупка кредитов"):
        """Добавление кредитов пользователю"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Сначала пытаемся обновить существующую запись
                if self.db_type == "postgresql":
                    cursor.execute('''
                        UPDATE user_credits 
                        SET credits_balance = credits_balance + %s, total_purchased = total_purchased + %s
                        WHERE user_id = %s
                    ''', (amount, amount, user_id))
                    
                    if cursor.rowcount == 0:
                        cursor.execute('''
                            INSERT INTO user_credits 
                            (user_id, credits_balance, total_purchased, total_used)
                            VALUES (%s, %s, %s, 0)
                        ''', (user_id, amount, amount))
                    
                    # Логируем транзакцию
                    cursor.execute('''
                        INSERT INTO credit_transactions 
                        (user_id, transaction_type, amount, description, payment_id)
                        VALUES (%s, 'purchase', %s, %s, %s)
                    ''', (user_id, amount, description, payment_id))
                else:
                    cursor.execute('''
                        UPDATE user_credits 
                        SET credits_balance = credits_balance + ?, total_purchased = total_purchased + ?
                        WHERE user_id = ?
                    ''', (amount, amount, user_id))
                    
                    if cursor.rowcount == 0:
                        cursor.execute('''
                            INSERT INTO user_credits 
                            (user_id, credits_balance, total_purchased, total_used)
                            VALUES (?, ?, ?, 0)
                        ''', (user_id, amount, amount))
                    
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
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Проверяем баланс
                if self.db_type == "postgresql":
                    cursor.execute('SELECT credits_balance FROM user_credits WHERE user_id = %s', (user_id,))
                else:
                    cursor.execute('SELECT credits_balance FROM user_credits WHERE user_id = ?', (user_id,))
                
                result = cursor.fetchone()
                
                if not result:
                    # Если записи нет, создаем с нулевым балансом
                    if self.db_type == "postgresql":
                        cursor.execute('''
                            INSERT INTO user_credits 
                            (user_id, credits_balance, total_purchased, total_used)
                            VALUES (%s, 0, 0, 0)
                        ''', (user_id,))
                    else:
                        cursor.execute('''
                            INSERT INTO user_credits 
                            (user_id, credits_balance, total_purchased, total_used)
                            VALUES (?, 0, 0, 0)
                        ''', (user_id,))
                    return False
                
                if result[0] < amount:
                    return False
                
                # Списываем кредиты
                if self.db_type == "postgresql":
                    cursor.execute('''
                        UPDATE user_credits 
                        SET credits_balance = credits_balance - %s, total_used = total_used + %s
                        WHERE user_id = %s
                    ''', (amount, amount, user_id))
                    
                    # Логируем транзакцию
                    cursor.execute('''
                        INSERT INTO credit_transactions 
                        (user_id, transaction_type, amount, description)
                        VALUES (%s, 'usage', %s, %s)
                    ''', (user_id, amount, description))
                else:
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
    
    # Методы для работы с платежами
    def create_payment(self, user_id: int, amount: float, currency: str = "UAH", 
                      payment_id: str = None, order_id: str = None, 
                      credit_amount: int = None) -> bool:
        """Создание записи о платеже"""
        query = '''
            INSERT INTO payments 
            (user_id, amount, currency, status, betatransfer_id, order_id, credit_amount, created_at)
            VALUES (%s, %s, %s, 'pending', %s, %s, %s, CURRENT_TIMESTAMP)
        ''' if self.db_type == "postgresql" else '''
            INSERT INTO payments 
            (user_id, amount, currency, status, betatransfer_id, order_id, credit_amount, created_at)
            VALUES (?, ?, ?, 'pending', ?, ?, ?, CURRENT_TIMESTAMP)
        '''
        return self.execute_query(query, (user_id, amount, currency, payment_id, order_id or '', credit_amount or 0))
    
    def get_payment_by_order_id(self, order_id: str) -> Optional[Dict]:
        """Получение информации о платеже по order_id"""
        query = '''
            SELECT * FROM payments 
            WHERE order_id = %s
        ''' if self.db_type == "postgresql" else '''
            SELECT * FROM payments 
            WHERE order_id = ?
        '''
        result = self.execute_query(query, (order_id,), fetch_one=True)
        
        if result and self.db_type == "postgresql":
            return dict(result)
        elif result:
            # Для SQLite возвращаем список колонок
            columns = ['id', 'user_id', 'amount', 'currency', 'status', 'betatransfer_id', 
                      'order_id', 'credit_amount', 'payment_method', 'created_at', 'completed_at']
            return dict(zip(columns, result))
        return None
    
    def update_payment_status(self, payment_id: str, status: str) -> bool:
        """Обновление статуса платежа"""
        query = '''
            UPDATE payments 
            SET status = %s, completed_at = CURRENT_TIMESTAMP
            WHERE betatransfer_id = %s
        ''' if self.db_type == "postgresql" else '''
            UPDATE payments 
            SET status = ?, completed_at = CURRENT_TIMESTAMP
            WHERE betatransfer_id = ?
        '''
        return self.execute_query(query, (status, payment_id))
    
    # Статистические методы
    def get_user_stats(self, user_id: int) -> Dict:
        """Получение статистики пользователя"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Основная статистика пользователя
                if self.db_type == "postgresql":
                    cursor.execute('''
                        SELECT total_generations, total_errors, first_seen, last_activity
                        FROM users WHERE user_id = %s
                    ''', (user_id,))
                else:
                    cursor.execute('''
                        SELECT total_generations, total_errors, first_seen, last_activity
                        FROM users WHERE user_id = ?
                    ''', (user_id,))
                
                user_data = cursor.fetchone()
                
                if not user_data:
                    return {}
                
                # Статистика по моделям
                if self.db_type == "postgresql":
                    cursor.execute('''
                        SELECT model_name, COUNT(*) as count, 
                               AVG(generation_time) as avg_time,
                               SUM(CASE WHEN success = true THEN 1 ELSE 0 END) as successful
                        FROM generations 
                        WHERE user_id = %s 
                        GROUP BY model_name
                        ORDER BY count DESC
                    ''', (user_id,))
                else:
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
                if self.db_type == "postgresql":
                    cursor.execute('''
                        SELECT format_type, COUNT(*) as count
                        FROM generations 
                        WHERE user_id = %s 
                        GROUP BY format_type
                        ORDER BY count DESC
                    ''', (user_id,))
                else:
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
            with self.get_connection() as conn:
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
                if self.db_type == "postgresql":
                    cursor.execute('''
                        SELECT COUNT(DISTINCT user_id) as active_users,
                               COUNT(*) as generations_count,
                               AVG(generation_time) as avg_generation_time
                        FROM generations 
                        WHERE timestamp >= %s
                    ''', (date_limit,))
                else:
                    cursor.execute('''
                        SELECT COUNT(DISTINCT user_id) as active_users,
                               COUNT(*) as generations_count,
                               AVG(generation_time) as avg_generation_time
                        FROM generations 
                        WHERE timestamp >= ?
                    ''', (date_limit,))
                
                recent_data = cursor.fetchone()
                
                return {
                    'total_users': global_data[0] or 0,
                    'total_generations': global_data[1] or 0,
                    'total_errors': global_data[2] or 0,
                    'active_users_30d': recent_data[0] or 0,
                    'generations_30d': recent_data[1] or 0,
                    'avg_generation_time': recent_data[2] or 0
                }
        except Exception as e:
            logging.error(f"Ошибка получения глобальной статистики: {e}")
            return {}
    
    def get_total_credits_statistics(self) -> Dict:
        """Получение общей статистики по кредитам"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Общая статистика по кредитам
                cursor.execute('''
                    SELECT 
                        SUM(total_purchased) as total_purchased,
                        SUM(total_used) as total_used,
                        SUM(credits_balance) as total_balance,
                        COUNT(*) as total_users
                    FROM user_credits
                ''')
                
                credits_stats = cursor.fetchone()
                
                # Статистика по платежам
                cursor.execute('''
                    SELECT 
                        COUNT(*) as total_payments,
                        SUM(amount) as total_revenue,
                        COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_payments,
                        SUM(CASE WHEN status = 'completed' THEN amount ELSE 0 END) as completed_revenue
                    FROM payments
                ''')
                
                payment_stats = cursor.fetchone()
                
                return {
                    'total_purchased': credits_stats[0] or 0,
                    'total_used': credits_stats[1] or 0,
                    'total_balance': credits_stats[2] or 0,
                    'total_users': credits_stats[3] or 0,
                    'total_payments': payment_stats[0] or 0,
                    'total_revenue': payment_stats[1] or 0,
                    'completed_payments': payment_stats[2] or 0,
                    'completed_revenue': payment_stats[3] or 0
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
                'completed_revenue': 0
            }

    def get_pending_payments(self):
        """Получает все pending платежи для проверки статуса"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if self.db_type == "postgresql":
                    cursor.execute('''
                        SELECT user_id, amount, currency, status, betatransfer_id, order_id, credit_amount, created_at
                        FROM payments 
                        WHERE status = 'pending' AND betatransfer_id IS NOT NULL
                        ORDER BY created_at ASC
                    ''')
                else:
                    cursor.execute('''
                        SELECT user_id, amount, currency, status, betatransfer_id, order_id, credit_amount, created_at
                        FROM payments 
                        WHERE status = 'pending' AND betatransfer_id IS NOT NULL
                        ORDER BY created_at ASC
                    ''')
                
                columns = [description[0] for description in cursor.description]
                payments = []
                
                for row in cursor.fetchall():
                    if self.db_type == "postgresql":
                        payment = dict(zip(columns, row))
                    else:
                        payment = dict(zip(columns, row))
                    payments.append(payment)
                
                return payments
                
        except Exception as e:
            logging.error(f"Ошибка получения pending платежей: {e}")
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
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if self.db_type == "postgresql":
                    cursor.execute("""
                        INSERT INTO payments 
                        (user_id, amount, currency, status, betatransfer_id, order_id, credit_amount, created_at)
                        VALUES (%s, %s, %s, 'pending', %s, %s, %s, CURRENT_TIMESTAMP)
                    """, (user_id, amount, currency, payment_id, order_id or '', credit_amount or 0))
                else:
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

    def get_credit_transaction_by_payment_id(self, payment_id: str):
        """Проверяет, есть ли уже транзакция кредитов для данного платежа"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if self.db_type == "postgresql":
                    cursor.execute('''
                        SELECT id FROM credit_transactions 
                        WHERE payment_id = (SELECT id FROM payments WHERE betatransfer_id = %s)
                    ''', (payment_id,))
                else:
                    cursor.execute('''
                        SELECT id FROM credit_transactions 
                        WHERE payment_id = (SELECT id FROM payments WHERE betatransfer_id = ?)
                    ''', (payment_id,))
                
                result = cursor.fetchone()
                return result is not None
                
        except Exception as e:
            logging.error(f"Ошибка проверки транзакции по payment_id: {e}")
            return False

    def create_credit_transaction_with_payment(self, user_id: int, amount: int, description: str, payment_id: str):
        """Создает транзакцию кредитов с привязкой к платежу"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Получаем ID платежа по betatransfer_id
                if self.db_type == "postgresql":
                    cursor.execute('SELECT id FROM payments WHERE betatransfer_id = %s', (payment_id,))
                else:
                    cursor.execute('SELECT id FROM payments WHERE betatransfer_id = ?', (payment_id,))
                
                payment_db_id = cursor.fetchone()
                
                if payment_db_id:
                    payment_db_id = payment_db_id[0]
                else:
                    payment_db_id = None
                
                if self.db_type == "postgresql":
                    cursor.execute('''
                        INSERT INTO credit_transactions 
                        (user_id, transaction_type, amount, description, payment_id, created_at)
                        VALUES (%s, 'purchase', %s, %s, %s, CURRENT_TIMESTAMP)
                    ''', (user_id, amount, description, payment_db_id))
                else:
                    cursor.execute('''
                        INSERT INTO credit_transactions 
                        (user_id, transaction_type, amount, description, payment_id, created_at)
                        VALUES (?, 'purchase', ?, ?, ?, CURRENT_TIMESTAMP)
                    ''', (user_id, amount, description, payment_db_id))
                
                conn.commit()
                return True
                
        except Exception as e:
            logging.error(f"Ошибка создания транзакции с платежом: {e}")
            return False

    def get_payment_by_betatransfer_id(self, betatransfer_id: str) -> Optional[Dict]:
        """Получение информации о платеже по betatransfer_id"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if self.db_type == "postgresql":
                    cursor.execute('''
                        SELECT * FROM payments 
                        WHERE betatransfer_id = %s
                    ''', (betatransfer_id,))
                else:
                    cursor.execute('''
                        SELECT * FROM payments 
                        WHERE betatransfer_id = ?
                    ''', (betatransfer_id,))
                
                row = cursor.fetchone()
                if row:
                    if self.db_type == "postgresql":
                        columns = [description[0] for description in cursor.description]
                        return dict(zip(columns, row))
                    else:
                        columns = ['id', 'user_id', 'amount', 'currency', 'status', 'betatransfer_id', 
                                  'order_id', 'credit_amount', 'payment_method', 'created_at', 'completed_at']
                        return dict(zip(columns, row))
                return None
        except Exception as e:
            logging.error(f"Ошибка получения платежа по betatransfer_id: {e}")
            return None

# Глобальный экземпляр базы данных
analytics_db = AnalyticsDB()

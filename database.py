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
                
                conn.commit()
                logging.info("База данных успешно инициализирована")
                
        except Exception as e:
            logging.error(f"Ошибка инициализации базы данных: {e}")
    
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

# Глобальный экземпляр базы данных
analytics_db = AnalyticsDB()


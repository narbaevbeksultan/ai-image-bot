#!/usr/bin/env python3
"""
Скрипт для просмотра статистики бота
Использование: python view_stats.py
"""

import sqlite3
from datetime import datetime, timedelta

def view_stats():
    """Показывает статистику из базы данных"""
    try:
        with sqlite3.connect("bot_analytics.db") as conn:
            cursor = conn.cursor()
            
            print("📊 СТАТИСТИКА БОТА")
            print("=" * 50)
            
            # Общая статистика
            cursor.execute('''
                SELECT COUNT(DISTINCT user_id) as total_users,
                       SUM(total_generations) as total_generations,
                       SUM(total_errors) as total_errors
                FROM users
            ''')
            global_data = cursor.fetchone()
            
            print(f"👥 Всего пользователей: {global_data[0] or 0}")
            print(f"🎨 Всего генераций: {global_data[1] or 0}")
            print(f"❌ Всего ошибок: {global_data[2] or 0}")
            print()
            
            # Статистика за последние 7 дней
            date_limit = datetime.now() - timedelta(days=7)
            cursor.execute('''
                SELECT COUNT(DISTINCT user_id) as active_users,
                       COUNT(*) as generations_count,
                       AVG(generation_time) as avg_generation_time
                FROM generations 
                WHERE timestamp >= ?
            ''', (date_limit,))
            recent_data = cursor.fetchone()
            
            print(f"📅 За последние 7 дней:")
            print(f"   • Активных пользователей: {recent_data[0] or 0}")
            print(f"   • Генераций: {recent_data[1] or 0}")
            print(f"   • Среднее время генерации: {recent_data[2]:.1f}с" if recent_data[2] else "   • Среднее время генерации: N/A")
            print()
            
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
            
            print("🔥 Популярные модели (7 дней):")
            if popular_models:
                for model, count in popular_models:
                    print(f"   • {model}: {count}")
            else:
                print("   • Нет данных")
            print()
            
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
            
            print("📱 Популярные форматы (7 дней):")
            if popular_formats:
                for format_type, count in popular_formats:
                    print(f"   • {format_type}: {count}")
            else:
                print("   • Нет данных")
            print()
            
            # Ежедневная статистика
            cursor.execute('''
                SELECT DATE(timestamp) as date,
                       COUNT(*) as generations,
                       COUNT(DISTINCT user_id) as users,
                       AVG(generation_time) as avg_time
                FROM generations 
                WHERE timestamp >= DATE('now', '-7 days')
                GROUP BY DATE(timestamp)
                ORDER BY date DESC
            ''')
            daily_stats = cursor.fetchall()
            
            print("📊 Ежедневная статистика (7 дней):")
            if daily_stats:
                for date, generations, users, avg_time in daily_stats:
                    avg_time_str = f"{avg_time:.1f}с" if avg_time else "N/A"
                    print(f"   • {date}: {generations} генераций, {users} пользователей, {avg_time_str}")
            else:
                print("   • Нет данных")
            print()
            
            # Топ пользователей
            cursor.execute('''
                SELECT user_id, username, first_name, total_generations, total_errors
                FROM users 
                ORDER BY total_generations DESC 
                LIMIT 10
            ''')
            top_users = cursor.fetchall()
            
            print("👑 Топ пользователей по генерациям:")
            if top_users:
                for i, (user_id, username, first_name, generations, errors) in enumerate(top_users, 1):
                    name = username or first_name or f"User{user_id}"
                    print(f"   {i}. {name} (ID: {user_id}): {generations} генераций, {errors} ошибок")
            else:
                print("   • Нет данных")
            
    except Exception as e:
        print(f"❌ Ошибка при получении статистики: {e}")

if __name__ == "__main__":
    view_stats()

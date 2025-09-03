#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для просмотра статистики по кредитам в боте
Показывает общее количество купленных кредитов и детальную информацию
"""

import sys
import os
from database import AnalyticsDB

def print_credits_statistics():
    """Выводит общую статистику по кредитам"""
    print("🪙 СТАТИСТИКА КРЕДИТОВ БОТА")
    print("=" * 50)
    
    try:
        db = AnalyticsDB()
        
        # Получаем общую статистику
        stats = db.get_total_credits_statistics()
        
        print(f"📊 ОБЩАЯ СТАТИСТИКА:")
        print(f"   👥 Пользователей с кредитами: {stats['total_users']}")
        print(f"   🪙 Всего куплено кредитов: {stats['total_purchased']:,}")
        print(f"   💸 Всего использовано кредитов: {stats['total_used']:,}")
        print(f"   💰 Текущий баланс кредитов: {stats['total_balance']:,}")
        print()
        
        print(f"💰 ФИНАНСОВАЯ СТАТИСТИКА:")
        print(f"   📈 Всего платежей: {stats['total_payments']}")
        print(f"   ✅ Завершенных платежей: {stats['completed_payments']}")
        print(f"   💵 Общая выручка: ₽{stats['total_revenue']:,.2f}")
        print(f"   💵 Выручка с завершенных: ₽{stats['completed_revenue']:,.2f}")
        print()
        
        print(f"🔄 ТРАНЗАКЦИИ:")
        print(f"   📝 Всего транзакций: {stats['total_transactions']}")
        print(f"   ➕ Покупки: {stats['total_purchased_transactions']:,}")
        print(f"   ➖ Использование: {stats['total_used_transactions']:,}")
        print()
        
        # Получаем список пользователей с кредитами
        users = db.get_user_credits_list()
        
        if users:
            print(f"👥 ДЕТАЛЬНАЯ ИНФОРМАЦИЯ ПО ПОЛЬЗОВАТЕЛЯМ:")
            print("-" * 80)
            print(f"{'ID':<8} {'Username':<20} {'Имя':<20} {'Баланс':<10} {'Куплено':<10} {'Использовано':<12}")
            print("-" * 80)
            
            for user in users:
                username = user.get('username', 'N/A') or 'N/A'
                first_name = user.get('first_name', 'N/A') or 'N/A'
                balance = user.get('credits_balance', 0)
                purchased = user.get('total_purchased', 0)
                used = user.get('total_used', 0)
                
                print(f"{user['user_id']:<8} {username:<20} {first_name:<20} {balance:<10,} {purchased:<10,} {used:<12,}")
        
        # Получаем историю платежей
        payments = db.get_payment_history(limit=20)
        
        if payments:
            print()
            print(f"💳 ПОСЛЕДНИЕ ПЛАТЕЖИ:")
            print("-" * 100)
            print(f"{'ID':<8} {'Пользователь':<20} {'Сумма':<10} {'Кредиты':<10} {'Статус':<12} {'Дата':<20}")
            print("-" * 100)
            
            for payment in payments:
                username = payment.get('username', 'N/A') or 'N/A'
                amount = payment.get('amount', 0)
                credits = payment.get('credit_amount', 0)
                status = payment.get('status', 'N/A')
                created_at = payment.get('created_at', 'N/A')
                
                print(f"{payment['id']:<8} {username:<20} ₽{amount:<9,.0f} {credits:<10,} {status:<12} {created_at}")
        
        print()
        print("=" * 50)
        print("💡 ИНФОРМАЦИЯ ДЛЯ ПОПОЛНЕНИЯ REPLICATE/OPENAI:")
        print(f"   🔥 Общее количество купленных кредитов: {stats['total_purchased']:,}")
        print(f"   💰 Необходимо пополнить на сумму: ₽{stats['completed_revenue']:,.2f}")
        print()
        print("⚠️  ВАЖНО: Пополняйте Replicate и OpenAI на сумму, соответствующую")
        print("    общему количеству купленных кредитов, чтобы все пользователи")
        print("    могли использовать свои кредиты!")
        
    except Exception as e:
        print(f"❌ Ошибка получения статистики: {e}")
        return False
    
    return True

def print_user_credits(user_id: int):
    """Выводит информацию о кредитах конкретного пользователя"""
    print(f"👤 КРЕДИТЫ ПОЛЬЗОВАТЕЛЯ {user_id}")
    print("=" * 40)
    
    try:
        db = AnalyticsDB()
        
        # Получаем кредиты пользователя
        credits = db.get_user_credits(user_id)
        
        if credits:
            print(f"💰 Баланс: {credits['balance']:,} кредитов")
            print(f"🪙 Всего куплено: {credits['total_purchased']:,} кредитов")
            print(f"💸 Всего использовано: {credits['total_used']:,} кредитов")
        else:
            print("❌ Пользователь не найден или у него нет кредитов")
        
        # Получаем историю транзакций
        # (нужно добавить функцию в базу данных)
        
    except Exception as e:
        print(f"❌ Ошибка получения кредитов пользователя: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Если передан ID пользователя, показываем его кредиты
        try:
            user_id = int(sys.argv[1])
            print_user_credits(user_id)
        except ValueError:
            print("❌ Неверный ID пользователя. Используйте число.")
    else:
        # Показываем общую статистику
        print_credits_statistics()


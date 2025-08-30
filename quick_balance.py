#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Быстрая проверка баланса кредитов
Показывает только основную информацию для пополнения Replicate/OpenAI
"""

from database import AnalyticsDB

def quick_balance():
    """Быстрая проверка баланса"""
    try:
        db = AnalyticsDB()
        stats = db.get_total_credits_statistics()
        
        print("🪙 БЫСТРАЯ ПРОВЕРКА КРЕДИТОВ")
        print("=" * 40)
        print(f"🔥 Всего куплено: {stats['total_purchased']:,} кредитов")
        print(f"💸 Всего использовано: {stats['total_used']:,} кредитов")
        print(f"💰 Текущий баланс: {stats['total_balance']:,} кредитов")
        print(f"👥 Пользователей: {stats['total_users']}")
        print(f"💵 Выручка: ₽{stats['completed_revenue']:,.2f}")
        print()
        print("💡 ДЛЯ ПОПОЛНЕНИЯ REPLICATE/OPENAI:")
        print(f"   Нужно пополнить на сумму для {stats['total_purchased']:,} генераций")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    quick_balance()

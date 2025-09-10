#!/usr/bin/env python3
"""
Автоматическое резервное копирование перед деплоем
Запускайте этот скрипт перед каждым коммитом/деплоем
"""

import os
import sys
import subprocess
from backup_database import backup_database

def main():
    print("🚀 Подготовка к деплою...")
    print("=" * 50)
    
    # Проверяем, существует ли база данных
    if not os.path.exists("bot_analytics.db"):
        print("⚠️  База данных bot_analytics.db не найдена")
        print("   Это нормально, если бот еще не запускался")
        return True
    
    # Создаем резервную копию
    print("📦 Создание резервной копии базы данных...")
    success = backup_database()
    
    if success:
        print("✅ Резервная копия создана успешно!")
        print("   Теперь можно безопасно делать коммит и деплой")
        return True
    else:
        print("❌ Ошибка при создании резервной копии!")
        print("   Рекомендуется исправить проблему перед деплоем")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

#!/usr/bin/env python3
"""
Скрипт для безопасного деплоя на Railway с сохранением данных пользователей
"""

import os
import sys
import subprocess
import shutil
from datetime import datetime
from backup_database import backup_database

def check_git_status():
    """Проверяет статус Git репозитория"""
    try:
        result = subprocess.run(['git', 'status', '--porcelain'], 
                              capture_output=True, text=True, check=True)
        
        if result.stdout.strip():
            print("📝 Обнаружены незакоммиченные изменения:")
            print(result.stdout)
            return False
        else:
            print("✅ Все изменения закоммичены")
            return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка проверки Git: {e}")
        return False
    except FileNotFoundError:
        print("❌ Git не найден. Убедитесь, что Git установлен")
        return False

def create_backup():
    """Создает резервную копию базы данных"""
    print("📦 Создание резервной копии базы данных...")
    
    if not os.path.exists("bot_analytics.db"):
        print("⚠️  База данных bot_analytics.db не найдена")
        print("   Это нормально, если бот еще не запускался")
        return True
    
    success = backup_database()
    if success:
        print("✅ Резервная копия создана успешно!")
        return True
    else:
        print("❌ Ошибка при создании резервной копии!")
        return False

def commit_changes():
    """Коммитит изменения в Git"""
    try:
        # Добавляем все файлы
        subprocess.run(['git', 'add', '.'], check=True)
        
        # Создаем коммит
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        commit_message = f"Deploy: {timestamp} - Database persistence fix"
        
        subprocess.run(['git', 'commit', '-m', commit_message], check=True)
        print(f"✅ Изменения закоммичены: {commit_message}")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка при коммите: {e}")
        return False

def push_to_github():
    """Отправляет изменения в GitHub"""
    try:
        subprocess.run(['git', 'push', 'origin', 'main'], check=True)
        print("✅ Изменения отправлены в GitHub")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка при отправке в GitHub: {e}")
        return False

def check_railway_status():
    """Проверяет статус Railway (если возможно)"""
    print("🚂 Railway автоматически подхватит изменения из GitHub")
    print("   Проверьте статус деплоя в Railway Dashboard")
    return True

def main():
    """Основная функция деплоя"""
    print("🚀 Railway Deploy Script")
    print("=" * 50)
    
    # 1. Проверяем статус Git
    print("\n1️⃣ Проверка Git статуса...")
    if not check_git_status():
        print("❌ Есть незакоммиченные изменения. Сначала закоммитьте их:")
        print("   git add .")
        print("   git commit -m 'Your commit message'")
        return False
    
    # 2. Создаем резервную копию
    print("\n2️⃣ Создание резервной копии...")
    if not create_backup():
        print("⚠️  Продолжаем без резервной копии...")
    
    # 3. Коммитим изменения
    print("\n3️⃣ Коммит изменений...")
    if not commit_changes():
        return False
    
    # 4. Отправляем в GitHub
    print("\n4️⃣ Отправка в GitHub...")
    if not push_to_github():
        return False
    
    # 5. Проверяем Railway
    print("\n5️⃣ Railway деплой...")
    check_railway_status()
    
    print("\n🎉 Деплой завершен!")
    print("   Railway автоматически перезапустит бота с новым кодом")
    print("   Проверьте логи в Railway Dashboard")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

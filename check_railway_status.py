#!/usr/bin/env python3
"""
Скрипт для проверки статуса Railway деплоя
"""

import os
import sys
import subprocess
from datetime import datetime

def check_git_status():
    """Проверяет статус Git репозитория"""
    try:
        result = subprocess.run(['git', 'status', '--porcelain'], 
                              capture_output=True, text=True, check=True)
        
        if result.stdout.strip():
            print("📝 Есть незакоммиченные изменения:")
            print(result.stdout)
            return False
        else:
            print("✅ Все изменения закоммичены")
            return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка проверки Git: {e}")
        return False
    except FileNotFoundError:
        print("❌ Git не найден")
        return False

def check_last_commit():
    """Показывает последний коммит"""
    try:
        result = subprocess.run(['git', 'log', '-1', '--oneline'], 
                              capture_output=True, text=True, check=True)
        print(f"📋 Последний коммит: {result.stdout.strip()}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка получения последнего коммита: {e}")
        return False

def check_remote_status():
    """Проверяет статус удаленного репозитория"""
    try:
        result = subprocess.run(['git', 'status', '-uno'], 
                              capture_output=True, text=True, check=True)
        
        if "Your branch is up to date" in result.stdout:
            print("✅ Локальная ветка синхронизирована с GitHub")
            return True
        elif "Your branch is ahead" in result.stdout:
            print("⚠️  Локальная ветка опережает GitHub")
            print("   Запустите: git push origin main")
            return False
        else:
            print("❓ Неизвестный статус Git")
            return False
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка проверки удаленного статуса: {e}")
        return False

def check_database():
    """Проверяет наличие базы данных"""
    if os.path.exists("bot_analytics.db"):
        size = os.path.getsize("bot_analytics.db")
        size_mb = size / (1024 * 1024)
        print(f"✅ База данных найдена: {size_mb:.2f} MB")
        return True
    else:
        print("⚠️  База данных не найдена")
        return False

def check_backups():
    """Проверяет наличие резервных копий"""
    if os.path.exists("backups"):
        backup_files = [f for f in os.listdir("backups") if f.endswith(".db")]
        if backup_files:
            print(f"✅ Найдено резервных копий: {len(backup_files)}")
            return True
        else:
            print("⚠️  Папка backups пуста")
            return False
    else:
        print("⚠️  Папка backups не найдена")
        return False

def main():
    """Основная функция проверки"""
    print("🔍 Проверка статуса Railway деплоя")
    print("=" * 50)
    
    all_good = True
    
    # 1. Проверяем Git статус
    print("\n1️⃣ Git статус:")
    if not check_git_status():
        all_good = False
    
    # 2. Показываем последний коммит
    print("\n2️⃣ Последний коммит:")
    check_last_commit()
    
    # 3. Проверяем синхронизацию с GitHub
    print("\n3️⃣ Синхронизация с GitHub:")
    if not check_remote_status():
        all_good = False
    
    # 4. Проверяем базу данных
    print("\n4️⃣ База данных:")
    check_database()
    
    # 5. Проверяем резервные копии
    print("\n5️⃣ Резервные копии:")
    check_backups()
    
    # Итог
    print("\n" + "=" * 50)
    if all_good:
        print("🎉 Все готово для деплоя!")
        print("   Запустите: python railway_deploy.py")
    else:
        print("⚠️  Есть проблемы, которые нужно исправить")
        print("   Сначала закоммитьте изменения и отправьте в GitHub")
    
    return all_good

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

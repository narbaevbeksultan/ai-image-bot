#!/usr/bin/env python3
"""
Скрипт для резервного копирования базы данных бота
Используйте этот скрипт перед каждым деплоем для сохранения данных пользователей
"""

import shutil
import datetime
import os
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def backup_database(db_path="bot_analytics.db", backup_dir="backups"):
    """
    Создает резервную копию базы данных
    
    Args:
        db_path: Путь к файлу базы данных
        backup_dir: Директория для хранения резервных копий
    """
    try:
        # Проверяем, существует ли файл базы данных
        if not os.path.exists(db_path):
            logging.error(f"Файл базы данных {db_path} не найден!")
            return False
        
        # Создаем директорию для резервных копий, если её нет
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
            logging.info(f"Создана директория {backup_dir}")
        
        # Генерируем имя файла с временной меткой
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"bot_analytics_backup_{timestamp}.db"
        backup_path = os.path.join(backup_dir, backup_filename)
        
        # Копируем файл
        shutil.copy2(db_path, backup_path)
        
        # Получаем размер файла
        file_size = os.path.getsize(backup_path)
        file_size_mb = file_size / (1024 * 1024)
        
        logging.info(f"✅ База данных успешно скопирована в {backup_path}")
        logging.info(f"📊 Размер файла: {file_size_mb:.2f} MB")
        
        return True
        
    except Exception as e:
        logging.error(f"❌ Ошибка при создании резервной копии: {e}")
        return False

def restore_database(backup_path, db_path="bot_analytics.db"):
    """
    Восстанавливает базу данных из резервной копии
    
    Args:
        backup_path: Путь к файлу резервной копии
        db_path: Путь к файлу базы данных для восстановления
    """
    try:
        # Проверяем, существует ли файл резервной копии
        if not os.path.exists(backup_path):
            logging.error(f"Файл резервной копии {backup_path} не найден!")
            return False
        
        # Создаем резервную копию текущей базы данных (если она существует)
        if os.path.exists(db_path):
            current_backup = f"{db_path}.current_backup"
            shutil.copy2(db_path, current_backup)
            logging.info(f"Текущая база данных сохранена как {current_backup}")
        
        # Восстанавливаем из резервной копии
        shutil.copy2(backup_path, db_path)
        
        logging.info(f"✅ База данных успешно восстановлена из {backup_path}")
        return True
        
    except Exception as e:
        logging.error(f"❌ Ошибка при восстановлении базы данных: {e}")
        return False

def list_backups(backup_dir="backups"):
    """
    Показывает список доступных резервных копий
    
    Args:
        backup_dir: Директория с резервными копиями
    """
    try:
        if not os.path.exists(backup_dir):
            logging.info(f"Директория {backup_dir} не существует")
            return []
        
        backups = []
        for filename in os.listdir(backup_dir):
            if filename.startswith("bot_analytics_backup_") and filename.endswith(".db"):
                file_path = os.path.join(backup_dir, filename)
                file_size = os.path.getsize(file_path)
                file_size_mb = file_size / (1024 * 1024)
                file_time = os.path.getmtime(file_path)
                file_time_str = datetime.datetime.fromtimestamp(file_time).strftime("%Y-%m-%d %H:%M:%S")
                
                backups.append({
                    'filename': filename,
                    'path': file_path,
                    'size_mb': file_size_mb,
                    'created': file_time_str
                })
        
        # Сортируем по времени создания (новые сначала)
        backups.sort(key=lambda x: x['created'], reverse=True)
        
        logging.info("📋 Доступные резервные копии:")
        for backup in backups:
            logging.info(f"  📁 {backup['filename']} - {backup['size_mb']:.2f} MB - {backup['created']}")
        
        return backups
        
    except Exception as e:
        logging.error(f"❌ Ошибка при получении списка резервных копий: {e}")
        return []

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python backup_database.py backup          - Создать резервную копию")
        print("  python backup_database.py restore <file>  - Восстановить из резервной копии")
        print("  python backup_database.py list            - Показать список резервных копий")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "backup":
        success = backup_database()
        sys.exit(0 if success else 1)
    
    elif command == "restore":
        if len(sys.argv) < 3:
            print("❌ Укажите путь к файлу резервной копии")
            sys.exit(1)
        backup_file = sys.argv[2]
        success = restore_database(backup_file)
        sys.exit(0 if success else 1)
    
    elif command == "list":
        list_backups()
        sys.exit(0)
    
    else:
        print(f"❌ Неизвестная команда: {command}")
        sys.exit(1)

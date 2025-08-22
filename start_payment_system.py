#!/usr/bin/env python3
"""
Скрипт запуска платежной системы AI Image Generator Bot
"""

import os
import sys
import subprocess
import time
import signal
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

def check_environment():
    """Проверяет наличие всех необходимых переменных окружения"""
    print("🔍 Проверяем переменные окружения...")
    
    required_vars = [
        'TELEGRAM_BOT_TOKEN',
        'OPENAI_API_KEY', 
        'REPLICATE_API_TOKEN',
        'BETATRANSFER_API_KEY',
        'BETATRANSFER_SECRET_KEY',
        'WEBHOOK_BASE_URL'
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
        else:
            print(f"  ✅ {var}: {os.getenv(var)[:20]}..." if len(os.getenv(var)) > 20 else f"  ✅ {var}: {os.getenv(var)}")
    
    if missing_vars:
        print(f"\n❌ Отсутствуют переменные окружения: {', '.join(missing_vars)}")
        print("Создайте файл .env с необходимыми переменными")
        return False
    
    print("\n✅ Все переменные окружения установлены")
    return True

def start_callback_server():
    """Запускает callback сервер в фоновом режиме"""
    print("\n🚀 Запускаем callback сервер...")
    
    try:
        # Запускаем callback сервер в фоновом режиме
        process = subprocess.Popen(
            [sys.executable, "callback_server.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Ждем немного, чтобы сервер запустился
        time.sleep(3)
        
        # Проверяем, что процесс запущен
        if process.poll() is None:
            print("✅ Callback сервер запущен успешно")
            return process
        else:
            print("❌ Ошибка запуска callback сервера")
            return None
            
    except Exception as e:
        print(f"❌ Ошибка запуска callback сервера: {e}")
        return None

def start_main_bot():
    """Запускает основной бот"""
    print("\n🤖 Запускаем основной бот...")
    
    try:
        # Запускаем основной бот
        subprocess.run([sys.executable, "bot.py"])
    except KeyboardInterrupt:
        print("\n⏹️ Бот остановлен пользователем")
    except Exception as e:
        print(f"❌ Ошибка запуска бота: {e}")

def main():
    """Основная функция"""
    print("🚀 Запуск платежной системы AI Image Generator Bot")
    print("=" * 60)
    
    # Проверяем переменные окружения
    if not check_environment():
        print("\n❌ Невозможно запустить систему без необходимых переменных окружения")
        return
    
    # Проверяем наличие необходимых файлов
    required_files = [
        "bot.py",
        "callback_server.py", 
        "database.py",
        "betatransfer_api.py",
        "pricing_config.py"
    ]
    
    missing_files = []
    for file in required_files:
        if not os.path.exists(file):
            missing_files.append(file)
    
    if missing_files:
        print(f"\n❌ Отсутствуют необходимые файлы: {', '.join(missing_files)}")
        return
    
    print("\n✅ Все необходимые файлы найдены")
    
    # Запускаем callback сервер
    callback_process = start_callback_server()
    if not callback_process:
        print("❌ Невозможно запустить систему без callback сервера")
        return
    
    try:
        # Запускаем основной бот
        start_main_bot()
    finally:
        # Останавливаем callback сервер
        if callback_process:
            print("\n🛑 Останавливаем callback сервер...")
            callback_process.terminate()
            callback_process.wait()
            print("✅ Callback сервер остановлен")

if __name__ == "__main__":
    main()




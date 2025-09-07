#!/usr/bin/env python3
"""
Упрощенная версия bot_clean.py для тестирования
Без Flask и payment polling
"""

import logging
import asyncio
import concurrent.futures
from typing import Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

import openai
import os
import replicate
import requests
import aiohttp
from PIL import Image
import io
import tempfile
import time
from datetime import datetime, timedelta

from database import analytics_db

# Создаем пул потоков для блокирующих операций
THREAD_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=10)

# Создаем пул HTTP соединений для aiohttp
HTTP_SESSION = None

# Асинхронные функции для работы с API
async def init_http_session():
    """Инициализирует HTTP сессию для aiohttp"""
    global HTTP_SESSION
    if HTTP_SESSION is None:
        connector = aiohttp.TCPConnector(limit=100, limit_per_host=30)
        timeout = aiohttp.ClientTimeout(total=300)
        HTTP_SESSION = aiohttp.ClientSession(connector=connector, timeout=timeout)
    return HTTP_SESSION

async def close_http_session():
    """Закрывает HTTP сессию"""
    global HTTP_SESSION
    if HTTP_SESSION:
        await HTTP_SESSION.close()
        HTTP_SESSION = None

# Включаем логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Состояния пользователя
USER_STATE = {}

# ============================================================================
# ASYNC HANDLERS
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Логируем нового пользователя
    user = update.effective_user
    analytics_db.add_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name
    )
    analytics_db.update_user_activity(user.id)
    analytics_db.log_action(user.id, "start_command")
    
    welcome_text = """
🎨 Добро пожаловать в AI Image Generator!

Я помогу вам создавать качественные изображения и видео с помощью ИИ.

💡 Быстрый старт:
• Нажмите "🎨 Создать контент" для создания под определенный формат
• Нажмите "🖼️ Создать изображения" для быстрой генерации изображений
• Нажмите "🎬 Создать видео" для генерации видео
• Выберите формат и модель
• Опишите, что хотите создать
• Получите результат!

❓ Если что-то непонятно - нажмите "Как пользоваться"
🔄 Если бот завис - напишите /start
📊 Ваша статистика - /stats
"""
    
    keyboard = [
        [InlineKeyboardButton("🎨 Создать контент", callback_data="create_content")],
        [InlineKeyboardButton("🖼️ Создать изображения", callback_data="create_simple_images")],
        [InlineKeyboardButton("🎬 Создать видео", callback_data="video_generation")],
        [InlineKeyboardButton("✏️ Редактировать изображение", callback_data="edit_image")],
        [InlineKeyboardButton("🪙 Купить кредиты", callback_data="credit_packages")],
        [InlineKeyboardButton("📊 Моя статистика", callback_data="user_stats")],
        [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
        [InlineKeyboardButton("ℹ️ О боте", callback_data="about_bot")],
        [InlineKeyboardButton("📞 Поддержка", callback_data="support")]
    ]
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    USER_STATE[update.effective_user.id] = {'step': 'main_menu'}

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = """
❓ Как пользоваться ботом:

1️⃣ Выберите "Создать контент" или "🖼️ Изображения"

2️⃣ Выберите формат:
   📱 Instagram Reels - для коротких видео в Instagram
   🎵 TikTok - для видео в TikTok
   📺 YouTube Shorts - для коротких видео на YouTube
   📸 Instagram Post - для постов в Instagram
   📱 Instagram Stories - для историй в Instagram
   🖼️ Изображения - для генерации только изображений
   📄 Другое - любой другой формат

3️⃣ Выберите модель генерации:
   📱 Ideogram (хорошо работает с текстом и логотипами)
   ⚡ Bytedance (Seedream-3) (высокое качество, реалистичность)
   🔬 Google Imagen 4 Ultra (детализация и сложные сцены)
   🏗️ Luma Photon (кинематографичность и атмосфера)
   💼 Bria 3.2 (коммерческое использование, безопасность)
   🎨 Recraft AI (дизайн, векторы, UI)

4️⃣ Опишите, что хотите создать:
   💡 Примеры: "красивая девушка в красном платье", "космический корабль над планетой"

5️⃣ Выберите количество изображений

6️⃣ Получите результат! 🎉

💡 Совет: Чем подробнее описание, тем лучше результат!

🖼️ Для "Изображения":
• Пропускается шаг выбора стиля контента
• Сразу переходите к выбору модели и стиля изображения
• Выбираете количество картинок (1-10)
• Описываете, что хотите видеть на картинке
• Получаете только изображения без текста

🔄 Если что-то пошло не так:
• Нажмите "🔄 Начать заново" в любом меню
• Или напишите команду /start в чат
• Это сбросит все настройки и вернет к началу
"""
    
    keyboard = [
        [InlineKeyboardButton("🎨 Начать создание", callback_data="create_content")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    await update.message.reply_text(
        help_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для просмотра статистики пользователя"""
    user_id = update.effective_user.id
    analytics_db.update_user_activity(user_id)
    analytics_db.log_action(user_id, "stats_command")
    
    # Получаем статистику пользователя
    user_stats = analytics_db.get_user_stats(user_id)
    
    if not user_stats:
        await update.message.reply_text(
            "📊 Статистика пока недоступна.\n\nПопробуйте создать несколько изображений!"
        )
        return
    
    # Формируем текст статистики
    stats_text = f"""
📊 **Ваша статистика:**

🎨 **Общая статистика:**
• Всего генераций: {user_stats['total_generations']}
• Ошибок: {user_stats['total_errors']}
• Первое использование: {user_stats['first_seen'][:10]}
• Последняя активность: {user_stats['last_activity'][:10]}

📈 **По моделям:**
"""
    
    # Добавляем статистику по моделям
    if user_stats['models_stats']:
        for model, count, avg_time, successful in user_stats['models_stats'][:5]:
            success_rate = (successful / count * 100) if count > 0 else 0
            avg_time_str = f"{avg_time:.1f}с" if avg_time else "N/A"
            stats_text += f"• {model}: {count} ({success_rate:.0f}% успешно, {avg_time_str})\n"
    else:
        stats_text += "• Нет данных\n"
    
    stats_text += "\n📱 **По форматам:**\n"
    
    # Добавляем статистику по форматам
    if user_stats['formats_stats']:
        for format_type, count in user_stats['formats_stats'][:5]:
            stats_text += f"• {format_type}: {count}\n"
    else:
        stats_text += "• Нет данных\n"
    
    keyboard = [
        [InlineKeyboardButton("🎨 Создать изображение", callback_data="create_content")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    
    await update.message.reply_text(
        stats_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def my_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Временная команда для получения ID пользователя"""
    user_id = update.effective_user.id
    await update.message.reply_text(f"🆔 Ваш ID в Telegram: {user_id}\n\nСохраните этот ID - он понадобится для настройки администратора.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "create_content":
        await query.edit_message_text("🎨 Создание контента будет добавлено в следующей версии.")
    elif query.data == "create_simple_images":
        await query.edit_message_text("🖼️ Создание изображений будет добавлено в следующей версии.")
    elif query.data == "video_generation":
        await query.edit_message_text("🎬 Генерация видео будет добавлена в следующей версии.")
    elif query.data == "edit_image":
        await query.edit_message_text("✏️ Редактирование изображений будет добавлено в следующей версии.")
    elif query.data == "credit_packages":
        await query.edit_message_text("🪙 Покупка кредитов будет добавлена в следующей версии.")
    elif query.data == "user_stats":
        await query.edit_message_text("📊 Статистика пользователя будет добавлена в следующей версии.")
    elif query.data == "how_to_use":
        await query.edit_message_text("❓ Помощь будет добавлена в следующей версии.")
    elif query.data == "about_bot":
        await query.edit_message_text("ℹ️ Информация о боте будет добавлена в следующей версии.")
    elif query.data == "support":
        await query.edit_message_text("📞 Поддержка будет добавлена в следующей версии.")
    else:
        await query.edit_message_text("🔘 Неизвестная команда.")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    await update.message.reply_text("💬 Обработка текста будет добавлена в следующей версии.")

async def setup_commands(application):
    """Настройка команд меню"""
    commands = [
        BotCommand("start", "🚀 Запустить бота"),
        BotCommand("help", "❓ Помощь"),
        BotCommand("stats", "📊 Статистика"),
        BotCommand("my_id", "🆔 Мой ID"),
    ]
    await application.bot.set_my_commands(commands)

# ============================================================================
# MAIN FUNCTION
# ============================================================================

def main():
    import os
    from dotenv import load_dotenv
    
    # Загружаем переменные из .env файла если он существует
    load_dotenv()
    
    TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    if not TOKEN:
        print("❌ ОШИБКА: TELEGRAM_BOT_TOKEN не установлен!")
        print("📝 Установите переменную окружения TELEGRAM_BOT_TOKEN")
        print("💡 Запустите setup_env.py для инструкций")
        return
    
    # Устанавливаем API токен для Replicate если не установлен
    if not os.getenv('REPLICATE_API_TOKEN'):
        print("⚠️ ВНИМАНИЕ: REPLICATE_API_TOKEN не установлен!")
        print("📝 Установите переменную окружения REPLICATE_API_TOKEN")
        print("💡 Для Railway добавьте её в настройках проекта")
        return
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Добавляем обработчик ошибок
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик ошибок для логирования"""
        import traceback
        error_traceback = traceback.format_exc()
        print(f"🔍 Ошибка в боте:")
        print(f"🔍 {error_traceback}")
        logging.error(f"Exception while handling an update: {context.error}")
        logging.error(f"Traceback: {error_traceback}")
    
    app.add_error_handler(error_handler)
    
    # Добавляем обработчики
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('stats', stats_command))
    app.add_handler(CommandHandler('my_id', my_id_command))
    
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, text_handler))
    
    # Устанавливаем команды меню при запуске
    app.post_init = setup_commands
    
    print("🚀 Бот запущен локально с polling")
    
    try:
        app.run_polling()
    except KeyboardInterrupt:
        print("👋 Бот остановлен")

if __name__ == '__main__':
    main()

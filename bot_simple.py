import logging
import asyncio
import concurrent.futures
from typing import Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

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
from betatransfer_api import BetatransferAPI

# Создаем пул потоков для блокирующих операций
THREAD_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=10)

# Создаем пул HTTP соединений для aiohttp
HTTP_SESSION = None

# Инициализируем Betatransfer API
betatransfer_api = BetatransferAPI()

# Словарь для отслеживания состояния пользователей
USER_STATE = {}

# Асинхронные функции для работы с API
async def init_http_session():
    """Инициализирует HTTP сессию для aiohttp"""
    global HTTP_SESSION
    if HTTP_SESSION is None:
        connector = aiohttp.TCPConnector(limit=100, limit_per_host=30)
        timeout = aiohttp.ClientTimeout(total=300)
        HTTP_SESSION = aiohttp.ClientSession(connector=connector, timeout=timeout)

async def close_http_session():
    """Закрывает HTTP сессию"""
    global HTTP_SESSION
    if HTTP_SESSION:
        await HTTP_SESSION.close()
        HTTP_SESSION = None

# ============================================================================
# TELEGRAM HANDLERS
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "Пользователь"
    
    # Регистрируем пользователя в базе данных
    analytics_db.register_user(user_id, user_name)
    
    # Сбрасываем состояние пользователя
    USER_STATE[user_id] = {'step': 'main_menu'}
    
    welcome_text = f"""
🎉 **Добро пожаловать, {user_name}!**

Я - AI Image Bot, ваш помощник для создания изображений с помощью искусственного интеллекта.

🆓 **Бесплатно доступно:**
• 3 генерации изображений
• 3 редактирования изображений

💡 **Что я умею:**
• Создавать изображения по описанию
• Редактировать существующие изображения
• Работать с разными стилями и моделями

🚀 **Начните с создания изображения!**

🔄 Если бот завис - напишите /start
📊 Ваша статистика - /stats
"""
    
    keyboard = [
        [InlineKeyboardButton("🎨 Создать контент", callback_data="create_content")],
        [InlineKeyboardButton("🖼️ Создать изображения", callback_data="create_simple_images")],
        [InlineKeyboardButton("🪙 Купить кредиты", callback_data="credit_packages")],
        [InlineKeyboardButton("📊 Моя статистика", callback_data="user_stats")],
        [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
        [InlineKeyboardButton("📞 Поддержка", callback_data="support")]
    ]
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда помощи"""
    help_text = """
❓ **Как пользоваться ботом:**

1. **Создание изображений:**
   • Нажмите "Создать контент"
   • Выберите "Изображения"
   • Опишите что хотите создать
   • Выберите стиль и модель
   • Получите результат!

2. **Редактирование изображений:**
   • Нажмите "Редактировать изображение"
   • Загрузите изображение
   • Опишите изменения
   • Получите отредактированное изображение!

3. **Покупка кредитов:**
   • Нажмите "Купить кредиты"
   • Выберите пакет
   • Оплатите через Betatransfer
   • Получите кредиты!

💡 **Советы:**
• Будьте конкретны в описаниях
• Используйте ключевые слова
• Экспериментируйте со стилями

🔄 Если бот завис - напишите /start
📊 Ваша статистика - /stats
"""
    
    keyboard = [
        [InlineKeyboardButton("🎨 Начать создание", callback_data="create_content")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    await update.message.reply_text(
        help_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    # Основные навигационные кнопки
    if data == "create_content":
        await show_format_selection(update, context)
    
    elif data == "create_simple_images":
        # Для простых изображений сначала выбираем ориентацию
        USER_STATE[user_id] = {'step': 'simple_orientation', 'format': 'изображения'}
        
        keyboard = [
            [InlineKeyboardButton("📱 Вертикальное (9:16)", callback_data="simple_orientation:vertical")],
            [InlineKeyboardButton("⬜ Квадратное (1:1)", callback_data="simple_orientation:square")]
        ]
        
        await query.edit_message_text(
            "📐 **Выберите ориентацию изображения:**",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data == "main_menu":
        await start(update, context)
    
    elif data == "how_to_use":
        await show_help(update, context)
    
    elif data == "support":
        await show_support(update, context)
    
    elif data == "user_stats":
        await show_user_stats(update, context)
    
    elif data == "credit_packages":
        await show_credit_packages(update, context)
    
    else:
        await query.edit_message_text("❌ Неизвестная команда. Попробуйте /start")

async def show_format_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает выбор формата с навигацией"""
    user_id = update.effective_user.id
    
    # Сбрасываем состояние пользователя
    USER_STATE[user_id] = {'step': 'format_selection'}
    
    format_text = """
🎨 **Выберите тип контента:**

🖼️ **Изображения** - создание картинок по описанию
🎬 **Видео** - генерация коротких видео (в разработке)
✏️ **Редактирование** - изменение существующих изображений

💡 **Совет:** Начните с изображений - это самый популярный формат!

🆓 **Бесплатно доступно:**
• 3 генерации изображений
• 3 редактирования изображений
"""
    
    keyboard = [
        [InlineKeyboardButton("🖼️ Изображения", callback_data="format:изображения")],
        [InlineKeyboardButton("✏️ Редактирование", callback_data="format:редактирование")],
        [InlineKeyboardButton("🎬 Видео (скоро)", callback_data="video_generation")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    await update.callback_query.edit_message_text(
        format_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает справку"""
    help_text = """
❓ **Как пользоваться ботом:**

1. **Создание изображений:**
   • Нажмите "Создать контент"
   • Выберите "Изображения"
   • Опишите что хотите создать
   • Выберите стиль и модель
   • Получите результат!

2. **Редактирование изображений:**
   • Нажмите "Редактировать изображение"
   • Загрузите изображение
   • Опишите изменения
   • Получите отредактированное изображение!

3. **Покупка кредитов:**
   • Нажмите "Купить кредиты"
   • Выберите пакет
   • Оплатите через Betatransfer
   • Получите кредиты!

💡 **Советы:**
• Будьте конкретны в описаниях
• Используйте ключевые слова
• Экспериментируйте со стилями

🔄 Если бот завис - напишите /start
📊 Ваша статистика - /stats
"""
    
    keyboard = [
        [InlineKeyboardButton("🎨 Начать создание", callback_data="create_content")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    await update.callback_query.edit_message_text(
        help_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает информацию о поддержке"""
    support_text = """
📞 **Поддержка**

Если у вас возникли проблемы или вопросы:

💬 **Telegram:** @your_support_username
📧 **Email:** support@yourdomain.com
🌐 **Сайт:** https://yourdomain.com

⏰ **Время работы:** 24/7

🔧 **Частые проблемы:**
• Бот не отвечает → напишите /start
• Ошибка генерации → попробуйте другой промпт
• Проблемы с оплатой → обратитесь в поддержку

💡 **Совет:** Чем подробнее опишете проблему, тем быстрее получите помощь!
"""
    
    keyboard = [
        [InlineKeyboardButton("🎨 Начать создание", callback_data="create_content")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    
    await update.callback_query.edit_message_text(
        support_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_user_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику пользователя"""
    user_id = update.effective_user.id
    
    # Получаем статистику пользователя
    user_stats = analytics_db.get_user_stats(user_id)
    
    if not user_stats:
        await update.callback_query.edit_message_text(
            "📊 Статистика пока недоступна.\n\nПопробуйте создать несколько изображений!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🎨 Создать изображение", callback_data="create_content"),
                InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
            ]])
        )
        return
    
    # Формируем текст статистики
    stats_text = f"""
📊 **Ваша статистика:**

🎨 **Общая статистика:**
• Всего генераций: {user_stats.get('total_generations', 0)}
• Успешных: {user_stats.get('successful_generations', 0)}
• Неудачных: {user_stats.get('failed_generations', 0)}

🪙 **Кредиты:**
• Баланс: {user_stats.get('credits_balance', 0)}
• Потрачено: {user_stats.get('credits_spent', 0)}
• Куплено: {user_stats.get('credits_purchased', 0)}

📈 **Активность:**
• Первое использование: {user_stats.get('first_use', 'Неизвестно')}
• Последняя активность: {user_stats.get('last_activity', 'Неизвестно')}
"""
    
    keyboard = [
        [InlineKeyboardButton("🎨 Создать изображение", callback_data="create_content")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    
    await update.callback_query.edit_message_text(
        stats_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_credit_packages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает пакеты кредитов для покупки"""
    user_id = update.effective_user.id
    
    # Получаем информацию о кредитах пользователя
    user_credits = analytics_db.get_user_credits(user_id)
    current_balance = user_credits['balance'] if user_credits else 0
    
    credit_text = f"""
🪙 **Пакеты кредитов**

💰 **Ваш текущий баланс:** {current_balance} кредитов

📦 **Доступные пакеты:**

🥉 **Малый пакет**
• 200 кредитов
• Цена: ₽1,129
• Хватит на ~67 генераций

🥈 **Средний пакет**
• 5,000 кредитов  
• Цена: ₽2,420
• Хватит на ~1,667 генераций

🥇 **Большой пакет**
• 10,000 кредитов
• Цена: ₽4,030
• Хватит на ~3,333 генераций

💡 **Стоимость генерации:** ~3 кредита за изображение
"""
    
    keyboard = [
        [InlineKeyboardButton("🥉 Малый пакет (200 кредитов)", callback_data="buy_credits:small")],
        [InlineKeyboardButton("🥈 Средний пакет (5,000 кредитов)", callback_data="buy_credits:medium")],
        [InlineKeyboardButton("🥇 Большой пакет (10,000 кредитов)", callback_data="buy_credits:large")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    await update.callback_query.edit_message_text(
        credit_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user_id = update.effective_user.id
    state = USER_STATE.get(user_id, {})
    
    if state.get('step') == 'image_prompt':
        # Обработка промпта для генерации изображения
        prompt = update.message.text
        
        # Проверяем безопасность промпта
        if not is_safe_prompt(prompt):
            await update.message.reply_text(
                "❌ Промпт содержит запрещенный контент. Попробуйте другой вариант.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Назад", callback_data="main_menu")
                ]])
            )
            return
        
        # Сохраняем промпт и переходим к выбору модели
        USER_STATE[user_id]['prompt'] = prompt
        USER_STATE[user_id]['step'] = 'model_selection'
        
        await update.message.reply_text(
            f"✅ Промпт сохранен: {prompt}\n\nТеперь выберите модель для генерации:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📱 Ideogram", callback_data="image_gen_model:Ideogram"),
                InlineKeyboardButton("⚡ Bytedance", callback_data="image_gen_model:Bytedance (Seedream-3)"),
                InlineKeyboardButton("🔬 Google Imagen", callback_data="image_gen_model:Google Imagen 4 Ultra")
            ]])
        )
    
    else:
        # Обычное текстовое сообщение
        await update.message.reply_text(
            "👋 Привет! Нажмите /start для начала работы с ботом.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🚀 Начать", callback_data="main_menu")
            ]])
        )

def is_safe_prompt(prompt: str) -> bool:
    """Проверяет безопасность промпта"""
    forbidden_words = [
        'nude', 'naked', 'sex', 'porn', 'nsfw', 'adult', 'explicit',
        'violence', 'blood', 'gore', 'weapon', 'gun', 'knife',
        'hate', 'racist', 'discrimination', 'terrorist'
    ]
    
    prompt_lower = prompt.lower()
    return not any(word in prompt_lower for word in forbidden_words)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Глобальный обработчик ошибок"""
    error = context.error
    user_id = update.effective_user.id if update and update.effective_user else None
    
    # Логируем ошибку
    logging.error(f"🔍 Ошибка в боте: {error}")
    logging.error(f"🔍 {type(error).__name__}: {error}")
    
    # Логируем в базу данных
    if user_id:
        analytics_db.log_action(user_id, "error", f"{type(error).__name__}: {str(error)[:200]}")
    
    # Отправляем уведомление пользователю
    if update and update.effective_message:
        try:
            error_text = """
❌ **Произошла ошибка**

К сожалению, что-то пошло не так. Попробуйте:

1. 🔄 Написать /start для перезапуска
2. 📞 Обратиться к поддержке
3. ⏰ Подождать несколько минут

Мы уже работаем над исправлением!
"""
            
            keyboard = [
                [InlineKeyboardButton("🔄 Перезапустить", callback_data="main_menu")],
                [InlineKeyboardButton("📞 Поддержка", callback_data="support")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            
            await update.effective_message.reply_text(
                error_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения об ошибке: {e}")

async def setup_commands(application):
    """Настройка команд меню"""
    commands = [
        BotCommand("start", "🚀 Запустить бота"),
        BotCommand("help", "❓ Помощь"),
        BotCommand("stats", "📊 Статистика"),
        BotCommand("my_id", "🆔 Мой ID"),
        BotCommand("credits_stats", "🪙 Статистика кредитов"),
        BotCommand("admin_stats", "👑 Админ статистика"),
        BotCommand("add_credits", "➕ Добавить кредиты (админ)"),
        BotCommand("check_credits", "🔍 Проверить кредиты (админ)"),
        BotCommand("set_credits", "⚙️ Установить кредиты (админ)")
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
    
    # Добавляем обработчики
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, text_handler))
    
    # Добавляем обработчик ошибок
    app.add_error_handler(error_handler)
    
    # Устанавливаем команды меню при запуске
    async def post_init(app):
        await setup_commands(app)
        await init_http_session()
        print("✅ HTTP сессия инициализирована")
    
    app.post_init = post_init
    
    # Запускаем локально с polling
    print("🚀 Бот запущен локально с polling")
    
    try:
        app.run_polling()
    except KeyboardInterrupt:
        print("👋 Бот остановлен")

if __name__ == '__main__':
    main()

import logging
import asyncio
from typing import Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

import os
from dotenv import load_dotenv

# Словарь для отслеживания состояния пользователей
USER_STATE = {}

# ============================================================================
# TELEGRAM HANDLERS
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "Пользователь"
    
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
    
    # Простая статистика без базы данных
    stats_text = f"""
📊 **Ваша статистика:**

🎨 **Общая статистика:**
• Всего генераций: 0
• Успешных: 0
• Неудачных: 0

🪙 **Кредиты:**
• Баланс: 3 (бесплатные)
• Потрачено: 0
• Куплено: 0

📈 **Активность:**
• Первое использование: Сегодня
• Последняя активность: Сейчас

💡 **Это тестовая версия бота!**
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
    
    credit_text = f"""
🪙 **Пакеты кредитов**

💰 **Ваш текущий баланс:** 3 кредита (бесплатные)

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

⚠️ **Внимание:** Система платежей в разработке!
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
        BotCommand("my_id", "🆔 Мой ID")
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
    app.post_init = setup_commands
    
    # Запускаем локально с polling
    print("🚀 Бот запущен локально с polling")
    
    try:
        app.run_polling()
    except KeyboardInterrupt:
        print("👋 Бот остановлен")

if __name__ == '__main__':
    main()

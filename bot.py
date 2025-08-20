import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
import openai
import os
import replicate
import requests
from PIL import Image
import io
import tempfile
import time
import asyncio
from datetime import datetime, timedelta
from database import analytics_db

# Включаем логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Состояния пользователя
USER_STATE = {}

# Новые шаги для диалога
STEP_FORMAT = 'format'
STEP_STYLE = 'style'
STEP_TOPIC = 'topic'  # Добавляем недостающую константу
STEP_DONE = 'done'    # Добавляем недостающую константу
STEP_IMAGE_COUNT = 'image_count'
STEP_IMAGE_MODEL = 'image_model'
STEP_IMAGE_GENERATION = 'image_generation'
STEP_IMAGE_EDIT = 'image_edit'
STEP_VIDEO_QUALITY = 'video_quality'
STEP_VIDEO_DURATION = 'video_duration'
STEP_VIDEO_GENERATION = 'video_generation'
STEP_PROMPT_REVIEW = 'prompt_review'  # Пользователь решает, улучшать ли промпт
STEP_PROMPT_ENHANCEMENT = 'prompt_enhancement'  # Процесс улучшения промпта

FORMATS = ['Instagram Reels', 'TikTok', 'YouTube Shorts', 'Instagram Post', 'Instagram Stories', '🖼️ Изображения']
STYLES = ['🎯 Экспертно', '😄 Легко', '🔥 Продающе', '💡 Вдохновляюще', '🧠 Юмористично', 'Дружелюбный', 'Мотивационный', 'Развлекательный']

# Новые стили генерации изображений для выбора пользователем
IMAGE_GEN_STYLES = [
    'Фотореализм',
    'Иллюстрация',
    'Минимализм',
    'Акварель',
    'Масляная живопись',
    'Пиксель-арт'
]

# Модели генерации изображений
IMAGE_GEN_MODELS = [
    'Ideogram',
    'Bytedance (Seedream-3)',
    'Google Imagen 4 Ultra',
    'Luma Photon',
    'Bria 3.2',
    'Recraft AI'
]

# Модели генерации видео
VIDEO_GEN_MODELS = [
    'Bytedance Seedance 1.0 Pro'
]

# Характеристики моделей для отображения на кнопках (краткие)
MODEL_DESCRIPTIONS = {
    'Ideogram': 'текст и логотипы',
    'Bytedance (Seedream-3)': 'высокое качество',
    'Google Imagen 4 Ultra': 'детализация',
    'Luma Photon': 'кинематографичность',
    'Bria 3.2': 'коммерческое',
    'Recraft AI': 'дизайн и векторы'
}

# Характеристики моделей видео
VIDEO_MODEL_DESCRIPTIONS = {
            'Bytedance Seedance 1.0 Pro': 'text-to-video + image-to-video, 480p/720p/1080p, aspect_ratio'
}

def get_image_size_for_format(format_type, simple_orientation=None):
    """Определяет размер изображения на основе выбранного формата"""
    format_type = format_type.lower().replace(' ', '')
    
    if format_type in ['instagramstories', 'instagramreels', 'tiktok', 'youtubeshorts']:
        # Вертикальные форматы для мобильных устройств
        return "1024x1792"  # 9:16 соотношение сторон
    elif format_type == 'instagrampost':
        # Квадратный формат для постов
        return "1024x1024"  # 1:1 соотношение сторон
    elif format_type == 'изображения':
        # Для "Изображения" используем выбранную ориентацию
        if simple_orientation == 'vertical':
            return "1024x1792"  # 9:16 соотношение сторон
        elif simple_orientation == 'square':
            return "1024x1024"  # 1:1 соотношение сторон
        else:
            # По умолчанию квадратный формат
            return "1024x1024"
    else:
        # По умолчанию квадратный формат
        return "1024x1024"

def get_replicate_size_for_format(format_type):
    """Определяет размер для Replicate моделей на основе формата"""
    format_type = format_type.lower().replace(' ', '')
    
    if format_type in ['instagramstories', 'instagramreels', 'tiktok', 'youtubeshorts']:
        # Вертикальные форматы для мобильных устройств
        return "1024x1792"  # 9:16 соотношение сторон
    elif format_type == 'instagrampost':
        # Квадратный формат для постов
        return "1024x1024"  # 1:1 соотношение сторон
    else:
        # По умолчанию квадратный формат
        return "1024x1024"

def get_replicate_size_for_model(model_name, format_type):
    """Определяет размер для конкретной модели Replicate на основе формата"""
    format_type = format_type.lower().replace(' ', '')
    
    if model_name == 'Bytedance (Seedream-3)':
        # Bytedance принимает только "small", "regular", "big"
        if format_type in ['instagramstories', 'instagramreels', 'tiktok', 'youtubeshorts']:
            return "big"  # Для вертикальных форматов используем максимальный размер
        else:
            return "regular"  # Для остальных форматов
    
    elif model_name == 'Ideogram':
        # Ideogram принимает точные размеры
        if format_type in ['instagramstories', 'instagramreels', 'tiktok', 'youtubeshorts']:
            return "1024x1792"  # 9:16 соотношение сторон
        elif format_type == 'instagrampost':
            return "1024x1024"  # 1:1 соотношение сторон
        else:
            return "1024x1024"
    
    elif model_name == 'Google Imagen 4 Ultra':
        # Google Imagen принимает точные размеры
        if format_type in ['instagramstories', 'instagramreels', 'tiktok', 'youtubeshorts']:
            return "1024x1792"  # 9:16 соотношение сторон
        elif format_type == 'instagrampost':
            return "1024x1024"  # 1:1 соотношение сторон
        else:
            return "1024x1024"
    
    elif model_name == 'Luma Photon':
        # Luma Photon принимает точные размеры
        if format_type in ['instagramstories', 'instagramreels', 'tiktok', 'youtubeshorts']:
            return "1024x1792"  # 9:16 соотношение сторон
        elif format_type == 'instagrampost':
            return "1024x1024"  # 1:1 соотношение сторон
        else:
            return "1024x1024"
    
    elif model_name == 'Bria 3.2':
        # Bria принимает точные размеры
        if format_type in ['instagramstories', 'instagramreels', 'tiktok', 'youtubeshorts']:
            return "1024x1792"  # 9:16 соотношение сторон
        elif format_type == 'instagrampost':
            return "1024x1024"  # 1:1 соотношение сторон
        else:
            return "1024x1024"
    
    elif model_name == 'Recraft AI':
        # Recraft AI принимает точные размеры
        if format_type in ['instagramstories', 'instagramreels', 'tiktok', 'youtubeshorts']:
            return "1024x1792"  # 9:16 соотношение сторон
        elif format_type == 'instagrampost':
            return "1024x1024"  # 1:1 соотношение сторон
        else:
            return "1024x1024"
    
    else:
        # По умолчанию используем стандартные размеры
        return get_replicate_size_for_format(format_type)

def get_replicate_params_for_model(model_name, format_type, simple_orientation=None):
    """Определяет параметры для конкретной модели Replicate на основе формата"""
    format_type = format_type.lower().replace(' ', '')
    
    # Все вертикальные форматы используют aspect_ratio 9:16
    if format_type in ['instagramstories', 'instagramreels', 'tiktok', 'youtubeshorts']:
        return {"aspect_ratio": "9:16"}
    
    # Квадратные форматы
    elif format_type == 'instagrampost':
        return {"aspect_ratio": "1:1"}
    
    # Для "Изображения" используем выбранную ориентацию
    elif format_type == 'изображения':
        if simple_orientation == 'vertical':
            return {"aspect_ratio": "9:16"}
        elif simple_orientation == 'square':
            return {"aspect_ratio": "1:1"}
        else:
            # По умолчанию квадратный формат
            return {"aspect_ratio": "1:1"}
    
    # По умолчанию квадратный формат
    else:
        return {"aspect_ratio": "1:1"}

# Список запрещённых слов для фильтрации промптов (без слов 'дети', 'детей', 'детск')
BANNED_WORDS = [
    'обнаж', 'эрот', 'секс', 'genital', 'nude', 'naked', 'интим', 'порн', 'sex', 'porn', 'anus', 'vagina', 'penis', 'ass', 'fuck', 'masturb', 'суицид', 'убий', 'насилие', 'violence', 'kill', 'murder', 'blood', 'gore', 'расчлен', 'расстрел', 'убийство', 'убийца', 'насильник', 'насил', 'rape', 'pedoph', 'pedo', 'child', 'suicide', 'suicidal', 'hang', 'повес', 'расстрел', 'расчлен', 'убий', 'насилие', 'насильник', 'насил', 'убийца', 'убийство', 'расчлен', 'расстрел', 'blood', 'gore', 'kill', 'murder', 'violence', 'rape', 'suicide', 'child', 'porn', 'nude', 'naked', 'sex', 'fuck', 'masturb', 'penis', 'vagina', 'anus', 'ass', 'genital', 'эрот', 'обнаж', 'интим', 'порн'
]

def get_format_tips(format_type):
    """Возвращает подсказки в зависимости от выбранного формата"""
    format_type = format_type.lower()
    
    if format_type in ['instagram reels', 'tiktok', 'youtube shorts']:
        return """💡 Советы для коротких видео:
• Опишите активные сцены и действия
• Добавьте детали о людях и их деятельности
• Укажите динамику и процессы
• Примеры: "турбаза с рыбалкой", "спортзал с тренирующимися", "кафе с приготовлением кофе"

✅ Хорошо: "турбаза с активными людьми, рыбалка на озере, баня с паром"
❌ Плохо: "отдых" """
    
    elif format_type in ['instagram post']:
        return """💡 Советы для постов:
• Опишите красивые статичные кадры
• Добавьте детали о стиле и дизайне
• Укажите атмосферу и настроение
• Примеры: "стильная турбаза", "современный спортзал", "уютное кафе"

✅ Хорошо: "современная турбаза с деревянными домиками, красивое освещение"
❌ Плохо: "место для отдыха" """
    
    elif format_type in ['instagram stories']:
        return """💡 Советы для Stories:
• Добавьте место для текста (обычно сверху/снизу)
• Укажите простые, но привлекательные кадры
• Примеры: "какр турбазы", "спортзал"

✅ Хорошо: "кадр турбазы с местом для текста, красивое освещение"
❌ Плохо: "горизонтальный вид" """
    
    else:
        return """💡 Общие советы:
• Будьте конкретны и детализированы
• Добавьте стиль, материалы, освещение
• Укажите атмосферу и контекст
• Примеры: "современный дизайн", "уютная атмосфера", "профессиональное качество"

✅ Хорошо: "современный объект с деталями, красивое освещение, уютная атмосфера"
❌ Плохо: "красиво" """

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
        [InlineKeyboardButton("ℹ️ О боте", callback_data="about_bot")]
    ]
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    USER_STATE[update.effective_user.id] = {'step': 'main_menu'}

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает главное меню"""
    user_id = update.effective_user.id
    
    # Получаем информацию о пользователе
    limits = analytics_db.get_user_limits(user_id)
    credits = analytics_db.get_user_credits(user_id)
    
    # Формируем информацию о статусе
    free_generations_left = analytics_db.get_free_generations_left(user_id)
    
    status_text = ""
    if free_generations_left > 0:
        status_text = f"🆓 **Бесплатные генерации:** {free_generations_left} осталось\n"
    else:
        status_text = f"🆓 **Бесплатные генерации:** закончились\n"
    
    # Добавляем информацию о кредитах
    if credits['balance'] > 0:
        status_text += f"🪙 **Кредиты:** {credits['balance']} доступно\n\n"
    else:
        status_text += f"🪙 **Кредиты:** не куплены\n\n"
    
    keyboard = [
        [InlineKeyboardButton("🎨 Создать контент", callback_data="create_content")],
        [InlineKeyboardButton("🖼️ Создать изображения", callback_data="create_simple_images")],
        [InlineKeyboardButton("🎬 Создать видео", callback_data="video_generation")],
        [InlineKeyboardButton("✏️ Редактировать изображение", callback_data="edit_image")],
        [InlineKeyboardButton("🪙 Купить кредиты", callback_data="credit_packages")],
        [InlineKeyboardButton("📊 Моя статистика", callback_data="user_stats")],
        [InlineKeyboardButton("🎨 Советы по Ideogram", callback_data="ideogram_tips")],
        [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
        [InlineKeyboardButton("ℹ️ О боте", callback_data="about_bot")]
    ]
    
    await update.callback_query.edit_message_text(
        f"🎨 AI Image Generator\n\n{status_text}"
        "💡 **Бесплатно:**\n"
        "• 🖼️ Создать изображения (только первые 3 раза)\n\n"
        "💰 **Платно (требуют кредиты):**\n"
        "• 🖼️ Создать изображения (4+ раз) - от 10 кредитов\n"
        "• ✏️ Редактировать изображения - 12 кредитов\n"
        "• 🎬 Создать видео - от 37 кредитов\n\n"
        "🪙 **Купите кредиты для полного доступа!**",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_how_to_use(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает инструкцию по использованию"""
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
    
    await update.callback_query.edit_message_text(
        help_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_about_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает информацию о боте"""
    about_text = """
ℹ️ О боте AI Image Generator:

🤖 Возможности:
• Генерация изображений с помощью ИИ
• Создание постов для социальных сетей
• Множество моделей генерации
• Автоматическое улучшение промптов

🎨 Поддерживаемые модели:
• FLUX.1 Kontext Pro (редактирование изображений)
• Ideogram (хорошо работает с текстом и логотипами)
• Bytedance (Seedream-3) (высокое качество, реалистичность)
• Google Imagen 4 Ultra (детализация и сложные сцены)
• Luma Photon (кинематографичность и атмосфера)
• Bria 3.2 (коммерческое использование, безопасность)
• Recraft AI (дизайн, векторы, UI)

📱 Форматы:
• Instagram посты (квадратные 1:1)
• Instagram Stories (вертикальные 9:16)
• Instagram Reels (вертикальные 9:16)
• TikTok (вертикальные 9:16)
• YouTube Shorts (вертикальные 9:16)
• Любые другие форматы

💡 Особенности:
• Автоматическое улучшение описаний
• Фильтрация запрещенного контента
• Высокое качество генерации
• Простой и понятный интерфейс
"""
    
    keyboard = [
        [InlineKeyboardButton("🎨 Начать создание", callback_data="create_content")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    await update.callback_query.edit_message_text(
        about_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_format_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает выбор формата с навигацией"""
    keyboard = [
        [InlineKeyboardButton("📱 Instagram Reels", callback_data="format:Instagram Reels")],
        [InlineKeyboardButton("🎵 TikTok", callback_data="format:TikTok")],
        [InlineKeyboardButton("📺 YouTube Shorts", callback_data="format:YouTube Shorts")],
        [InlineKeyboardButton("📸 Instagram Post", callback_data="format:Instagram Post")],
        [InlineKeyboardButton("📱 Instagram Stories", callback_data="format:Instagram Stories")],
        [InlineKeyboardButton("🖼️ Изображения", callback_data="format:Изображения")],
        [InlineKeyboardButton("📄 Другое", callback_data="format:custom")],
        [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    await update.callback_query.edit_message_text(
        "Выберите формат:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_model_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает выбор модели с навигацией"""
    keyboard = [
        [InlineKeyboardButton("🎨 FLUX.1 Kontext Pro (редактирование изображений)", callback_data="image_gen_model:FLUX.1 Kontext Pro")],
        [InlineKeyboardButton("📱 Ideogram (лидер в генерации текста в изображениях: баннеры, постеры, соцсети)", callback_data="image_gen_model:Ideogram")],
        [InlineKeyboardButton("⚡ Bytedance Seedream-3 (нативная 2K генерация, быстрая)", callback_data="image_gen_model:Bytedance (Seedream-3)")],
        [InlineKeyboardButton("🔬 Google Imagen 4 Ultra (максимальное качество, детали)", callback_data="image_gen_model:Google Imagen 4 Ultra")],
        [InlineKeyboardButton("🏗️ Luma Photon (креативные возможности, высокое качество)", callback_data="image_gen_model:Luma Photon")],
        [InlineKeyboardButton("💼 Bria 3.2 (коммерческое использование, 4B параметров)", callback_data="image_gen_model:Bria 3.2")],
        [InlineKeyboardButton("🎨 Recraft AI (дизайн, вектор, логотипы, бренд-дизайн, SVG)", callback_data="image_gen_model:Recraft AI")],
        [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
        [InlineKeyboardButton("🔙 Назад", callback_data="format_selection")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    
    await update.callback_query.edit_message_text(
        "Выберите модель генерации:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

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
   🎨 FLUX.1 Kontext Pro (редактирование изображений)
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

⚠️ **Важно о FLUX.1 Kontext Pro:**
• Имеет строгие фильтры безопасности
• Может блокировать промпты с описанием внешности людей
• Рекомендуется использовать нейтральные слова: "женщина" вместо "красивая", "девушка" вместо "сексуальная"
• Для портретов лучше выбрать Ideogram, Bytedance или Google Imagen

🎨 **Советы по Ideogram:**
• Используйте простые, четкие описания
• Избегайте длинных сложных фраз
• Фокусируйтесь на главном объекте
• Для фотореалистичных изображений лучше используйте Bytedance или Google Imagen

💰 **Информация о стоимости:**
• 🖼️ Создание изображений - БЕСПЛАТНО
• ✏️ Редактирование изображений - БЕСПЛАТНО
• 🎬 Создание видео - требует кредиты Replicate
• 💳 Для видео пополните баланс на https://replicate.com/account/billing
"""
    
    keyboard = [
        [InlineKeyboardButton("🎨 Начать создание", callback_data="create_content")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
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

async def ideogram_tips_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для получения советов по использованию Ideogram"""
    tips_text = """
🎨 **Советы по использованию Ideogram**

## Почему Ideogram может генерировать изображения, не соответствующие описанию?

### Основные причины:
1. **Слишком сложные промпты** - Ideogram лучше работает с простыми, четкими описаниями
2. **Перегруженность параметрами** - Множество стилей и форматов могут "забивать" основное описание
3. **Особенности модели** - Ideogram специализируется на тексте и логотипах

## ✅ Как улучшить результаты:

### 1. **Используйте простые описания**
```
❌ Плохо: "Очень красивая девушка с длинными волнистыми каштановыми волосами, одетая в элегантное красное платье"
✅ Хорошо: "девушка в красном платье"
```

### 2. **Фокусируйтесь на главном объекте**
```
❌ Плохо: "Современный дом с большими окнами, красивым садом, бассейном, гаражом"
✅ Хорошо: "современный дом с большими окнами"
```

### 3. **Избегайте длинных фраз**
- Используйте 3-7 ключевых слов
- Убирайте лишние прилагательные
- Фокусируйтесь на сути

## 🎯 Лучшие практики:

### Для портретов:
- "женщина с темными волосами"
- "мужчина в костюме"
- "девушка в платье"

### Для пейзажей:
- "горный пейзаж"
- "городская улица"
- "лесная тропа"

## ⚠️ Ограничения Ideogram:

1. **Не идеален для фотореалистичных изображений** - лучше используйте Bytedance или Google Imagen
2. **Медленная генерация** - может занимать до 60 секунд
3. **Чувствителен к сложным промптам** - лучше работает с простыми описаниями

## 🔄 Альтернативы:

Если Ideogram не дает желаемых результатов:
- **Bytedance (Seedream-3)** - для фотореалистичных изображений
- **Google Imagen 4 Ultra** - для максимального качества и детализации
- **Luma Photon** - для креативных и художественных изображений

💡 **Главный совет:** Начните с простого описания и постепенно добавляйте детали!
"""
    
    keyboard = [
        [InlineKeyboardButton("🎨 Начать создание", callback_data="create_content")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    
    await update.message.reply_text(
        tips_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def edit_image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для редактирования изображений с помощью FLUX.1 Kontext Pro"""
    user_id = update.effective_user.id
    
    # Сохраняем состояние для ожидания загрузки изображения
    USER_STATE[user_id]['step'] = 'upload_image_for_edit'
    
    await update.message.reply_text(
        "🎨 Редактирование изображений с FLUX.1 Kontext Pro\n\n"
        "1️⃣ Отправьте изображение, которое хотите отредактировать\n"
        "2️⃣ Затем опишите, что именно хотите изменить\n\n"
        "💡 Примеры:\n"
        "• \"Изменить цвет фона на синий\"\n"
        "• \"Добавить солнцезащитные очки\"\n"
        "• \"Сделать изображение в стиле акварели\"\n"
        "• \"Заменить текст на 'Новый текст'\"\n"
        "• \"Изменить прическу на короткую\"\n\n"
        "🔙 Для отмены напишите /start"
    )

def is_prompt_safe(prompt):
    prompt_lower = prompt.lower()
    for word in BANNED_WORDS:
        if word in prompt_lower:
            return False
    return True

def improve_prompt_for_ideogram(prompt):
    """
    Улучшает промпт для лучшей работы с Ideogram
    Ideogram лучше работает с простыми, четкими описаниями
    """
    if not prompt:
        return prompt
    
    # Убираем лишние слова, которые могут сбивать Ideogram
    prompt = prompt.strip()
    
    # Если промпт слишком длинный, сокращаем его
    words = prompt.split()
    if len(words) > 15:
        # Оставляем только ключевые слова
        important_words = []
        for word in words:
            if len(word) > 3 and word.lower() not in ['very', 'really', 'quite', 'rather', 'somewhat', 'rather', 'quite', 'very', 'really', 'extremely', 'incredibly', 'amazingly', 'wonderfully', 'beautifully', 'gorgeously', 'stunningly', 'magnificently', 'exquisitely', 'elegantly', 'gracefully', 'perfectly', 'absolutely', 'completely', 'totally', 'entirely', 'wholly', 'thoroughly', 'completely', 'fully', 'entirely', 'wholly', 'thoroughly', 'completely', 'fully', 'entirely', 'wholly', 'thoroughly']:
                important_words.append(word)
            if len(important_words) >= 10:
                break
        prompt = ' '.join(important_words)
    
    # Убираем повторяющиеся слова
    words = prompt.split()
    unique_words = []
    for word in words:
        if word.lower() not in [w.lower() for w in unique_words]:
            unique_words.append(word)
    
    return ' '.join(unique_words)

async def extract_scenes_from_script(script_text, format_type=None):
    """
    Извлекает ключевые сцены из сценария (по квадратным скобкам или ключевым фразам).
    Возвращает список коротких описаний для генерации изображений.
    """
    import re
    
    # Определяем количество кадров из текста
    frame_count = None
    frame_patterns = [
        r'(\d+)\s*кадр[аов]*',
        r'(\d+)\s*сцен[аы]*',
        r'(\d+)\s*изображени[йя]*',
        r'(\d+)\s*фото',
        r'(\d+)\s*картин[аок]*'
    ]
    
    for pattern in frame_patterns:
        match = re.search(pattern, script_text.lower())
        if match:
            frame_count = int(match.group(1))
            break
    
    # Если кадры не найдены, но есть квадратные скобки, считаем их количество
    if not frame_count and '[' in script_text and ']' in script_text:
        # Ищем все кадры в квадратных скобках
        frame_matches = re.findall(r'\[.*?\]', script_text)
        if frame_matches:
            frame_count = len(frame_matches)
    
    # Если количество кадров найдено, используем его
    if frame_count:
        prompt = (
            f"Вот сценарий для видео:\n{script_text}\n"
            f"В сценарии указано {frame_count} кадров. Выдели ровно {frame_count} ключевых сцен по хронологии сценария. "
            f"ВАЖНО: "
            f"- Если в сценарии есть главный персонаж (человек), указывай его пол и внешность в каждом кадре "
            f"- НЕ добавляй людей, если их нет в сценарии "
            f"- Для каждой сцены напиши короткое описание для генерации изображения (1-2 предложения, только суть, без номеров и кавычек) "
            f"Ответ выдай списком, ровно {frame_count} пунктов, каждый с новой строки."
        )
    else:
        # Если количество кадров не указано, используем стандартную логику
        if format_type and format_type.lower() in ['tiktok', 'instagram reels', 'youtube shorts']:
            # Проверяем, есть ли кадры в квадратных скобках
            if '[' in script_text and ']' in script_text:
                prompt = (
                    f"Вот сценарий для {format_type.title()} видео:\n{script_text}\n"
                    "В тексте есть кадры в квадратных скобках. Извлеки описания из каждого кадра [Кадр X: Описание] и создай короткие промпты для генерации изображений. Для каждой сцены напиши короткое описание для генерации изображения (1-2 предложения, только суть, без номеров и кавычек). Ответ выдай списком, каждый пункт с новой строки."
                )
            else:
                prompt = (
                    f"Вот сценарий для {format_type.title()} видео:\n{script_text}\n"
                    "Выдели ключевые сцены по хронологии сценария. "
                    f"ВАЖНО: "
                    f"- Если в сценарии есть главный персонаж (человек), указывай его пол и внешность в каждом кадре "
                    f"- НЕ добавляй людей, если их нет в сценарии "
                    f"- Для каждой сцены напиши короткое описание для генерации изображения (1-2 предложения, только суть, без номеров и кавычек) "
                    f"Ответ выдай списком, каждый пункт с новой строки."
                )
        else:
            prompt = (
                f"Вот сценарий для видео:\n{script_text}\n"
                "Выдели сцены строго по хронологии и структуре сценария, не добавляй свои, не объединяй и не пропускай сцены. "
                f"ВАЖНО: "
                f"- Если в сценарии есть главный персонаж (человек), указывай его пол и внешность в каждом кадре "
                f"- НЕ добавляй людей, если их нет в сценарии "
                f"- Для каждой сцены напиши короткое описание для генерации изображения (1-2 предложения, только суть, без номеров и кавычек) "
                f"Ответ выдай списком, каждый пункт с новой строки."
            )
    
    try:
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model="gpt-4o-mini",
                    messages=[
            {"role": "system", "content": "Ты помощник по созданию визуальных промптов для генерации изображений. НЕ добавляй людей в промпты, если они не упомянуты в сценарии."},
            {"role": "user", "content": prompt}
        ],
            max_tokens=700,
            temperature=0.5,
        )
        scenes_text = response.choices[0].message.content.strip()
        scenes = [s for s in scenes_text.split('\n') if s.strip()]
        
        # Ограничиваем количество сцен согласно найденному количеству кадров
        if frame_count:
            scenes = scenes[:frame_count]
    except Exception as e:
        # Fallback на простую логику если OpenAI недоступен
        scenes = []
        
        # Ищем кадры в квадратных скобках
        frame_matches = re.findall(r'\[.*?\]', script_text)
        if frame_matches:
            for match in frame_matches:
                # Убираем квадратные скобки и номер кадра
                scene_text = re.sub(r'^\[Кадр\s*\d+:\s*', '', match)
                scene_text = re.sub(r'^\[', '', scene_text)
                scene_text = re.sub(r'\]$', '', scene_text)
                if scene_text.strip():
                    scenes.append(scene_text.strip())
        
        # Если кадры не найдены, разбиваем текст на предложения
        if not scenes:
            sentences = re.split(r'[.!?]+', script_text)
            for sentence in sentences:
                sentence = sentence.strip()
                if len(sentence) > 10:  # Минимальная длина предложения
                    scenes.append(sentence)
        
        # Ограничиваем количество сцен
        if frame_count:
            scenes = scenes[:frame_count]
    
    # Ограничиваем количество сцен согласно найденному количеству кадров
    if frame_count:
        scenes = scenes[:frame_count]
    
    # Ограничиваем общее количество сцен до 10 (максимум для Telegram альбома)
    scenes = scenes[:10]
    
    return scenes

def enhance_prompts_with_character_context(prompts, topic):
    """
    Улучшает промпты, добавляя контекст персонажей для сохранения консистентности
    Только если в теме действительно есть люди
    """
    if not prompts:
        return prompts
    
    # Ищем ключевые слова, указывающие на персонажей
    # Убираем 'она' и 'он' из списка, так как они могут быть в контексте неодушевленных объектов
    character_keywords = {
        'женщина': ['woman', 'female', 'lady', 'girl'],
        'девушка': ['girl', 'young woman', 'female'],
        'брюнетка': ['brunette woman', 'brunette girl', 'dark-haired woman'],
        'блондинка': ['blonde woman', 'blonde girl', 'blonde female'],
        'мужчина': ['man', 'male', 'guy'],
        'парень': ['young man', 'guy', 'male']
    }
    
    # Проверяем, есть ли в теме или промптах упоминания людей
    has_people_in_topic = any(keyword in topic.lower() for keyword in character_keywords.keys())
    has_people_in_prompts = any(any(keyword in prompt.lower() for keyword in character_keywords.keys()) for prompt in prompts)
    
    # Если в теме и промптах нет упоминаний людей, не добавляем ничего
    if not has_people_in_topic and not has_people_in_prompts:
        return prompts
    
    # Определяем главного персонажа из первого промпта
    main_character = None
    for keyword, english_terms in character_keywords.items():
        if any(keyword in prompt.lower() for prompt in prompts):
            main_character = english_terms[0]  # Берем первый английский термин
            break
    
    # Если нашли персонажа, добавляем его контекст ко всем промптам
    if main_character:
        enhanced_prompts = []
        for i, prompt in enumerate(prompts):
            # Проверяем, есть ли уже указание на персонажа в промпте
            has_character = any(term in prompt.lower() for terms in character_keywords.values() for term in terms)
            
            if not has_character and any(word in prompt.lower() for word in ['смотрит', 'looks', 'смотрит в камеру', 'looking at camera']):
                # Добавляем персонажа к промптам с взглядом
                enhanced_prompt = f"{main_character}, {prompt}"
            elif not has_character and i > 0:
                # Для остальных промптов добавляем персонажа, если его нет
                enhanced_prompt = f"{main_character}, {prompt}"
            else:
                enhanced_prompt = prompt
            
            enhanced_prompts.append(enhanced_prompt)
        
        return enhanced_prompts
    
    return prompts

async def setup_commands(application):
    """Устанавливает команды меню для бота"""
    commands = [
        BotCommand("start", "🚀 Начать работу с ботом / Перезагрузить бота"),
        BotCommand("help", "❓ Как пользоваться ботом"),
        BotCommand("stats", "📊 Ваша статистика"),
        BotCommand("ideogram_tips", "🎨 Советы по использованию Ideogram")
    ]
    
    try:
        await application.bot.set_my_commands(commands)
        logging.info("Команды меню успешно установлены")
    except Exception as e:
        logging.error(f"Ошибка при установке команд меню: {e}")

# Заглушки для основных функций (нужно будет дополнить)
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "main_menu":
        await show_main_menu(update, context)
    elif query.data == "create_content":
        await show_format_selection(update, context)
    elif query.data == "how_to_use":
        await show_how_to_use(update, context)
    elif query.data == "about_bot":
        await show_about_bot(update, context)
    elif query.data == "format_selection":
        await show_format_selection(update, context)
    elif query.data.startswith("format:"):
        # Обработка выбора формата
        format_type = query.data.split(":", 1)[1]
        user_id = update.effective_user.id
        if user_id not in USER_STATE:
            USER_STATE[user_id] = {}
        USER_STATE[user_id]['format'] = format_type
        USER_STATE[user_id]['step'] = STEP_TOPIC
        await query.edit_message_text(
            f"Выбран формат: {format_type}\n\nТеперь опишите, что хотите создать:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="format_selection")
            ]])
        )
    elif query.data.startswith("image_gen_model:"):
        # Обработка выбора модели
        model = query.data.split(":", 1)[1]
        user_id = update.effective_user.id
        if user_id not in USER_STATE:
            USER_STATE[user_id] = {}
        USER_STATE[user_id]['model'] = model
        USER_STATE[user_id]['step'] = STEP_IMAGE_COUNT
        await query.edit_message_text(
            f"Выбрана модель: {model}\n\nВыберите количество изображений:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("1", callback_data="count:1")],
                [InlineKeyboardButton("2", callback_data="count:2")],
                [InlineKeyboardButton("3", callback_data="count:3")],
                [InlineKeyboardButton("4", callback_data="count:4")],
                [InlineKeyboardButton("5", callback_data="count:5")],
                [InlineKeyboardButton("🔙 Назад", callback_data="image_gen_model")]
            ])
        )
    else:
        await query.edit_message_text(
            "❌ Неизвестная команда. Нажмите /start для перезапуска бота."
        )

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user_id = update.effective_user.id
    text = update.message.text
    
    if user_id not in USER_STATE:
        USER_STATE[user_id] = {'step': 'main_menu'}
        await update.message.reply_text(
            "Добро пожаловать! Нажмите /start для начала работы."
        )
        return
    
    step = USER_STATE[user_id].get('step', 'main_menu')
    
    if step == STEP_TOPIC:
        # Пользователь описывает, что хочет создать
        USER_STATE[user_id]['topic'] = text
        USER_STATE[user_id]['step'] = STEP_IMAGE_MODEL
        await show_model_selection(update, context)
    elif step == 'upload_image_for_edit':
        # Пользователь отправляет описание для редактирования
        await update.message.reply_text(
            "✅ Описание получено! Теперь отправьте изображение для редактирования."
        )
        USER_STATE[user_id]['edit_prompt'] = text
    else:
        await update.message.reply_text(
            "Используйте кнопки меню для навигации или нажмите /start для перезапуска."
        )

async def send_images(update, context, state, prompt_type='auto', user_prompt=None, scenes=None):
    """Отправляет сгенерированные изображения"""
    user_id = update.effective_user.id
    
    # Получаем параметры из состояния
    format_type = state.get('format', 'Изображения')
    model = state.get('model', 'Ideogram')
    topic = state.get('topic', '')
    image_count = state.get('image_count', 1)
    
    # Определяем, какой промпт использовать
    if user_prompt:
        prompt = user_prompt
    elif scenes:
        prompt = scenes[0] if scenes else topic
    else:
        prompt = topic
    
    if not prompt:
        await update.message.reply_text(
            "❌ Ошибка: не указан промпт для генерации. Нажмите /start для перезапуска."
        )
        return
    
    # Проверяем безопасность промпта
    if not is_prompt_safe(prompt):
        await update.message.reply_text(
            "❌ Промпт содержит запрещенный контент. Попробуйте описать по-другому."
        )
        return
    
    # Логируем начало генерации
    analytics_db.log_action(user_id, f"image_generation_start_{model}")
    start_time = time.time()
    
    try:
        await update.message.reply_text(
            f"🎨 Генерирую {image_count} изображений...\n"
            f"📝 Промпт: {prompt[:100]}{'...' if len(prompt) > 100 else ''}\n"
            f"🤖 Модель: {model}\n"
            f"⏳ Это может занять 30-60 секунд..."
        )
        
        # Генерируем изображения в зависимости от модели
        if model == 'Ideogram':
            images = await generate_ideogram_images(prompt, image_count, format_type)
        elif model == 'Bytedance (Seedream-3)':
            images = await generate_bytedance_images(prompt, image_count, format_type)
        elif model == 'Google Imagen 4 Ultra':
            images = await generate_google_imagen_images(prompt, image_count, format_type)
        elif model == 'Luma Photon':
            images = await generate_luma_photon_images(prompt, image_count, format_type)
        elif model == 'Bria 3.2':
            images = await generate_bria_images(prompt, image_count, format_type)
        elif model == 'Recraft AI':
            images = await generate_recraft_images(prompt, image_count, format_type)
        else:
            await update.message.reply_text(f"❌ Неподдерживаемая модель: {model}")
            return
        
        if not images:
            await update.message.reply_text("❌ Не удалось сгенерировать изображения. Попробуйте другой промпт.")
            return
        
        # Отправляем изображения
        if len(images) == 1:
            # Одно изображение
            await update.message.reply_photo(
                photo=images[0],
                caption=f"🎨 Сгенерировано с помощью {model}\n📝 Промпт: {prompt[:200]}{'...' if len(prompt) > 200 else ''}"
            )
        else:
            # Несколько изображений
            media_group = []
            for i, image_url in enumerate(images):
                media_group.append(
                    InputMediaPhoto(
                        media=image_url,
                        caption=f"🎨 Изображение {i+1}/{len(images)} - {model}\n📝 Промпт: {prompt[:100]}{'...' if len(prompt) > 100 else ''}"
                    )
                )
            
            await update.message.reply_media_group(media=media_group)
        
        # Логируем успешную генерацию
        generation_time = time.time() - start_time
        analytics_db.log_generation(
            user_id=user_id,
            model_name=model,
            format_type=format_type,
            prompt=prompt,
            image_count=image_count,
            success=True,
            generation_time=generation_time
        )
        
        # Показываем кнопки для дальнейших действий
        keyboard = [
            [InlineKeyboardButton("🔄 Создать еще", callback_data="create_content")],
            [InlineKeyboardButton("✏️ Редактировать", callback_data="edit_image")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        
        await update.message.reply_text(
            f"✅ Готово! Сгенерировано {len(images)} изображений за {generation_time:.1f} секунд.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except Exception as e:
        # Логируем ошибку
        generation_time = time.time() - start_time
        analytics_db.log_generation(
            user_id=user_id,
            model_name=model,
            format_type=format_type,
            prompt=prompt,
            image_count=image_count,
            success=False,
            error_message=str(e),
            generation_time=generation_time
        )
        
        await update.message.reply_text(
            f"❌ Ошибка при генерации: {str(e)}\n\nПопробуйте другой промпт или нажмите /start для перезапуска."
        )

async def generate_video(update, context, state):
    """Генерирует видео"""
    # Заглушка - нужно будет дополнить
    await update.message.reply_text(
        "🎬 Функция генерации видео в разработке. Используйте /start для возврата в меню."
    )

async def edit_image_with_flux(update, context, state, original_image_url, edit_prompt):
    """Редактирует изображение с помощью FLUX.1 Kontext Pro"""
    # Заглушка - нужно будет дополнить
    await update.message.reply_text(
        "✏️ Функция редактирования изображений в разработке. Используйте /start для возврата в меню."
    )

async def generate_ideogram_images(prompt, image_count, format_type):
    """Генерирует изображения через Ideogram"""
    try:
        # Улучшаем промпт для Ideogram
        improved_prompt = improve_prompt_for_ideogram(prompt)
        
        # Определяем размер изображения
        size = get_replicate_size_for_model('Ideogram', format_type)
        
        # Генерируем изображения
        images = []
        for i in range(image_count):
            output = replicate.run(
                "ideogram-ai/ideogram-v3-turbo",
                input={
                    "prompt": improved_prompt,
                    "width": int(size.split('x')[0]),
                    "height": int(size.split('x')[1])
                }
            )
            
            # Обрабатываем результат
            if hasattr(output, 'url'):
                image_url = output.url
            elif isinstance(output, list) and len(output) > 0:
                image_url = output[0]
            else:
                image_url = str(output)
            
            if image_url and image_url.startswith('http'):
                images.append(image_url)
            
            # Небольшая задержка между генерациями
            if i < image_count - 1:
                await asyncio.sleep(1)
        
        return images
        
    except Exception as e:
        logging.error(f"Ошибка генерации Ideogram: {e}")
        return []

async def generate_bytedance_images(prompt, image_count, format_type):
    """Генерирует изображения через Bytedance Seedream-3"""
    try:
        # Определяем размер для Bytedance
        size = get_replicate_size_for_model('Bytedance (Seedream-3)', format_type)
        
        # Генерируем изображения
        images = []
        for i in range(image_count):
            output = replicate.run(
                "bytedance/seedream-3",
                input={
                    "prompt": prompt,
                    "size": size,
                    "aspect_ratio": "9:16" if format_type.lower() in ['instagramstories', 'instagramreels', 'tiktok', 'youtubeshorts'] else "1:1"
                }
            )
            
            # Обрабатываем результат
            if hasattr(output, 'url'):
                image_url = output.url
            elif isinstance(output, list) and len(output) > 0:
                image_url = output[0]
            else:
                image_url = str(output)
            
            if image_url and image_url.startswith('http'):
                images.append(image_url)
            
            # Небольшая задержка между генерациями
            if i < image_count - 1:
                await asyncio.sleep(1)
        
        return images
        
    except Exception as e:
        logging.error(f"Ошибка генерации Bytedance: {e}")
        return []

async def generate_google_imagen_images(prompt, image_count, format_type):
    """Генерирует изображения через Google Imagen 4 Ultra"""
    try:
        # Определяем размер изображения
        size = get_replicate_size_for_model('Google Imagen 4 Ultra', format_type)
        
        # Генерируем изображения
        images = []
        for i in range(image_count):
            output = replicate.run(
                "google/imagen-4-ultra",
                input={
                    "prompt": prompt,
                    "width": int(size.split('x')[0]),
                    "height": int(size.split('x')[1])
                }
            )
            
            # Обрабатываем результат
            if hasattr(output, 'url'):
                image_url = output.url
            elif isinstance(output, list) and len(output) > 0:
                image_url = output[0]
            else:
                image_url = str(output)
            
            if image_url and image_url.startswith('http'):
                images.append(image_url)
            
            # Небольшая задержка между генерациями
            if i < image_count - 1:
                await asyncio.sleep(1)
        
        return images
        
    except Exception as e:
        logging.error(f"Ошибка генерации Google Imagen: {e}")
        return []

async def generate_luma_photon_images(prompt, image_count, format_type):
    """Генерирует изображения через Luma Photon"""
    try:
        # Определяем размер изображения
        size = get_replicate_size_for_model('Luma Photon', format_type)
        
        # Генерируем изображения
        images = []
        for i in range(image_count):
            output = replicate.run(
                "luma-ai/luma-photoreal",
                input={
                    "prompt": prompt,
                    "width": int(size.split('x')[0]),
                    "height": int(size.split('x')[1])
                }
            )
            
            # Обрабатываем результат
            if hasattr(output, 'url'):
                image_url = output.url
            elif isinstance(output, list) and len(output) > 0:
                image_url = output[0]
            else:
                image_url = str(output)
            
            if image_url and image_url.startswith('http'):
                images.append(image_url)
            
            # Небольшая задержка между генерациями
            if i < image_count - 1:
                await asyncio.sleep(1)
        
        return images
        
    except Exception as e:
        logging.error(f"Ошибка генерации Luma Photon: {e}")
        return []

async def generate_bria_images(prompt, image_count, format_type):
    """Генерирует изображения через Bria 3.2"""
    try:
        # Определяем размер изображения
        size = get_replicate_size_for_model('Bria 3.2', format_type)
        
        # Генерируем изображения
        images = []
        for i in range(image_count):
            output = replicate.run(
                "briaai/bria-3.2",
                input={
                    "prompt": prompt,
                    "width": int(size.split('x')[0]),
                    "height": int(size.split('x')[1])
                }
            )
            
            # Обрабатываем результат
            if hasattr(output, 'url'):
                image_url = output.url
            elif isinstance(output, list) and len(output) > 0:
                image_url = output[0]
            else:
                image_url = str(output)
            
            if image_url and image_url.startswith('http'):
                images.append(image_url)
            
            # Небольшая задержка между генерациями
            if i < image_count - 1:
                await asyncio.sleep(1)
        
        return images
        
    except Exception as e:
        logging.error(f"Ошибка генерации Bria: {e}")
        return []

async def generate_recraft_images(prompt, image_count, format_type):
    """Генерирует изображения через Recraft AI"""
    try:
        # Определяем размер изображения
        size = get_replicate_size_for_model('Recraft AI', format_type)
        
        # Генерируем изображения
        images = []
        for i in range(image_count):
            output = replicate.run(
                "recraftai/recraft-ai",
                input={
                    "prompt": prompt,
                    "width": int(size.split('x')[0]),
                    "height": int(size.split('x')[1])
                }
            )
            
            # Обрабатываем результат
            if hasattr(output, 'url'):
                image_url = output.url
            elif isinstance(output, list) and len(output) > 0:
                image_url = output[0]
            else:
                image_url = str(output)
            
            if image_url and image_url.startswith('http'):
                images.append(image_url)
            
            # Небольшая задержка между генерациями
            if i < image_count - 1:
                await asyncio.sleep(1)
        
        return images
        
    except Exception as e:
        logging.error(f"Ошибка генерации Recraft AI: {e}")
        return []

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
    app.add_handler(CommandHandler('stats', stats_command))
    app.add_handler(CommandHandler('ideogram_tips', ideogram_tips_command))
    app.add_handler(CommandHandler('edit_image', edit_image_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, text_handler))
    
    # Устанавливаем команды меню при запуске
    app.post_init = setup_commands
    
    # Проверяем, запущены ли мы на Railway
    port = int(os.environ.get('PORT', 0))
    
    if port:
        # Запускаем на Railway с webhook
        import asyncio
        
        async def start_webhook():
            await app.initialize()
            await app.start()
            
            # Устанавливаем webhook
            webhook_url = f"https://web-production-3dd82.up.railway.app/{TOKEN}"
            print(f"🌐 Устанавливаем webhook: {webhook_url}")
            
            try:
                await app.bot.set_webhook(url=webhook_url)
                print("✅ Webhook установлен успешно")
            except Exception as e:
                print(f"❌ Ошибка установки webhook: {e}")
                return
            
            # Запускаем webhook
            try:
                await app.updater.start_webhook(
                    listen="0.0.0.0",
                    port=port,
                    url_path=TOKEN,
                    webhook_url=webhook_url
                )
                print("✅ Webhook запущен успешно")
            except Exception as e:
                print(f"❌ Ошибка запуска webhook: {e}")
                return
            print(f"🚀 Бот запущен на Railway на порту {port}")
            print(f"🌐 Webhook URL: {webhook_url}")
            print(f"🔑 Token: {TOKEN[:10]}...")
            
            # Проверяем статус webhook
            try:
                webhook_info = await app.bot.get_webhook_info()
                print(f"📊 Webhook статус: {webhook_info}")
            except Exception as e:
                print(f"❌ Ошибка получения webhook статуса: {e}")
            
            # Держим приложение запущенным
            try:
                await asyncio.Event().wait()
            except KeyboardInterrupt:
                pass
        
        asyncio.run(start_webhook())
    else:
        # Запускаем локально с polling
        print("🚀 Бот запущен локально с polling")
        app.run_polling()

if __name__ == '__main__':
    main()

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
STEP_IMAGE_COUNT = 'image_count'
STEP_IMAGE_MODEL = 'image_model'
STEP_IMAGE_GENERATION = 'image_generation'
STEP_IMAGE_EDIT = 'image_edit'
STEP_VIDEO_QUALITY = 'video_quality'
STEP_VIDEO_DURATION = 'video_duration'
STEP_VIDEO_GENERATION = 'video_generation'

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
    'Bytedance Seedance 1.0 Pro': 'text-to-video + image-to-video, 480p/1080p'
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
• Нажмите "🎨 Создать контент" для создания видео или изображений
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
        [InlineKeyboardButton("📊 Моя статистика", callback_data="user_stats")],
        [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")]
    ]
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    USER_STATE[update.effective_user.id] = {'step': 'main_menu'}

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает главное меню"""
    keyboard = [
        [InlineKeyboardButton("🎨 Создать контент", callback_data="create_content")],
        [InlineKeyboardButton("🖼️ Создать изображения", callback_data="create_simple_images")],
        [InlineKeyboardButton("🎬 Создать видео", callback_data="video_generation")],
        [InlineKeyboardButton("✏️ Редактировать изображение", callback_data="edit_image")],
        [InlineKeyboardButton("🎨 Советы по Ideogram", callback_data="ideogram_tips")],
        [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
        [InlineKeyboardButton("ℹ️ О боте", callback_data="about_bot")]
    ]
    
    await update.callback_query.edit_message_text(
        "🎨 AI Image Generator\n\n"
        "Выберите, что хотите создать:",
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
        [InlineKeyboardButton("🎨 FLUX.1 Kontext Pro (редактирование изображений)", callback_data="image_gen_model:FLUX.1 Kontext Pro")],
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
"""
    
    keyboard = [
        [InlineKeyboardButton("🎨 Начать создание", callback_data="create_content")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    
    await update.message.reply_text(
        help_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def check_replicate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет статус Replicate API"""
    try:
        # Проверяем API токен
        api_token = os.environ.get('REPLICATE_API_TOKEN')
        if not api_token:
            await update.message.reply_text("❌ API токен Replicate не найден")
            return
        
        # Пробуем простой запрос к Replicate
        try:
            output = replicate.run(
                "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
                input={"prompt": "test"}
            )
            await update.message.reply_text("✅ Replicate API работает нормально")
        except Exception as e:
            error_msg = str(e)
            if "insufficient_credit" in error_msg.lower():
                await update.message.reply_text("❌ Недостаточно кредитов на Replicate")
            elif "api" in error_msg.lower() or "token" in error_msg.lower():
                await update.message.reply_text("❌ Ошибка API токена Replicate")
            else:
                await update.message.reply_text(f"❌ Ошибка Replicate: {error_msg}")
                
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при проверке Replicate: {e}")

async def test_ideogram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестирует Ideogram API"""
    try:
        await update.message.reply_text("🧪 Тестирую Ideogram v3 Turbo...")
        
        # Проверяем API токен
        api_token = os.environ.get('REPLICATE_API_TOKEN')
        if not api_token:
            await update.message.reply_text("❌ API токен Replicate не найден")
            return
        
        # Тестируем Ideogram v3 Turbo
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            output = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: replicate.run(
                    "ideogram-ai/ideogram-v3-turbo",
                    input={"prompt": "simple test image"}
                )),
                timeout=30.0  # 30 секунд для теста
            )
            
            # Обработка ответа от Replicate API
            image_url = None
            
            # Проверяем, является ли output объектом FileOutput
            if hasattr(output, 'url'):
                # Это объект FileOutput, используем его URL
                image_url = output.url
                await update.message.reply_text(f"✅ Получен URL из FileOutput: {image_url[:50]}...")
            elif hasattr(output, '__iter__') and not isinstance(output, str):
                # Если это итератор (генератор)
                try:
                    # Преобразуем в список и берем первый элемент
                    output_list = list(output)
                    if output_list:
                        image_url = output_list[0]
                except Exception as e:
                    await update.message.reply_text(f"❌ Ошибка при обработке итератора: {e}")
                    return
            else:
                # Если это не итератор, используем как есть
                image_url = output
            
            # Конвертация bytes в строку если необходимо (только для URL, не для бинарных данных)
            if isinstance(image_url, bytes):
                try:
                    # Пробуем декодировать как UTF-8 (для URL)
                    image_url = image_url.decode('utf-8')
                except UnicodeDecodeError:
                    # Если не удается декодировать как UTF-8, это может быть бинарные данные
                    await update.message.reply_text("❌ Получены бинарные данные вместо URL от Ideogram")
                    return
            
            if image_url:
                # Проверяем, что URL действительно работает
                if image_url.startswith(('http://', 'https://')):
                    await update.message.reply_text("✅ Ideogram v3 Turbo работает! Изображение сгенерировано.")
                else:
                    await update.message.reply_text("❌ Получен неверный URL от Ideogram")
            else:
                await update.message.reply_text("❌ Ideogram v3 Turbo вернул пустой результат")
                
        except asyncio.TimeoutError:
            await update.message.reply_text("❌ Ideogram v3 Turbo: таймаут (30 сек)\n\nМодель работает медленно или недоступна.")
        except Exception as e:
            error_msg = str(e)
            if "insufficient_credit" in error_msg.lower():
                await update.message.reply_text("❌ Недостаточно кредитов для Ideogram")
            else:
                await update.message.reply_text(f"❌ Ошибка Ideogram: {error_msg}")
                
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при тестировании Ideogram: {e}")

async def test_image_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестирует отправку изображений"""
    try:
        # Проверяем API токен Replicate
        if not os.environ.get('REPLICATE_API_TOKEN'):
            await update.message.reply_text("❌ Ошибка: API токен Replicate не найден")
            return
        
        # Генерируем простое изображение через Ideogram
        output = replicate.run(
            "ideogram-ai/ideogram-v3-turbo",
            input={"prompt": "A simple test image of a red apple on a white background, professional photography"}
        )
        
        # Обработка результата
        if hasattr(output, 'url'):
            image_url = output.url
        elif hasattr(output, '__getitem__'):
            image_url = output[0] if output else None
        elif isinstance(output, (list, tuple)) and len(output) > 0:
            image_url = output[0]
        else:
            image_url = str(output) if output else None
        
        if not image_url:
            await update.message.reply_text("❌ Не удалось получить изображение")
            return
        
        # Отправляем изображение
        await update.message.reply_photo(
            photo=image_url,
            caption="✅ Тест отправки изображений прошел успешно!"
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при тестировании: {e}")

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

async def admin_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для просмотра глобальной статистики (только для админов)"""
    user_id = update.effective_user.id
    
    # Проверяем, является ли пользователь админом
    admin_ids = [int(id.strip()) for id in os.getenv('ADMIN_IDS', '').split(',') if id.strip()]
    
    if user_id not in admin_ids:
        await update.message.reply_text("❌ У вас нет доступа к этой команде.")
        return
    
    analytics_db.update_user_activity(user_id)
    analytics_db.log_action(user_id, "admin_stats_command")
    
    # Получаем глобальную статистику
    global_stats = analytics_db.get_global_stats(30)
    daily_stats = analytics_db.get_daily_stats(7)
    
    stats_text = f"""
📊 **Глобальная статистика бота (30 дней):**

👥 **Пользователи:**
• Всего пользователей: {global_stats['total_users']}
• Активных за 30 дней: {global_stats['active_users_30d']}

🎨 **Генерации:**
• Всего генераций: {global_stats['total_generations']}
• За 30 дней: {global_stats['generations_30d']}
• Ошибок: {global_stats['total_errors']}
• Среднее время генерации: {global_stats['avg_generation_time']:.1f}с

🔥 **Популярные модели:**
"""
    
    # Добавляем популярные модели
    if global_stats['popular_models']:
        for model, count in global_stats['popular_models']:
            stats_text += f"• {model}: {count}\n"
    else:
        stats_text += "• Нет данных\n"
    
    stats_text += "\n📱 **Популярные форматы:**\n"
    
    # Добавляем популярные форматы
    if global_stats['popular_formats']:
        for format_type, count in global_stats['popular_formats']:
            stats_text += f"• {format_type}: {count}\n"
    else:
        stats_text += "• Нет данных\n"
    
    stats_text += "\n📅 **За последние 7 дней:**\n"
    
    # Добавляем ежедневную статистику
    if daily_stats:
        for date, generations, users, avg_time in daily_stats:
            avg_time_str = f"{avg_time:.1f}с" if avg_time else "N/A"
            stats_text += f"• {date}: {generations} генераций, {users} пользователей, {avg_time_str}\n"
    else:
        stats_text += "• Нет данных\n"
    
    keyboard = [
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
    # Убираем ограничение для коротких видео - теперь используем все найденные сцены
    # elif format_type and format_type.lower() in ['tiktok', 'instagram reels', 'youtube shorts']:
    #     # Для коротких видео по умолчанию 3 кадра, если не указано иное
    #     scenes = scenes[:3]
    
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

async def edit_image_with_flux(update, context, state, original_image_url, edit_prompt):
    """
    Редактирует изображение с помощью FLUX.1 Kontext Pro
    """
    # Определяем chat_id и функцию отправки сообщений
    if hasattr(update, 'message') and update.message:
        chat_id = update.message.chat_id
        send_text = update.message.reply_text
        send_media = update.message.reply_media_group
    elif hasattr(update, 'callback_query') and update.callback_query and update.callback_query.message:
        chat_id = update.callback_query.message.chat_id
        send_text = lambda text, **kwargs: context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
        send_media = lambda media, **kwargs: context.bot.send_media_group(chat_id=chat_id, media=media, **kwargs)
    else:
        chat_id = None
        send_text = None
        send_media = None
    
    try:
        if send_text:
            keyboard = [
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            await context.bot.send_message(
                chat_id=chat_id,
                text="🎨 Редактирую изображение с помощью FLUX.1 Kontext Pro...",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        # Проверяем API токен
        if not os.environ.get('REPLICATE_API_TOKEN'):
            logging.error("API токен Replicate не найден")
            if send_text:
                keyboard = [
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                ]
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Ошибка: API токен Replicate не найден",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            return None
        
        # Проверяем входные параметры
        if not original_image_url or not edit_prompt:
            logging.error("Отсутствуют обязательные параметры")
            if send_text:
                keyboard = [
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                ]
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Ошибка: отсутствуют обязательные параметры",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            return None
        
        # Загружаем изображение
        logging.info(f"Загружаем изображение с URL: {original_image_url}")
        try:
            response = requests.get(original_image_url, timeout=30)
            if response.status_code != 200:
                logging.error(f"Ошибка загрузки изображения: {response.status_code}")
                if send_text:
                    keyboard = [
                        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                    ]
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"❌ Не удалось загрузить исходное изображение (статус: {response.status_code})",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                return None
            logging.info(f"Изображение успешно загружено, размер: {len(response.content)} байт")
        except requests.exceptions.Timeout:
            logging.error("Таймаут при загрузке исходного изображения")
            if send_text:
                keyboard = [
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                ]
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Таймаут при загрузке исходного изображения",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            return None
        except Exception as e:
            logging.error(f"Ошибка загрузки изображения: {e}")
            if send_text:
                keyboard = [
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                ]
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Ошибка при загрузке исходного изображения",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            return None
        
        # Сохраняем изображение во временный файл
        temp_file_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as temp_file:
                temp_file.write(response.content)
                temp_file_path = temp_file.name
            
            # Открываем изображение с помощью PIL для получения размеров
            with Image.open(temp_file_path) as img:
                width, height = img.size
            
            # Генерируем отредактированное изображение через FLUX.1 Kontext Pro
            logging.info(f"Отправляем запрос в FLUX с промптом: {edit_prompt}")
            try:
                with open(temp_file_path, "rb") as image_file:
                    output = replicate.run(
                        "black-forest-labs/flux-kontext-pro",
                        input={
                            "input_image": image_file,
                            "prompt": edit_prompt,
                            "aspect_ratio": "match_input_image",
                            "output_format": "jpg",
                            "safety_tolerance": 2,
                            "prompt_upsampling": False
                        }
                    )
                logging.info(f"Получен ответ от FLUX: {output}")
                logging.info(f"Тип ответа: {type(output)}")
            except Exception as replicate_error:
                logging.error(f"Ошибка при вызове Replicate FLUX: {replicate_error}")
                logging.error(f"Тип ошибки Replicate: {type(replicate_error).__name__}")
                if send_text:
                    keyboard = [
                        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                    ]
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"❌ Ошибка при обработке изображения в FLUX: {str(replicate_error)}",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                return None
            
            # Обработка результата
            edited_image_url = None
            if hasattr(output, 'url'):
                if callable(output.url):
                    edited_image_url = output.url()
                else:
                    edited_image_url = output.url
            elif isinstance(output, list) and len(output) > 0:
                edited_image_url = output[0]
            elif isinstance(output, str):
                edited_image_url = output
            elif hasattr(output, '__getitem__'):
                edited_image_url = output[0] if output else None
            
            logging.info(f"Извлеченный URL: {edited_image_url}")
            
            if not edited_image_url:
                logging.error("Не удалось извлечь URL из ответа FLUX")
                if send_text:
                    keyboard = [
                        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                    ]
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="❌ Не удалось получить отредактированное изображение от FLUX",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                return None
            
            # Проверяем, что URL валидный
            if not edited_image_url.startswith('http'):
                logging.error(f"Некорректный URL отредактированного изображения: {edited_image_url}")
                if send_text:
                    keyboard = [
                        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                    ]
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="❌ Получен некорректный URL отредактированного изображения",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                return None
            
            # Отправляем результат
            try:
                # Загружаем отредактированное изображение
                logging.info(f"Загружаем отредактированное изображение с URL: {edited_image_url}")
                edited_response = requests.get(edited_image_url, timeout=30)
                logging.info(f"Статус загрузки отредактированного изображения: {edited_response.status_code}")
                
                if edited_response.status_code == 200:
                    logging.info(f"Успешно загружено отредактированное изображение, размер: {len(edited_response.content)} байт")
                    
                    try:
                        # Отправляем отредактированное изображение напрямую по URL
                        logging.info("Пытаемся отправить изображение по URL...")
                        await context.bot.send_photo(
                            chat_id=chat_id,
                            photo=edited_image_url,
                            caption=f"Отредактировано: {edit_prompt}"
                        )
                        logging.info("Изображение успешно отправлено по URL")
                        
                        # Отправляем сообщение об успехе с кнопкой главного меню
                        if send_text:
                            keyboard = [
                                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                            ]
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text="✅ Изображение успешно отредактировано!",
                                reply_markup=InlineKeyboardMarkup(keyboard)
                            )
                            
                    except Exception as send_error:
                        logging.error(f"Ошибка отправки по URL: {send_error}")
                        logging.error(f"Тип ошибки отправки: {type(send_error).__name__}")
                        
                        # Попробуем альтернативный способ - сохранить во временный файл
                        try:
                            logging.info("Пытаемся отправить изображение из файла...")
                            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as temp_edited:
                                temp_edited.write(edited_response.content)
                                temp_edited_path = temp_edited.name
                            
                            logging.info(f"Временный файл создан: {temp_edited_path}")
                            
                            # Отправляем отредактированное изображение из файла
                            with open(temp_edited_path, 'rb') as edited_file:
                                await context.bot.send_photo(
                                    chat_id=chat_id,
                                    photo=edited_file,
                                    caption=f"Отредактировано: {edit_prompt}"
                                )
                            
                            logging.info("Изображение успешно отправлено из файла")
                            
                            # Удаляем временный файл
                            try:
                                os.unlink(temp_edited_path)
                                logging.info("Временный файл удален")
                            except Exception as cleanup_error:
                                logging.warning(f"Не удалось удалить временный файл: {cleanup_error}")
                            
                            # Отправляем сообщение об успехе с кнопкой главного меню
                            if send_text:
                                keyboard = [
                                    [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                                ]
                                await context.bot.send_message(
                                    chat_id=chat_id,
                                    text="✅ Изображение успешно отредактировано!",
                                    reply_markup=InlineKeyboardMarkup(keyboard)
                                )
                                
                        except Exception as file_send_error:
                            logging.error(f"Ошибка отправки из файла: {file_send_error}")
                            logging.error(f"Тип ошибки файла: {type(file_send_error).__name__}")
                            if send_text:
                                keyboard = [
                                    [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                                ]
                                await context.bot.send_message(
                                    chat_id=chat_id,
                                    text="❌ Ошибка при отправке отредактированного изображения",
                                    reply_markup=InlineKeyboardMarkup(keyboard)
                                )
                        
                else:
                    logging.error(f"Ошибка загрузки отредактированного изображения: {edited_response.status_code}")
                    if send_text:
                        keyboard = [
                            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                        ]
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"❌ Не удалось загрузить отредактированное изображение (статус: {edited_response.status_code})",
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                        
            except requests.exceptions.Timeout:
                logging.error("Таймаут при загрузке отредактированного изображения")
                if send_text:
                    keyboard = [
                        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                    ]
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="❌ Таймаут при загрузке отредактированного изображения",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
            except Exception as e:
                logging.error(f"Общая ошибка отправки изображения: {e}")
                logging.error(f"Тип ошибки: {type(e).__name__}")
                logging.error(f"Детали ошибки: {str(e)}")
                if send_text:
                    keyboard = [
                        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                    ]
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="❌ Ошибка при отправке отредактированного изображения",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
        finally:
            # Удаляем временный файл
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except:
                    pass
        
        return edited_image_url
                
    except Exception as e:
        error_msg = str(e)
        logging.error(f"Общая ошибка в edit_image_with_flux: {e}")
        logging.error(f"Тип ошибки: {type(e).__name__}")
        logging.error(f"Детали ошибки: {str(e)}")
        
        if "insufficient_credit" in error_msg.lower():
            if send_text:
                keyboard = [
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                ]
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Недостаточно кредитов на Replicate для FLUX.1 Kontext Pro\n\nПополните баланс на https://replicate.com/account/billing",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        elif "api" in error_msg.lower() or "token" in error_msg.lower():
            if send_text:
                keyboard = [
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                ]
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Ошибка API Replicate\n\nПроверьте настройки API токена",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        else:
            if send_text:
                keyboard = [
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                ]
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Ошибка при редактировании изображения: {error_msg}",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        return None

async def send_images(update, context, state, prompt_type='auto', user_prompt=None, scenes=None):
    """
    Генерирует 2-3 изображения по коротким промптам через GPT и отправляет их пользователю.
    prompt_type: 'auto' — промпты формируются автоматически, 'user' — по пользовательскому описанию.
    user_prompt: если prompt_type == 'user', использовать этот промпт.
    """

    # Определяем chat_id и функцию отправки сообщений
    if hasattr(update, 'message') and update.message:
        chat_id = update.message.chat_id
        send_text = update.message.reply_text
        send_media = update.message.reply_media_group
    elif hasattr(update, 'callback_query') and update.callback_query and update.callback_query.message:
        chat_id = update.callback_query.message.chat_id
        send_text = lambda text, **kwargs: context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
        send_media = lambda media, **kwargs: context.bot.send_media_group(chat_id=chat_id, media=media, **kwargs)
    else:
        # fallback
        chat_id = None
        send_text = None
        send_media = None
    user_id = update.effective_user.id
    
    # Логируем начало генерации
    analytics_db.update_user_activity(user_id)
    analytics_db.log_action(user_id, "start_generation", f"format:{state.get('format', 'unknown')}, model:{state.get('image_gen_model', 'unknown')}")
    
    # Засекаем время начала генерации
    start_time = time.time()
    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    images = []
    prompts = []
    processed_count = 0  # Счетчик успешно обработанных изображений
    
    # Проверяем наличие API токенов
    if not os.getenv('REPLICATE_API_TOKEN'):
        if send_text:
            keyboard = [
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await send_text("❌ Ошибка: REPLICATE_API_TOKEN не установлен\n\nОбратитесь к администратору бота.", reply_markup=reply_markup)
        return
    
    # Проверяем баланс Replicate
    try:
        import replicate
        replicate_client = replicate.Client(api_token=os.getenv('REPLICATE_API_TOKEN'))
        # Попытка получить информацию об аккаунте для проверки баланса
        try:
            # Простая проверка доступности API
            test_response = replicate.run(
                "replicate/hello-world",
                input={"text": "test"}
            )
            # Если дошли до сюда, значит API работает
        except Exception as e:
            error_msg = str(e).lower()
            if "insufficient_credit" in error_msg or "insufficient credit" in error_msg or "billing" in error_msg:
                if send_text:
                    keyboard = [
                        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await send_text("❌ Недостаточно кредитов на Replicate\n\nПополните баланс на https://replicate.com/account/billing или обратитесь к администратору.", reply_markup=reply_markup)
                return
            elif "unauthorized" in error_msg or "invalid" in error_msg:
                if send_text:
                    keyboard = [
                        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await send_text("❌ Ошибка авторизации Replicate API\n\nПроверьте токен или обратитесь к администратору.", reply_markup=reply_markup)
                return
    except Exception as e:
        if send_text:
            keyboard = [
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await send_text(f"❌ Ошибка при проверке Replicate API: {str(e)[:100]}...\n\nОбратитесь к администратору.", reply_markup=reply_markup)
        return
    
    # Определяем максимальное количество изображений
    user_format = state.get('format', '').lower()
    image_count = state.get('image_count', 'default')
    
    # Логируем параметры для отладки
    if send_text:
        await send_text(f"🔍 Отладка: format='{user_format}', image_count='{image_count}', prompt_type='{prompt_type}', user_prompt='{user_prompt}'")
        await send_text(f"🔍 Состояние: {state}")
    
    # Если у нас есть сцены, используем их количество
    if scenes:
        max_scenes = len(scenes)
    elif image_count == 'all_scenes':
        max_scenes = 7
    elif image_count == 'auto':
        max_scenes = 2  # Для генерации промптов по умолчанию 2, если не указано иначе
    elif user_format in ['instagram reels', 'tiktok', 'youtube shorts'] and image_count == 'default':
        max_scenes = 2  # Для коротких видео по умолчанию 2
    elif user_format in ['instagram stories'] and image_count == 'default':
        max_scenes = 1  # Для Instagram Stories по умолчанию 1 изображение
    elif user_format in ['instagram post'] and image_count == 'default':
        max_scenes = 2  # Для постов по умолчанию 2 изображения
    elif isinstance(image_count, int):
        max_scenes = min(image_count, 10)  # максимум 10
    else:
        max_scenes = 2  # по умолчанию для остальных форматов

    # Ограничиваем максимальное количество изображений до 10 (лимит Telegram)
    # Но если пользователь выбрал конкретное количество, строго соблюдаем его
    if isinstance(image_count, int):
        max_scenes = image_count  # Строго соблюдаем выбранное пользователем количество
    else:
        max_scenes = min(max_scenes, 10)  # Для остальных случаев ограничиваем до 10
    
    if prompt_type == 'auto':
        # Если scenes переданы — используем их для раскадровки
        if scenes:
            prompts = scenes[:max_scenes]
        else:
            # Создаём качественные промпты для изображений
            topic = state.get('topic', '')
            
            # Определяем модель для генерации
            selected_model = state.get('image_gen_model', 'Ideogram')
            
            # Создаём промпты в зависимости от выбранной модели
            if selected_model == 'Ideogram':
                # Для Ideogram используем более простые и точные промпты
                # Ideogram лучше работает с простыми, четкими описаниями
                prompts = []
                
                # Создаем базовые промпты без лишних суффиксов
                if max_scenes >= 1:
                    prompts.append(f"{topic}")
                if max_scenes >= 2:
                    prompts.append(f"{topic}, professional design")
                if max_scenes >= 3:
                    prompts.append(f"{topic}, modern style")
                
                # Ограничиваем количество промптов
                prompts = prompts[:max_scenes]
            elif selected_model == 'Bytedance (Seedream-3)':
                # Для Bytedance Seedream-3 - нативная 2K генерация, быстрая
                prompts = [
                    f"{topic}, high quality, professional, detailed composition, architectural design, modern aesthetic",
                    f"{topic}, premium quality, well balanced, sharp focus, clean design, sophisticated style",
                    f"{topic}, excellent quality, clear details, professional result, contemporary design, elegant composition"
                ][:max_scenes]
            elif selected_model == 'Google Imagen 4 Ultra':
                # Для Google Imagen 4 Ultra - максимальное качество и детали
                prompts = [
                    f"{topic}, photorealistic, ultra high quality, maximum detail, 8k resolution, professional photography, studio lighting",
                    f"{topic}, hyperrealistic, intricate details, perfect composition, cinematic quality, premium photography",
                    f"{topic}, ultra detailed, professional grade, perfect lighting, high end photography, masterpiece quality"
                ][:max_scenes]
            elif selected_model == 'Luma Photon':
                # Для Luma Photon - креативные возможности, высокое качество
                prompts = [
                    f"{topic}, high quality, detailed, cinematic lighting, creative composition, professional result",
                    f"{topic}, artistic style, excellent quality, creative vision, detailed composition, premium quality",
                    f"{topic}, creative approach, high resolution, professional lighting, detailed result, artistic quality"
                ][:max_scenes]
            elif selected_model == 'Bria 3.2':
                # Для Bria 3.2 - коммерческое использование, 4B параметров
                prompts = [
                    f"{topic}, professional quality, high resolution, clean composition, commercial grade, safe content",
                    f"{topic}, excellent quality, professional result, clear details, commercial use, premium quality",
                    f"{topic}, high quality, professional photography, detailed composition, commercial standard, clean result"
                ][:max_scenes]
            elif selected_model == 'Recraft AI':
                # Для Recraft AI - дизайн, вектор, логотипы, SVG
                prompts = [
                    f"{topic}, SVG design, logo style, brand identity, clean composition, professional design, modern aesthetic, vector graphics",
                    f"{topic}, design elements, brand graphics, modern logo concept, clean art style, professional branding, scalable design",
                    f"{topic}, design system, brand design, graphic elements, logo style, professional identity, clean design, vector art"
                ][:max_scenes]
            else:
                # Для Ideogram используем OpenAI для создания детальных промптов
                image_prompts = (
                    f"Тема: {topic}\n"
                    f"Создай {max_scenes} детальных промпта на английском языке для генерации изображений. "
                    f"ВАЖНО: "
                    f"- Каждый промпт должен точно описывать {topic} "
                    f"- Добавь конкретные детали, особенности, элементы {topic} "
                    f"- Используй: professional photography, ultra high quality, 8k resolution, sharp focus, natural lighting "
                    f"- НЕ добавляй людей, если они не упомянуты в теме "
                    f"- Каждый промпт должен быть уникальным и показывать разные аспекты {topic} "
                    f"Примеры для разных тем: "
                    f"- Турбаза: 'wooden cabin resort, forest landscape, professional photography', 'russian bathhouse, steam room, traditional design' "
                    f"- Спортзал: 'modern gym interior, fitness equipment, professional lighting', 'weight training area, cardio machines, clean design' "
                    f"- Кафе: 'cozy cafe interior, coffee shop, modern design', 'outdoor seating, garden cafe, comfortable atmosphere' "
                    f"- Только если в теме есть люди: 'beautiful brunette woman in elegant dress', 'attractive woman with long hair', 'gorgeous woman looking at camera' "
                    f"Ответ выдай списком, каждый промпт с новой строки, без номеров и кавычек."
                )
                
                try:
                    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
                    response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": "Ты эксперт по созданию промптов для генерации изображений. Создавай детальные, профессиональные промпты на английском языке, которые точно описывают тему и включают конкретные детали. Избегай общих фраз, используй специфичные элементы. НЕ добавляй людей в промпты, если они не упомянуты в теме."},
                            {"role": "user", "content": image_prompts}
                        ],
                        max_tokens=800,
                        temperature=0.7,
                    )
                    raw_prompts = response.choices[0].message.content.strip()
                    prompts = [p.strip() for p in raw_prompts.split('\n') if p.strip() and not p.strip().startswith(('1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.'))]
                    prompts = prompts[:max_scenes]
                    
                    # Если промпты получились слишком короткими, добавляем качественные суффиксы
                    enhanced_prompts = []
                    for prompt in prompts:
                        if len(prompt.split()) < 8:  # Если промпт слишком короткий
                            enhanced_prompt = f"{prompt}, professional photography, ultra high quality, 8k resolution, sharp focus, natural lighting"
                        else:
                            enhanced_prompt = prompt
                        enhanced_prompts.append(enhanced_prompt)
                    prompts = enhanced_prompts
                    
                except Exception as e:
                    # Fallback на простые промпты если OpenAI недоступен
                    prompts = [
                        f"{topic}, professional photography, ultra high quality, 8k resolution, sharp focus, natural lighting",
                        f"{topic}, modern design, contemporary style, professional environment, high quality photography"
                    ][:max_scenes]
    elif prompt_type == 'user' and user_prompt:
        prompts = [user_prompt] * min(3, max_scenes)
    else:
        prompts = [state.get('topic', '')] * min(3, max_scenes)
    
    # Улучшаем промпты, добавляя контекст персонажей
    topic = state.get('topic', '')
    prompts = enhance_prompts_with_character_context(prompts, topic)
    
    # Фильтрация промптов
    safe_prompts = []
    blocked_prompts = []
    for prompt in prompts:
        if is_prompt_safe(prompt):
            safe_prompts.append(prompt)
        else:
            blocked_prompts.append(prompt)
    if not safe_prompts:
        if send_text:
            msg = "Все сгенерированные описания содержат запрещённые слова. Пожалуйста, попробуйте ещё раз или уточните тему."
            if blocked_prompts:
                msg += "\nБлокированы промпты:\n" + "\n".join(blocked_prompts)
            
            # Добавляем кнопки для навигации
            keyboard = [
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="retry_generation")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await send_text(msg, reply_markup=reply_markup)
        return
    if blocked_prompts and send_text:
        msg = "Некоторые описания были заблокированы фильтром и не будут сгенерированы:\n" + "\n".join(blocked_prompts)
        await send_text(msg)
    media = []
    for idx, prompt in enumerate(safe_prompts, 1):
        if idx > max_scenes:
            break
        # Добавляем стиль генерации к промпту (упрощенная версия для Ideogram)
        image_gen_style = state.get('image_gen_style', '')
        selected_model = state.get('image_gen_model', 'Ideogram')
        style_suffix = ''
        
        if image_gen_style and selected_model != 'Ideogram':
            # Для других моделей используем полные стили
            if image_gen_style == 'Фотореализм':
                style_suffix = ', photorealistic, ultra-realistic, high detail, 8k, professional photography, sharp focus, natural lighting, cinematic, award-winning photo'
            elif image_gen_style == 'Иллюстрация':
                style_suffix = ', illustration, digital art, high detail, artistic, creative, vibrant colors'
            elif image_gen_style == 'Минимализм':
                style_suffix = ', minimalism, clean, simple, high contrast, modern design, geometric shapes'
            elif image_gen_style == 'Акварель':
                style_suffix = ', watercolor, painting, soft colors, artistic, flowing, organic'
            elif image_gen_style == 'Масляная живопись':
                style_suffix = ', oil painting, canvas texture, brush strokes, artistic, traditional art'
            elif image_gen_style == 'Пиксель-арт':
                style_suffix = ', pixel art, 8-bit, retro style, digital art'
        elif image_gen_style and selected_model == 'Ideogram':
            # Для Ideogram используем минимальные стили
            if image_gen_style == 'Фотореализм':
                style_suffix = ', realistic'
            elif image_gen_style == 'Иллюстрация':
                style_suffix = ', illustration'
            elif image_gen_style == 'Минимализм':
                style_suffix = ', minimal'
            elif image_gen_style == 'Акварель':
                style_suffix = ', watercolor'
            elif image_gen_style == 'Масляная живопись':
                style_suffix = ', oil painting'
            elif image_gen_style == 'Пиксель-арт':
                style_suffix = ', pixel art'
        
        # Добавляем формат для разных типов контента (упрощенная версия для Ideogram)
        format_suffix = ''
        user_format = state.get('format', '').lower().replace(' ', '')
        simple_orientation = state.get('simple_orientation', None)
        
        if selected_model == 'Ideogram':
            # Для Ideogram используем минимальные форматные указания
            if user_format == 'instagramstories':
                format_suffix = ', vertical'
            elif user_format == 'instagramreels':
                format_suffix = ', vertical'
            elif user_format == 'tiktok':
                format_suffix = ', vertical'
            elif user_format == 'youtubeshorts':
                format_suffix = ', vertical'
            elif user_format == 'instagrampost':
                format_suffix = ', square'
            elif user_format == 'изображения':
                # Для "Изображения" добавляем указания в зависимости от выбранной ориентации
                if simple_orientation == 'vertical':
                    format_suffix = ', vertical'
                elif simple_orientation == 'square':
                    format_suffix = ', square'
                else:
                    format_suffix = ', square'  # По умолчанию квадратный
        else:
            # Для других моделей используем полные форматные указания
            if user_format == 'instagramstories':
                format_suffix = ', vertical composition, Instagram Stories format, mobile optimized, space for text overlay'
            elif user_format == 'instagramreels':
                format_suffix = ', vertical composition, mobile video format, dynamic composition'
            elif user_format == 'tiktok':
                format_suffix = ', vertical composition, TikTok format, mobile optimized, trending style'
            elif user_format == 'youtubeshorts':
                format_suffix = ', vertical composition, YouTube Shorts format, mobile video optimized'
            elif user_format == 'instagrampost':
                format_suffix = ', square composition, Instagram Post format, social media optimized'
            elif user_format == 'изображения':
                # Для "Изображения" добавляем указания в зависимости от выбранной ориентации
                if simple_orientation == 'vertical':
                    format_suffix = ', vertical composition, portrait orientation, tall vertical image'
                elif simple_orientation == 'square':
                    format_suffix = ', square composition, balanced layout'
                else:
                    format_suffix = ', square composition, balanced layout'  # По умолчанию квадратный
        
        prompt_with_style = prompt + style_suffix + format_suffix
        
        # Улучшаем промпт для Ideogram
        if selected_model == 'Ideogram':
            prompt_with_style = improve_prompt_for_ideogram(prompt_with_style)
        
        # Определяем размер изображения на основе формата и модели
        image_size = get_image_size_for_format(user_format, simple_orientation)
        selected_model = state.get('image_gen_model', 'Ideogram')
        simple_orientation = state.get('simple_orientation', None)
        replicate_params = get_replicate_params_for_model(selected_model, user_format, simple_orientation)
        

        
        try:
            if send_text:
                caption = f'Сцена {idx}: {prompt}' if scenes else f'Вариант {idx}'
                await send_text(f'Генерирую изображение {idx}...')
            
            # Определяем модель для генерации
            selected_model = state.get('image_gen_model', 'Ideogram')
            
            # Генерация изображения в зависимости от выбранной модели
            if selected_model == 'Ideogram':
                try:
                    if send_text:
                        await send_text(f"🎨 Генерирую через Ideogram...\n\n💡 Совет: Ideogram лучше работает с простыми, четкими описаниями")
                    
                    # Генерация через Ideogram на Replicate с таймаутом
                    import asyncio
                    try:
                        # Проверяем API токен
                        if not os.environ.get('REPLICATE_API_TOKEN'):
                            if send_text:
                                keyboard = [
                                    [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                                ]
                                reply_markup = InlineKeyboardMarkup(keyboard)
                                await send_text(f"❌ Ошибка: API токен Replicate не найден", reply_markup=reply_markup)
                            continue
                        
                        # Запускаем генерацию с таймаутом
                        loop = asyncio.get_event_loop()
                        
                        # Используем Ideogram v3 Turbo (более стабильная версия)
                        try:
                            output = await asyncio.wait_for(
                                loop.run_in_executor(None, lambda: replicate.run(
                                    "ideogram-ai/ideogram-v3-turbo",
                                    input={"prompt": prompt_with_style, **replicate_params}
                                )),
                                timeout=60.0  # Увеличиваем таймаут до 60 секунд для Ideogram
                            )
                        except Exception as e:
                            # Если v3 не работает, пробуем v2
                            if send_text:
                                await send_text(f"⚠️ Ideogram v3 Turbo недоступен, пробуем v2...")
                            try:
                                output = await asyncio.wait_for(
                                    loop.run_in_executor(None, lambda: replicate.run(
                                        "ideogram-ai/ideogram-v2",
                                        input={"prompt": prompt_with_style, **replicate_params}
                                    )),
                                    timeout=60.0
                                )
                            except Exception as e2:
                                if send_text:
                                    await send_text(f"❌ Ideogram недоступен: {str(e2)[:100]}...\n💡 Попробуйте выбрать другую модель (Bytedance, Google Imagen)")
                                continue
                        
                        # Обработка ответа от Replicate API
                        image_url = None
                        
                        # Проверяем, является ли output объектом FileOutput
                        if hasattr(output, 'url'):
                            # Это объект FileOutput, используем его URL
                            image_url = output.url
                        elif hasattr(output, '__iter__') and not isinstance(output, str):
                            # Если это итератор (генератор)
                            try:
                                # Преобразуем в список и берем первый элемент
                                output_list = list(output)
                                if output_list:
                                    image_url = output_list[0]
                            except Exception as e:
                                if send_text:
                                    await send_text(f"❌ Ошибка при обработке итератора: {e}")
                                continue
                        else:
                            # Если это не итератор, используем как есть
                            image_url = output
                        
                        # Проверяем, что получили URL
                        if not image_url:
                            if send_text:
                                await send_text(f"❌ Не удалось получить изображение от Ideogram (пустой результат)")
                            continue
                        
                        # Конвертация bytes в строку если необходимо (только для URL, не для бинарных данных)
                        if isinstance(image_url, bytes):
                            try:
                                # Пробуем декодировать как UTF-8 (для URL)
                                image_url = image_url.decode('utf-8')
                            except UnicodeDecodeError:
                                # Если не удается декодировать как UTF-8, это может быть бинарные данные
                                if send_text:
                                    await send_text(f"❌ Получены бинарные данные вместо URL от Ideogram")
                                continue
                        
                        # Проверяем, что это строка и начинается с http
                        if not isinstance(image_url, str):
                            if send_text:
                                await send_text(f"❌ Неверный тип URL от Ideogram")
                            continue
                        
                        if not image_url.startswith(('http://', 'https://')):
                            if send_text:
                                await send_text(f"❌ Получен неверный URL от Ideogram")
                            continue
                            
                    except asyncio.TimeoutError:
                        if send_text:
                            await send_text(f"⏰ Таймаут при генерации через Ideogram (60 секунд)\n\n💡 Ideogram может работать медленно. Попробуйте:\n• Выбрать другую модель (Bytedance, Google Imagen)\n• Упростить описание\n• Попробовать снова")
                        continue
                        
                except Exception as e:
                    error_msg = str(e)
                    if "insufficient_credit" in error_msg.lower() or "insufficient credit" in error_msg.lower():
                        if send_text:
                            keyboard = [
                                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                            ]
                            reply_markup = InlineKeyboardMarkup(keyboard)
                            await send_text(f"❌ Недостаточно кредитов на Replicate для Ideogram\n\nПополните баланс на https://replicate.com/account/billing или выберите другую модель.", reply_markup=reply_markup)
                    elif "api" in error_msg.lower() or "token" in error_msg.lower():
                        if send_text:
                            keyboard = [
                                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                            ]
                            reply_markup = InlineKeyboardMarkup(keyboard)
                            await send_text(f"❌ Ошибка API Replicate\n\nПроверьте настройки API токена или выберите другую модель.", reply_markup=reply_markup)
                    else:
                        if send_text:
                            keyboard = [
                                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="retry_generation")]
                            ]
                            reply_markup = InlineKeyboardMarkup(keyboard)
                            await send_text(f"❌ Ошибка при генерации через Ideogram: {error_msg}\n\nПопробуйте выбрать другую модель или выберите действие ниже:", reply_markup=reply_markup)
                    continue
            elif selected_model == 'Bytedance (Seedream-3)':
                try:
                    if send_text:
                        await send_text(f"Генерирую через Bytedance Seedream-3 (нативная 2K генерация, быстрая)...")
                    
                    # Генерация через Bytedance на Replicate
                    output = replicate.run(
                        "bytedance/seedream-3",
                        input={"prompt": prompt_with_style, **replicate_params}
                    )
                    
                    # Обработка результата
                    if hasattr(output, 'url'):
                        image_url = output.url
                    elif hasattr(output, '__getitem__'):
                        image_url = output[0] if output else None
                    elif isinstance(output, (list, tuple)) and len(output) > 0:
                        image_url = output[0]
                    else:
                        image_url = str(output) if output else None
                    
                    # Отладочная информация убрана для чистоты интерфейса
                except Exception as e:
                    if send_text:
                        await send_text(f"Ошибка при генерации через Bytedance: {e}")
                    continue
            elif selected_model == 'Google Imagen 4 Ultra':
                try:
                    if send_text:
                        await send_text(f"Генерирую через Google Imagen 4 Ultra (максимальное качество, детали)...")
                    
                    # Генерация через Google Imagen 4 на Replicate
                    output = replicate.run(
                        "google/imagen-4-ultra",
                        input={"prompt": prompt_with_style, **replicate_params}
                    )
                    
                    # Обработка результата
                    if hasattr(output, 'url'):
                        image_url = output.url
                    elif hasattr(output, '__getitem__'):
                        image_url = output[0] if output else None
                    elif isinstance(output, (list, tuple)) and len(output) > 0:
                        image_url = output[0]
                    else:
                        image_url = str(output) if output else None
                    
                    # Отладочная информация убрана для чистоты интерфейса
                except Exception as e:
                    if send_text:
                        await send_text(f"Ошибка при генерации через Google Imagen 4: {e}")
                    continue
            elif selected_model == 'Luma Photon':
                try:
                    if send_text:
                        await send_text(f"Генерирую через Luma Photon (креативные возможности, высокое качество)...")
                    
                    # Генерация через Luma на Replicate
                    output = replicate.run(
                        "luma/photon",
                        input={"prompt": prompt_with_style, **replicate_params}
                    )
                    
                    # Обработка результата
                    if hasattr(output, 'url'):
                        image_url = output.url
                    elif hasattr(output, '__getitem__'):
                        image_url = output[0] if output else None
                    elif isinstance(output, (list, tuple)) and len(output) > 0:
                        image_url = output[0]
                    else:
                        image_url = str(output) if output else None
                    
                    # Отладочная информация убрана для чистоты интерфейса
                except Exception as e:
                    if send_text:
                        await send_text(f"Ошибка при генерации через Luma: {e}")
                    continue
            elif selected_model == 'Bria 3.2':
                try:
                    if send_text:
                        await send_text(f"Генерирую через Bria 3.2 (коммерческое использование, 4B параметров)...")
                    
                    # Генерация через Bria на Replicate
                    output = replicate.run(
                        "bria/image-3.2",
                        input={"prompt": prompt_with_style, **replicate_params}
                    )
                    
                    # Обработка результата
                    if hasattr(output, 'url'):
                        image_url = output.url
                    elif hasattr(output, '__getitem__'):
                        image_url = output[0] if output else None
                    elif isinstance(output, (list, tuple)) and len(output) > 0:
                        image_url = output[0]
                    else:
                        image_url = str(output) if output else None
                    
                    # Отладочная информация убрана для чистоты интерфейса
                except Exception as e:
                    if send_text:
                        await send_text(f"Ошибка при генерации через Bria: {e}")
                    continue
            elif selected_model == 'Recraft AI':
                try:
                    if send_text:
                        await send_text(f"Генерирую через Recraft AI (дизайн, вектор, логотипы)...")
                    
                    # Генерация через Recraft AI на Replicate
                    output = replicate.run(
                        "recraft-ai/recraft-v3-svg",
                        input={"prompt": prompt_with_style, **replicate_params}
                    )
                    
                    # Обработка FileOutput объекта для Recraft AI
                    if hasattr(output, 'url'):
                        image_url = output.url
                    elif hasattr(output, '__getitem__'):
                        image_url = output[0] if output else None
                    elif isinstance(output, (list, tuple)) and len(output) > 0:
                        image_url = output[0]
                    else:
                        image_url = str(output) if output else None
                    
                    # Проверяем, является ли файл SVG
                    if image_url and image_url.endswith('.svg'):
                        if send_text:
                            await send_text("⚠️ Recraft AI сгенерировал SVG файл. Telegram не поддерживает SVG напрямую.")
                            await send_text("🔗 Ссылка на изображение: " + image_url)
                            await send_text("💡 Попробуйте другую модель или сохраните ссылку для просмотра в браузере.")
                        
                        # Увеличиваем счетчик обработанных изображений
                        processed_count += 1
                        
                        # Пропускаем отправку SVG файла
                        continue
                        
                except Exception as e:
                    if send_text:
                        await send_text(f"Ошибка при генерации через Recraft AI: {e}")
                    continue

            else:  # Fallback на Ideogram
                try:
                    if send_text:
                        await send_text(f"Генерирую через Ideogram (универсальная модель)...")
                    
                    # Fallback на Ideogram если модель не поддерживается
                    output = replicate.run(
                        "ideogram-ai/ideogram-v3-turbo",
                        input={"prompt": prompt_with_style, **replicate_params}
                    )
                    
                    # Обработка результата
                    if hasattr(output, 'url'):
                        image_url = output.url
                    elif hasattr(output, '__getitem__'):
                        image_url = output[0] if output else None
                    elif isinstance(output, (list, tuple)) and len(output) > 0:
                        image_url = output[0]
                    else:
                        image_url = str(output) if output else None
                except Exception as e:
                    if send_text:
                        await send_text(f"Ошибка при генерации изображения {idx}: {e}")
                    continue
            
            images.append(image_url)
            media.append(InputMediaPhoto(media=image_url, caption=caption))
            processed_count += 1
            
            # Отладочная информация убрана для чистоты интерфейса
        except Exception as e:
            if send_text:
                await send_text(f"Ошибка при генерации изображения {idx}: {e}")
    if media and send_media:
        await send_media(media=media)
    elif processed_count == 0 and send_text:
        keyboard = [
            [InlineKeyboardButton("🔄 Попробовать снова", callback_data="retry_generation")],
            [InlineKeyboardButton("❓ Помощь с фильтрами", callback_data="help_filters")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await send_text("❌ Не удалось сгенерировать ни одного изображения\n\nПопробуйте еще раз или выберите действие ниже:", reply_markup=reply_markup)
    # Логируем результаты генерации
    generation_time = time.time() - start_time
    selected_model = state.get('image_gen_model', 'Ideogram')
    format_type = state.get('format', 'unknown')
    
    # Логируем успешную генерацию
    if processed_count > 0:
        analytics_db.log_generation(
            user_id=user_id,
            model_name=selected_model,
            format_type=format_type,
            prompt=state.get('topic', 'unknown'),
            image_count=processed_count,
            success=True,
            generation_time=generation_time
        )
        analytics_db.log_action(user_id, "generation_success", f"count:{processed_count}, time:{generation_time:.1f}s")
    else:
        # Логируем неудачную генерацию
        analytics_db.log_generation(
            user_id=user_id,
            model_name=selected_model,
            format_type=format_type,
            prompt=state.get('topic', 'unknown'),
            image_count=0,
            success=False,
            error_message="No images generated",
            generation_time=generation_time
        )
        analytics_db.log_action(user_id, "generation_failed", f"time:{generation_time:.1f}s")
    
    # Сохраняем сгенерированные изображения для редактирования
    if images:
        state['last_generated_images'] = images
    
    # Сохраняем последние настройки для повторного использования
    state['last_prompt_type'] = prompt_type
    state['last_user_prompt'] = user_prompt
    state['last_settings'] = {
        'model': state.get('image_gen_model', 'Ideogram'),
        'style': state.get('image_gen_style', ''),
        'count': state.get('image_count', 2)
    }
    USER_STATE[user_id] = state
    
    # Сохраняем сцены для повторной генерации
    if scenes:
        # Если это первая генерация, сохраняем все сцены
        if 'last_scenes' not in state:
            state['last_scenes'] = scenes
            state['total_scenes_count'] = len(scenes)
        
        # Сохраняем информацию о том, сколько сцен было сгенерировано
        if 'generated_scenes_count' not in state:
            # Если это первая генерация, устанавливаем счетчик
            state['generated_scenes_count'] = len(scenes[:max_scenes]) if isinstance(max_scenes, int) else len(scenes)
        else:
            # Если это не первая генерация, добавляем к уже сгенерированным
            current_generated = state.get('generated_scenes_count', 0)
            new_scenes_count = len(scenes[:max_scenes]) if isinstance(max_scenes, int) else len(scenes)
            state['generated_scenes_count'] = current_generated + new_scenes_count
    
    # Создаем кнопки с учетом сохраненных настроек
    user_format = state.get('format', '').lower()
    if user_format == 'изображения':
        # Для "Изображения" показываем сохраненные настройки
        last_settings = state.get('last_settings', {})
        settings_text = f"({last_settings.get('model', 'Ideogram')}, {last_settings.get('style', '')}, {last_settings.get('count', 2)} шт.)"
        
        keyboard = [
            [InlineKeyboardButton(f"🔄 С теми же настройками {settings_text}", callback_data="more_images_same_settings")],
            [InlineKeyboardButton("⚙️ Изменить настройки", callback_data="change_settings")],
            [InlineKeyboardButton("📝 Только новое описание", callback_data="custom_image_prompt")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if send_text:
            await send_text("Хотите создать еще картинки?", reply_markup=reply_markup)
    else:
        # Для остальных форматов - проверяем, есть ли еще сцены для генерации
        generated_count = state.get('generated_scenes_count', 0)
        total_count = state.get('total_scenes_count', 0)
        
        keyboard = []
        
        # Кнопка для генерации тех же изображений заново
        keyboard.append([InlineKeyboardButton("🔄 Сгенерировать ещё (те же сцены)", callback_data="more_images")])
        
        # Если есть еще сцены для генерации, добавляем кнопки
        if total_count > generated_count:
            remaining_count = total_count - generated_count
            start_scene = generated_count + 1
            end_scene = total_count
            keyboard.append([InlineKeyboardButton(f"📸 Сгенерировать сцены {start_scene}-{end_scene}", callback_data="generate_remaining_scenes")])
            keyboard.append([InlineKeyboardButton(f"📸 Сгенерировать все сцены 1-{total_count}", callback_data="generate_all_scenes")])
        
        # Кнопка для выбора конкретного количества
        keyboard.append([InlineKeyboardButton("🔢 Выбрать количество сцен", callback_data="select_scene_count")])
        
        # Кнопки для генерации видео
        keyboard.extend([
            [InlineKeyboardButton("🎬 Создать видео из изображений", callback_data="create_video_from_images")],
            [InlineKeyboardButton("🎭 Создать видео по сценарию", callback_data="create_video_from_script")],
        ])
        
        # Остальные кнопки
        keyboard.extend([
            [InlineKeyboardButton("Уточнить, что должно быть на картинке", callback_data="custom_image_prompt")],
            [InlineKeyboardButton("🔄 Сбросить", callback_data="reset")],
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        if send_text:
            await send_text("Хотите другие варианты или уточнить, что должно быть на картинке?", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    state = USER_STATE.get(user_id, {})
    data = query.data

    # Обработка статистики пользователя
    if data == "user_stats":
        analytics_db.update_user_activity(user_id)
        analytics_db.log_action(user_id, "view_stats_button")
        
        # Получаем статистику пользователя
        user_stats = analytics_db.get_user_stats(user_id)
        
        if not user_stats:
            await query.edit_message_text(
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
        
        await query.edit_message_text(
            stats_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # Новые обработчики навигации
    if data == "help_filters":
        help_filters_text = (
            "🚫 **Проблема с фильтрами моделей**\n\n"
            "Некоторые модели имеют строгие фильтры безопасности и могут блокировать:\n\n"
            "❌ **Что может блокироваться:**\n"
            "• Слова типа 'сексуальная', 'красивая', 'привлекательная'\n"
            "• Описания взглядов: 'смотрит в камеру', 'приглашающий взгляд'\n"
            "• Определенные комбинации слов о внешности\n\n"
            "✅ **Как решить:**\n"
            "• Используйте нейтральные слова: 'женщина' вместо 'красивая'\n"
            "• Выберите другую модель: Ideogram, Bytedance, Google Imagen\n"
            "• Добавьте контекст: 'профессиональная фотография'\n"
            "• Попробуйте: 'элегантная женщина с темными волосами'\n\n"
            "💡 **Рекомендации:**\n"
            "• Для портретов лучше использовать Ideogram или Bytedance\n"
            "• Для пейзажей и архитектуры подходят все модели"
        )
        keyboard = [
            [InlineKeyboardButton("🔄 Попробовать снова", callback_data="retry_generation")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(help_filters_text, reply_markup=reply_markup)
    elif data == "ideogram_tips":
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
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(tips_text, reply_markup=reply_markup)
    elif data == "help_image_edit":
        help_image_edit_text = (
            "📤 **Как редактировать изображения с FLUX**\n\n"
            "FLUX.1 Kontext Pro - это мощная модель для редактирования изображений через текст.\n\n"
            "🎨 **Что можно делать:**\n"
            "• **Смена стиля**: 'преврати в акварельную живопись', 'сделай в стиле масляной живописи'\n"
            "• **Изменение объектов**: 'измени прическу на короткую боб', 'замени красное платье на синее'\n"
            "• **Редактирование текста**: 'замени текст \"старый\" на \"новый\"'\n"
            "• **Смена фона**: 'смени фон на пляжный, сохранив человека в том же положении'\n"
            "• **Сохранение идентичности**: 'измени стиль, но сохрани лицо человека'\n\n"
            "💡 **Советы для лучшего результата:**\n"
            "• Будьте конкретны: 'короткая черная прическа' вместо 'другая прическа'\n"
            "• Указывайте, что сохранить: 'сохрани лицо, измени только одежду'\n"
            "• Используйте точные цвета: 'синее платье' вместо 'другое платье'\n"
            "• Для текста используйте кавычки: 'замени \"старый текст\" на \"новый\"'\n\n"
            "⚠️ **Ограничения:**\n"
            "• Изображение должно быть подходящим для редактирования\n"
            "• Не работает с изображениями, содержащими логотипы или защищенный контент\n"
            "• Максимальный размер файла: 10MB"
        )
        keyboard = [
            [InlineKeyboardButton("📤 Начать редактирование", callback_data="edit_image")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(help_image_edit_text, reply_markup=reply_markup)
    elif data == "retry_generation":
        # Возвращаемся к предыдущему шагу для повторной попытки
        current_step = state.get('step', '')
        if current_step in ['custom_image_prompt', 'custom_image_style', 'simple_image_prompt']:
            # Возвращаемся к предыдущему шагу
            if current_step == 'custom_image_prompt':
                await query.edit_message_text("Попробуйте еще раз. Опишите, что должно быть на картинке:")
            elif current_step == 'custom_image_style':
                await query.edit_message_text("Попробуйте еще раз. Опишите стиль генерации изображения:")
            elif current_step == 'simple_image_prompt':
                await query.edit_message_text("Попробуйте еще раз. Опишите, что вы хотите видеть на картинке:")
        else:
            # Если не можем определить предыдущий шаг, возвращаемся в главное меню
            await show_main_menu(update, context)
    elif data == "create_content":
        await show_format_selection(update, context)
    elif data == "create_simple_images":
        # Для простых изображений сразу переходим к выбору модели
        USER_STATE[user_id] = {'step': 'image_gen_model', 'format': 'изображения'}
        await show_model_selection(update, context)
    elif data == "edit_image":
        # Начинаем процесс редактирования изображения
        USER_STATE[user_id] = {'step': 'upload_image_for_edit'}
        keyboard = [
            [InlineKeyboardButton("❓ Как редактировать изображения", callback_data="help_image_edit")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        help_text = """📤 **Редактирование изображений с FLUX**

Загрузите изображение, которое хотите отредактировать.

💡 **Что можно делать:**
• Изменить стиль (акварель, масло, эскиз)
• Заменить объекты (прическа, одежда, цвета)
• Редактировать текст на изображениях
• Сменить фон, сохранив объекты
• Сохранить идентичность персонажей

📋 **Как это работает:**
1. Загрузите изображение
2. Опишите, что хотите изменить
3. Получите отредактированную версию

⚠️ **Ограничения:**
• Максимальный размер: 10MB
• Поддерживаемые форматы: JPG, PNG
• Изображение должно быть "подходящим" для редактирования"""
        
        await query.edit_message_text(help_text, reply_markup=reply_markup)
    elif data == "how_to_use":
        await show_how_to_use(update, context)
    elif data == "about_bot":
        await show_about_bot(update, context)
    elif data == "main_menu":
        await show_main_menu(update, context)
    elif data == "format_selection":
        await show_format_selection(update, context)
    elif data.startswith('format:'):
        selected_format = data.split(':', 1)[1]
        if selected_format == 'custom':
            # Если выбрано "Другое", просим пользователя ввести формат вручную
            USER_STATE[user_id] = {'step': 'custom_format'}
            await query.edit_message_text(
                "Введите название формата (например: Facebook Post, Twitter, LinkedIn и т.д.):",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Назад", callback_data="format_selection")],
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                ])
            )
        elif selected_format == 'Изображения':
            # Для "Изображения" сначала выбираем ориентацию
            USER_STATE[user_id] = {'step': 'simple_image_orientation', 'format': selected_format}
            keyboard = [
                [InlineKeyboardButton("📱 Вертикальное (9:16)", callback_data="simple_orientation:vertical")],
                [InlineKeyboardButton("⬜ Квадратное (1:1)", callback_data="simple_orientation:square")]
            ]
            # Добавляем кнопки навигации
            keyboard.extend([
                [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
                [InlineKeyboardButton("🔙 Назад", callback_data="format_selection")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f'Формат выбран: {selected_format}\nВыберите ориентацию изображения:',
                reply_markup=reply_markup
            )
        else:
            USER_STATE[user_id] = {'step': STEP_STYLE, 'format': selected_format}
            keyboard = [
                [InlineKeyboardButton(style, callback_data=f"style:{style}")] for style in STYLES
            ]
            # Добавляем кнопку "Другое"
            keyboard.append([InlineKeyboardButton("📄 Другое", callback_data="style:custom")])
            # Добавляем кнопки навигации
            keyboard.extend([
                [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
                [InlineKeyboardButton("🔙 Назад", callback_data="format_selection")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f'Формат выбран: {selected_format}\nТеперь выбери стиль:',
                reply_markup=reply_markup
            )
    elif data.startswith('style:'):
        selected_style = data.split(':', 1)[1]
        if selected_style == 'custom':
            # Сохраняем формат из текущего состояния
            current_format = state.get('format', '')
            USER_STATE[user_id] = {'step': 'custom_style', 'format': current_format}
            await query.edit_message_text(
                "Введите название стиля (например: Деловой, Креативный, Романтичный и т.д.):",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Назад", callback_data="style_back")],
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                ])
            )
            return
        else:
            # Сохраняем стиль и переходим к выбору модели
            USER_STATE[user_id]['style'] = selected_style
            USER_STATE[user_id]['step'] = 'image_gen_model'
            keyboard = [[InlineKeyboardButton(f"{model} ({MODEL_DESCRIPTIONS[model]})", callback_data=f"image_gen_model:{model}")] for model in IMAGE_GEN_MODELS]
            # Добавляем кнопки навигации
            keyboard.extend([
                [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
                [InlineKeyboardButton("🔙 Назад", callback_data="style_back")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f'Стиль выбран: {selected_style}\nВыберите модель для генерации изображений:',
                reply_markup=reply_markup
            )
    elif data == "style_back":
        # Возврат к выбору стиля
        keyboard = [
            [InlineKeyboardButton(style, callback_data=f"style:{style}")] for style in STYLES
        ]
        # Добавляем кнопку "Другое"
        keyboard.append([InlineKeyboardButton("📄 Другое", callback_data="style:custom")])
        keyboard.extend([
            [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
            [InlineKeyboardButton("🔙 Назад", callback_data="format_selection")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f'Формат: {state.get("format", "")}\nВыбери стиль:',
            reply_markup=reply_markup
        )
    elif data.startswith('image_count:'):
        count_type = data.split(':', 1)[1]
        if count_type == 'default':
            user_format = state.get('format', '').lower()
            if user_format in ['instagram reels', 'tiktok', 'youtube shorts']:
                USER_STATE[user_id]['image_count'] = 'auto'  # Для коротких видео количество определяется из текста
            elif user_format in ['instagram stories']:
                USER_STATE[user_id]['image_count'] = 1  # Для Instagram Stories 1 изображение
            elif user_format in ['instagram post']:
                USER_STATE[user_id]['image_count'] = 2  # Для постов 2 изображения
            else:
                USER_STATE[user_id]['image_count'] = 2  # По умолчанию 2 изображения
            USER_STATE[user_id]['step'] = 'image_gen_model'  # Новый шаг для выбора модели
            # Кнопки выбора модели генерации
            keyboard = [[InlineKeyboardButton(f"{model} ({MODEL_DESCRIPTIONS[model]})", callback_data=f"image_gen_model:{model}")] for model in IMAGE_GEN_MODELS]
            # Добавляем кнопки навигации
            keyboard.extend([
                [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
                [InlineKeyboardButton("🔙 Назад", callback_data="image_count_back")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"Выберите модель для генерации изображений:",
                reply_markup=reply_markup
            )
            return
        elif count_type == 'custom':
            USER_STATE[user_id]['step'] = 'custom_image_count'
            await query.edit_message_text("Введите количество изображений:")
            return
    elif data == "image_count_back":
        # Возврат к выбору количества изображений
        user_format = state.get('format', '').lower()
        if user_format in ['reels']:
            default_text = "по количеству в тексте"
        elif user_format in ['tiktok']:
            default_text = "по количеству в тексте"
        elif user_format in ['instagram stories']:
            default_text = "1 изображение"
        elif user_format in ['пост']:
            default_text = "2 изображения"
        else:
            default_text = "2 изображения"
        keyboard = [
            [InlineKeyboardButton(f"По умолчанию ({default_text})", callback_data="image_count:default")],
            [InlineKeyboardButton("Выбрать количество", callback_data="image_count:custom")]
        ]
        keyboard.extend([
            [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
            [InlineKeyboardButton("🔙 Назад", callback_data="style_back")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"Стиль: {state.get('style', '')}\nСколько изображений сгенерировать?",
            reply_markup=reply_markup
        )
    elif data.startswith('simple_orientation:'):
        orientation = data.split(':', 1)[1]
        USER_STATE[user_id]['simple_orientation'] = orientation
        
        # Переходим к выбору модели
        USER_STATE[user_id]['step'] = 'image_gen_model'
        keyboard = [[InlineKeyboardButton(f"{model} ({MODEL_DESCRIPTIONS[model]})", callback_data=f"image_gen_model:{model}")] for model in IMAGE_GEN_MODELS]
        # Добавляем кнопки навигации
        keyboard.extend([
            [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
            [InlineKeyboardButton("🔙 Назад", callback_data="simple_orientation_back")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        orientation_text = "Вертикальное (9:16)" if orientation == "vertical" else "Квадратное (1:1)"
        await query.edit_message_text(
            f'Ориентация выбрана: {orientation_text}\nВыберите модель для генерации изображений:',
            reply_markup=reply_markup
        )
    elif data == "simple_orientation_back":
        # Возврат к выбору ориентации
        keyboard = [
            [InlineKeyboardButton("📱 Вертикальное (9:16)", callback_data="simple_orientation:vertical")],
            [InlineKeyboardButton("⬜ Квадратное (1:1)", callback_data="simple_orientation:square")]
        ]
        keyboard.extend([
            [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
            [InlineKeyboardButton("🔙 Назад", callback_data="format_selection")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f'Формат: {state.get("format", "")}\nВыберите ориентацию изображения:',
            reply_markup=reply_markup
        )
    elif data.startswith('image_gen_model:'):
        selected_model = data.split(':', 1)[1]
        USER_STATE[user_id]['image_gen_model'] = selected_model
        
        # Добавляем специальные подсказки для Ideogram
        ideogram_tips = ""
        if selected_model == 'Ideogram':
            ideogram_tips = "\n\n💡 **Советы для Ideogram:**\n• Используйте простые, четкие описания\n• Избегайте длинных сложных фраз\n• Фокусируйтесь на главном объекте\n• Ideogram лучше работает с текстом и логотипами"
        
        # Проверяем формат для разного поведения
        user_format = state.get('format', '').lower()
        if user_format == 'изображения':
            # Для "Изображения" переходим к выбору стиля
            USER_STATE[user_id]['step'] = 'image_gen_style'
            keyboard = [[InlineKeyboardButton(style, callback_data=f"image_gen_style:{style}")] for style in IMAGE_GEN_STYLES]
            keyboard.append([InlineKeyboardButton("✏️ Написать самому", callback_data="custom_image_style")])
            keyboard.extend([
                [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
                [InlineKeyboardButton("🔙 Назад", callback_data="model_back")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"Модель выбрана: {selected_model}{ideogram_tips}\n\nВыберите стиль генерации изображения:",
                reply_markup=reply_markup
            )
        else:
            # Для остальных форматов переходим к выбору стиля изображения
            USER_STATE[user_id]['step'] = 'image_gen_style'
            keyboard = [[InlineKeyboardButton(style, callback_data=f"image_gen_style:{style}")] for style in IMAGE_GEN_STYLES]
            keyboard.append([InlineKeyboardButton("✏️ Написать самому", callback_data="custom_image_style")])
            keyboard.extend([
                [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
                [InlineKeyboardButton("🔙 Назад", callback_data="model_back")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"Модель выбрана: {selected_model}{ideogram_tips}\n\nВыберите стиль генерации изображения:",
                reply_markup=reply_markup
            )
        return
    elif data == "model_back":
        # Возврат к выбору модели
        user_format = state.get('format', '').lower()
        if user_format == 'изображения':
            # Для "Изображения" возвращаемся к выбору ориентации
            keyboard = [
                [InlineKeyboardButton("📱 Вертикальное (9:16)", callback_data="simple_orientation:vertical")],
                [InlineKeyboardButton("⬜ Квадратное (1:1)", callback_data="simple_orientation:square")]
            ]
            keyboard.extend([
                [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
                [InlineKeyboardButton("🔙 Назад", callback_data="format_selection")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f'Формат: {state.get("format", "")}\nВыберите ориентацию изображения:',
                reply_markup=reply_markup
            )
        else:
            # Для остальных форматов возвращаемся к выбору стиля
            keyboard = [
                [InlineKeyboardButton(style, callback_data=f"style:{style}")] for style in STYLES
            ]
            keyboard.append([InlineKeyboardButton("📄 Другое", callback_data="style:custom")])
            keyboard.extend([
                [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
                [InlineKeyboardButton("🔙 Назад", callback_data="format_selection")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f'Формат: {state.get("format", "")}\nВыбери стиль:',
                reply_markup=reply_markup
            )
    elif data.startswith('image_gen_style:'):
        selected_img_style = data.split(':', 1)[1]
        USER_STATE[user_id]['image_gen_style'] = selected_img_style
        
        # Проверяем формат для разного поведения
        user_format = state.get('format', '').lower()
        if user_format == 'изображения':
            # Для "Изображения" переходим к выбору количества изображений
            USER_STATE[user_id]['step'] = 'image_count_simple'
            keyboard = [
                [InlineKeyboardButton("1 изображение", callback_data="image_count_simple:1")],
                [InlineKeyboardButton("2 изображения", callback_data="image_count_simple:2")],
                [InlineKeyboardButton("3 изображения", callback_data="image_count_simple:3")],
                [InlineKeyboardButton("4 изображения", callback_data="image_count_simple:4")],
                [InlineKeyboardButton("5 изображений", callback_data="image_count_simple:5")],
                [InlineKeyboardButton("Выбрать другое количество", callback_data="image_count_simple:custom")]
            ]
            keyboard.extend([
                [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
                [InlineKeyboardButton("🔙 Назад", callback_data="style_gen_back")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"Стиль генерации выбран: {selected_img_style}\nСколько изображений сгенерировать?",
                reply_markup=reply_markup
            )
        else:
            # Для остальных форматов переходим к вводу темы
            USER_STATE[user_id]['step'] = STEP_TOPIC
            
            # Создаем подсказки в зависимости от формата
            format_tips = get_format_tips(user_format)
            message_text = f"Стиль генерации выбран: {selected_img_style}\n\nРасскажите, что должно получиться:\n\n{format_tips}"
            
            # Добавляем кнопки навигации
            keyboard = [
                [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
                [InlineKeyboardButton("🔙 Назад", callback_data="style_gen_back")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                message_text,
                reply_markup=reply_markup
            )
        return
    elif data == "style_gen_back":
        # Возврат к выбору стиля генерации
        keyboard = [[InlineKeyboardButton(style, callback_data=f"image_gen_style:{style}")] for style in IMAGE_GEN_STYLES]
        keyboard.append([InlineKeyboardButton("✏️ Написать самому", callback_data="custom_image_style")])
        keyboard.extend([
            [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
            [InlineKeyboardButton("🔙 Назад", callback_data="model_back")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"Модель: {state.get('image_gen_model', '')}\nВыберите стиль генерации изображения:",
            reply_markup=reply_markup
        )
    elif data.startswith('image_count_simple:'):
        count_data = data.split(':', 1)[1]
        if count_data == 'custom':
            USER_STATE[user_id]['step'] = 'custom_image_count_simple'
            await query.edit_message_text("Введите количество изображений:")
            return
        else:
            try:
                count = int(count_data)
                if 1 <= count <= 10:
                    USER_STATE[user_id]['image_count'] = count
                    USER_STATE[user_id]['step'] = 'simple_image_prompt'
                    keyboard = [
                        [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
                        [InlineKeyboardButton("🔙 Назад", callback_data="style_gen_back")],
                        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    # Добавляем подсказки для "Изображения"
                    tips = """💡 Советы для лучшего результата:
• Опишите главный объект и его детали
• Укажите стиль, материалы, цвета
• Добавьте информацию об освещении
• Опишите ракурс или композицию
• Укажите атмосферу и контекст

✅ Примеры:
• "Современный дом с большими окнами, окруженный садом, закатное освещение"
• "Космический корабль в открытом космосе, звезды, футуристический дизайн"
• "Цветущий сад с розами, бабочки, солнечный день"

❌ Избегайте:
• "красиво", "хорошо", "красивая картинка"
• Слишком общие описания
• Противоположные требования"""
                    
                    await query.edit_message_text(
                        f"Количество выбрано: {count} изображений\n\nОпишите, что вы хотите видеть на картинке:\n\n{tips}",
                        reply_markup=reply_markup
                    )
                else:
                    await query.edit_message_text("Пожалуйста, выберите количество от 1 до 10:")
            except ValueError:
                await query.edit_message_text("Пожалуйста, выберите корректное количество:")
    elif data == "custom_image_count_simple":
        USER_STATE[user_id]['step'] = 'custom_image_count_simple'
        await query.edit_message_text("Введите количество изображений (от 1 до 10):")
        return
    elif data == "more_images":
        user_format = state.get('format', '').lower()
        if user_format in ['instagram reels', 'tiktok', 'youtube shorts'] and 'last_scenes' in state:
            # Для генерации тех же сцен заново, сбрасываем счетчик
            state['generated_scenes_count'] = 0
            USER_STATE[user_id] = state
            
            await update.callback_query.edit_message_text('Генерирую новые изображения по тем же сценам...')
            await send_images(update, context, state, prompt_type='auto', scenes=state['last_scenes'])
        elif user_format in ['instagram reels', 'tiktok', 'youtube shorts'] and 'last_script' in state:
            await update.callback_query.edit_message_text('Генерирую новые изображения по сценам...')
            scenes = await extract_scenes_from_script(state['last_script'], user_format)
            state['last_scenes'] = scenes
            await send_images(update, context, state, prompt_type='auto', scenes=scenes)
        else:
            await send_images(update, context, state, prompt_type=state.get('last_prompt_type', 'auto'), user_prompt=state.get('last_user_prompt'))
    elif data == "more_images_same_settings":
        # Генерация с теми же настройками для "Изображения"
        user_format = state.get('format', '').lower()
        if user_format == 'изображения':
            await update.callback_query.edit_message_text('Генерирую новые изображения с теми же настройками...')
            await send_images(update, context, state, prompt_type=state.get('last_prompt_type', 'user'), user_prompt=state.get('last_user_prompt'))
        else:
            # Fallback для других форматов
            await send_images(update, context, state, prompt_type=state.get('last_prompt_type', 'auto'), user_prompt=state.get('last_user_prompt'))
    elif data == "change_settings":
        # Возврат к выбору модели для изменения настроек
        user_format = state.get('format', '').lower()
        if user_format == 'изображения':
            USER_STATE[user_id]['step'] = 'image_gen_model'
            keyboard = [[InlineKeyboardButton(f"{model} ({MODEL_DESCRIPTIONS[model]})", callback_data=f"image_gen_model:{model}")] for model in IMAGE_GEN_MODELS]
            keyboard.extend([
                [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
                [InlineKeyboardButton("🔙 Назад", callback_data="format_selection")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "Выберите модель для генерации изображений:",
                reply_markup=reply_markup
            )
        else:
            # Для других форматов возвращаемся к главному меню
            await show_main_menu(update, context)
    elif data == "reset":
        # Сбрасываем состояние пользователя
        USER_STATE[user_id] = {'step': 'main_menu'}
        await show_format_selection(update, context)
    elif data == "custom_image_prompt":
        USER_STATE[user_id]['step'] = 'custom_image_prompt'
        await query.edit_message_text("Опишите, что вы хотите видеть на изображении (1-2 предложения):")
    elif data == "edit_image":
        # Перенаправляем на команду редактирования
        await edit_image_command(update, context)

    elif data == "back_to_main":
        await show_main_menu(update, context)
    elif data == "custom_image_style":
        USER_STATE[user_id]['step'] = 'custom_image_style'
        await query.edit_message_text("Опишите стиль генерации изображения (например: фотографический, художественный, минималистичный, яркий, темный и т.д.):")
    elif data == "generate_images":
        try:
            user_format = state.get('format', '').lower()
            state = USER_STATE.get(user_id, {})
            if user_format in ['instagram reels', 'tiktok', 'youtube shorts'] and 'last_scenes' in state:
                await send_images(update, context, state, prompt_type='auto', scenes=state['last_scenes'])
            elif user_format in ['instagram reels', 'tiktok', 'youtube shorts'] and 'last_script' in state:
                scenes = await extract_scenes_from_script(state['last_script'], user_format)
                state['last_scenes'] = scenes
                await send_images(update, context, state, prompt_type='auto', scenes=scenes)
            else:
                await send_images(update, context, state, prompt_type='auto')
        except Exception as e:
            keyboard = [
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="retry_generation")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(f"Ошибка при генерации изображений: {e}\nПопробуйте еще раз или выберите действие ниже:", reply_markup=reply_markup)
            # Сбрасываем состояние пользователя
            USER_STATE[user_id] = {'step': STEP_FORMAT}
    elif data.startswith('generate_with_count:'):
        try:
            count = int(data.split(':', 1)[1])
            user_format = state.get('format', '').lower()
            state = USER_STATE.get(user_id, {})
            
            # Устанавливаем количество изображений
            state['image_count'] = count
            USER_STATE[user_id] = state
            
            if 'last_scenes' in state:
                # Ограничиваем сцены до выбранного количества
                scenes = state['last_scenes'][:count]
                await send_images(update, context, state, prompt_type='auto', scenes=scenes)
            else:
                await send_images(update, context, state, prompt_type='auto')
        except Exception as e:
            keyboard = [
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="retry_generation")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(f"Ошибка при генерации изображений: {e}\nПопробуйте еще раз или выберите действие ниже:", reply_markup=reply_markup)
            USER_STATE[user_id] = {'step': STEP_FORMAT}
    elif data.startswith('simple_image_count:'):
        count_data = data.split(':', 1)[1]
        if count_data == 'custom':
            USER_STATE[user_id]['step'] = 'custom_simple_image_count'
            await query.edit_message_text("Введите количество изображений:")
            return
        else:
            try:
                count = int(count_data)
                if 1 <= count <= 10:
                    USER_STATE[user_id]['image_count'] = count
                    USER_STATE[user_id]['step'] = STEP_DONE
                    state = USER_STATE[user_id]
                    
                    await query.edit_message_text(f'Количество выбрано: {count} изображений\n\nГенерирую изображения...')
                    await send_images(update, context, state, prompt_type='user', user_prompt=state.get('topic', ''))
                else:
                    await query.edit_message_text("Пожалуйста, выберите количество от 1 до 10:")
            except ValueError:
                await query.edit_message_text("Пожалуйста, выберите корректное количество:")
    elif data == "simple_image_prompt_back":
        # Возврат к вводу описания для "Изображения"
        USER_STATE[user_id]['step'] = 'simple_image_prompt'
        keyboard = [
            [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
            [InlineKeyboardButton("🔙 Назад", callback_data="style_gen_back")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        tips = """💡 Советы для лучшего результата:
• Опишите главный объект и его детали
• Укажите стиль, материалы, цвета
• Добавьте информацию об освещении
• Опишите ракурс или композицию
• Укажите атмосферу и контекст

✅ Примеры:
• "Современный дом с большими окнами, окруженный садом, закатное освещение"
• "Космический корабль в открытом космосе, звезды, футуристический дизайн"
• "Цветущий сад с розами, бабочки, солнечный день"

❌ Избегайте:
• "красиво", "хорошо", "красивая картинка"
• Слишком общие описания
• Противоположные требования"""
        
        await query.edit_message_text(
            f"Опишите, что вы хотите видеть на картинке:\n\n{tips}",
            reply_markup=reply_markup
        )
    elif data == "custom_count_after_text":
        USER_STATE[user_id]['step'] = 'custom_count_after_text'
        await query.edit_message_text("Введите количество изображений:")
    elif data == "generate_remaining_scenes":
        # Генерация оставшихся сцен
        try:
            user_format = state.get('format', '').lower()
            if 'last_scenes' in state and 'generated_scenes_count' in state:
                generated_count = state.get('generated_scenes_count', 0)
                total_scenes = state.get('last_scenes', [])
                
                # Берем только оставшиеся сцены
                remaining_scenes = total_scenes[generated_count:]
                
                # Устанавливаем количество изображений равным количеству оставшихся сцен
                state['image_count'] = len(remaining_scenes)
                
                # Временно сбрасываем счетчик, чтобы send_images правильно посчитала новые сцены
                state['generated_scenes_count'] = generated_count
                USER_STATE[user_id] = state
                
                await query.edit_message_text(f'Генерирую изображения для оставшихся {len(remaining_scenes)} сцен...')
                await send_images(update, context, state, prompt_type='auto', scenes=remaining_scenes)
            else:
                await query.edit_message_text("Ошибка: не найдены сохраненные сцены")
        except Exception as e:
            keyboard = [
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="retry_generation")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(f"Ошибка при генерации изображений: {e}\nПопробуйте еще раз или выберите действие ниже:", reply_markup=reply_markup)
    elif data == "generate_all_scenes":
        # Генерация всех сцен
        try:
            user_format = state.get('format', '').lower()
            if 'last_scenes' in state:
                all_scenes = state.get('last_scenes', [])
                
                # Устанавливаем количество изображений равным количеству всех сцен
                state['image_count'] = len(all_scenes)
                
                # Сбрасываем счетчик, чтобы генерировать все сцены заново
                state['generated_scenes_count'] = 0
                USER_STATE[user_id] = state
                
                await query.edit_message_text(f'Генерирую изображения для всех {len(all_scenes)} сцен...')
                await send_images(update, context, state, prompt_type='auto', scenes=all_scenes)
            else:
                await query.edit_message_text("Ошибка: не найдены сохраненные сцены")
        except Exception as e:
            keyboard = [
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="retry_generation")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(f"Ошибка при генерации изображений: {e}\nПопробуйте еще раз или выберите действие ниже:", reply_markup=reply_markup)
    elif data == "select_scene_count":
        # Показать меню выбора количества сцен
        try:
            user_format = state.get('format', '').lower()
            if 'last_scenes' in state:
                total_scenes = state.get('last_scenes', [])
                generated_count = state.get('generated_scenes_count', 0)
                
                keyboard = []
                
                # Кнопки для выбора количества оставшихся сцен
                remaining_count = len(total_scenes) - generated_count
                if remaining_count > 0:
                    for i in range(1, min(remaining_count + 1, 6)):  # Максимум 5 кнопок
                        start_scene = generated_count + 1
                        end_scene = generated_count + i
                        if i == 1:
                            scene_text = f"Сцена {start_scene}"
                        else:
                            scene_text = f"Сцены {start_scene}-{end_scene}"
                        keyboard.append([InlineKeyboardButton(scene_text, callback_data=f"generate_scenes_count:{i}")])
                
                # Кнопка для всех сцен
                keyboard.append([InlineKeyboardButton(f"Все сцены 1-{len(total_scenes)}", callback_data=f"generate_scenes_count:{len(total_scenes)}")])
                
                # Кнопка для кастомного количества
                keyboard.append([InlineKeyboardButton("🔢 Другое количество", callback_data="custom_scene_count")])
                
                # Навигация
                keyboard.extend([
                    [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main_options")],
                ])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    f"Выберите сцены для генерации:\n"
                    f"Всего сцен: {len(total_scenes)}\n"
                    f"Уже сгенерировано: сцены 1-{generated_count}\n"
                    f"Доступно для генерации: сцены {generated_count + 1}-{len(total_scenes)}",
                    reply_markup=reply_markup
                )
            else:
                await query.edit_message_text("Ошибка: не найдены сохраненные сцены")
        except Exception as e:
            await query.edit_message_text(f"Ошибка при создании меню: {e}")
    elif data.startswith('generate_scenes_count:'):
        # Генерация определенного количества сцен
        try:
            count = int(data.split(':', 1)[1])
            user_format = state.get('format', '').lower()
            
            if 'last_scenes' in state:
                all_scenes = state.get('last_scenes', [])
                generated_count = state.get('generated_scenes_count', 0)
                
                # Берем сцены начиная с уже сгенерированных
                scenes_to_generate = all_scenes[generated_count:generated_count + count]
                
                # Устанавливаем количество изображений равным количеству выбранных сцен
                state['image_count'] = len(scenes_to_generate)
                
                # Временно сбрасываем счетчик, чтобы send_images правильно посчитала новые сцены
                state['generated_scenes_count'] = generated_count
                USER_STATE[user_id] = state
                
                await query.edit_message_text(f'Генерирую изображения для {len(scenes_to_generate)} сцен...')
                await send_images(update, context, state, prompt_type='auto', scenes=scenes_to_generate)
            else:
                await query.edit_message_text("Ошибка: не найдены сохраненные сцены")
        except Exception as e:
            keyboard = [
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="retry_generation")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(f"Ошибка при генерации изображений: {e}\nПопробуйте еще раз или выберите действие ниже:", reply_markup=reply_markup)
    elif data == "custom_scene_count":
        # Запрос кастомного количества сцен
        USER_STATE[user_id]['step'] = 'custom_scene_count'
        total_scenes = state.get('total_scenes_count', 0)
        generated_count = state.get('generated_scenes_count', 0)
        remaining_count = total_scenes - generated_count
        
        await query.edit_message_text(
            f"Введите количество сцен для генерации (от 1 до {remaining_count}):\n"
            f"Всего сцен: {total_scenes}\n"
            f"Уже сгенерировано: сцены 1-{generated_count}\n"
            f"Доступно для генерации: сцены {generated_count + 1}-{total_scenes}"
        )
    elif data == "back_to_main_options":
        # Возврат к основным опциям после генерации изображений
        user_format = state.get('format', '').lower()
        generated_count = state.get('generated_scenes_count', 0)
        total_count = state.get('total_scenes_count', 0)
        
        keyboard = []
        
        # Кнопка для генерации тех же изображений заново
        keyboard.append([InlineKeyboardButton("🔄 Сгенерировать ещё (те же сцены)", callback_data="more_images")])
        
        # Если есть еще сцены для генерации, добавляем кнопки
        if total_count > generated_count:
            remaining_count = total_count - generated_count
            start_scene = generated_count + 1
            end_scene = total_count
            keyboard.append([InlineKeyboardButton(f"📸 Сгенерировать сцены {start_scene}-{end_scene}", callback_data="generate_remaining_scenes")])
            keyboard.append([InlineKeyboardButton(f"📸 Сгенерировать все сцены 1-{total_count}", callback_data="generate_all_scenes")])
        
        # Кнопка для выбора конкретного количества
        keyboard.append([InlineKeyboardButton("🔢 Выбрать количество сцен", callback_data="select_scene_count")])
        
        # Кнопки для генерации видео
        keyboard.extend([
            [InlineKeyboardButton("🎬 Создать видео из изображений", callback_data="create_video_from_images")],
            [InlineKeyboardButton("🎭 Создать видео по сценарию", callback_data="create_video_from_script")],
        ])
        
        # Остальные кнопки
        keyboard.extend([
            [InlineKeyboardButton("Уточнить, что должно быть на картинке", callback_data="custom_image_prompt")],
            [InlineKeyboardButton("🔄 Сбросить", callback_data="reset")],
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Хотите другие варианты или уточнить, что должно быть на картинке?", reply_markup=reply_markup)

    # Обработчики для генерации видео
    elif data == "video_generation":
        # Показываем меню выбора типа генерации видео
        keyboard = [
            [InlineKeyboardButton("🎭 Создать видео по тексту", callback_data="video_text_to_video")],
            [InlineKeyboardButton("🖼️ Создать видео из изображения", callback_data="video_image_to_video")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🎬 **Генерация видео**\n\n"
            "Выберите тип генерации видео:",
            reply_markup=reply_markup
        )

    elif data == "create_video_from_script":
        # Создание видео по сценарию (text-to-video)
        state['video_type'] = 'text_to_video'
        state['step'] = STEP_VIDEO_QUALITY
        keyboard = [
            [InlineKeyboardButton("⚡ Быстрое (480p)", callback_data="video_quality:480p")],
            [InlineKeyboardButton("⭐ Качественное (1080p)", callback_data="video_quality:1080p")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main_options")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🎭 **Создание видео по сценарию**\n\n"
            "Выберите качество видео:",
            reply_markup=reply_markup
        )

    elif data == "create_video_from_images":
        # Создание видео из изображений (image-to-video)
        state['video_type'] = 'image_to_video'
        state['step'] = STEP_VIDEO_QUALITY
        keyboard = [
            [InlineKeyboardButton("⚡ Быстрое (480p)", callback_data="video_quality:480p")],
            [InlineKeyboardButton("⭐ Качественное (1080p)", callback_data="video_quality:1080p")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main_options")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🎬 **Создание видео из изображений**\n\n"
            "Выберите качество видео:",
            reply_markup=reply_markup
        )

    elif data.startswith("video_quality:"):
        # Обработка выбора качества видео
        quality = data.split(":")[1]
        state['video_quality'] = quality
        state['step'] = STEP_VIDEO_DURATION
        
        keyboard = [
            [InlineKeyboardButton("⏱️ 5 секунд", callback_data="video_duration:5")],
            [InlineKeyboardButton("⏱️ 10 секунд", callback_data="video_duration:10")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main_options")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"🎬 **Качество выбрано: {quality}**\n\n"
            "Выберите длительность видео:",
            reply_markup=reply_markup
        )

    elif data.startswith("video_duration:"):
        # Обработка выбора длительности видео
        duration = int(data.split(":")[1])
        state['video_duration'] = duration
        state['step'] = STEP_VIDEO_GENERATION
        
        # Начинаем генерацию видео
        await generate_video(update, context, state)

    elif data == "video_text_to_video":
        # Прямая генерация видео по тексту из главного меню
        state['video_type'] = 'text_to_video'
        state['step'] = STEP_VIDEO_QUALITY
        keyboard = [
            [InlineKeyboardButton("⚡ Быстрое (480p)", callback_data="video_quality:480p")],
            [InlineKeyboardButton("⭐ Качественное (1080p)", callback_data="video_quality:1080p")],
            [InlineKeyboardButton("🔙 Назад", callback_data="video_generation")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🎭 **Создание видео по тексту**\n\n"
            "Выберите качество видео:",
            reply_markup=reply_markup
        )

    elif data == "video_image_to_video":
        # Прямая генерация видео из изображения из главного меню
        state['video_type'] = 'image_to_video'
        state['step'] = STEP_VIDEO_QUALITY
        keyboard = [
            [InlineKeyboardButton("⚡ Быстрое (480p)", callback_data="video_quality:480p")],
            [InlineKeyboardButton("⭐ Качественное (1080p)", callback_data="video_quality:1080p")],
            [InlineKeyboardButton("🔙 Назад", callback_data="video_generation")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🖼️ **Создание видео из изображения**\n\n"
            "Выберите качество видео:",
            reply_markup=reply_markup
        )

    elif data == "waiting":
        # Обработка кнопки "Генерация..." - просто игнорируем
        await query.answer("⏳ Генерация в процессе...")


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logging.info(f"Получено сообщение от пользователя {user_id}: тип={type(update.message).__name__}, фото={bool(update.message.photo)}, текст={bool(update.message.text)}")
    state = USER_STATE.get(user_id, {})
    step = state.get('step')
    if step == STEP_TOPIC:
        user_format = state.get('format', '').lower()
        
        if user_format == 'изображения':
            # Для "Изображения" сохраняем описание и предлагаем выбрать количество изображений
            USER_STATE[user_id]['topic'] = update.message.text
            USER_STATE[user_id]['step'] = 'simple_image_count_selection'
            state = USER_STATE[user_id]
            
            # Предлагаем выбрать количество изображений
            keyboard = [
                [InlineKeyboardButton("1 изображение", callback_data="simple_image_count:1")],
                [InlineKeyboardButton("2 изображения", callback_data="simple_image_count:2")],
                [InlineKeyboardButton("3 изображения", callback_data="simple_image_count:3")],
                [InlineKeyboardButton("4 изображения", callback_data="simple_image_count:4")],
                [InlineKeyboardButton("5 изображений", callback_data="simple_image_count:5")],
                [InlineKeyboardButton("Выбрать другое количество", callback_data="simple_image_count:custom")]
            ]
            keyboard.extend([
                [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
                [InlineKeyboardButton("🔙 Назад", callback_data="simple_image_prompt_back")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f'Описание сохранено: "{update.message.text}"\n\nСколько изображений сгенерировать?',
                reply_markup=reply_markup
            )
            return
        else:
            # Для остальных форматов - старая логика
            USER_STATE[user_id]['topic'] = update.message.text
            USER_STATE[user_id]['step'] = STEP_DONE
            state = USER_STATE[user_id]
            
            # Специальный промпт для коротких видео с кадрами
            if user_format in ['instagram reels', 'tiktok', 'youtube shorts']:
                prompt = (
                    f"Формат: {state.get('format', '')}\n"
                    f"Стиль: {state.get('style', '')}\n"
                    f"Тема: {state.get('topic', '')}\n"
                    "Сгенерируй сценарий для видео с кадрами в квадратных скобках. Например: [Кадр 1: Описание сцены] Текст на экране. [Кадр 2: Описание сцены] Текст на экране."
                )
            else:
                prompt = (
                    f"Формат: {state.get('format', '')}\n"
                    f"Стиль: {state.get('style', '')}\n"
                    f"Тема: {state.get('topic', '')}\n"
                    "Сгенерируй, пожалуйста, подходящий текст."
                )
            await update.message.reply_text('Спасибо! Генерирую ответ...')
        
        # Создаём качественный контент
        topic = state.get('topic', '')
        style = state.get('style', '')
        format_name = state.get('format', '')
        selected_model = state.get('image_gen_model', 'Ideogram')
        
        # Генерируем контент с помощью OpenAI
        content_prompt = (
            f"Создай уникальный и качественный контент для {format_name} на тему '{topic}'. "
            f"Стиль: {style}. "
            f"ВАЖНО: "
            f"- НЕ используй шаблонные фразы типа 'добро пожаловать', 'удивительный мир', 'незабываемый отдых', 'качество встречается с инновациями' "
            f"- Создай конкретный, детальный контент именно про {topic} "
            f"- Используй живые, современные выражения "
            f"- Добавь конкретные детали, особенности, преимущества {topic} "
            f"- Сделай контент продающим, но не навязчивым "
            f"- Для коротких видео (Reels/TikTok/Shorts): создай динамичный сценарий с кадрами [Кадр 1: описание] текст "
            f"- Для постов: создай привлекательный текст с хештегами в конце "
            f"- Контент должен быть уникальным для каждой темы, не шаблонным "
            f"Примеры хорошего контента: "
            f"- Для 'турбаза': 'Деревянные домики среди сосен, баня с вениками, рыбалка на озере' "
            f"- Для 'спортзал': 'Современные тренажеры, персональные тренировки, групповые занятия' "
            f"Создай контент, который заинтересует и привлечет внимание."
        )
        
        try:
            client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Ты эксперт по созданию уникального контента для социальных сетей. Твоя задача - создавать качественный, нешаблонный контент, который точно описывает тему и привлекает внимание. Избегай общих фраз, используй конкретные детали."},
                    {"role": "user", "content": content_prompt}
                ],
                max_tokens=1000,
                temperature=0.8,
            )
            gpt_reply = response.choices[0].message.content.strip()
        except Exception as e:
            # Fallback на простой контент если OpenAI недоступен
            if user_format in ['instagram reels', 'tiktok', 'youtube shorts']:
                gpt_reply = f"[Кадр 1: {topic} - общий вид] Откройте для себя {topic}! [Кадр 2: детали {topic}] Уникальные особенности и преимущества. [Кадр 3: атмосфера {topic}] Создайте незабываемые впечатления."
            else:
                gpt_reply = f"Откройте для себя {topic}! Уникальные особенности и преимущества ждут вас. Создайте незабываемые впечатления и получите максимум удовольствия. #{topic.replace(' ', '')} #качество #впечатления"

        
        await update.message.reply_text(gpt_reply)
        user_format = state.get('format', '').lower()
        
        # Для обычных форматов предлагаем выбрать количество изображений
        if user_format not in ['изображения']:
            # Определяем количество сцен из текста
            scenes = await extract_scenes_from_script(gpt_reply, user_format)
            scene_count = len(scenes)
            
            # Предлагаем количество изображений на основе сцен
            keyboard = []
            if scene_count <= 3:
                keyboard.append([InlineKeyboardButton(f"Все сцены ({scene_count} изображений)", callback_data=f"generate_with_count:{scene_count}")])
            else:
                keyboard.append([InlineKeyboardButton(f"Первые 3 сцены (3 изображения)", callback_data="generate_with_count:3")])
                keyboard.append([InlineKeyboardButton(f"Все сцены ({scene_count} изображений)", callback_data=f"generate_with_count:{scene_count}")])
            
            keyboard.append([InlineKeyboardButton("Выбрать другое количество", callback_data="custom_count_after_text")])
            keyboard.append([InlineKeyboardButton("Уточнить, что должно быть на картинке", callback_data="custom_image_prompt")])
            keyboard.append([InlineKeyboardButton("Сбросить и начать заново", callback_data="reset")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"Сценарий готов! Найдено {scene_count} сцен.\n\nСколько изображений сгенерировать?",
                reply_markup=reply_markup
            )
            state['last_scenes'] = scenes
        else:
            # Для "Изображения" - старые кнопки
            keyboard = [
                [InlineKeyboardButton("Сгенерировать изображения", callback_data="generate_images")],
                [InlineKeyboardButton("🎭 Создать видео по сценарию", callback_data="create_video_from_script")],
                [InlineKeyboardButton("Уточнить, что должно быть на картинке", callback_data="custom_image_prompt")],
                [InlineKeyboardButton("Сбросить и начать заново", callback_data="reset")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "Хотите сгенерировать изображения по сценарию или уточнить, что должно быть на картинке?",
                reply_markup=reply_markup
            )
        state['last_script'] = gpt_reply
        if user_format in ['instagram reels', 'tiktok', 'youtube shorts']:
            scenes = await extract_scenes_from_script(gpt_reply, user_format)
            state['last_scenes'] = scenes
        # Убираем автоматическую генерацию изображений - теперь пользователь сам выбирает
    elif step == 'custom_image_count':
        try:
            count = int(update.message.text.strip())
            if 1 <= count <= 10:
                USER_STATE[user_id]['image_count'] = count
                USER_STATE[user_id]['step'] = 'image_gen_model'
                # Кнопки выбора модели генерации
                keyboard = [[InlineKeyboardButton(f"{model} ({MODEL_DESCRIPTIONS[model]})", callback_data=f"image_gen_model:{model}")] for model in IMAGE_GEN_MODELS]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(
                    f"Выберите модель для генерации изображений:",
                    reply_markup=reply_markup
                )
            else:
                await update.message.reply_text("Пожалуйста, введите число от 1 до 10:")
        except ValueError:
            await update.message.reply_text("Пожалуйста, введите число от 1 до 10:")
    elif step == 'custom_image_count_simple':
        try:
            count = int(update.message.text.strip())
            if 1 <= count <= 10:
                USER_STATE[user_id]['image_count'] = count
                USER_STATE[user_id]['step'] = 'simple_image_prompt'
                keyboard = [
                    [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
                    [InlineKeyboardButton("🔙 Назад", callback_data="style_gen_back")],
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Добавляем подсказки для "Изображения"
                tips = """💡 Советы для лучшего результата:
• Опишите главный объект и его детали
• Укажите стиль, материалы, цвета
• Добавьте информацию об освещении
• Опишите ракурс или композицию
• Укажите атмосферу и контекст

✅ Примеры:
• "Современный дом с большими окнами, окруженный садом, закатное освещение"
• "Космический корабль в открытом космосе, звезды, футуристический дизайн"
• "Цветущий сад с розами, бабочки, солнечный день"

❌ Избегайте:
• "красиво", "хорошо", "красивая картинка"
• Слишком общие описания
• Противоположные требования"""
                
                await update.message.reply_text(
                    f"Количество выбрано: {count} изображений\n\nОпишите, что вы хотите видеть на картинке:\n\n{tips}",
                    reply_markup=reply_markup
                )
            else:
                await update.message.reply_text("Пожалуйста, введите число от 1 до 10:")
        except ValueError:
            await update.message.reply_text("Пожалуйста, введите число от 1 до 10:")
    elif step == 'custom_format':
        custom_format = update.message.text.strip()
        if len(custom_format) > 50:
            await update.message.reply_text("Название формата слишком длинное. Пожалуйста, введите более короткое название (до 50 символов).")
            return
        USER_STATE[user_id]['format'] = custom_format
        USER_STATE[user_id]['step'] = STEP_STYLE
        keyboard = [
            [InlineKeyboardButton(style, callback_data=f"style:{style}")] for style in STYLES
        ]
        # Добавляем кнопку "Другое"
        keyboard.append([InlineKeyboardButton("📄 Другое", callback_data="style:custom")])
        # Добавляем кнопки навигации
        keyboard.extend([
            [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
            [InlineKeyboardButton("🔙 Назад", callback_data="format_selection")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f'Формат выбран: {custom_format}\nТеперь выбери стиль:',
            reply_markup=reply_markup
        )
    elif step == 'custom_style':
        custom_style = update.message.text.strip()
        if len(custom_style) > 50:
            await update.message.reply_text("Название стиля слишком длинное. Пожалуйста, введите более короткое название (до 50 символов).")
            return
        # Сохраняем стиль и переходим к выбору модели генерации изображений
        USER_STATE[user_id]['style'] = custom_style
        USER_STATE[user_id]['step'] = 'image_gen_model'
        keyboard = [[InlineKeyboardButton(f"{model} ({MODEL_DESCRIPTIONS[model]})", callback_data=f"image_gen_model:{model}")] for model in IMAGE_GEN_MODELS]
        # Добавляем кнопки навигации
        keyboard.extend([
            [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
            [InlineKeyboardButton("🔙 Назад", callback_data="style_back")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f'Стиль выбран: {custom_style}\nВыберите модель для генерации изображений:',
            reply_markup=reply_markup
        )
    elif step == 'custom_image_prompt':
        user_prompt = update.message.text.strip()
        if not is_prompt_safe(user_prompt):
            keyboard = [
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="retry_generation")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Описание изображения содержит запрещённые слова. Пожалуйста, измените описание.", reply_markup=reply_markup)
            return
        USER_STATE[user_id]['step'] = STEP_DONE
        await send_images(update, context, state, prompt_type='user', user_prompt=user_prompt)
    elif step == 'custom_image_style':
        custom_style = update.message.text.strip()
        if not is_prompt_safe(custom_style):
            keyboard = [
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="retry_generation")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Описание стиля содержит запрещённые слова. Пожалуйста, измените описание.", reply_markup=reply_markup)
            return
        USER_STATE[user_id]['image_gen_style'] = custom_style
        
        # Проверяем формат для разного поведения
        user_format = state.get('format', '').lower()
        if user_format == 'изображения':
            # Для "Изображения" переходим к выбору количества изображений
            USER_STATE[user_id]['step'] = 'image_count_simple'
            keyboard = [
                [InlineKeyboardButton("1 изображение", callback_data="image_count_simple:1")],
                [InlineKeyboardButton("2 изображения", callback_data="image_count_simple:2")],
                [InlineKeyboardButton("3 изображения", callback_data="image_count_simple:3")],
                [InlineKeyboardButton("4 изображения", callback_data="image_count_simple:4")],
                [InlineKeyboardButton("5 изображений", callback_data="image_count_simple:5")],
                [InlineKeyboardButton("Выбрать другое количество", callback_data="image_count_simple:custom")]
            ]
            keyboard.extend([
                [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
                [InlineKeyboardButton("🔙 Назад", callback_data="style_gen_back")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"Стиль генерации выбран: {custom_style}\nСколько изображений сгенерировать?",
                reply_markup=reply_markup
            )
        else:
            # Для остальных форматов переходим к вводу темы
            USER_STATE[user_id]['step'] = STEP_TOPIC
            
            # Создаем подсказки в зависимости от формата
            format_tips = get_format_tips(user_format)
            message_text = f"Стиль генерации выбран: {custom_style}\n\nРасскажите, что должно получиться:\n\n{format_tips}"
            
            # Добавляем кнопки навигации
            keyboard = [
                [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
                [InlineKeyboardButton("🔙 Назад", callback_data="style_gen_back")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                message_text,
                reply_markup=reply_markup
            )
    elif step == 'custom_image_count_simple':
        try:
            count = int(update.message.text.strip())
            if 1 <= count <= 10:
                USER_STATE[user_id]['image_count'] = count
                USER_STATE[user_id]['step'] = 'simple_image_prompt'
                keyboard = [
                    [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
                    [InlineKeyboardButton("🔙 Назад", callback_data="style_gen_back")],
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                # Добавляем подсказки для "Изображения"
                tips = """�� Советы для лучшего результата:
• Опишите главный объект и его детали
• Укажите стиль, материалы, цвета
• Добавьте информацию об освещении
• Опишите ракурс или композицию
• Укажите атмосферу и контекст

✅ Примеры:
• "Современный дом с большими окнами, окруженный садом, закатное освещение"
• "Космический корабль в открытом космосе, звезды, футуристический дизайн"
• "Цветущий сад с розами, бабочки, солнечный день"

❌ Избегайте:
• "красиво", "хорошо", "красивая картинка"
• Слишком общие описания
• Противоположные требования"""
                
                await update.message.reply_text(
                    f"Количество выбрано: {count} изображений\n\nОпишите, что вы хотите видеть на картинке:\n\n{tips}",
                    reply_markup=reply_markup
                )
            else:
                await update.message.reply_text("Пожалуйста, введите число от 1 до 10:")
        except ValueError:
            await update.message.reply_text("Пожалуйста, введите число от 1 до 10:")
    elif step == 'simple_image_prompt':
        user_prompt = update.message.text.strip()
        if not is_prompt_safe(user_prompt):
            keyboard = [
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="retry_generation")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Описание изображения содержит запрещённые слова. Пожалуйста, измените описание.", reply_markup=reply_markup)
            return
        
        # Сохраняем промпт в состоянии
        USER_STATE[user_id]['topic'] = user_prompt
        USER_STATE[user_id]['step'] = STEP_DONE
        state = USER_STATE[user_id]
        
        await update.message.reply_text('Спасибо! Генерирую изображения...')
        await send_images(update, context, state, prompt_type='user', user_prompt=user_prompt)
    
    elif step == STEP_VIDEO_GENERATION:
        # Обработка ввода текста для генерации видео
        video_prompt = update.message.text.strip()
        if not is_prompt_safe(video_prompt):
            keyboard = [
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="retry_generation")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Описание видео содержит запрещённые слова. Пожалуйста, измените описание.", reply_markup=reply_markup)
            return
        
        # Сохраняем промпт и начинаем генерацию
        state['video_prompt'] = video_prompt
        await generate_video(update, context, state)
    
    elif step == 'waiting_for_image':
        # Обработка загрузки изображения для генерации видео
        if update.message.photo:
            # Получаем URL изображения
            photo = update.message.photo[-1]  # Берем самое большое изображение
            file = await context.bot.get_file(photo.file_id)
            image_url = file.file_path
            
            # Сохраняем URL изображения в состоянии
            state['selected_image_url'] = image_url
            
            # Показываем сообщение о получении изображения
            await update.message.reply_text(
                "🖼️ **Изображение получено!**\n\n"
                "Теперь начинаю генерацию видео...",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⏳ Генерация...", callback_data="waiting")
                ]])
            )
            
            # Начинаем генерацию видео
            await generate_video(update, context, state)
        else:
            await update.message.reply_text(
                "❌ **Ошибка!**\n\n"
                "Пожалуйста, загрузите изображение в формате JPG или PNG.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Назад", callback_data="back_to_main_options")
                ]])
            )
    elif step == 'custom_simple_image_count':
        try:
            count = int(update.message.text.strip())
            if 1 <= count <= 10:
                USER_STATE[user_id]['image_count'] = count
                USER_STATE[user_id]['step'] = STEP_DONE
                state = USER_STATE[user_id]
                
                await update.message.reply_text(f'Количество выбрано: {count} изображений\n\nГенерирую изображения...')
                await send_images(update, context, state, prompt_type='user', user_prompt=state.get('topic', ''))
            else:
                await update.message.reply_text("Пожалуйста, введите число от 1 до 10:")
        except ValueError:
            await update.message.reply_text("Пожалуйста, введите число от 1 до 10:")
    elif step == 'custom_count_after_text':
        try:
            count = int(update.message.text.strip())
            if 1 <= count <= 10:
                USER_STATE[user_id]['image_count'] = count
                state = USER_STATE[user_id]
                
                # Генерируем изображения с выбранным количеством
                if 'last_scenes' in state:
                    scenes = state['last_scenes'][:count]
                    await update.message.reply_text(f'Генерирую {count} изображений...')
                    await send_images(update, context, state, prompt_type='auto', scenes=scenes)
                else:
                    await update.message.reply_text(f'Генерирую {count} изображений...')
                    await send_images(update, context, state, prompt_type='auto')
            else:
                await update.message.reply_text("Пожалуйста, введите число от 1 до 10:")
        except ValueError:
            await update.message.reply_text("Пожалуйста, введите число от 1 до 10:")
    elif step == 'custom_scene_count':
        try:
            count = int(update.message.text.strip())
            total_scenes = state.get('total_scenes_count', 0)
            generated_count = state.get('generated_scenes_count', 0)
            remaining_count = total_scenes - generated_count
            
            if 1 <= count <= remaining_count:
                # Берем сцены начиная с уже сгенерированных
                all_scenes = state.get('last_scenes', [])
                scenes_to_generate = all_scenes[generated_count:generated_count + count]
                
                # Устанавливаем количество изображений равным количеству выбранных сцен
                state['image_count'] = len(scenes_to_generate)
                
                # Временно сбрасываем счетчик, чтобы send_images правильно посчитала новые сцены
                state['generated_scenes_count'] = generated_count
                USER_STATE[user_id] = state
                
                await update.message.reply_text(f'Генерирую изображения для {count} сцен...')
                await send_images(update, context, state, prompt_type='auto', scenes=scenes_to_generate)
            else:
                await update.message.reply_text(f"Пожалуйста, введите число от 1 до {remaining_count}:")
        except ValueError:
            total_scenes = state.get('total_scenes_count', 0)
            generated_count = state.get('generated_scenes_count', 0)
            remaining_count = total_scenes - generated_count
            await update.message.reply_text(f"Пожалуйста, введите корректное число от 1 до {remaining_count} (сцены {generated_count + 1}-{total_scenes}):")
    elif step == 'select_image_for_edit':
        try:
            image_index = int(update.message.text.strip()) - 1
            last_images = state.get('last_images', [])
            
            if 0 <= image_index < len(last_images):
                selected_image_url = last_images[image_index]
                USER_STATE[user_id]['selected_image_url'] = selected_image_url
                USER_STATE[user_id]['step'] = 'enter_edit_prompt'
                
                await update.message.reply_text(
                    f"✅ Выбрано изображение #{image_index + 1}\n\n"
                    "Теперь опишите, как вы хотите отредактировать это изображение.\n\n"
                    "💡 Примеры:\n"
                    "• \"Изменить цвет фона на синий\"\n"
                    "• \"Добавить солнцезащитные очки\"\n"
                    "• \"Сделать изображение в стиле акварели\"\n"
                    "• \"Заменить текст на 'Новый текст'\"\n"
                    "• \"Изменить прическу на короткую\""
                )
            else:
                await update.message.reply_text(f"Пожалуйста, введите число от 1 до {len(last_images)}:")
        except ValueError:
            await update.message.reply_text("Пожалуйста, введите корректный номер изображения:")
    elif step == 'upload_image_for_edit':
        # Пользователь отправил изображение для редактирования
        logging.info(f"Получено изображение для редактирования от пользователя {user_id}")
        if update.message.photo:
            # Получаем файл изображения
            photo = update.message.photo[-1]  # Берем самое большое изображение
            file = await context.bot.get_file(photo.file_id)
            
            # Сохраняем URL изображения
            USER_STATE[user_id]['selected_image_url'] = file.file_path
            USER_STATE[user_id]['step'] = 'enter_edit_prompt'
            
            await update.message.reply_text(
                "✅ Изображение получено!\n\n"
                "Теперь опишите, что именно хотите изменить в этом изображении.\n"
                "🔄 Ваш промпт будет автоматически переведен на английский для лучшего результата.\n\n"
                "💡 Примеры:\n"
                "• \"Изменить цвет фона на синий\"\n"
                "• \"Добавить солнцезащитные очки\"\n"
                "• \"Сделать изображение в стиле акварели\"\n"
                "• \"Заменить текст на 'Новый текст'\"\n"
                "• \"Изменить прическу на короткую\"\n\n"
                "🔙 Для отмены напишите /start"
            )
        else:
            logging.info(f"Пользователь {user_id} отправил не изображение в режиме редактирования")
            await update.message.reply_text("❌ Пожалуйста, отправьте изображение для редактирования.")
    
    elif step == 'enter_edit_prompt':
        edit_prompt = update.message.text.strip()
        selected_image_url = state.get('selected_image_url')
        
        if not selected_image_url:
            await update.message.reply_text("❌ Ошибка: изображение не загружено. Попробуйте снова /edit_image")
            return
        
        # Переводим промпт на английский для FLUX и улучшаем его
        try:
            client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            translation_response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Ты - эксперт по редактированию изображений. Переведи запрос на редактирование с русского на английский и улучши его для FLUX.1 Kontext Pro. Используй конкретные, детальные инструкции. Сохрани точный смысл. Отвечай только улучшенным переводом."},
                    {"role": "user", "content": f"Переведи и улучши для редактирования изображения: {edit_prompt}"}
                ],
                max_tokens=200,
                temperature=0.1
            )
            english_prompt = translation_response.choices[0].message.content.strip()
            
            await update.message.reply_text(f"🔄 Улучшенный промпт на английском: {english_prompt}")
            
        except Exception as e:
            logging.error(f"Ошибка перевода промпта: {e}")
            english_prompt = edit_prompt  # Используем оригинальный промпт если перевод не удался
            await update.message.reply_text("⚠️ Не удалось перевести промпт, используем оригинальный текст")
        
        # Редактируем изображение с переведенным промптом
        await edit_image_with_flux(update, context, state, selected_image_url, english_prompt)
        
        # Сбрасываем состояние
        USER_STATE[user_id]['step'] = None
        USER_STATE[user_id].pop('selected_image_url', None)
    else:
        if update.message.photo:
            logging.info(f"Пользователь {user_id} отправил изображение, но не в режиме редактирования")
            await update.message.reply_text('📸 Вы отправили изображение, но сейчас не в режиме редактирования.\n\nНажмите кнопку "✏️ Редактировать изображение" в главном меню, чтобы начать редактирование.')
        else:
            await update.message.reply_text('Пожалуйста, следуйте инструкциям бота.')

async def generate_video(update, context, state):
    """Генерирует видео с помощью Replicate API"""
    user_id = update.effective_user.id
    
    try:
        # Получаем параметры из состояния
        video_type = state.get('video_type', 'text_to_video')
        video_quality = state.get('video_quality', '480p')
        video_duration = state.get('video_duration', 5)
        video_prompt = state.get('video_prompt', '')
        
        # Определяем параметры для модели
        if video_type == 'text_to_video':
            # Для text-to-video используем промпт из состояния
            if not video_prompt:
                # Если промпт не задан, запрашиваем его
                state['step'] = STEP_VIDEO_GENERATION
                if hasattr(update, 'callback_query') and update.callback_query:
                    await update.callback_query.edit_message_text(
                        "🎭 **Создание видео по тексту**\n\n"
                        "Опишите, что должно происходить в видео:\n\n"
                        "💡 Примеры:\n"
                        "• Красивая природа с цветущими деревьями\n"
                        "• Космический корабль летит среди звезд\n"
                        "• Городской пейзаж с небоскребами",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🔙 Назад", callback_data="back_to_main_options")
                        ]])
                    )
                else:
                    await update.message.reply_text(
                        "🎭 **Создание видео по тексту**\n\n"
                        "Опишите, что должно происходить в видео:\n\n"
                        "💡 Примеры:\n"
                        "• Красивая природа с цветущими деревьями\n"
                        "• Космический корабль летит среди звезд\n"
                        "• Городской пейзаж с небоскребами",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🔙 Назад", callback_data="back_to_main_options")
                        ]])
                    )
                return
            
            # Параметры для text-to-video
            input_data = {
                "prompt": video_prompt,
                "width": 512 if video_quality == "480p" else 1024,
                "height": 512 if video_quality == "480p" else 1024,
                "num_frames": 16 if video_duration == 5 else 32,
                "fps": 8
            }
        else:
            # Для image-to-video нужен URL изображения
            # Проверяем, есть ли изображение в состоянии
            if 'selected_image_url' not in state:
                # Если изображение не выбрано, запрашиваем его
                state['step'] = 'waiting_for_image'
                if hasattr(update, 'callback_query') and update.callback_query:
                    await update.callback_query.edit_message_text(
                        "🖼️ **Создание видео из изображения**\n\n"
                        "Пожалуйста, загрузите изображение, из которого хотите создать видео.\n\n"
                        "💡 Рекомендуется использовать качественные изображения в формате JPG или PNG.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🔙 Назад", callback_data="back_to_main_options")
                        ]])
                    )
                else:
                    await update.message.reply_text(
                        "🖼️ **Создание видео из изображения**\n\n"
                        "Пожалуйста, загрузите изображение, из которого хотите создать видео.\n\n"
                        "💡 Рекомендуется использовать качественные изображения в формате JPG или PNG.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🔙 Назад", callback_data="back_to_main_options")
                        ]])
                    )
                return
            
            # Параметры для image-to-video
            input_data = {
                "image": state['selected_image_url'],
                "width": 512 if video_quality == "480p" else 1024,
                "height": 512 if video_quality == "480p" else 1024,
                "num_frames": 16 if video_duration == 5 else 32,
                "fps": 8
            }
        
        # Отправляем сообщение о начале генерации
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(
                f"🎬 **Генерация видео началась!**\n\n"
                f"📝 Промпт: {video_prompt}\n"
                f"⚡ Качество: {video_quality}\n"
                f"⏱️ Длительность: {video_duration} сек\n\n"
                f"⏳ Пожалуйста, подождите...\n"
                f"Это может занять 1-3 минуты.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⏳ Генерация...", callback_data="waiting")
                ]])
            )
        else:
            # Если это не callback_query (например, загрузка изображения)
            await update.message.reply_text(
                f"🎬 **Генерация видео началась!**\n\n"
                f"📝 Промпт: {video_prompt}\n"
                f"⚡ Качество: {video_quality}\n"
                f"⏱️ Длительность: {video_duration} сек\n\n"
                f"⏳ Пожалуйста, подождите...\n"
                f"Это может занять 1-3 минуты."
            )
        
        # Вызываем Replicate API для генерации видео
        import replicate
        
        # Используем модель Bytedance Seedance 1.0 Pro
        output = replicate.run(
            "bytedance/seedance-1-pro",
            input=input_data
        )
        
        if output and len(output) > 0:
            video_url = output[0]
            
            # Отправляем видео пользователю
            await context.bot.send_video(
                chat_id=user_id,
                video=video_url,
                caption=f"🎬 **Видео готово!**\n\n"
                        f"📝 Промпт: {video_prompt}\n"
                        f"⚡ Качество: {video_quality}\n"
                        f"⏱️ Длительность: {video_duration} сек\n\n"
                        f"✨ Создано с помощью Bytedance Seedance 1.0 Pro"
            )
            
            # Показываем кнопки для дальнейших действий
            keyboard = [
                [InlineKeyboardButton("🎬 Создать еще видео", callback_data="video_generation")],
                [InlineKeyboardButton("🎨 Создать изображения", callback_data="create_content")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=user_id,
                text="🎉 **Видео успешно создано!**\n\n"
                     "Что хотите сделать дальше?",
                reply_markup=reply_markup
            )
            
            # Сбрасываем состояние
            state['step'] = None
            state.pop('video_type', None)
            state.pop('video_quality', None)
            state.pop('video_duration', None)
            state.pop('video_prompt', None)
            
        else:
            raise Exception("API не вернул результат")
            
    except Exception as e:
        logging.error(f"Ошибка при генерации видео: {e}")
        
        # Показываем сообщение об ошибке
        keyboard = [
            [InlineKeyboardButton("🔄 Попробовать снова", callback_data="video_generation")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(
                f"❌ **Ошибка при генерации видео**\n\n"
                f"Произошла ошибка: {str(e)}\n\n"
                f"Попробуйте еще раз или обратитесь в поддержку.",
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                f"❌ **Ошибка при генерации видео**\n\n"
                f"Произошла ошибка: {str(e)}\n\n"
                f"Попробуйте еще раз или обратитесь в поддержку.",
                reply_markup=reply_markup
            )
        
        # Сбрасываем состояние
        state['step'] = None
        state.pop('video_type', None)
        state.pop('video_quality', None)
        state.pop('video_duration', None)
        state.pop('video_prompt', None)

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
    app.add_handler(CommandHandler('my_id', my_id_command))  # Временная команда
    app.add_handler(CommandHandler('admin_stats', admin_stats_command))
    app.add_handler(CommandHandler('ideogram_tips', ideogram_tips_command))
    app.add_handler(CommandHandler('check_replicate', check_replicate))
    app.add_handler(CommandHandler('test_ideogram', test_ideogram))
    app.add_handler(CommandHandler('test_image_send', test_image_send))
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
        from telegram.ext import Application
        import asyncio
        
        async def start_webhook():
            await app.initialize()
            await app.start()
            await app.bot.set_webhook(url=f"https://web-production-3dd82.up.railway.app/{TOKEN}")
            await app.updater.start_webhook(
                listen="0.0.0.0",
                port=port,
                url_path=TOKEN,
                webhook_url=f"https://web-production-3dd82.up.railway.app/{TOKEN}"
            )
            print(f"🚀 Бот запущен на Railway на порту {port}")
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
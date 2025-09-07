import logging
import asyncio
import concurrent.futures
from typing import Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, BotCommand

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
from betatransfer_api import BetatransferAPI

# Создаем пул потоков для блокирующих операций
THREAD_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=10)

# Создаем пул HTTP соединений для aiohttp
HTTP_SESSION = None

# Flask для callback сервера
from flask import Flask, request, jsonify
from betatransfer_api import betatransfer_api

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

async def replicate_run_async(model: str, input_params: Dict[str, Any], timeout: int = 300) -> Any:
    """
    Асинхронная обертка для replicate.run
    Использует пул потоков для предотвращения блокировки event loop
    """
    try:
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(
                THREAD_POOL,
                lambda: replicate.run(model, input=input_params)
            ),
            timeout=timeout
        )
        return result
    except asyncio.TimeoutError:
        logging.error(f"Таймаут при выполнении replicate.run для модели {model}")
        raise
    except Exception as e:
        logging.error(f"Ошибка при выполнении replicate.run для модели {model}: {e}")
        raise

async def openai_chat_completion_async(messages: list, model: str = "gpt-4o-mini", max_tokens: int = 800, temperature: float = 0.7) -> str:
    """
    Асинхронная обертка для OpenAI chat completion
    """
    try:
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        loop = asyncio.get_event_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(
                THREAD_POOL,
                lambda: client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            ),
            timeout=30.0
        )
        return response.choices[0].message.content.strip()
    except asyncio.TimeoutError:
        logging.error("Таймаут при выполнении OpenAI chat completion")
        raise
    except Exception as e:
        logging.error(f"Ошибка при выполнении OpenAI chat completion: {e}")
        raise

# Функция для автоматической проверки статуса платежей
async def check_pending_payments():
    """Проверяет статус всех pending платежей и зачисляет кредиты при завершении"""
    try:
        # Получаем все pending платежи из базы данных
        pending_payments = analytics_db.get_pending_payments()
        
        if not pending_payments:
            return
        
        logging.info(f"Проверяем {len(pending_payments)} pending платежей")
        
        for payment in pending_payments:
            payment_id = payment.get('betatransfer_id')
            user_id = payment.get('user_id')
            order_id = payment.get('order_id')
            
            if not payment_id:
                continue
            
            try:
                # Проверяем статус платежа через Betatransfer API
                status_result = betatransfer_api.get_payment_status(payment_id)
                
                if 'error' in status_result:
                    logging.error(f"Ошибка проверки статуса платежа {payment_id}: {status_result['error']}")
                    continue
                
                payment_status = status_result.get('status')
                logging.info(f"Платеж {payment_id} имеет статус: {payment_status}")
                
                # Если платеж завершен, зачисляем кредиты
                if payment_status == 'success':
                    credit_amount = payment.get('credit_amount')
                    
                    if credit_amount and credit_amount > 0:
                        # Проверяем, не зачислены ли уже кредиты за этот платеж
                        # Ищем транзакцию с этим payment_id
                        existing_transaction = analytics_db.get_credit_transaction_by_payment_id(payment_id)
                        
                        if not existing_transaction:
                            # Кредиты еще не зачислены, зачисляем
                            analytics_db.add_credits(user_id, credit_amount)
                            
                            # Создаем транзакцию с привязкой к платежу
                            analytics_db.create_credit_transaction_with_payment(user_id, credit_amount, f"Покупка кредитов (платеж {payment_id})", payment_id)
                            
                            # Обновляем статус платежа
                            analytics_db.update_payment_status(payment_id, 'success')
                            
                            # Отправляем уведомление пользователю
                            notification_message = (
                                f"✅ **Кредиты зачислены!**\n\n"
                                f"🪙 **Получено:** {credit_amount:,} кредитов\n"
                                f"💰 **Сумма:** {payment.get('amount')} {payment.get('currency', 'RUB')}\n"
                                f"📦 **Платеж:** {payment_id}\n\n"
                                f"Теперь вы можете использовать кредиты для генерации изображений!"
                            )
                            
                            await send_telegram_notification(user_id, notification_message)
                            logging.info(f"Кредиты зачислены пользователю {user_id}: {credit_amount}")
                        else:
                            # Кредиты уже зачислены, просто обновляем статус платежа
                            analytics_db.update_payment_status(payment_id, 'success')
                            logging.info(f"Кредиты уже зачислены за платеж {payment_id}, обновляем только статус")
                
                elif payment_status == 'failed':
                    # Обновляем статус неудачного платежа
                    analytics_db.update_payment_status(payment_id, 'failed')
                    logging.info(f"Платеж {payment_id} завершился неудачно")
                
            except Exception as e:
                logging.error(f"Ошибка обработки платежа {payment_id}: {e}")
                continue
                
    except Exception as e:
        logging.error(f"Ошибка проверки pending платежей: {e}")

# Функция для запуска периодической проверки платежей
async def start_payment_polling():
    """Запускает периодическую проверку статуса платежей"""
    while True:
        try:
            await check_pending_payments()
            # Ждем 45 секунд перед следующей проверкой
            await asyncio.sleep(45)
        except Exception as e:
            logging.error(f"Ошибка в payment polling: {e}")
            # При ошибке ждем меньше времени
            await asyncio.sleep(15)

# Создаем Flask приложение для callback
flask_app = Flask(__name__)

async def send_telegram_notification(user_id: int, message: str):
    """
    Отправляет уведомление пользователю в Telegram
    
    Args:
        user_id: ID пользователя в Telegram
        message: Текст сообщения
    """
    try:
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not bot_token:
            logging.error("TELEGRAM_BOT_TOKEN не установлен")
            return False
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = {
            'chat_id': user_id,
            'text': message,
            'parse_mode': 'Markdown'
        }
        
        # Используем асинхронный вызов для предотвращения блокировки
        loop = asyncio.get_event_loop()
        # Используем асинхронный HTTP клиент
        session = await init_http_session()
        async with session.post(url, data=data) as response:
            if response.status == 200:
                logging.info(f"Уведомление отправлено пользователю {user_id}")
                return True
            else:
                response_text = await response.text()
                logging.error(f"Ошибка отправки уведомления: {response.status} - {response_text}")
                return False
        
        if response.status_code == 200:
            logging.info(f"Уведомление отправлено пользователю {user_id}")
            return True
        else:
            logging.error(f"Ошибка отправки уведомления: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logging.error(f"Ошибка отправки уведомления пользователю {user_id}: {e}")
        return False

@flask_app.route('/payment/ca', methods=['POST'])
async def payment_callback():
    """
    Обрабатывает callback уведомления от Betatransfer
    """
    try:
        # Получаем данные callback (формат: application/x-www-form-urlencoded)
        callback_data = request.form.to_dict()
        logging.info(f"Получен callback: {callback_data}")
        
        if not callback_data:
            logging.error("Пустые данные callback")
            return jsonify({"error": "Empty callback data"}), 400
        
        # Обрабатываем callback через API
        result = betatransfer_api.process_callback(callback_data)
        
        if result.get("status") == "error":
            logging.error(f"Ошибка обработки callback: {result.get('error')}")
            return jsonify({"error": result.get("error")}), 400
        
        # Извлекаем информацию о платеже
        payment_info = result.get("payment_info", {})
        payment_id = payment_info.get("payment_id")
        status = payment_info.get("status")
        amount = payment_info.get("amount")
        order_id = payment_info.get("order_id")
        currency = payment_info.get("currency", "RUB")
        
        logging.info(f"Платеж {payment_id} обработан, статус: {status}")
        
        # Если платеж успешен, зачисляем кредиты
        if status == "completed":
            # Получаем информацию о заказе из базы
            payment_record = analytics_db.get_payment_by_order_id(order_id)
            if payment_record:
                user_id = payment_record.get("user_id")
                credit_amount = payment_record.get("credit_amount")
                
                # Зачисляем кредиты пользователю
                analytics_db.add_credits(user_id, credit_amount)
                
                # Обновляем статус платежа
                analytics_db.update_payment_status(payment_id, "completed")
                
                logging.info(f"Кредиты зачислены пользователю {user_id}: {credit_amount}")
                
                # Отправляем уведомление пользователю
                notification_message = (
                    f"✅ **Кредиты зачислены!**\n\n"
                    f"🪙 **Получено:** {credit_amount:,} кредитов\n"
                    f"💰 **Сумма:** {amount} {currency}\n"
                    f"📦 **Платеж:** {payment_id}\n\n"
                    f"Теперь вы можете использовать кредиты для генерации изображений!"
                )
                
                # Отправляем уведомление пользователю
                notification_sent = await send_telegram_notification(user_id, notification_message)
                if notification_sent:
                    logging.info(f"Уведомление о зачислении кредитов отправлено пользователю {user_id}")
                else:
                    logging.warning(f"Не удалось отправить уведомление пользователю {user_id}")
            else:
                logging.error(f"Платеж с order_id {order_id} не найден в базе данных")
        
        # Возвращаем 200 OK (требование Betatransfer)
        return jsonify({"status": "success"}), 200
        
    except Exception as e:
        logging.error(f"Ошибка обработки callback: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@flask_app.route('/payment/su', methods=['GET'])
def payment_success():
    """
    Страница успешной оплаты
    """
    return jsonify({
        "status": "success",
        "message": "Payment completed successfully"
    })

@flask_app.route('/payment/fai', methods=['GET'])
def payment_fail():
    """
    Страница неуспешной оплаты
    """
    return jsonify({
        "status": "failed",
        "message": "Payment failed"
    })

@flask_app.route('/health', methods=['GET'])
def health_check():
    """
    Проверка здоровья сервера
    """
    return jsonify({"status": "healthy"})

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
        return "1024x1792"  # 9:16 соотношение сторон
    elif format_type == 'instagrampost':
        return "1024x1024"  # 1:1 соотношение сторон
    else:
        return "1024x1024"  # По умолчанию квадратный формат

def get_replicate_size_for_model(model_name, format_type):
    """Определяет размер для конкретной модели Replicate"""
    # Для Ideogram используем специальные размеры
    if 'ideogram' in model_name.lower():
        return get_replicate_size_for_format(format_type)
    
    # Для других моделей используем стандартные размеры
    return get_replicate_size_for_format(format_type)

def get_replicate_params_for_model(model_name, format_type, simple_orientation=None):
    """Возвращает параметры для конкретной модели Replicate"""
    size = get_replicate_size_for_model(model_name, format_type)
    
    # Базовые параметры
    params = {
        'width': int(size.split('x')[0]),
        'height': int(size.split('x')[1])
    }
    
    # Специфичные параметры для разных моделей
    if 'ideogram' in model_name.lower():
        params.update({
            'style': 'auto',
            'aspect_ratio': f"{params['width']}:{params['height']}"
        })
    elif 'bytedance' in model_name.lower():
        params.update({
            'style': 'realistic',
            'quality': 'high'
        })
    elif 'imagen' in model_name.lower():
        params.update({
            'style': 'photorealistic',
            'safety_filter': 'moderate'
        })
    
    return params

def get_format_tips(format_type):
    """Возвращает советы по формату"""
    tips = {
        'instagram reels': "🎬 Для Reels: используйте вертикальные кадры, яркие цвета, динамичные сцены",
        'tiktok': "🎵 Для TikTok: короткие клипы, трендовые эффекты, молодежный стиль",
        'youtube shorts': "📺 Для Shorts: информативный контент, четкая структура, призыв к действию",
        'instagram post': "📸 Для постов: квадратный формат, качественные изображения, хештеги",
        'instagram stories': "📱 Для Stories: вертикальный формат, временный контент, интерактивность",
        'изображения': "🖼️ Для изображений: выберите подходящую ориентацию и стиль"
    }
    
    return tips.get(format_type.lower(), "Выберите подходящий формат для вашего контента")

def is_prompt_safe(prompt):
    """Проверяет безопасность промпта"""
    # Список запрещенных слов и фраз
    forbidden_words = [
        'nude', 'naked', 'sex', 'porn', 'nsfw', 'adult', 'explicit',
        'violence', 'blood', 'gore', 'weapon', 'gun', 'knife',
        'hate', 'racism', 'discrimination', 'offensive'
    ]
    
    prompt_lower = prompt.lower()
    for word in forbidden_words:
        if word in prompt_lower:
            return False
    
    return True

def improve_prompt_for_ideogram(prompt):
    """Улучшает промпт для Ideogram"""
    # Добавляем ключевые слова для лучшего качества
    improvements = [
        "high quality",
        "detailed",
        "professional",
        "sharp focus",
        "vibrant colors"
    ]
    
    # Проверяем, есть ли уже эти слова
    prompt_lower = prompt.lower()
    for improvement in improvements:
        if improvement not in prompt_lower:
            prompt += f", {improvement}"
    
    return prompt

def enhance_prompts_with_character_context(prompts, topic):
    """Улучшает промпты с контекстом персонажа"""
    enhanced_prompts = []
    
    for prompt in prompts:
        # Добавляем контекст темы
        enhanced_prompt = f"{prompt}, {topic} theme, character-focused"
        enhanced_prompts.append(enhanced_prompt)
    
    return enhanced_prompts

# ============================================================================
# ASYNC HANDLERS - ТОЛЬКО ПЕРВЫЕ ВЕРСИИ (БЕЗ ДУБЛИКАТОВ)
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
        [InlineKeyboardButton("ℹ️ О боте", callback_data="about_bot")],
        [InlineKeyboardButton("📞 Поддержка", callback_data="support")]
    ]
    
    await update.callback_query.edit_message_text(
        f"🎨 AI Image Generator\n\n{status_text}"
        "💡 **Бесплатно:**\n"
        "• 🖼️ Создать изображения (3 раза)\n"
        "• ✏️ Редактировать изображения (3 раза)\n\n"
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

async def show_model_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает выбор модели с навигацией"""
    keyboard = [
        [InlineKeyboardButton("📱 Ideogram (лидер в генерации текста в изображениях: баннеры, постеры, соцсети)", callback_data="image_gen_model:Ideogram")],
        [InlineKeyboardButton("⚡ Bytedance Seedream-3 (нативная 2K генерация, быстрая)", callback_data="image_gen_model:Bytedance (Seedream-3)")],
        [InlineKeyboardButton("🔬 Google Imagen 4 Ultra (максимальное качество, детали)", callback_data="image_gen_model:Google Imagen 4 Ultra")],
        [InlineKeyboardButton("🏗️ Luma Photon (креативные возможности, высокое качество)", callback_data="image_gen_model:Luma Photon")],
        [InlineKeyboardButton("💼 Bria 3.2 (коммерческое использование, 4B параметров)", callback_data="image_gen_model:Bria 3.2")],
        [InlineKeyboardButton("🎨 Recraft AI (дизайн, вектор, логотипы, бренд-дизайн, SVG)", callback_data="image_gen_model:Recraft AI")],
        [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")],
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

async def credits_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для просмотра статистики по кредитам (только для админа)"""
    ADMIN_USER_ID = 7735323051  # Ваш ID
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("❌ У вас нет доступа к этой команде.")
        return
    try:
        stats = analytics_db.get_total_credits_statistics()
        stats_text = f"""🪙 **СТАТИСТИКА КРЕДИТОВ БОТА**
📊 **ОБЩАЯ СТАТИСТИКА:**
• 👥 Пользователей с кредитами: {stats['total_users']}
• 🪙 Всего куплено кредитов: {stats['total_purchased']:,}
• 💸 Всего использовано кредитов: {stats['total_used']:,}
• 💰 Текущий баланс кредитов: {stats['total_balance']:,}
💡 **ДЛЯ ПОПОЛНЕНИЯ REPLICATE/OPENAI:**
🔥 Общее количество купленных кредитов: **{stats['total_purchased']:,}**
💰 Необходимо пополнить на сумму: **сом{stats['completed_revenue']:,.2f}**"""
        await update.message.reply_text(stats_text, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text("❌ Ошибка получения статистики.")

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
    global_stats = analytics_db.get_global_stats()
    
    if not global_stats:
        await update.message.reply_text("📊 Статистика пока недоступна.")
        return
    
    # Формируем текст статистики
    stats_text = f"""
📊 **Глобальная статистика бота:**

👥 **Пользователи:**
• Всего пользователей: {global_stats['total_users']}
• Активных за 24ч: {global_stats['active_24h']}
• Активных за 7д: {global_stats['active_7d']}
• Активных за 30д: {global_stats['active_30d']}

🎨 **Генерации:**
• Всего генераций: {global_stats['total_generations']}
• Успешных: {global_stats['successful_generations']}
• Ошибок: {global_stats['total_errors']}
• Успешность: {(global_stats['successful_generations'] / global_stats['total_generations'] * 100):.1f}%

📈 **Популярные модели:**
"""
    
    # Добавляем статистику по моделям
    if global_stats['top_models']:
        for model, count in global_stats['top_models'][:5]:
            stats_text += f"• {model}: {count}\n"
    else:
        stats_text += "• Нет данных\n"
    
    stats_text += "\n📱 **Популярные форматы:**\n"
    
    # Добавляем статистику по форматам
    if global_stats['top_formats']:
        for format_type, count in global_stats['top_formats'][:5]:
            stats_text += f"• {format_type}: {count}\n"
    else:
        stats_text += "• Нет данных\n"
    
    keyboard = [
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    
    await update.message.reply_text(
        stats_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ============================================================================
# PLACEHOLDER FUNCTIONS - НУЖНО ДОБАВИТЬ ОСТАЛЬНЫЕ ФУНКЦИИ
# ============================================================================

# Временные заглушки для функций, которые нужно добавить
async def ideogram_tips_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для показа советов по Ideogram"""
    await update.message.reply_text("🎨 Советы по Ideogram будут добавлены в следующей версии.")

async def check_replicate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка статуса Replicate"""
    await update.message.reply_text("🔍 Проверка Replicate будет добавлена в следующей версии.")

async def test_ideogram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тест Ideogram"""
    await update.message.reply_text("🧪 Тест Ideogram будет добавлен в следующей версии.")

async def test_image_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тест отправки изображений"""
    await update.message.reply_text("📤 Тест отправки изображений будет добавлен в следующей версии.")

async def edit_image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда редактирования изображений"""
    await update.message.reply_text("✏️ Редактирование изображений будет добавлено в следующей версии.")

async def add_credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление кредитов (админ)"""
    user_id = update.effective_user.id
    
    # Проверяем, является ли пользователь админом
    if user_id not in [int(x) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip()]:
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    
    # Получаем аргументы команды
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "❌ Неверный формат команды.\n\n"
            "Использование: /add_credits <user_id> <amount>\n"
            "Пример: /add_credits 123456789 1000"
        )
        return
    
    try:
        target_user_id = int(args[0])
        credits_amount = int(args[1])
        
        if credits_amount <= 0:
            await update.message.reply_text("❌ Количество кредитов должно быть положительным числом.")
            return
        
        # Добавляем кредиты пользователю
        success = analytics_db.add_user_credits(target_user_id, credits_amount, "admin_add")
        
        if success:
            await update.message.reply_text(
                f"✅ **Кредиты успешно добавлены!**\n\n"
                f"👤 Пользователь: `{target_user_id}`\n"
                f"🪙 Добавлено: **{credits_amount} кредитов**\n"
                f"📅 Дата: {time.strftime('%Y-%m-%d %H:%M:%S')}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("❌ Ошибка при добавлении кредитов.")
            
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID пользователя или количества кредитов.")

async def check_credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка кредитов"""
    user_id = update.effective_user.id
    
    # Проверяем, является ли пользователь админом
    if user_id not in [int(x) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip()]:
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    
    # Получаем аргументы команды
    args = context.args
    if len(args) < 1:
        await update.message.reply_text(
            "❌ Неверный формат команды.\n\n"
            "Использование: /check_credits <user_id>\n"
            "Пример: /check_credits 123456789"
        )
        return
    
    try:
        target_user_id = int(args[0])
        
        # Получаем информацию о кредитах пользователя
        user_credits = analytics_db.get_user_credits(target_user_id)
        
        if user_credits:
            await update.message.reply_text(
                f"🪙 **Информация о кредитах пользователя**\n\n"
                f"👤 ID: `{target_user_id}`\n"
                f"💰 Текущий баланс: **{user_credits['balance']} кредитов**\n"
                f"🛒 Всего куплено: **{user_credits['total_purchased']} кредитов**\n"
                f"💸 Всего использовано: **{user_credits['total_used']} кредитов**\n"
                f"📅 Последнее обновление: {user_credits['updated_at'][:19]}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(f"❌ Пользователь `{target_user_id}` не найден в базе данных.", parse_mode='Markdown')
            
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID пользователя.")

async def set_credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка кредитов (админ)"""
    user_id = update.effective_user.id
    
    # Проверяем, является ли пользователь админом
    if user_id not in [int(x) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip()]:
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    
    # Получаем аргументы команды
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "❌ Неверный формат команды.\n\n"
            "Использование: /set_credits <user_id> <amount>\n"
            "Пример: /set_credits 123456789 1000"
        )
        return
    
    try:
        target_user_id = int(args[0])
        credits_amount = int(args[1])
        
        if credits_amount < 0:
            await update.message.reply_text("❌ Количество кредитов не может быть отрицательным.")
            return
        
        # Устанавливаем кредиты пользователю
        success = analytics_db.set_user_credits(target_user_id, credits_amount, "admin_set")
        
        if success:
            await update.message.reply_text(
                f"✅ **Кредиты успешно установлены!**\n\n"
                f"👤 Пользователь: `{target_user_id}`\n"
                f"🪙 Установлено: **{credits_amount} кредитов**\n"
                f"📅 Дата: {time.strftime('%Y-%m-%d %H:%M:%S')}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("❌ Ошибка при установке кредитов.")
            
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID пользователя или количества кредитов.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок"""
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
    
    # Обработка советов по Ideogram
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
❌ Плохо: "Очень красивая девушка с длинными волнистыми каштановыми волосами, одетая в элегантное красное платье"
✅ Хорошо: "девушка в красном платье"

### 2. **Фокусируйтесь на главном объекте**
❌ Плохо: "Современный дом с большими окнами, красивым садом, бассейном, гаражом"
✅ Хорошо: "современный дом с большими окнами"

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
    
    # Основные навигационные кнопки
    elif data == "create_content":
        await show_format_selection(update, context)
    
    elif data == "create_simple_images":
        # Для простых изображений сначала выбираем ориентацию
        USER_STATE[user_id] = {'step': 'simple_orientation', 'format': 'изображения'}
        
        keyboard = [
            [InlineKeyboardButton("📱 Вертикальное (9:16)", callback_data="simple_orientation:vertical")],
            [InlineKeyboardButton("⬜ Квадратное (1:1)", callback_data="simple_orientation:square")]
        ]
        keyboard.extend([
            [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "Выберите ориентацию изображения:",
            reply_markup=reply_markup
        )
    
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
    
    elif data == "support":
        await show_support(update, context)
    
    elif data == "main_menu":
        await show_main_menu(update, context)
    
    elif data == "format_selection":
        await show_format_selection(update, context)
    
    # Обработка выбора формата
    elif data.startswith("format:"):
        format_type = data.split(":", 1)[1]
        USER_STATE[user_id] = {'step': 'style', 'format': format_type}
        await show_style_selection(update, context)
    
    # Обработка выбора модели
    elif data.startswith("image_gen_model:"):
        model_name = data.split(":", 1)[1]
        USER_STATE[user_id]['model'] = model_name
        USER_STATE[user_id]['step'] = 'image_style'
        await show_image_style_selection(update, context)
    
    # Обработка выбора стиля изображения
    elif data.startswith("image_style:"):
        style = data.split(":", 1)[1]
        USER_STATE[user_id]['image_style'] = style
        USER_STATE[user_id]['step'] = 'image_count'
        await show_image_count_selection(update, context)
    
    # Обработка выбора количества изображений
    elif data.startswith("image_count:"):
        count = int(data.split(":", 1)[1])
        USER_STATE[user_id]['image_count'] = count
        USER_STATE[user_id]['step'] = 'image_prompt'
        await query.edit_message_text("Опишите, что должно быть на картинке:")
    
    # Обработка выбора ориентации для простых изображений
    elif data.startswith("simple_orientation:"):
        orientation = data.split(":", 1)[1]
        USER_STATE[user_id]['orientation'] = orientation
        USER_STATE[user_id]['step'] = 'simple_model'
        await show_model_selection(update, context)
    
    # Обработка генерации видео
    elif data == "video_generation":
        await query.edit_message_text(
            "🎬 **Генерация видео**\n\n"
            "⚠️ Функция генерации видео будет добавлена в следующей версии.\n\n"
            "Планируемые возможности:\n"
            "• Создание коротких видео для TikTok, Instagram Reels\n"
            "• Генерация анимации по описанию\n"
            "• Создание видео с текстом и изображениями",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
            ]])
        )
    
    # Обработка покупки кредитов
    elif data == "credit_packages":
        await show_credit_packages(update, context)
    
    # Обработка покупки конкретного пакета кредитов
    elif data.startswith("buy_credits:"):
        package_type = data.split(":", 1)[1]
        await handle_credit_purchase(update, context, package_type)
    
    # Обработка проверки статуса платежа
    elif data.startswith("check_payment:"):
        order_id = data.split(":", 1)[1]
        await check_payment_status(update, context, order_id)
    
    # Обработка выбора стиля
    elif data.startswith("style:"):
        style = data.split(":", 1)[1]
        USER_STATE[user_id]['style'] = style
        USER_STATE[user_id]['step'] = 'model'
        await show_model_selection(update, context)
    
    # Обработка возврата к предыдущему шагу
    elif data == "retry_generation":
        current_step = state.get('step', '')
        if current_step in ['image_prompt', 'edit_prompt']:
            if current_step == 'image_prompt':
                await query.edit_message_text("Попробуйте еще раз. Опишите, что должно быть на картинке:")
            elif current_step == 'edit_prompt':
                await query.edit_message_text("Попробуйте еще раз. Опишите, что хотите изменить в изображении:")
        else:
            await show_main_menu(update, context)
    
    # Обработка сброса настроек
    elif data == "reset":
        USER_STATE[user_id] = {'step': 'main_menu'}
        await show_main_menu(update, context)
    
    # Обработка возврата к главному меню
    elif data == "back_to_main":
        await show_main_menu(update, context)
    
    # Обработка изменения настроек
    elif data == "change_settings":
        await show_format_selection(update, context)
    
    # Обработка создания больше изображений
    elif data == "more_images":
        current_step = state.get('step', '')
        if current_step == 'main_menu':
            await show_format_selection(update, context)
        else:
            await show_main_menu(update, context)
    
    # Обработка создания больше изображений с теми же настройками
    elif data == "more_images_same_settings":
        if 'prompt' in state and 'model' in state:
            await send_images(update, context, state, prompt_type='user', user_prompt=state['prompt'])
        else:
            await show_main_menu(update, context)
    
    # Обработка кастомного количества изображений
    elif data == "custom_image_count_simple":
        USER_STATE[user_id]['step'] = 'custom_image_count'
        await query.edit_message_text("Введите количество изображений (от 1 до 10):")
    
    # Обработка кастомного промпта для изображений
    elif data == "custom_image_prompt":
        USER_STATE[user_id]['step'] = 'custom_image_prompt'
        await query.edit_message_text("Опишите, что должно быть на картинке:")
    
    # Обработка кастомного стиля для изображений
    elif data == "custom_image_style":
        USER_STATE[user_id]['step'] = 'custom_image_style'
        await query.edit_message_text("Опишите стиль генерации изображения:")
    
    # Обработка генерации изображений
    elif data == "generate_images":
        if 'prompt' in state:
            await send_images(update, context, state, prompt_type='user', user_prompt=state['prompt'])
        else:
            await query.edit_message_text("❌ Промпт не найден. Попробуйте еще раз.")
    
    # Обработка возврата к выбору стиля
    elif data == "style_back":
        await show_style_selection(update, context)
    
    # Обработка возврата к выбору количества изображений
    elif data == "image_count_back":
        await show_image_count_selection(update, context)
    
    # Обработка возврата к выбору ориентации
    elif data == "simple_orientation_back":
        USER_STATE[user_id] = {'step': 'simple_orientation', 'format': 'изображения'}
        keyboard = [
            [InlineKeyboardButton("📱 Вертикальное (9:16)", callback_data="simple_orientation:vertical")],
            [InlineKeyboardButton("⬜ Квадратное (1:1)", callback_data="simple_orientation:square")]
        ]
        keyboard.extend([
            [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Выберите ориентацию изображения:", reply_markup=reply_markup)
    
    # Обработка возврата к выбору модели
    elif data == "model_back":
        await show_model_selection(update, context)
    
    # Обработка возврата к выбору стиля генерации
    elif data == "style_gen_back":
        await show_style_selection(update, context)
    
    # Обработка возврата к промпту простого изображения
    elif data == "simple_image_prompt_back":
        USER_STATE[user_id]['step'] = 'image_prompt'
        await query.edit_message_text("Опишите, что должно быть на картинке:")
    
    else:
        await query.edit_message_text("🔘 Неизвестная команда.")

async def show_style_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает выбор стиля контента"""
    keyboard = [
        [InlineKeyboardButton("🎯 Экспертно", callback_data="style:🎯 Экспертно")],
        [InlineKeyboardButton("😄 Легко", callback_data="style:😄 Легко")],
        [InlineKeyboardButton("🔥 Продающе", callback_data="style:🔥 Продающе")],
        [InlineKeyboardButton("💡 Вдохновляюще", callback_data="style:💡 Вдохновляюще")],
        [InlineKeyboardButton("🧠 Юмористично", callback_data="style:🧠 Юмористично")],
        [InlineKeyboardButton("Дружелюбный", callback_data="style:Дружелюбный")],
        [InlineKeyboardButton("Мотивационный", callback_data="style:Мотивационный")],
        [InlineKeyboardButton("Развлекательный", callback_data="style:Развлекательный")],
        [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    await update.callback_query.edit_message_text(
        "Выберите стиль контента:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_image_style_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает выбор стиля изображения"""
    keyboard = [
        [InlineKeyboardButton("Фотореализм", callback_data="image_style:Фотореализм")],
        [InlineKeyboardButton("Иллюстрация", callback_data="image_style:Иллюстрация")],
        [InlineKeyboardButton("Минимализм", callback_data="image_style:Минимализм")],
        [InlineKeyboardButton("Акварель", callback_data="image_style:Акварель")],
        [InlineKeyboardButton("Масляная живопись", callback_data="image_style:Масляная живопись")],
        [InlineKeyboardButton("Пиксель-арт", callback_data="image_style:Пиксель-арт")],
        [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    await update.callback_query.edit_message_text(
        "Выберите стиль изображения:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_image_count_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает выбор количества изображений"""
    keyboard = [
        [InlineKeyboardButton("1", callback_data="image_count:1")],
        [InlineKeyboardButton("2", callback_data="image_count:2")],
        [InlineKeyboardButton("3", callback_data="image_count:3")],
        [InlineKeyboardButton("4", callback_data="image_count:4")],
        [InlineKeyboardButton("5", callback_data="image_count:5")],
        [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    await update.callback_query.edit_message_text(
        "Выберите количество изображений:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает информацию о поддержке"""
    user_id = update.effective_user.id
    user_info = analytics_db.get_user_info_by_id(user_id)
    
    # Формируем информацию о пользователе
    username_display = f"@{user_info['username']}" if user_info and user_info['username'] else "Без username"
    name_display = f"{user_info['first_name'] or ''} {user_info['last_name'] or ''}".strip() if user_info else "Пользователь"
    
    support_text = f"""
📞 **Поддержка**

👤 **Ваша информация:**
🆔 ID: `{user_id}`
📝 Username: {username_display}
📝 Имя: {name_display}

💬 **Как связаться с поддержкой:**

1️⃣ **Напишите мне напрямую в Telegram:**
   👤 @aiimagebotmanager (основной канал связи)

2️⃣ **Опишите проблему:**
   • Проблема с оплатой
   • Техническая ошибка
   • Вопрос по использованию
   • Другое

3️⃣ **Приложите скриншоты** (если нужно)

4️⃣ **Укажите ваш ID:** `{user_id}`

⏰ **Время ответа:** обычно в течение 24 часов

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

🟢 **Малый пакет**
• 200 кредитов
• Цена: ₽1,129
• Идеально для тестирования

🟡 **Средний пакет** (Рекомендуется)
• 5,000 кредитов
• Цена: ₽2,420
• Экономия: 20%

🔴 **Большой пакет** (Максимальная экономия)
• 10,000 кредитов
• Цена: ₽4,030
• Экономия: 30%

💡 **Стоимость генераций:**
• Ideogram: 10 кредитов
• Bytedance: 10 кредитов
• Google Imagen: 16 кредитов
• Редактирование: 12 кредитов

🔄 **Кредиты не сгорают!**
Покупаете один раз, используете всегда.
"""
    
    keyboard = [
        [InlineKeyboardButton("🟢 Малый пакет (200 кредитов)", callback_data="buy_credits:small")],
        [InlineKeyboardButton("🟡 Средний пакет (5,000 кредитов)", callback_data="buy_credits:medium")],
        [InlineKeyboardButton("🔴 Большой пакет (10,000 кредитов)", callback_data="buy_credits:large")],
        [InlineKeyboardButton("📊 Моя статистика", callback_data="user_stats")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    
    await update.callback_query.edit_message_text(
        credit_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_credit_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE, package_type: str):
    """Обрабатывает покупку кредитов"""
    user_id = update.effective_user.id
    
    # Определяем параметры пакета
    packages = {
        'small': {'credits': 200, 'price': 1129, 'name': 'Малый пакет'},
        'medium': {'credits': 5000, 'price': 2420, 'name': 'Средний пакет'},
        'large': {'credits': 10000, 'price': 4030, 'name': 'Большой пакет'}
    }
    
    if package_type not in packages:
        await update.callback_query.edit_message_text("❌ Неверный тип пакета.")
        return
    
    package = packages[package_type]
    
    try:
        # Получаем информацию о пользователе
        user_info = analytics_db.get_user_info_by_id(user_id)
        user_name = f"{user_info['first_name'] or ''} {user_info['last_name'] or ''}".strip() if user_info else "Пользователь"
        user_email = user_info.get('email', '') if user_info else ''
        
        # Создаем уникальный ID заказа
        order_id = f"credits_{user_id}_{int(time.time())}"
        
        # Создаем платеж через Betatransfer API
        payment_result = betatransfer_api.create_payment(
            amount=package['price'],
            currency="RUB",
            description=f"Покупка {package['name']} - {package['credits']} кредитов",
            order_id=order_id,
            payer_email=user_email,
            payer_name=user_name,
            payer_id=str(user_id)
        )
        
        if payment_result.get('success'):
            # Сохраняем информацию о платеже в базе данных
            analytics_db.create_payment(
                user_id=user_id,
                order_id=order_id,
                amount=package['price'],
                currency="RUB",
                credits_amount=package['credits'],
                status="pending",
                payment_url=payment_result.get('payment_url', ''),
                description=f"Покупка {package['name']}"
            )
            
            # Показываем информацию о платеже
            purchase_text = f"""
🛒 **Платеж создан!**

📦 **Пакет:** {package['name']}
🪙 **Кредиты:** {package['credits']}
💰 **Цена:** ₽{package['price']}
🆔 **ID заказа:** `{order_id}`

💳 **Для оплаты:**
1. Нажмите кнопку "Оплатить"
2. Выберите способ оплаты
3. Завершите платеж
4. Нажмите "Проверить статус"

⏰ **Время на оплату:** 30 минут
"""
            
            keyboard = [
                [InlineKeyboardButton("💳 Оплатить", url=payment_result.get('payment_url', ''))],
                [InlineKeyboardButton("🔍 Проверить статус", callback_data=f"check_payment:{order_id}")],
                [InlineKeyboardButton("🪙 Другие пакеты", callback_data="credit_packages")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            
            await update.callback_query.edit_message_text(
                purchase_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            # Ошибка создания платежа
            error_text = f"""
❌ **Ошибка создания платежа**

📦 **Пакет:** {package['name']}
🪙 **Кредиты:** {package['credits']}
💰 **Цена:** ₽{package['price']}

🚨 **Проблема:** {payment_result.get('error', 'Неизвестная ошибка')}

💡 **Что делать:**
1. Попробуйте еще раз
2. Обратитесь к поддержке
3. Используйте бесплатные генерации
"""
            
            keyboard = [
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data=f"buy_credits:{package_type}")],
                [InlineKeyboardButton("📞 Поддержка", callback_data="support")],
                [InlineKeyboardButton("🎨 Бесплатные генерации", callback_data="create_content")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            
            await update.callback_query.edit_message_text(
                error_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    except Exception as e:
        logging.error(f"Ошибка при создании платежа: {str(e)}")
        
        # Fallback на старую логику
        purchase_text = f"""
🛒 **Подтверждение покупки**

📦 **Пакет:** {package['name']}
🪙 **Кредиты:** {package['credits']}
💰 **Цена:** ₽{package['price']}

⚠️ **Внимание:** Система платежей временно недоступна.

Для тестирования вы можете:
1. Обратиться к администратору
2. Использовать бесплатные генерации
3. Дождаться восстановления системы

💡 **Бесплатно доступно:**
• 3 генерации изображений
• 3 редактирования изображений
"""
        
        keyboard = [
            [InlineKeyboardButton("📞 Связаться с администратором", callback_data="support")],
            [InlineKeyboardButton("🎨 Использовать бесплатные генерации", callback_data="create_content")],
            [InlineKeyboardButton("🪙 Другие пакеты", callback_data="credit_packages")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        
        await update.callback_query.edit_message_text(
            purchase_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def check_payment_status(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str):
    """Проверяет статус платежа"""
    user_id = update.effective_user.id
    
    try:
        # Получаем информацию о платеже из базы данных
        payment_info = analytics_db.get_payment_by_order_id(order_id)
        
        if not payment_info:
            await update.callback_query.edit_message_text(
                "❌ Платеж не найден в базе данных.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🪙 Пакеты кредитов", callback_data="credit_packages"),
                    InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
                ]])
            )
            return
        
        # Проверяем статус платежа через Betatransfer API
        status_result = betatransfer_api.get_payment_status(order_id)
        
        if status_result.get('success'):
            payment_status = status_result.get('status', 'unknown')
            
            if payment_status == 'completed':
                # Платеж успешно завершен
                if payment_info['status'] != 'completed':
                    # Зачисляем кредиты пользователю
                    analytics_db.add_user_credits(
                        user_id=user_id,
                        credits_amount=payment_info['credits_amount'],
                        transaction_type="payment",
                        description=f"Покупка кредитов (заказ {order_id})"
                    )
                    
                    # Обновляем статус платежа
                    analytics_db.update_payment_status(order_id, 'completed')
                    
                    # Получаем обновленную информацию о кредитах
                    user_credits = analytics_db.get_user_credits(user_id)
                    new_balance = user_credits['balance'] if user_credits else 0
                    
                    success_text = f"""
✅ **Платеж успешно завершен!**

🆔 **ID заказа:** `{order_id}`
🪙 **Зачислено кредитов:** {payment_info['credits_amount']}
💰 **Сумма:** ₽{payment_info['amount']}
💳 **Статус:** Оплачено

🎉 **Ваш новый баланс:** {new_balance} кредитов

Теперь вы можете создавать изображения!
"""
                    
                    keyboard = [
                        [InlineKeyboardButton("🎨 Создать изображения", callback_data="create_content")],
                        [InlineKeyboardButton("📊 Моя статистика", callback_data="user_stats")],
                        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                    ]
                    
                    await update.callback_query.edit_message_text(
                        success_text,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                else:
                    # Платеж уже был обработан
                    await update.callback_query.edit_message_text(
                        "✅ Платеж уже был обработан ранее.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🎨 Создать изображения", callback_data="create_content"),
                            InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
                        ]])
                    )
            
            elif payment_status == 'pending':
                # Платеж в ожидании
                pending_text = f"""
⏳ **Платеж в ожидании**

🆔 **ID заказа:** `{order_id}`
🪙 **Кредиты:** {payment_info['credits_amount']}
💰 **Сумма:** ₽{payment_info['amount']}
💳 **Статус:** Ожидает оплаты

💡 **Что делать:**
1. Завершите оплату по ссылке
2. Нажмите "Проверить статус" еще раз
3. Кредиты будут зачислены автоматически

⏰ **Время на оплату:** 30 минут
"""
                
                keyboard = [
                    [InlineKeyboardButton("💳 Оплатить", url=payment_info.get('payment_url', ''))],
                    [InlineKeyboardButton("🔍 Проверить статус", callback_data=f"check_payment:{order_id}")],
                    [InlineKeyboardButton("🪙 Другие пакеты", callback_data="credit_packages")],
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                ]
                
                await update.callback_query.edit_message_text(
                    pending_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            
            elif payment_status == 'failed':
                # Платеж не удался
                failed_text = f"""
❌ **Платеж не удался**

🆔 **ID заказа:** `{order_id}`
🪙 **Кредиты:** {payment_info['credits_amount']}
💰 **Сумма:** ₽{payment_info['amount']}
💳 **Статус:** Не оплачен

💡 **Что делать:**
1. Попробуйте другой способ оплаты
2. Обратитесь к поддержке
3. Выберите другой пакет
"""
                
                keyboard = [
                    [InlineKeyboardButton("🔄 Попробовать снова", callback_data="credit_packages")],
                    [InlineKeyboardButton("📞 Поддержка", callback_data="support")],
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                ]
                
                await update.callback_query.edit_message_text(
                    failed_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            
            else:
                # Неизвестный статус
                await update.callback_query.edit_message_text(
                    f"❓ Неизвестный статус платежа: {payment_status}",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔍 Проверить еще раз", callback_data=f"check_payment:{order_id}"),
                        InlineKeyboardButton("📞 Поддержка", callback_data="support"),
                        InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
                    ]])
                )
        
        else:
            # Ошибка проверки статуса
            error_text = f"""
❌ **Ошибка проверки статуса**

🆔 **ID заказа:** `{order_id}`
🚨 **Проблема:** {status_result.get('error', 'Неизвестная ошибка')}

💡 **Что делать:**
1. Попробуйте еще раз
2. Обратитесь к поддержке
3. Проверьте правильность ID заказа
"""
            
            keyboard = [
                [InlineKeyboardButton("🔍 Проверить еще раз", callback_data=f"check_payment:{order_id}")],
                [InlineKeyboardButton("📞 Поддержка", callback_data="support")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            
            await update.callback_query.edit_message_text(
                error_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    except Exception as e:
        logging.error(f"Ошибка при проверке статуса платежа: {str(e)}")
        
        await update.callback_query.edit_message_text(
            "❌ Произошла ошибка при проверке статуса платежа. Попробуйте еще раз или обратитесь к поддержке.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔍 Проверить еще раз", callback_data=f"check_payment:{order_id}"),
                InlineKeyboardButton("📞 Поддержка", callback_data="support"),
                InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
            ]])
        )

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user_id = update.effective_user.id
    state = USER_STATE.get(user_id, {})
    step = state.get('step', '')
    
    if step == 'image_prompt':
        # Обработка промпта для генерации изображений
        prompt = update.message.text
        
        # Проверяем безопасность промпта
        if not is_prompt_safe(prompt):
            await update.message.reply_text(
                "❌ Промпт содержит запрещенный контент. Попробуйте другое описание.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Попробовать снова", callback_data="retry_generation"),
                    InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
                ]])
            )
            return
        
        # Обновляем состояние
        USER_STATE[user_id]['prompt'] = prompt
        USER_STATE[user_id]['step'] = 'generating'
        
        # Показываем сообщение о начале генерации
        await update.message.reply_text(
            f"🎨 **Генерация изображений началась!**\n\n"
            f"📝 **Промпт:** {prompt}\n"
            f"🎯 **Модель:** {state.get('model', 'Неизвестно')}\n"
            f"🎨 **Стиль:** {state.get('image_style', 'Неизвестно')}\n"
            f"🔢 **Количество:** {state.get('image_count', 1)}\n\n"
            f"⏳ Пожалуйста, подождите...",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
            ]])
        )
        
        # Запускаем генерацию изображений
        await send_images(update, context, state, prompt_type='user', user_prompt=prompt)
        
        # Сбрасываем состояние
        USER_STATE[user_id] = {'step': 'main_menu'}
    
    elif step == 'upload_image_for_edit':
        # Обработка загрузки изображения для редактирования
        if update.message.photo:
            await update.message.reply_text(
                "📤 **Изображение получено!**\n\n"
                "Теперь опишите, что хотите изменить в изображении:",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
                ]])
            )
            USER_STATE[user_id]['step'] = 'edit_prompt'
        else:
            await update.message.reply_text(
                "❌ Пожалуйста, отправьте изображение (фото), а не текст.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Назад", callback_data="edit_image"),
                    InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
                ]])
            )
    
    elif step == 'edit_prompt':
        # Обработка промпта для редактирования
        edit_prompt = update.message.text
        
        await update.message.reply_text(
            f"✏️ **Редактирование изображения началось!**\n\n"
            f"📝 **Изменения:** {edit_prompt}\n\n"
            f"⏳ Пожалуйста, подождите...",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
            ]])
        )
        
        # Здесь должна быть логика редактирования изображений
        await asyncio.sleep(2)  # Имитация редактирования
        
        await update.message.reply_text(
            "✅ **Редактирование завершено!**\n\n"
            "⚠️ Функция редактирования изображений будет добавлена в следующей версии.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✏️ Редактировать еще", callback_data="edit_image"),
                InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
            ]])
        )
        
        # Сбрасываем состояние
        USER_STATE[user_id] = {'step': 'main_menu'}
    
    elif step == 'custom_image_count':
        # Обработка кастомного количества изображений
        try:
            count = int(update.message.text)
            if 1 <= count <= 10:
                USER_STATE[user_id]['image_count'] = count
                USER_STATE[user_id]['step'] = 'image_prompt'
                await update.message.reply_text(f"✅ Установлено количество изображений: {count}\n\nТеперь опишите, что должно быть на картинке:")
            else:
                await update.message.reply_text(
                    "❌ Количество изображений должно быть от 1 до 10.\n\nПопробуйте еще раз:",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Назад", callback_data="image_count_back"),
                        InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
                    ]])
                )
        except ValueError:
            await update.message.reply_text(
                "❌ Пожалуйста, введите число от 1 до 10.\n\nПопробуйте еще раз:",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Назад", callback_data="image_count_back"),
                    InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
                ]])
            )
    
    elif step == 'custom_image_prompt':
        # Обработка кастомного промпта для изображений
        prompt = update.message.text
        
        # Проверяем безопасность промпта
        if not is_prompt_safe(prompt):
            await update.message.reply_text(
                "❌ Промпт содержит запрещенный контент. Попробуйте другое описание.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Попробовать снова", callback_data="retry_generation"),
                    InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
                ]])
            )
            return
        
        # Обновляем состояние
        USER_STATE[user_id]['prompt'] = prompt
        USER_STATE[user_id]['step'] = 'generating'
        
        # Запускаем генерацию изображений
        await send_images(update, context, state, prompt_type='user', user_prompt=prompt)
        
        # Сбрасываем состояние
        USER_STATE[user_id] = {'step': 'main_menu'}
    
    elif step == 'custom_image_style':
        # Обработка кастомного стиля для изображений
        style = update.message.text
        
        # Обновляем состояние
        USER_STATE[user_id]['image_style'] = style
        USER_STATE[user_id]['step'] = 'image_prompt'
        
        await update.message.reply_text(f"✅ Установлен стиль: {style}\n\nТеперь опишите, что должно быть на картинке:")
    
    else:
        # Обычное текстовое сообщение
        await update.message.reply_text(
            "💬 Я понимаю только команды и кнопки.\n\n"
            "Используйте меню для навигации или команду /start для начала.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
            ]])
        )

async def send_images(update, context, state, prompt_type='auto', user_prompt=None, scenes=None):
    """
    Генерирует изображения по промптам через Replicate API и отправляет их пользователю.
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

    user_id = update.effective_user.id
    
    # Логируем начало генерации
    analytics_db.update_user_activity(user_id)
    analytics_db.log_action(user_id, "start_generation", f"format:{state.get('format', 'unknown')}, model:{state.get('model', 'unknown')}")
    
    # Засекаем время начала генерации
    start_time = time.time()
    
    # Проверяем наличие API токенов
    if not os.getenv('REPLICATE_API_TOKEN'):
        if send_text:
            keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await send_text("❌ Ошибка: REPLICATE_API_TOKEN не установлен\n\nОбратитесь к администратору бота.", reply_markup=reply_markup)
        return
    
    # Определяем промпты для генерации
    if prompt_type == 'user' and user_prompt:
        prompts = [user_prompt]
    elif scenes:
        prompts = scenes[:5]  # Максимум 5 изображений
    else:
        # Создаем промпт на основе состояния
        topic = state.get('topic', 'красивый пейзаж')
        style = state.get('image_style', 'Фотореализм')
        prompts = [f"{topic}, {style}"]
    
    # Ограничиваем количество изображений
    max_images = min(len(prompts), 5)
    prompts = prompts[:max_images]
    
    images = []
    processed_count = 0
    
    # Показываем сообщение о начале генерации
    if send_text:
        await send_text(f"🎨 **Генерация {len(prompts)} изображений началась!**\n\n⏳ Пожалуйста, подождите...")
    
    # Генерируем изображения
    for i, prompt in enumerate(prompts):
        try:
            # Определяем модель для генерации
            selected_model = state.get('model', 'Ideogram')
            
            # Параметры для разных моделей
            if selected_model == 'Ideogram':
                model_name = "ideogram-ai/ideogram-v3-turbo"
                replicate_params = {
                    "prompt": prompt,
                    "aspect_ratio": "1:1",
                    "style": "auto",
                    "safety_tolerance": 2,
                    "magic_prompt": False
                }
            elif selected_model == 'Bytedance':
                model_name = "bytedance/seedream-3"
                replicate_params = {
                    "prompt": prompt,
                    "aspect_ratio": "1:1",
                    "style": "realistic",
                    "quality": "high"
                }
            elif selected_model == 'Google Imagen':
                model_name = "google/imagen-4-ultra"
                replicate_params = {
                    "prompt": prompt,
                    "aspect_ratio": "1:1",
                    "style": "realistic"
                }
            else:
                # Fallback на Ideogram
                model_name = "ideogram-ai/ideogram-v3-turbo"
                replicate_params = {
                    "prompt": prompt,
                    "aspect_ratio": "1:1",
                    "style": "auto"
                }
            
            # Генерируем изображение
            output = await replicate_run_async(model_name, replicate_params, timeout=120)
            
            # Обрабатываем результат
            image_url = None
            
            if hasattr(output, 'url'):
                image_url = output.url
            elif hasattr(output, '__getitem__'):
                image_url = output[0] if output else None
            elif isinstance(output, (list, tuple)) and len(output) > 0:
                image_url = output[0]
            else:
                image_url = str(output) if output else None
            
            if image_url:
                images.append(InputMediaPhoto(media=image_url))
                processed_count += 1
                
                # Логируем успешную генерацию
                analytics_db.log_action(user_id, "image_generated", f"model:{selected_model}, prompt_length:{len(prompt)}")
            
        except Exception as e:
            logging.error(f"Ошибка генерации изображения {i+1}: {str(e)}")
            analytics_db.log_action(user_id, "generation_error", f"model:{selected_model}, error:{str(e)[:100]}")
            continue
    
    # Отправляем результаты
    if images:
        try:
            if send_media:
                await send_media(images)
            
            # Логируем успешную отправку
            generation_time = time.time() - start_time
            analytics_db.log_action(user_id, "images_sent", f"count:{len(images)}, time:{generation_time:.1f}s")
            
            # Показываем статистику
            if send_text:
                keyboard = [
                    [InlineKeyboardButton("🎨 Создать еще", callback_data="create_content")],
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                stats_text = f"✅ **Генерация завершена!**\n\n"
                stats_text += f"🖼️ Изображений создано: **{len(images)}**\n"
                stats_text += f"⏱️ Время генерации: **{generation_time:.1f}с**\n"
                stats_text += f"🎯 Модель: **{selected_model}**\n\n"
                stats_text += "💡 **Совет:** Попробуйте разные модели для лучших результатов!"
                
                await send_text(stats_text, reply_markup=reply_markup)
        
        except Exception as e:
            logging.error(f"Ошибка отправки изображений: {str(e)}")
            if send_text:
                await send_text("❌ Ошибка при отправке изображений. Попробуйте еще раз.")
    
    else:
        # Если не удалось сгенерировать ни одного изображения
        if send_text:
            keyboard = [
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="retry_generation")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await send_text(
                "❌ **Не удалось сгенерировать изображения**\n\n"
                "Возможные причины:\n"
                "• Проблемы с API Replicate\n"
                "• Недостаточно кредитов\n"
                "• Неподходящий промпт\n\n"
                "Попробуйте еще раз или выберите другую модель.",
                reply_markup=reply_markup
            )
    
    # Сбрасываем состояние пользователя
    USER_STATE[user_id] = {'step': 'main_menu'}

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
    app.add_handler(CommandHandler('stats', stats_command))
    app.add_handler(CommandHandler('my_id', my_id_command))
    app.add_handler(CommandHandler('admin_stats', admin_stats_command))
    app.add_handler(CommandHandler('credits_stats', credits_stats_command))
    app.add_handler(CommandHandler('ideogram_tips', ideogram_tips_command))
    app.add_handler(CommandHandler('check_replicate', check_replicate))
    app.add_handler(CommandHandler('test_ideogram', test_ideogram))
    app.add_handler(CommandHandler('test_image_send', test_image_send))
    app.add_handler(CommandHandler('edit_image', edit_image_command))
    
    # Админ-команды для управления кредитами
    app.add_handler(CommandHandler('add_credits', add_credits_command))
    app.add_handler(CommandHandler('check_credits', check_credits_command))
    app.add_handler(CommandHandler('set_credits', set_credits_command))
    
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
    
    # Проверяем, запущены ли мы на Railway
    port = int(os.environ.get('PORT', 0))
    
    if port:
        # Запускаем на Railway с webhook
        async def start_webhook():
            # Инициализируем HTTP сессию для асинхронных запросов
            await init_http_session()
            print("✅ HTTP сессия инициализирована")
            
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
            
            # Запускаем Flask сервер для callback в отдельном потоке
            import threading
            def run_flask():
                flask_app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
            
            flask_thread = threading.Thread(target=run_flask, daemon=True)
            flask_thread.start()
            print("🌐 Flask callback сервер запущен на порту 5000")
            
            # Запускаем периодическую проверку платежей
            payment_polling_task = asyncio.create_task(start_payment_polling())
            print("🔄 Автоматическая проверка платежей запущена (каждые 45 секунд)")
            
            # Держим приложение запущенным
            try:
                await asyncio.Event().wait()
            except KeyboardInterrupt:
                # Закрываем HTTP сессию при завершении
                await close_http_session()
                print("✅ HTTP сессия закрыта")
                pass
        
        asyncio.run(start_webhook())
    else:
        # Запускаем локально с polling (упрощенная версия)
        print("🚀 Бот запущен локально с polling")
        
        try:
            app.run_polling()
        except KeyboardInterrupt:
            print("👋 Бот остановлен")

if __name__ == '__main__':
    main()


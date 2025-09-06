import logging
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, InputMediaPhoto, BotCommand

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

# Flask для callback сервера
from flask import Flask, request, jsonify
from betatransfer_api import betatransfer_api

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
        response = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: requests.post(url, data=data, timeout=10)),
            timeout=15.0
        )
        
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

# USER_STATE заменен на context.user_data для параллельной работы
# USER_STATE = {}



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

        [InlineKeyboardButton("ℹ️ О боте", callback_data="about_bot")],

        [InlineKeyboardButton("📞 Поддержка", callback_data="support")]

    ]

    

    await update.message.reply_text(

        welcome_text,

        reply_markup=InlineKeyboardMarkup(keyboard)

    )

    context.user_data['step'] = 'main_menu'



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
            # Используем асинхронный вызов для предотвращения блокировки
            loop = asyncio.get_event_loop()
            output = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: replicate.run(
                    "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
                    input={"prompt": "test"}
                )),
                timeout=30.0
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

                image_url = output.url()

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
        # Используем асинхронный вызов для предотвращения блокировки
        loop = asyncio.get_event_loop()
        output = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: replicate.run(
                "ideogram-ai/ideogram-v3-turbo",
                input={"prompt": "A simple test image of a red apple on a white background, professional photography"}
            )),
            timeout=30.0
        )

        

        # Обработка результата

        if hasattr(output, 'url'):

            image_url = output.url()

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

    context.user_data['step'] = 'upload_image_for_edit'

    

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

        # Используем асинхронный вызов для предотвращения блокировки
        loop = asyncio.get_event_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Ты помощник по созданию визуальных промптов для генерации изображений. НЕ добавляй людей в промпты, если они не упомянуты в сценарии."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=700,
                temperature=0.5,
            )),
            timeout=30.0
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



async def show_subscription_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню кредитов"""
    user_id = update.effective_user.id
    
    # Получаем информацию о пользователе
    limits = analytics_db.get_user_limits(user_id)
    credits = analytics_db.get_user_credits(user_id)
    
    # Формируем текст статуса
    free_generations_left = analytics_db.get_free_generations_left(user_id)
    
    status_text = f"""
🪙 **Ваши кредиты: {credits}**

📊 **Статистика:**
• Бесплатных генераций осталось: {free_generations_left}
• Всего генераций: {limits.get('total_generations', 0)}
• Ошибок: {limits.get('total_errors', 0)}

💡 **Как получить кредиты:**
• Покупайте пакеты кредитов
• Используйте бесплатные генерации
"""
    
    keyboard = [
        [InlineKeyboardButton("🛒 Купить кредиты", callback_data="credit_packages")],
        [InlineKeyboardButton("📊 Статистика", callback_data="user_stats")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(status_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(status_text, reply_markup=reply_markup)

async def show_credit_packages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает пакеты кредитов"""
    packages_text = """
🛒 **Пакеты кредитов:**

💰 **Малый пакет:**
• 100 кредитов за 100₽
• Достаточно для 10-20 изображений

💰 **Средний пакет:**
• 500 кредитов за 450₽
• Достаточно для 50-100 изображений

💰 **Большой пакет:**
• 1000 кредитов за 800₽
• Достаточно для 100-200 изображений

💡 **Стоимость генерации:**
• Изображения: 5-10 кредитов
• Видео: 50-100 кредитов
"""
    
    keyboard = [
        [InlineKeyboardButton("💰 Малый (100₽)", callback_data="buy_credits:small")],
        [InlineKeyboardButton("💰 Средний (450₽)", callback_data="buy_credits:medium")],
        [InlineKeyboardButton("💰 Большой (800₽)", callback_data="buy_credits:large")],
        [InlineKeyboardButton("🔙 Назад", callback_data="subscription_menu")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(packages_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(packages_text, reply_markup=reply_markup)

async def handle_credit_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает покупку кредитов"""
    user_id = update.effective_user.id
    data = update.callback_query.data
    
    # Извлекаем тип пакета
    package_type = data.split(':')[1]
    
    # Определяем стоимость и количество кредитов
    if package_type == "small":
        amount = 100.0
        credits = 100
    elif package_type == "medium":
        amount = 450.0
        credits = 500
    elif package_type == "large":
        amount = 800.0
        credits = 1000
    else:
        await update.callback_query.edit_message_text("❌ Неверный тип пакета")
        return
    
    try:
        # Создаем платеж
        result = betatransfer_api.create_payment(
            amount=amount,
            currency="RUB",
            description=f"Покупка {credits} кредитов",
            order_id=f"order{int(time.time())}",
            payer_email="",
            payer_name="",
            payer_id=str(user_id)
        )
        
        if 'error' in result:
            await update.callback_query.edit_message_text(f"❌ Ошибка создания платежа: {result['error']}")
            return
        
        payment_url = result.get('url')
        payment_id = result.get('id')
        
        # Сохраняем информацию о платеже
        analytics_db.create_payment(
            user_id=user_id,
            amount=amount,
            currency="RUB",
            status="pending",
            betatransfer_id=payment_id,
            order_id=result.get('orderId')
        )
        
        # Отправляем ссылку на оплату
        keyboard = [
            [InlineKeyboardButton("💳 Оплатить", url=payment_url)],
            [InlineKeyboardButton("🔄 Проверить статус", callback_data=f"check_payment:{payment_id}")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            f"💳 **Оплата кредитов**\n\n"
            f"💰 Сумма: {amount}₽\n"
            f"🪙 Кредитов: {credits}\n\n"
            f"Нажмите кнопку ниже для оплаты:",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logging.error(f"Ошибка создания платежа: {e}")
        await update.callback_query.edit_message_text(f"❌ Ошибка создания платежа: {e}")

async def check_payment_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет статус платежа"""
    user_id = update.effective_user.id
    data = update.callback_query.data
    
    # Извлекаем ID платежа
    payment_id = data.split(':')[1]
    
    try:
        # Проверяем статус платежа
        status_result = betatransfer_api.get_payment_status(payment_id)
        
        if 'error' in status_result:
            await update.callback_query.edit_message_text(f"❌ Ошибка проверки статуса: {status_result['error']}")
            return
        
        status = status_result.get('status')
        
        if status == 'success':
            await update.callback_query.edit_message_text(
                "✅ **Платеж успешно завершен!**\n\nКредиты зачислены на ваш счет.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
                ]])
            )
        elif status == 'failed':
            await update.callback_query.edit_message_text(
                "❌ **Платеж не удался**\n\nПопробуйте еще раз или обратитесь в поддержку.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🛒 Попробовать снова", callback_data="credit_packages"),
                    InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
                ]])
            )
        else:
            await update.callback_query.edit_message_text(
                f"⏳ **Платеж в обработке**\n\nСтатус: {status}\n\nПопробуйте проверить позже.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Проверить снова", callback_data=f"check_payment:{payment_id}"),
                    InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
                ]])
            )
            
    except Exception as e:
        logging.error(f"Ошибка проверки статуса платежа: {e}")
        await update.callback_query.edit_message_text(f"❌ Ошибка проверки статуса: {e}")

async def setup_commands(application):
    """Устанавливает команды меню бота"""
    commands = [
        BotCommand("start", "🚀 Запустить бота"),
        BotCommand("help", "❓ Помощь"),
        BotCommand("stats", "📊 Статистика"),
        BotCommand("my_id", "🆔 Мой ID"),
        BotCommand("admin_stats", "👑 Админ статистика"),
        BotCommand("credits_stats", "🪙 Статистика кредитов"),
        BotCommand("ideogram_tips", "💡 Советы по Ideogram"),
        BotCommand("check_replicate", "🔍 Проверить Replicate"),
        BotCommand("test_ideogram", "🧪 Тест Ideogram"),
        BotCommand("test_image_send", "📤 Тест отправки изображений"),
        BotCommand("edit_image", "✏️ Редактировать изображение"),
        BotCommand("add_credits", "➕ Добавить кредиты"),
        BotCommand("check_credits", "🔍 Проверить кредиты"),
        BotCommand("set_credits", "⚙️ Установить кредиты")
    ]
    
    await application.bot.set_my_commands(commands)

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user_id = update.effective_user.id
    message = update.message
    
    # Логируем сообщение
    logging.info(f"Получено сообщение от пользователя {user_id}: {message.text}")
    
    # Простая обработка - показываем главное меню
    await show_main_menu(update, context)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    # Обработка основных кнопок
    if data == "main_menu":
        await show_main_menu(update, context)
    elif data == "create_content":
        await show_format_selection(update, context)
    elif data == "how_to_use":
        await show_how_to_use(update, context)
    elif data == "about_bot":
        await show_about_bot(update, context)
    elif data == "format_selection":
        await show_format_selection(update, context)
    elif data == "subscription_menu":
        await show_subscription_menu(update, context)
    elif data == "credit_packages":
        await show_credit_packages(update, context)
    elif data.startswith("buy_credits:"):
        await handle_credit_purchase(update, context)
    elif data.startswith("check_payment:"):
        await check_payment_status(update, context)
    else:
        # Для остальных кнопок показываем главное меню
        await show_main_menu(update, context)

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

    app.add_handler(CommandHandler('my_id', my_id_command))  # Временная команда

    app.add_handler(CommandHandler('admin_stats', admin_stats_command))
    
    app.add_handler(CommandHandler('credits_stats', credits_stats_command))  # Статистика по кредитам

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

    

    # Устанавливаем команды меню при запуске

    app.post_init = setup_commands

    

    # Проверяем, запущены ли мы на Railway

    port = int(os.environ.get('PORT', 0))

    

    if port:

        # Запускаем на Railway с webhook


        

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

                pass

        

        asyncio.run(start_webhook())

    else:

        # Запускаем локально с polling

        print("🚀 Бот запущен локально с polling")
        
        # Запускаем Flask сервер для callback в отдельном потоке
        import threading
        def run_flask():
            flask_app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
        
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        print("🌐 Flask callback сервер запущен на порту 5000")
        
        # Запускаем периодическую проверку платежей в отдельном потоке
        def run_payment_polling():
            asyncio.run(start_payment_polling())
        
        polling_thread = threading.Thread(target=run_payment_polling, daemon=True)
        polling_thread.start()
        print("🔄 Автоматическая проверка платежей запущена (каждые 45 секунд)")

        app.run_polling()



# ==================== СИСТЕМА ПОДДЕРЖКИ ====================

async def show_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает информацию о поддержке"""
    
    # Получаем информацию о пользователе
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

💡 **Совет:** Чем подробнее опишете проблему, тем быстрее смогу помочь!
    """
    
    keyboard = [
        [InlineKeyboardButton("🔙 Назад в меню", callback_data="main_menu")]
    ]
    
    await update.callback_query.edit_message_text(
        support_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

# ==================== АДМИН-КОМАНДЫ ДЛЯ УПРАВЛЕНИЯ КРЕДИТАМИ ====================

async def add_credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для добавления кредитов пользователю (только для админа)"""
    ADMIN_USER_ID = 7735323051  # Ваш ID
    
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("❌ У вас нет доступа к этой команде.")
        return
    
    # Проверяем аргументы команды
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "📝 **Использование:** `/add_credits @username количество` или `/add_credits user_id количество`\n"
            "**Примеры:** `/add_credits @john_doe 100` или `/add_credits 123456789 100`"
        )
        return
    
    user_identifier = context.args[0]
    try:
        credits_to_add = int(context.args[1])
        if credits_to_add <= 0:
            await update.message.reply_text("❌ Количество кредитов должно быть положительным числом.")
            return
    except ValueError:
        await update.message.reply_text("❌ Количество кредитов должно быть числом.")
        return
    
    # Определяем, это username или user_id
    user_id = None
    user_info = None
    
    if user_identifier.startswith('@'):
        # Поиск по username
        username = user_identifier[1:]
        user_id = analytics_db.get_user_id_by_username(username)
        if user_id:
            user_info = analytics_db.get_user_info_by_id(user_id)
    else:
        # Попытка поиска по user_id
        try:
            user_id = int(user_identifier)
            user_info = analytics_db.get_user_info_by_id(user_id)
        except ValueError:
            pass
    
    if not user_id or not user_info:
        await update.message.reply_text(f"❌ Пользователь {user_identifier} не найден в базе данных.")
        return
    
    # Получаем текущий баланс
    credits_data = analytics_db.get_user_credits(user_id)
    current_credits = credits_data.get('balance', 0)
    
    # Добавляем кредиты
    new_credits = current_credits + credits_to_add
    analytics_db.set_user_credits(user_id, new_credits)
    
    # Формируем информацию о пользователе
    username_display = f"@{user_info['username']}" if user_info['username'] else "Без username"
    name_display = f"{user_info['first_name'] or ''} {user_info['last_name'] or ''}".strip() or "Без имени"
    
    # Логируем операцию
    logging.info(f"Админ {update.effective_user.id} добавил {credits_to_add} кредитов пользователю {user_id} ({username_display})")
    
    # Отправляем подтверждение админу
    await update.message.reply_text(
        f"✅ **Кредиты добавлены!**\n\n"
        f"👤 **Пользователь:** {name_display}\n"
        f"🆔 **ID:** {user_id}\n"
        f"📝 **Username:** {username_display}\n"
        f"➕ **Добавлено:** {credits_to_add} кредитов\n"
        f"💳 **Новый баланс:** {new_credits} кредитов"
    )
    
    # Уведомляем пользователя (если возможно)
    try:
                await context.bot.send_message(
            chat_id=user_id,
            text=f"🎉 **Вам начислено {credits_to_add} кредитов!**\n\n"
                 f"💳 **Текущий баланс:** {new_credits} кредитов\n\n"
                 f"Спасибо за использование нашего бота! 🚀"
        )
    except Exception as e:
        logging.warning(f"Не удалось отправить уведомление пользователю {user_id}: {e}")


async def check_credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для проверки баланса пользователя (только для админа)"""
    ADMIN_USER_ID = 7735323051  # Ваш ID
    
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("❌ У вас нет доступа к этой команде.")
        return
    
    # Проверяем аргументы команды
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "📝 **Использование:** `/check_credits @username` или `/check_credits user_id`\n"
            "**Примеры:** `/check_credits @john_doe` или `/check_credits 123456789`"
        )
        return
    
    user_identifier = context.args[0]
    
    # Определяем, это username или user_id
    user_id = None
    user_info = None
    
    if user_identifier.startswith('@'):
        # Поиск по username
        username = user_identifier[1:]
        user_id = analytics_db.get_user_id_by_username(username)
        if user_id:
            user_info = analytics_db.get_user_info_by_id(user_id)
    else:
        # Попытка поиска по user_id
        try:
            user_id = int(user_identifier)
            user_info = analytics_db.get_user_info_by_id(user_id)
        except ValueError:
            pass
    
    if not user_id or not user_info:
        await update.message.reply_text(f"❌ Пользователь {user_identifier} не найден в базе данных.")
        return
    
    # Получаем информацию о пользователе
    credits_data = analytics_db.get_user_credits(user_id)
    current_credits = credits_data.get('balance', 0)
    free_generations = analytics_db.get_free_generations_left(user_id)
    
    # Формируем информацию о пользователе
    username_display = f"@{user_info['username']}" if user_info['username'] else "Без username"
    name_display = f"{user_info['first_name'] or ''} {user_info['last_name'] or ''}".strip() or "Без имени"
    
    await update.message.reply_text(
        f"👤 **Информация о пользователе**\n\n"
        f"📝 **Имя:** {name_display}\n"
        f"🆔 **ID:** {user_id}\n"
        f"📝 **Username:** {username_display}\n"
        f"💳 **Кредиты:** {current_credits}\n"
        f"🆓 **Бесплатные генерации:** {free_generations}"
    )


async def set_credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для установки точного количества кредитов (только для админа)"""
    ADMIN_USER_ID = 7735323051  # Ваш ID
    
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("❌ У вас нет доступа к этой команде.")
        return
    
    # Проверяем аргументы команды
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "📝 **Использование:** `/set_credits @username количество` или `/set_credits user_id количество`\n"
            "**Примеры:** `/set_credits @john_doe 500` или `/set_credits 123456789 500`"
        )
        return
    
    user_identifier = context.args[0]
    try:
        credits_to_set = int(context.args[1])
        if credits_to_set < 0:
            await update.message.reply_text("❌ Количество кредитов не может быть отрицательным.")
            return
    except ValueError:
        await update.message.reply_text("❌ Количество кредитов должно быть числом.")
        return
    
    # Определяем, это username или user_id
    user_id = None
    user_info = None
    
    if user_identifier.startswith('@'):
        # Поиск по username
        username = user_identifier[1:]
        user_id = analytics_db.get_user_id_by_username(username)
        if user_id:
            user_info = analytics_db.get_user_info_by_id(user_id)
    else:
        # Попытка поиска по user_id
        try:
            user_id = int(user_identifier)
            user_info = analytics_db.get_user_info_by_id(user_id)
        except ValueError:
            pass
    
    if not user_id or not user_info:
        await update.message.reply_text(f"❌ Пользователь {user_identifier} не найден в базе данных.")
        return
    
    # Получаем старый баланс
    credits_data = analytics_db.get_user_credits(user_id)
    old_credits = credits_data.get('balance', 0)
    
    # Устанавливаем новые кредиты
    analytics_db.set_user_credits(user_id, credits_to_set)
    
    # Формируем информацию о пользователе
    username_display = f"@{user_info['username']}" if user_info['username'] else "Без username"
    name_display = f"{user_info['first_name'] or ''} {user_info['last_name'] or ''}".strip() or "Без имени"
    
    # Логируем операцию
    logging.info(f"Админ {update.effective_user.id} установил {credits_to_set} кредитов пользователю {user_id} ({username_display}) (было: {old_credits})")
    
    # Отправляем подтверждение админу
    await update.message.reply_text(
        f"✅ **Кредиты установлены!**\n\n"
        f"👤 **Пользователь:** {name_display}\n"
        f"🆔 **ID:** {user_id}\n"
        f"📝 **Username:** {username_display}\n"
        f"💳 **Новый баланс:** {credits_to_set} кредитов\n"
        f"📊 **Было:** {old_credits} кредитов"
    )


if __name__ == '__main__':

    main() 
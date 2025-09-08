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

# Создаем пул потоков для блокирующих операций
THREAD_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=100)

# Создаем пул HTTP соединений для aiohttp
HTTP_SESSION = None

# Flask для callback сервера
from flask import Flask, request, jsonify
from betatransfer_api import betatransfer_api

# Функция для параллельной генерации одного изображения
async def generate_single_image_async(idx, prompt, state, send_text=None):
    """
    Генерирует одно изображение асинхронно.
    Возвращает кортеж (idx, success, image_url, caption, error)
    """
    try:
        # Добавляем стиль генерации к промпту
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
            # Для Ideogram используем упрощенные стили
            if image_gen_style == 'Фотореализм':
                style_suffix = ', photorealistic'
            elif image_gen_style == 'Иллюстрация':
                style_suffix = ', illustration'
            elif image_gen_style == 'Минимализм':
                style_suffix = ', minimalism'
            elif image_gen_style == 'Акварель':
                style_suffix = ', watercolor'
            elif image_gen_style == 'Масляная живопись':
                style_suffix = ', oil painting'
            elif image_gen_style == 'Пиксель-арт':
                style_suffix = ', pixel art'

        prompt_with_style = f"{prompt}{style_suffix}"
        
        # Определяем параметры для Replicate
        user_format = state.get('format', '')
        simple_orientation = state.get('simple_orientation', None)
        
        # Простые параметры для Ideogram
        replicate_params = {}
        if user_format == '1:1':
            replicate_params['aspect_ratio'] = '1:1'
        elif user_format == '16:9':
            replicate_params['aspect_ratio'] = '16:9'
        elif user_format == '9:16':
            replicate_params['aspect_ratio'] = '9:16'
        else:
            replicate_params['aspect_ratio'] = '1:1'
        
        if send_text:
            await send_text(f'Генерирую изображение {idx}...')
        
        # Генерация изображения в зависимости от выбранной модели
        if selected_model == 'Ideogram':
            try:
                if send_text:
                    await send_text(f"🎨 Генерирую через Ideogram...\n\n💡 Совет: Ideogram лучше работает с простыми, четкими описаниями")
                
                # Проверяем API токен
                if not os.environ.get('REPLICATE_API_TOKEN'):
                    return (idx, False, None, None, "API токен Replicate не найден")
                
                # Запускаем генерацию с таймаутом
                try:
                    output = await replicate_run_async(
                        "ideogram-ai/ideogram-v3-turbo",
                        {"prompt": prompt_with_style, **replicate_params},
                        timeout=60
                    )
                except Exception as e:
                    # Если v3 не работает, пробуем v2
                    logging.warning(f"Ideogram v3 Turbo недоступен: {e}, пробуем v2...")
                    try:
                        output = await replicate_run_async(
                            "ideogram-ai/ideogram-v2",
                            {"prompt": prompt_with_style, **replicate_params},
                            timeout=60
                        )
                    except Exception as e2:
                        logging.error(f"Ideogram недоступен: {e2}")
                        return (idx, False, None, None, f"Ошибка Ideogram: {e2}")
                
                # Обработка ответа от Replicate API
                image_url = None
                
                # Проверяем, является ли output объектом FileOutput
                if hasattr(output, 'url'):
                    if callable(output.url):
                        image_url = output.url()
                    else:
                        image_url = output.url
                elif hasattr(output, '__iter__') and not isinstance(output, str):
                    try:
                        output_list = list(output)
                        if output_list:
                            image_url = output_list[0]
                    except Exception as e:
                        return (idx, False, None, None, f"Ошибка обработки итератора: {e}")
                else:
                    image_url = output
                
                # Проверяем, что получили URL
                if not image_url:
                    return (idx, False, None, None, "Не удалось получить изображение от Ideogram (пустой результат)")
                
                # Конвертация bytes в строку если необходимо
                if isinstance(image_url, bytes):
                    try:
                        image_url = image_url.decode('utf-8')
                    except UnicodeDecodeError:
                        return (idx, False, None, None, "Получены бинарные данные вместо URL от Ideogram")
                
                # Проверяем, что это строка и начинается с http
                if not isinstance(image_url, str) or not image_url.startswith('http'):
                    return (idx, False, None, None, "Неверный тип URL от Ideogram")
                
                caption = f'Вариант {idx}'
                return (idx, True, image_url, caption, None)
                
            except Exception as e:
                logging.error(f"Ошибка при генерации изображения {idx} через Ideogram: {e}")
                return (idx, False, None, None, f"Ошибка Ideogram: {e}")
        
        elif selected_model == 'Bytedance (Seedream-3)':
            try:
                if send_text:
                    await send_text(f"⚡ Генерирую через Bytedance Seedream-3...\n\n💡 Совет: Bytedance отлично подходит для фотореалистичных изображений")
                
                # Проверяем API токен
                if not os.environ.get('REPLICATE_API_TOKEN'):
                    return (idx, False, None, None, "API токен Replicate не найден")
                
                # Запускаем генерацию через Bytedance
                try:
                    output = await replicate_run_async(
                        "bytedance/seedream-3",
                        {"prompt": prompt_with_style, **replicate_params},
                        timeout=180
                    )
                except Exception as e:
                    logging.error(f"Bytedance Seedream-3 недоступен: {e}")
                    return (idx, False, None, None, f"Ошибка Bytedance: {e}")
                
                # Обработка ответа от Replicate API
                image_url = None
                
                if hasattr(output, 'url'):
                    if callable(output.url):
                        image_url = output.url()
                    else:
                        image_url = output.url
                elif hasattr(output, '__iter__') and not isinstance(output, str):
                    try:
                        output_list = list(output)
                        if output_list:
                            image_url = output_list[0]
                    except Exception as e:
                        return (idx, False, None, None, f"Ошибка обработки итератора: {e}")
                else:
                    image_url = output
                
                if not image_url:
                    return (idx, False, None, None, "Не удалось получить изображение от Bytedance")
                
                if isinstance(image_url, bytes):
                    try:
                        image_url = image_url.decode('utf-8')
                    except UnicodeDecodeError:
                        return (idx, False, None, None, "Получены бинарные данные вместо URL от Bytedance")
                
                if not isinstance(image_url, str) or not image_url.startswith('http'):
                    return (idx, False, None, None, "Неверный тип URL от Bytedance")
                
                caption = f'Вариант {idx}'
                return (idx, True, image_url, caption, None)
                
            except Exception as e:
                logging.error(f"Ошибка при генерации изображения {idx} через Bytedance: {e}")
                return (idx, False, None, None, f"Ошибка Bytedance: {e}")
        
        elif selected_model == 'Google Imagen 4 Ultra':
            try:
                if send_text:
                    await send_text(f"🔬 Генерирую через Google Imagen 4 Ultra...\n\n💡 Совет: Google Imagen отлично подходит для детализированных изображений")
                
                # Проверяем API токен
                if not os.environ.get('REPLICATE_API_TOKEN'):
                    return (idx, False, None, None, "API токен Replicate не найден")
                
                # Запускаем генерацию через Google Imagen
                try:
                    output = await replicate_run_async(
                        "google/imagen-4-ultra",
                        {"prompt": prompt_with_style, **replicate_params},
                        timeout=60
                    )
                except Exception as e:
                    logging.error(f"Google Imagen 4 Ultra недоступен: {e}")
                    return (idx, False, None, None, f"Ошибка Google Imagen: {e}")
                
                # Обработка ответа от Replicate API
                image_url = None
                
                if hasattr(output, 'url'):
                    if callable(output.url):
                        image_url = output.url()
                    else:
                        image_url = output.url
                elif hasattr(output, '__iter__') and not isinstance(output, str):
                    try:
                        output_list = list(output)
                        if output_list:
                            image_url = output_list[0]
                    except Exception as e:
                        return (idx, False, None, None, f"Ошибка обработки итератора: {e}")
                else:
                    image_url = output
                
                if not image_url:
                    return (idx, False, None, None, "Не удалось получить изображение от Google Imagen")
                
                if isinstance(image_url, bytes):
                    try:
                        image_url = image_url.decode('utf-8')
                    except UnicodeDecodeError:
                        return (idx, False, None, None, "Получены бинарные данные вместо URL от Google Imagen")
                
                if not isinstance(image_url, str) or not image_url.startswith('http'):
                    return (idx, False, None, None, "Неверный тип URL от Google Imagen")
                
                caption = f'Вариант {idx}'
                return (idx, True, image_url, caption, None)
                
            except Exception as e:
                logging.error(f"Ошибка при генерации изображения {idx} через Google Imagen: {e}")
                return (idx, False, None, None, f"Ошибка Google Imagen: {e}")
        
        else:
            # Для остальных моделей пока возвращаем ошибку
            return (idx, False, None, None, f"Модель {selected_model} пока не поддерживается в параллельном режиме")
        
    except Exception as e:
        logging.error(f"Общая ошибка при генерации изображения {idx}: {e}")
        return (idx, False, None, None, f"Общая ошибка: {e}")

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

# Асинхронные обертки для операций с базой данных
async def analytics_db_add_user_async(user_id: int, username: str = None, first_name: str = None, last_name: str = None):
    """Асинхронная обертка для analytics_db.add_user"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        THREAD_POOL,
        lambda: analytics_db.add_user(user_id, username, first_name, last_name)
    )

async def analytics_db_update_user_activity_async(user_id: int):
    """Асинхронная обертка для analytics_db.update_user_activity"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        THREAD_POOL,
        lambda: analytics_db.update_user_activity(user_id)
    )

async def analytics_db_log_action_async(user_id: int, action_type: str, action_data: str = None):
    """Асинхронная обертка для analytics_db.log_action"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        THREAD_POOL,
        lambda: analytics_db.log_action(user_id, action_type, action_data)
    )

async def analytics_db_get_user_limits_async(user_id: int):
    """Асинхронная обертка для analytics_db.get_user_limits"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        THREAD_POOL,
        lambda: analytics_db.get_user_limits(user_id)
    )

async def analytics_db_get_user_credits_async(user_id: int):
    """Асинхронная обертка для analytics_db.get_user_credits"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        THREAD_POOL,
        lambda: analytics_db.get_user_credits(user_id)
    )

async def analytics_db_get_free_generations_left_async(user_id: int):
    """Асинхронная обертка для analytics_db.get_free_generations_left"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        THREAD_POOL,
        lambda: analytics_db.get_free_generations_left(user_id)
    )

async def analytics_db_increment_free_generations_async(user_id: int):
    """Асинхронная обертка для analytics_db.increment_free_generations"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        THREAD_POOL,
        lambda: analytics_db.increment_free_generations(user_id)
    )

async def analytics_db_use_credits_async(user_id: int, amount: int, description: str = "Использование кредитов"):
    """Асинхронная обертка для analytics_db.use_credits"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        THREAD_POOL,
        lambda: analytics_db.use_credits(user_id, amount, description)
    )

async def analytics_db_log_generation_async(user_id: int, model_name: str, format_type: str, 
                                          prompt: str, image_count: int, success: bool, 
                                          error_message: str = None, generation_time: float = None):
    """Асинхронная обертка для analytics_db.log_generation"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        THREAD_POOL,
        lambda: analytics_db.log_generation(user_id, model_name, format_type, prompt, 
                                          image_count, success, error_message, generation_time)
    )

async def analytics_db_get_user_stats_async(user_id: int):
    """Асинхронная обертка для analytics_db.get_user_stats"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        THREAD_POOL,
        lambda: analytics_db.get_user_stats(user_id)
    )

async def analytics_db_get_global_stats_async(days: int = 30):
    """Асинхронная обертка для analytics_db.get_global_stats"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        THREAD_POOL,
        lambda: analytics_db.get_global_stats(days)
    )

async def analytics_db_get_daily_stats_async(days: int = 7):
    """Асинхронная обертка для analytics_db.get_daily_stats"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        THREAD_POOL,
        lambda: analytics_db.get_daily_stats(days)
    )

async def analytics_db_get_total_credits_statistics_async():
    """Асинхронная обертка для analytics_db.get_total_credits_statistics"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        THREAD_POOL,
        lambda: analytics_db.get_total_credits_statistics()
    )

async def analytics_db_get_pending_payments_async():
    """Асинхронная обертка для analytics_db.get_pending_payments"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        THREAD_POOL,
        lambda: analytics_db.get_pending_payments()
    )

async def analytics_db_get_credit_transaction_by_payment_id_async(payment_id: str):
    """Асинхронная обертка для analytics_db.get_credit_transaction_by_payment_id"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        THREAD_POOL,
        lambda: analytics_db.get_credit_transaction_by_payment_id(payment_id)
    )

async def analytics_db_add_credits_async(user_id: int, amount: int, payment_id: int = None, 
                                        description: str = "Покупка кредитов"):
    """Асинхронная обертка для analytics_db.add_credits"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        THREAD_POOL,
        lambda: analytics_db.add_credits(user_id, amount, payment_id, description)
    )

async def analytics_db_create_credit_transaction_with_payment_async(user_id: int, amount: int, description: str, payment_id: str):
    """Асинхронная обертка для analytics_db.create_credit_transaction_with_payment"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        THREAD_POOL,
        lambda: analytics_db.create_credit_transaction_with_payment(user_id, amount, description, payment_id)
    )

async def analytics_db_update_payment_status_async(payment_id: str, status: str):
    """Асинхронная обертка для analytics_db.update_payment_status"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        THREAD_POOL,
        lambda: analytics_db.update_payment_status(payment_id, status)
    )

async def analytics_db_get_payment_by_order_id_async(order_id: str):
    """Асинхронная обертка для analytics_db.get_payment_by_order_id"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        THREAD_POOL,
        lambda: analytics_db.get_payment_by_order_id(order_id)
    )

async def analytics_db_set_user_credits_async(user_id: int, credits: int):
    """Асинхронная обертка для analytics_db.set_user_credits"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        THREAD_POOL,
        lambda: analytics_db.set_user_credits(user_id, credits)
    )

async def analytics_db_create_payment_with_credits_async(user_id: int, amount: float, currency: str = "UAH", 
                                                       payment_id: str = None, order_id: str = None, 
                                                       credit_amount: int = None):
    """Асинхронная обертка для analytics_db.create_payment_with_credits"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        THREAD_POOL,
        lambda: analytics_db.create_payment_with_credits(user_id, amount, currency, payment_id, order_id, credit_amount)
    )

async def analytics_db_get_user_info_by_id_async(user_id: int):
    """Асинхронная обертка для analytics_db.get_user_info_by_id"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        THREAD_POOL,
        lambda: analytics_db.get_user_info_by_id(user_id)
    )

async def analytics_db_get_user_id_by_username_async(username: str):
    """Асинхронная обертка для analytics_db.get_user_id_by_username"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        THREAD_POOL,
        lambda: analytics_db.get_user_id_by_username(username)
    )

# Функция для автоматической проверки статуса платежей
async def check_pending_payments():
    """Проверяет статус всех pending платежей и зачисляет кредиты при завершении"""
    try:
        # Получаем все pending платежи из базы данных
        pending_payments = await analytics_db_get_pending_payments_async()
        
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
                        existing_transaction = await analytics_db_get_credit_transaction_by_payment_id_async(payment_id)
                        
                        if not existing_transaction:
                            # Кредиты еще не зачислены, зачисляем
                            await analytics_db_add_credits_async(user_id, credit_amount)
                            
                            # Создаем транзакцию с привязкой к платежу
                            await analytics_db_create_credit_transaction_with_payment_async(user_id, credit_amount, f"Покупка кредитов (платеж {payment_id})", payment_id)
                            
                            # Обновляем статус платежа
                            await analytics_db_update_payment_status_async(payment_id, 'success')
                            
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
                            await analytics_db_update_payment_status_async(payment_id, 'success')
                            logging.info(f"Кредиты уже зачислены за платеж {payment_id}, обновляем только статус")
                
                elif payment_status == 'failed':
                    # Обновляем статус неудачного платежа
                    await analytics_db_update_payment_status_async(payment_id, 'failed')
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
            payment_record = await analytics_db_get_payment_by_order_id_async(order_id)
            if payment_record:
                user_id = payment_record.get("user_id")
                credit_amount = payment_record.get("credit_amount")
                
                # Зачисляем кредиты пользователю
                await analytics_db_add_credits_async(user_id, credit_amount)
                
                # Обновляем статус платежа
                await analytics_db_update_payment_status_async(payment_id, "completed")
                
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

    await analytics_db_add_user_async(

        user_id=user.id,

        username=user.username,

        first_name=user.first_name,

        last_name=user.last_name

    )

    await analytics_db_update_user_activity_async(user.id)

    await analytics_db_log_action_async(user.id, "start_command")

    

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

    limits = await analytics_db_get_user_limits_async(user_id)

    credits = await analytics_db_get_user_credits_async(user_id)

    

    # Формируем информацию о статусе

    free_generations_left = await analytics_db_get_free_generations_left_async(user_id)

    

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
            output = await replicate_run_async(
                    "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
                {"prompt": "test"},
                timeout=30
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
            output = await replicate_run_async(
                    "ideogram-ai/ideogram-v3-turbo",
                {"prompt": "simple test image"},
                timeout=30
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
        output = await replicate_run_async(
            "ideogram-ai/ideogram-v3-turbo",
            {"prompt": "A simple test image of a red apple on a white background, professional photography"},
            timeout=30
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

    await analytics_db_update_user_activity_async(user_id)

    await analytics_db_log_action_async(user_id, "stats_command")

    

    # Получаем статистику пользователя

    user_stats = await analytics_db_get_user_stats_async(user_id)

    

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
        stats = await analytics_db_get_total_credits_statistics_async()
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

    

    await analytics_db_update_user_activity_async(user_id)

    await analytics_db_log_action_async(user_id, "admin_stats_command")

    

    # Получаем глобальную статистику

    global_stats = await analytics_db_get_global_stats_async(30)

    daily_stats = await analytics_db_get_daily_stats_async(7)

    

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

        # Используем асинхронный вызов для предотвращения блокировки
        loop = asyncio.get_event_loop()
        messages = [
                    {"role": "system", "content": "Ты помощник по созданию визуальных промптов для генерации изображений. НЕ добавляй людей в промпты, если они не упомянуты в сценарии."},
                    {"role": "user", "content": prompt}
        ]
        scenes_text = await openai_chat_completion_async(messages, "gpt-4o-mini", 700, 0.5)

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



import logging

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

    await analytics_db_add_user_async(

        user_id=user.id,

        username=user.username,

        first_name=user.first_name,

        last_name=user.last_name

    )

    await analytics_db_update_user_activity_async(user.id)

    await analytics_db_log_action_async(user.id, "start_command")

    

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

    limits = await analytics_db_get_user_limits_async(user_id)

    credits = await analytics_db_get_user_credits_async(user_id)

    

    # Формируем информацию о статусе

    free_generations_left = await analytics_db_get_free_generations_left_async(user_id)

    

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
            output = await replicate_run_async(
                    "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
                {"prompt": "test"},
                timeout=30
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
            output = await replicate_run_async(
                    "ideogram-ai/ideogram-v3-turbo",
                {"prompt": "simple test image"},
                timeout=30
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
        output = await replicate_run_async(
                "ideogram-ai/ideogram-v3-turbo",
            {"prompt": "A simple test image of a red apple on a white background, professional photography"},
            timeout=30
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

    await analytics_db_update_user_activity_async(user_id)

    await analytics_db_log_action_async(user_id, "stats_command")

    

    # Получаем статистику пользователя

    user_stats = await analytics_db_get_user_stats_async(user_id)

    

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

    

    await analytics_db_update_user_activity_async(user_id)

    await analytics_db_log_action_async(user_id, "admin_stats_command")

    

    # Получаем глобальную статистику

    global_stats = await analytics_db_get_global_stats_async(30)

    daily_stats = await analytics_db_get_daily_stats_async(7)

    

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

        # Используем асинхронный вызов для предотвращения блокировки
        loop = asyncio.get_event_loop()
        messages = [
                    {"role": "system", "content": "Ты помощник по созданию визуальных промптов для генерации изображений. НЕ добавляй людей в промпты, если они не упомянуты в сценарии."},
                    {"role": "user", "content": prompt}
        ]
        scenes_text = await openai_chat_completion_async(messages, "gpt-4o-mini", 700, 0.5)

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

    # Проверяем доступ к редактированию изображений
    user_id = None
    generation_type = None  # Инициализируем переменную
    
    if hasattr(update, 'message') and update.message:
        user_id = update.message.from_user.id
    elif hasattr(update, 'callback_query') and update.callback_query:
        user_id = update.callback_query.from_user.id

    if user_id:
        logging.info(f"DEBUG: Найден user_id={user_id}")
        free_generations_left = await analytics_db_get_free_generations_left_async(user_id)
        user_credits = await analytics_db_get_user_credits_async(user_id)
        
        # Редактирование доступно за бесплатные генерации ИЛИ за кредиты
        logging.info(f"DEBUG: free_generations_left={free_generations_left}, user_credits['balance']={user_credits['balance']}")
        if free_generations_left > 0:
            # Доступно за бесплатную генерацию
            generation_type = "free"
            logging.info(f"DEBUG: Установлен generation_type=free для пользователя {user_id}")
        elif user_credits['balance'] >= 12:  # Стоимость редактирования FLUX
            # Доступно за кредиты
            generation_type = "credits"
            logging.info(f"DEBUG: Установлен generation_type=credits для пользователя {user_id}")
        else:
            # Нет доступа - ни бесплатных генераций, ни кредитов
            keyboard = [
                [InlineKeyboardButton("🪙 Купить кредиты", callback_data="credit_packages")],
                [InlineKeyboardButton("🖼️ Создать изображения", callback_data="create_content")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ **Доступ к редактированию заблокирован!**\n\n"
                     "✏️ **Редактирование изображений доступно:**\n"
                     "• За бесплатные генерации (3 раза)\n"
                     "• За кредиты (12 кредитов за редактирование)\n\n"
                     "💡 **Что доступно бесплатно:**\n"
                     "• 🖼️ Создание изображений (3 раза)\n"
                     "• ✏️ Редактирование изображений (3 раза)\n\n"
                     "💰 **Для продолжения нужны кредиты:**\n"
                     "• Купите кредиты для доступа к редактированию\n"
                     "• Или используйте бесплатные генерации для изображений",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return None
    else:
        logging.warning(f"DEBUG: user_id не найден! update.message={hasattr(update, 'message')}, update.callback_query={hasattr(update, 'callback_query')}")

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

            # Используем асинхронный вызов для предотвращения блокировки
            loop = asyncio.get_event_loop()
            # Используем асинхронный HTTP клиент
            session = await init_http_session()
            async with session.get(original_image_url) as response:
                if response.status != 200:
                    logging.error(f"Ошибка загрузки изображения: {response.status}")
                    if send_text:
                        keyboard = [
                            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        await send_text(f"❌ Ошибка загрузки изображения: {response.status}", reply_markup=reply_markup)
                    return
                
                image_data = await response.read()

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

            # Создаем временный файл асинхронно
            loop = asyncio.get_event_loop()
            temp_file_path = await loop.run_in_executor(
                THREAD_POOL,
                lambda: tempfile.NamedTemporaryFile(delete=False, suffix='.png').name
            )
            
            # Записываем данные в файл асинхронно
            await loop.run_in_executor(
                THREAD_POOL,
                lambda: open(temp_file_path, 'wb').write(response.content)
            )

            

            # Открываем изображение с помощью PIL для получения размеров (асинхронно)
            loop = asyncio.get_event_loop()
            width, height = await loop.run_in_executor(
                THREAD_POOL,
                lambda: Image.open(temp_file_path).size
            )

            

            # Генерируем отредактированное изображение через FLUX.1 Kontext Pro

            logging.info(f"Отправляем запрос в FLUX с промптом: {edit_prompt}")

            try:

                # Читаем файл асинхронно
                loop = asyncio.get_event_loop()
                image_data = await loop.run_in_executor(
                    THREAD_POOL,
                    lambda: open(temp_file_path, "rb").read()
                )
                
                # Используем асинхронный вызов для предотвращения блокировки
                output = await replicate_run_async(
                        "black-forest-labs/flux-kontext-pro",
                    {
                            "input_image": image_data,
                                "prompt": edit_prompt,
                                "aspect_ratio": "match_input_image",
                                "output_format": "jpg",
                                "safety_tolerance": 2,
                                "prompt_upsampling": False
                        },
                        timeout=60
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

                    edited_image_url = output.url()

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

                # Используем асинхронный вызов для предотвращения блокировки
                loop = asyncio.get_event_loop()
                # Используем асинхронный HTTP клиент
                session = await init_http_session()
                async with session.get(edited_image_url) as edited_response:
                    if edited_response.status != 200:
                        logging.error(f"Ошибка загрузки отредактированного изображения: {edited_response.status}")
                        if send_text:
                            keyboard = [
                                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                            ]
                            reply_markup = InlineKeyboardMarkup(keyboard)
                            await send_text(f"❌ Ошибка загрузки отредактированного изображения: {edited_response.status}", reply_markup=reply_markup)
                        return
                    
                    edited_image_data = await edited_response.read()

                logging.info(f"Статус загрузки отредактированного изображения: {edited_response.status_code}")

                

                if edited_response.status_code == 200:

                    logging.info(f"Успешно загружено отредактированное изображение, размер: {len(edited_response.content)} байт")

                    # СПИСЫВАЕМ БЕСПЛАТНУЮ ГЕНЕРАЦИЮ ИЛИ КРЕДИТЫ
                    logging.info(f"DEBUG: user_id={user_id}, generation_type={generation_type}")
                    if user_id and generation_type:
                        if generation_type == "free":
                            # Списываем бесплатную генерацию
                            logging.info(f"DEBUG: Списываем бесплатную генерацию для пользователя {user_id}")
                            if await analytics_db_increment_free_generations_async(user_id):
                                logging.info(f"Пользователь {user_id} использовал бесплатную генерацию для редактирования")
                            else:
                                logging.error(f"Ошибка списания бесплатной генерации для пользователя {user_id}")
                        elif generation_type == "credits":
                            # Списываем кредиты
                            logging.info(f"DEBUG: Списываем кредиты для пользователя {user_id}")
                            if await analytics_db_use_credits_async(user_id, 12, "Редактирование изображения через FLUX.1 Kontext Pro"):
                                logging.info(f"Пользователь {user_id} использовал 12 кредитов для редактирования")
                            else:
                                logging.error(f"Ошибка списания кредитов для пользователя {user_id}")
                    else:
                        logging.warning(f"DEBUG: Не удалось списать - user_id={user_id}, generation_type={generation_type}")
                    
                    

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

                            # Создаем временный файл асинхронно
                            loop = asyncio.get_event_loop()
                            temp_edited_path = await loop.run_in_executor(
                                THREAD_POOL,
                                lambda: tempfile.NamedTemporaryFile(delete=False, suffix='.jpg').name
                            )
                            
                            # Записываем данные в файл асинхронно
                            await loop.run_in_executor(
                                THREAD_POOL,
                                lambda: open(temp_edited_path, 'wb').write(edited_response.content)
                            )

                            

                            logging.info(f"Временный файл создан: {temp_edited_path}")

                            

                            # Отправляем отредактированное изображение из файла (асинхронно)
                            loop = asyncio.get_event_loop()
                            edited_data = await loop.run_in_executor(
                                THREAD_POOL,
                                lambda: open(temp_edited_path, 'rb').read()
                            )

                            await context.bot.send_photo(

                                    chat_id=chat_id,

                                    photo=edited_data,

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

import logging

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



async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):

    """Показывает главное меню"""

    user_id = update.effective_user.id

    

    # Получаем информацию о пользователе

    limits = await analytics_db_get_user_limits_async(user_id)

    credits = await analytics_db_get_user_credits_async(user_id)

    

    # Формируем информацию о статусе

    free_generations_left = await analytics_db_get_free_generations_left_async(user_id)

    

    status_text = ""

    if free_generations_left > 0:

        status_text += f"🆓 **Бесплатные генерации:** {free_generations_left} осталось\n"

    else:

        status_text += f"🆓 **Бесплатные генерации:** закончились\n"

    

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
            output = await replicate_run_async(
                    "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
                {"prompt": "test"},
                timeout=30
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
            output = await replicate_run_async(
                    "ideogram-ai/ideogram-v3-turbo",
                {"prompt": "simple test image"},
                timeout=30
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
        output = await replicate_run_async(
                "ideogram-ai/ideogram-v3-turbo",
            {"prompt": "A simple test image of a red apple on a white background, professional photography"},
            timeout=30
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

    await analytics_db_update_user_activity_async(user_id)

    await analytics_db_log_action_async(user_id, "stats_command")

    

    # Получаем статистику пользователя

    user_stats = await analytics_db_get_user_stats_async(user_id)

    

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

    

    await analytics_db_update_user_activity_async(user_id)

    await analytics_db_log_action_async(user_id, "admin_stats_command")

    

    # Получаем глобальную статистику

    global_stats = await analytics_db_get_global_stats_async(30)

    daily_stats = await analytics_db_get_daily_stats_async(7)

    

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

        # Используем асинхронный вызов для предотвращения блокировки
        loop = asyncio.get_event_loop()
        messages = [
                    {"role": "system", "content": "Ты помощник по созданию визуальных промптов для генерации изображений. НЕ добавляй людей в промпты, если они не упомянуты в сценарии."},
                    {"role": "user", "content": prompt}
        ]
        scenes_text = await openai_chat_completion_async(messages, "gpt-4o-mini", 700, 0.5)

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

    # Проверяем доступ к редактированию изображений
    user_id = None
    generation_type = None  # Инициализируем переменную
    
    if hasattr(update, 'message') and update.message:
        user_id = update.message.from_user.id
    elif hasattr(update, 'callback_query') and update.callback_query:
        user_id = update.callback_query.from_user.id

    if user_id:
        logging.info(f"DEBUG: Найден user_id={user_id}")
        free_generations_left = await analytics_db_get_free_generations_left_async(user_id)
        user_credits = await analytics_db_get_user_credits_async(user_id)
        
        # Редактирование доступно за бесплатные генерации ИЛИ за кредиты
        logging.info(f"DEBUG: free_generations_left={free_generations_left}, user_credits['balance']={user_credits['balance']}")
        if free_generations_left > 0:
            # Доступно за бесплатную генерацию
            generation_type = "free"
            logging.info(f"DEBUG: Установлен generation_type=free для пользователя {user_id}")
        elif user_credits['balance'] >= 12:  # Стоимость редактирования FLUX
            # Доступно за кредиты
            generation_type = "credits"
            logging.info(f"DEBUG: Установлен generation_type=credits для пользователя {user_id}")
        else:
            # Нет доступа - ни бесплатных генераций, ни кредитов
            keyboard = [
                [InlineKeyboardButton("🪙 Купить кредиты", callback_data="credit_packages")],
                [InlineKeyboardButton("🖼️ Создать изображения", callback_data="create_content")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ **Доступ к редактированию заблокирован!**\n\n"
                     "✏️ **Редактирование изображений доступно:**\n"
                     "• За бесплатные генерации (3 раза)\n"
                     "• За кредиты (12 кредитов за редактирование)\n\n"
                     "💡 **Что доступно бесплатно:**\n"
                     "• 🖼️ Создание изображений (3 раза)\n"
                     "• ✏️ Редактирование изображений (3 раза)\n\n"
                     "💰 **Для продолжения нужны кредиты:**\n"
                     "• Купите кредиты для доступа к редактированию\n"
                     "• Или используйте бесплатные генерации для изображений",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return None
    else:
        logging.warning(f"DEBUG: user_id не найден! update.message={hasattr(update, 'message')}, update.callback_query={hasattr(update, 'callback_query')}")

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

            # Используем асинхронный вызов для предотвращения блокировки
            loop = asyncio.get_event_loop()
            # Используем асинхронный HTTP клиент
            session = await init_http_session()
            async with session.get(original_image_url) as response:
                if response.status != 200:
                    logging.error(f"Ошибка загрузки изображения: {response.status}")
                    if send_text:
                        keyboard = [
                            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        await send_text(f"❌ Ошибка загрузки изображения: {response.status}", reply_markup=reply_markup)
                    return
                
                image_data = await response.read()

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

            # Создаем временный файл асинхронно
            loop = asyncio.get_event_loop()
            temp_file_path = await loop.run_in_executor(
                THREAD_POOL,
                lambda: tempfile.NamedTemporaryFile(delete=False, suffix='.png').name
            )
            
            # Записываем данные в файл асинхронно
            await loop.run_in_executor(
                THREAD_POOL,
                lambda: open(temp_file_path, 'wb').write(response.content)
            )

            

            # Открываем изображение с помощью PIL для получения размеров (асинхронно)
            loop = asyncio.get_event_loop()
            width, height = await loop.run_in_executor(
                THREAD_POOL,
                lambda: Image.open(temp_file_path).size
            )

            

            # Генерируем отредактированное изображение через FLUX.1 Kontext Pro

            logging.info(f"Отправляем запрос в FLUX с промптом: {edit_prompt}")

            try:

                # Читаем файл асинхронно
                loop = asyncio.get_event_loop()
                image_data = await loop.run_in_executor(
                    THREAD_POOL,
                    lambda: open(temp_file_path, "rb").read()
                )
                
                # Используем асинхронный вызов для предотвращения блокировки
                output = await replicate_run_async(
                        "black-forest-labs/flux-kontext-pro",
                    {
                            "input_image": image_data,
                                "prompt": edit_prompt,
                                "aspect_ratio": "match_input_image",
                                "output_format": "jpg",
                                "safety_tolerance": 2,
                                "prompt_upsampling": False
                        },
                        timeout=60
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

                    edited_image_url = output.url()

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

                # Используем асинхронный вызов для предотвращения блокировки
                loop = asyncio.get_event_loop()
                # Используем асинхронный HTTP клиент
                session = await init_http_session()
                async with session.get(edited_image_url) as edited_response:
                    if edited_response.status != 200:
                        logging.error(f"Ошибка загрузки отредактированного изображения: {edited_response.status}")
                        if send_text:
                            keyboard = [
                                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                            ]
                            reply_markup = InlineKeyboardMarkup(keyboard)
                            await send_text(f"❌ Ошибка загрузки отредактированного изображения: {edited_response.status}", reply_markup=reply_markup)
                        return
                    
                    edited_image_data = await edited_response.read()

                logging.info(f"Статус загрузки отредактированного изображения: {edited_response.status_code}")

                

                if edited_response.status_code == 200:

                    logging.info(f"Успешно загружено отредактированное изображение, размер: {len(edited_response.content)} байт")

                    # СПИСЫВАЕМ БЕСПЛАТНУЮ ГЕНЕРАЦИЮ ИЛИ КРЕДИТЫ
                    logging.info(f"DEBUG: user_id={user_id}, generation_type={generation_type}")
                    if user_id and generation_type:
                        if generation_type == "free":
                            # Списываем бесплатную генерацию
                            logging.info(f"DEBUG: Списываем бесплатную генерацию для пользователя {user_id}")
                            if await analytics_db_increment_free_generations_async(user_id):
                                logging.info(f"Пользователь {user_id} использовал бесплатную генерацию для редактирования")
                            else:
                                logging.error(f"Ошибка списания бесплатной генерации для пользователя {user_id}")
                        elif generation_type == "credits":
                            # Списываем кредиты
                            logging.info(f"DEBUG: Списываем кредиты для пользователя {user_id}")
                            if await analytics_db_use_credits_async(user_id, 12, "Редактирование изображения через FLUX.1 Kontext Pro"):
                                logging.info(f"Пользователь {user_id} использовал 12 кредитов для редактирования")
                            else:
                                logging.error(f"Ошибка списания кредитов для пользователя {user_id}")
                    else:
                        logging.warning(f"DEBUG: Не удалось списать - user_id={user_id}, generation_type={generation_type}")

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

                            # Создаем временный файл асинхронно
                            loop = asyncio.get_event_loop()
                            temp_edited_path = await loop.run_in_executor(
                                THREAD_POOL,
                                lambda: tempfile.NamedTemporaryFile(delete=False, suffix='.jpg').name
                            )
                            
                            # Записываем данные в файл асинхронно
                            await loop.run_in_executor(
                                THREAD_POOL,
                                lambda: open(temp_edited_path, 'wb').write(edited_response.content)
                            )

                            

                            logging.info(f"Временный файл создан: {temp_edited_path}")

                            

                            # Отправляем отредактированное изображение из файла (асинхронно)
                            loop = asyncio.get_event_loop()
                            edited_data = await loop.run_in_executor(
                                THREAD_POOL,
                                lambda: open(temp_edited_path, 'rb').read()
                            )

                            await context.bot.send_photo(

                                    chat_id=chat_id,

                                    photo=edited_data,

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

    await analytics_db_update_user_activity_async(user_id)

    await analytics_db_log_action_async(user_id, "start_generation", f"format:{state.get('format', 'unknown')}, model:{state.get('image_gen_model', 'unknown')}")

    

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
            loop = asyncio.get_event_loop()
            test_response = await replicate_run_async(
                    "replicate/hello-world",
                {"text": "test"},
                timeout=30
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

    

    # Проверяем лимиты пользователя
    user_id = update.effective_user.id
    free_generations_left = await analytics_db_get_free_generations_left_async(user_id)
    user_credits = await analytics_db_get_user_credits_async(user_id)
    
    # Определяем стоимость генерации
    selected_model = state.get('image_gen_model', 'Ideogram')
    try:
        from pricing_config import get_generation_cost
        generation_cost = get_generation_cost(selected_model, state.get('format', ''))
    except ImportError:
        # Fallback если модуль не импортирован
        generation_cost = 10  # По умолчанию 10 кредитов
    
    # Проверяем, может ли пользователь генерировать
    can_generate = False
    if free_generations_left > 0:
        can_generate = True
        generation_type = "free"
    elif user_credits['balance'] >= generation_cost:
        can_generate = True
        generation_type = "credits"
    else:
        can_generate = False
        generation_type = "none"
    
    # Если пользователь не может генерировать, показываем сообщение
    if not can_generate:
        if send_text:
            keyboard = [
                [InlineKeyboardButton("🪙 Купить кредиты", callback_data="credit_packages")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            text = "❌ **У вас закончились бесплатные генерации и кредиты!**\n\n"
            text += f"🆓 Бесплатных генераций осталось: **{free_generations_left}**\n"
            text += f"🪙 Кредитов на балансе: **{user_credits['balance']}**\n"
            text += f"💰 Стоимость генерации: **{generation_cost} кредитов**\n\n"
            text += "💳 **Купите кредиты для продолжения работы!**"
            
            await send_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        return

    # Определяем максимальное количество изображений

    user_format = state.get('format', '').lower()

    image_count = state.get('image_count', 'default')

    

    # Логируем параметры для отладки (только в логи)

    logging.info(f"Отладка: format='{user_format}', image_count='{image_count}', prompt_type='{prompt_type}', user_prompt='{user_prompt}'")

    logging.info(f"Состояние: {state}")

    

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

        max_scenes = min(image_count, 10)  # Строго соблюдаем выбранное пользователем количество, но не более 10

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

                    # Используем асинхронную функцию для предотвращения блокировки
                    messages = [
                                {"role": "system", "content": "Ты эксперт по созданию промптов для генерации изображений. Создавай детальные, профессиональные промпты на английском языке, которые точно описывают тему и включают конкретные детали. Избегай общих фраз, используй специфичные элементы. НЕ добавляй людей в промпты, если они не упомянуты в теме."},
                                {"role": "user", "content": image_prompts}
                    ]
                    raw_prompts = await openai_chat_completion_async(messages, "gpt-4o-mini", 800, 0.7)

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

    # ПАРАЛЛЕЛЬНАЯ ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЙ
    # Создаем задачи для параллельной генерации всех изображений
    tasks = []
    for idx, prompt in enumerate(safe_prompts, 1):
        if idx > max_scenes:
            break
        # Создаем задачу для генерации одного изображения
        task = generate_single_image_async(idx, prompt, state, send_text)
        tasks.append(task)

    # Запускаем все задачи параллельно
    if tasks:
        if send_text:
            await send_text(f"🚀 Запускаю параллельную генерацию {len(tasks)} изображений...")

        # Ждем завершения всех задач
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Обрабатываем результаты
        for result in results:
            if isinstance(result, Exception):
                logging.error(f"Ошибка в параллельной генерации: {result}")
                if send_text:
                    await send_text(f"❌ Ошибка при генерации: {result}")
                continue

            idx, success, image_url, caption, error = result

            if success and image_url:
                # Успешно сгенерировано изображение
                images.append(image_url)
                media.append(InputMediaPhoto(media=image_url, caption=caption))
                processed_count += 1

                print(f"🔍 Добавлено изображение {idx}:")
                print(f"   image_url: {image_url}")
                print(f"   длина image_url: {len(str(image_url)) if image_url else 'None'}")
                print(f"   последний элемент media: {media[-1].media}")
                print(f"   длина media[-1].media: {len(str(media[-1].media)) if media[-1].media else 'None'}")
            else:
                # Ошибка при генерации
                logging.error(f"Ошибка генерации изображения {idx}: {error}")
                if send_text:
                    await send_text(f"❌ Ошибка при генерации изображения {idx}: {error}")

    # Удаляем старый последовательный код - он заменен на параллельный выше
    # Оставляем только обработку результатов
    if media and send_media:
        print(f"🔍 Попытка отправки media группы...")
        print(f"🔍 Количество изображений: {len(media)}")
        for i, item in enumerate(media):
            print(f"🔍 Изображение {i+1}: {item.media}")
            print(f"🔍 Длина URL: {len(str(item.media)) if item.media else 'None'}")
        
        try:
            # Пытаемся отправить как группу
            await send_media(media=media)
            print(f"✅ Media группа отправлена успешно")
        except Exception as group_error:
            print(f"❌ Ошибка отправки группы: {group_error}")
            # Если группа не отправляется, отправляем по одному
            for i, item in enumerate(media):
                try:
                    if hasattr(update, 'message') and update.message:
                        await update.message.reply_photo(photo=item.media, caption=item.caption)
                    else:
                        await context.bot.send_photo(chat_id=chat_id, photo=item.media, caption=item.caption)
                    print(f"✅ Изображение {i+1} отправлено отдельно")
                except Exception as photo_error:
                    print(f"❌ Ошибка отправки изображения {i+1}: {photo_error}")
                    if send_text:
                        await send_text(f"❌ Ошибка отправки изображения {i+1}: {str(photo_error)[:100]}")

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

        await analytics_db_log_generation_async(

            user_id=user_id,

            model_name=selected_model,

            format_type=format_type,

            prompt=state.get('topic', 'unknown'),

            image_count=processed_count,

            success=True,

            generation_time=generation_time

        )

        await analytics_db_log_action_async(user_id, "generation_success", f"count:{processed_count}, time:{generation_time:.1f}s")
        
        # Списываем кредиты или увеличиваем счетчик бесплатных генераций
        if generation_type == "free":
            # Списываем по количеству реально созданных изображений
            for i in range(processed_count):
                if await analytics_db_get_free_generations_left_async(user_id) > 0:
                    await analytics_db_increment_free_generations_async(user_id)
                else:
                    # Если бесплатные закончились, переключаемся на кредиты
                    generation_type = "credits"
                    break
    
            # Если переключились на кредиты, списываем их
            if generation_type == "credits":
                remaining_count = processed_count - i
                total_cost = generation_cost * remaining_count
                await analytics_db_use_credits_async(user_id, total_cost, f"Генерация {remaining_count} изображений через {selected_model}")
                logging.info(f"Пользователь {user_id} использовал {total_cost} кредитов за {remaining_count} изображений")
            else:
                logging.info(f"Пользователь {user_id} использовал {processed_count} бесплатных генераций")

        elif generation_type == "credits":
            # Списываем кредиты за каждое изображение
            total_cost = generation_cost * processed_count
            if await analytics_db_use_credits_async(user_id, total_cost, f"Генерация {processed_count} изображений через {selected_model}"):
                logging.info(f"Пользователь {user_id} использовал {total_cost} кредитов за {processed_count} изображений")
            else:
                logging.error(f"Ошибка списания кредитов для пользователя {user_id}")

    else:

        # Логируем неудачную генерацию

        await analytics_db_log_generation_async(

            user_id=user_id,

            model_name=selected_model,

            format_type=format_type,

            prompt=state.get('topic', 'unknown'),

            image_count=0,

            success=False,

            error_message="No images generated",

            generation_time=generation_time

        )

        await analytics_db_log_action_async(user_id, "generation_failed", f"time:{generation_time:.1f}s")

    

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




async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # Логируем нового пользователя

    user = update.effective_user

    await analytics_db_add_user_async(

        user_id=user.id,

        username=user.username,

        first_name=user.first_name,

        last_name=user.last_name

    )

    await analytics_db_update_user_activity_async(user.id)

    await analytics_db_log_action_async(user.id, "start_command")

    

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

    limits = await analytics_db_get_user_limits_async(user_id)

    credits = await analytics_db_get_user_credits_async(user_id)

    

    # Формируем информацию о статусе

    free_generations_left = await analytics_db_get_free_generations_left_async(user_id)

    

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
            output = await replicate_run_async(
                    "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
                {"prompt": "test"},
                timeout=30
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
            output = await replicate_run_async(
                    "ideogram-ai/ideogram-v3-turbo",
                {"prompt": "simple test image"},
                timeout=30
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
        output = await replicate_run_async(
                "ideogram-ai/ideogram-v3-turbo",
            {"prompt": "A simple test image of a red apple on a white background, professional photography"},
            timeout=30
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

    await analytics_db_update_user_activity_async(user_id)

    await analytics_db_log_action_async(user_id, "stats_command")

    

    # Получаем статистику пользователя

    user_stats = await analytics_db_get_user_stats_async(user_id)

    

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

    

    await analytics_db_update_user_activity_async(user_id)

    await analytics_db_log_action_async(user_id, "admin_stats_command")

    

    # Получаем глобальную статистику

    global_stats = await analytics_db_get_global_stats_async(30)

    daily_stats = await analytics_db_get_daily_stats_async(7)

    

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

        # Используем асинхронный вызов для предотвращения блокировки
        loop = asyncio.get_event_loop()
        messages = [
                    {"role": "system", "content": "Ты помощник по созданию визуальных промптов для генерации изображений. НЕ добавляй людей в промпты, если они не упомянуты в сценарии."},
                    {"role": "user", "content": prompt}
        ]
        scenes_text = await openai_chat_completion_async(messages, "gpt-4o-mini", 700, 0.5)

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



import logging

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

    await analytics_db_add_user_async(

        user_id=user.id,

        username=user.username,

        first_name=user.first_name,

        last_name=user.last_name

    )

    await analytics_db_update_user_activity_async(user.id)

    await analytics_db_log_action_async(user.id, "start_command")

    

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

    limits = await analytics_db_get_user_limits_async(user_id)

    credits = await analytics_db_get_user_credits_async(user_id)

    

    # Формируем информацию о статусе

    free_generations_left = await analytics_db_get_free_generations_left_async(user_id)

    

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
            output = await replicate_run_async(
                    "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
                {"prompt": "test"},
                timeout=30
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
            output = await replicate_run_async(
                    "ideogram-ai/ideogram-v3-turbo",
                {"prompt": "simple test image"},
                timeout=30
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
        output = await replicate_run_async(
                "ideogram-ai/ideogram-v3-turbo",
            {"prompt": "A simple test image of a red apple on a white background, professional photography"},
            timeout=30
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

    await analytics_db_update_user_activity_async(user_id)

    await analytics_db_log_action_async(user_id, "stats_command")

    

    # Получаем статистику пользователя

    user_stats = await analytics_db_get_user_stats_async(user_id)

    

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

    

    await analytics_db_update_user_activity_async(user_id)

    await analytics_db_log_action_async(user_id, "admin_stats_command")

    

    # Получаем глобальную статистику

    global_stats = await analytics_db_get_global_stats_async(30)

    daily_stats = await analytics_db_get_daily_stats_async(7)

    

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

        # Используем асинхронный вызов для предотвращения блокировки
        loop = asyncio.get_event_loop()
        messages = [
                    {"role": "system", "content": "Ты помощник по созданию визуальных промптов для генерации изображений. НЕ добавляй людей в промпты, если они не упомянуты в сценарии."},
                    {"role": "user", "content": prompt}
        ]
        scenes_text = await openai_chat_completion_async(messages, "gpt-4o-mini", 700, 0.5)

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

    # Проверяем доступ к редактированию изображений
    user_id = None
    generation_type = None  # Инициализируем переменную
    
    if hasattr(update, 'message') and update.message:
        user_id = update.message.from_user.id
    elif hasattr(update, 'callback_query') and update.callback_query:
        user_id = update.callback_query.from_user.id

    if user_id:
        logging.info(f"DEBUG: Найден user_id={user_id}")
        free_generations_left = await analytics_db_get_free_generations_left_async(user_id)
        user_credits = await analytics_db_get_user_credits_async(user_id)
        
        # Редактирование доступно за бесплатные генерации ИЛИ за кредиты
        logging.info(f"DEBUG: free_generations_left={free_generations_left}, user_credits['balance']={user_credits['balance']}")
        if free_generations_left > 0:
            # Доступно за бесплатную генерацию
            generation_type = "free"
            logging.info(f"DEBUG: Установлен generation_type=free для пользователя {user_id}")
        elif user_credits['balance'] >= 12:  # Стоимость редактирования FLUX
            # Доступно за кредиты
            generation_type = "credits"
            logging.info(f"DEBUG: Установлен generation_type=credits для пользователя {user_id}")
        else:
            # Нет доступа - ни бесплатных генераций, ни кредитов
            keyboard = [
                [InlineKeyboardButton("🪙 Купить кредиты", callback_data="credit_packages")],
                [InlineKeyboardButton("🖼️ Создать изображения", callback_data="create_content")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ **Доступ к редактированию заблокирован!**\n\n"
                     "✏️ **Редактирование изображений доступно:**\n"
                     "• За бесплатные генерации (3 раза)\n"
                     "• За кредиты (12 кредитов за редактирование)\n\n"
                     "💡 **Что доступно бесплатно:**\n"
                     "• 🖼️ Создание изображений (3 раза)\n"
                     "• ✏️ Редактирование изображений (3 раза)\n\n"
                     "💰 **Для продолжения нужны кредиты:**\n"
                     "• Купите кредиты для доступа к редактированию\n"
                     "• Или используйте бесплатные генерации для изображений",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return None
    else:
        logging.warning(f"DEBUG: user_id не найден! update.message={hasattr(update, 'message')}, update.callback_query={hasattr(update, 'callback_query')}")

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

            # Используем асинхронный вызов для предотвращения блокировки
            loop = asyncio.get_event_loop()
            # Используем асинхронный HTTP клиент
            session = await init_http_session()
            async with session.get(original_image_url) as response:
                if response.status != 200:
                    logging.error(f"Ошибка загрузки изображения: {response.status}")
                    if send_text:
                        keyboard = [
                            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        await send_text(f"❌ Ошибка загрузки изображения: {response.status}", reply_markup=reply_markup)
                    return
                
                image_data = await response.read()

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

            # Создаем временный файл асинхронно
            loop = asyncio.get_event_loop()
            temp_file_path = await loop.run_in_executor(
                THREAD_POOL,
                lambda: tempfile.NamedTemporaryFile(delete=False, suffix='.png').name
            )
            
            # Записываем данные в файл асинхронно
            await loop.run_in_executor(
                THREAD_POOL,
                lambda: open(temp_file_path, 'wb').write(response.content)
            )

            

            # Открываем изображение с помощью PIL для получения размеров (асинхронно)
            loop = asyncio.get_event_loop()
            width, height = await loop.run_in_executor(
                THREAD_POOL,
                lambda: Image.open(temp_file_path).size
            )

            

            # Генерируем отредактированное изображение через FLUX.1 Kontext Pro

            logging.info(f"Отправляем запрос в FLUX с промптом: {edit_prompt}")

            try:

                # Читаем файл асинхронно
                loop = asyncio.get_event_loop()
                image_data = await loop.run_in_executor(
                    THREAD_POOL,
                    lambda: open(temp_file_path, "rb").read()
                )
                
                # Используем асинхронный вызов для предотвращения блокировки
                output = await replicate_run_async(
                        "black-forest-labs/flux-kontext-pro",
                    {
                            "input_image": image_data,
                                "prompt": edit_prompt,
                                "aspect_ratio": "match_input_image",
                                "output_format": "jpg",
                                "safety_tolerance": 2,
                                "prompt_upsampling": False
                        },
                        timeout=60
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

                    edited_image_url = output.url()

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

                # Используем асинхронный вызов для предотвращения блокировки
                loop = asyncio.get_event_loop()
                # Используем асинхронный HTTP клиент
                session = await init_http_session()
                async with session.get(edited_image_url) as edited_response:
                    if edited_response.status != 200:
                        logging.error(f"Ошибка загрузки отредактированного изображения: {edited_response.status}")
                        if send_text:
                            keyboard = [
                                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                            ]
                            reply_markup = InlineKeyboardMarkup(keyboard)
                            await send_text(f"❌ Ошибка загрузки отредактированного изображения: {edited_response.status}", reply_markup=reply_markup)
                        return
                    
                    edited_image_data = await edited_response.read()

                logging.info(f"Статус загрузки отредактированного изображения: {edited_response.status_code}")

                

                if edited_response.status_code == 200:

                    logging.info(f"Успешно загружено отредактированное изображение, размер: {len(edited_response.content)} байт")

                    # СПИСЫВАЕМ БЕСПЛАТНУЮ ГЕНЕРАЦИЮ ИЛИ КРЕДИТЫ
                    logging.info(f"DEBUG: user_id={user_id}, generation_type={generation_type}")
                    if user_id and generation_type:
                        if generation_type == "free":
                            # Списываем бесплатную генерацию
                            logging.info(f"DEBUG: Списываем бесплатную генерацию для пользователя {user_id}")
                            if await analytics_db_increment_free_generations_async(user_id):
                                logging.info(f"Пользователь {user_id} использовал бесплатную генерацию для редактирования")
                            else:
                                logging.error(f"Ошибка списания бесплатной генерации для пользователя {user_id}")
                        elif generation_type == "credits":
                            # Списываем кредиты
                            logging.info(f"DEBUG: Списываем кредиты для пользователя {user_id}")
                            if await analytics_db_use_credits_async(user_id, 12, "Редактирование изображения через FLUX.1 Kontext Pro"):
                                logging.info(f"Пользователь {user_id} использовал 12 кредитов для редактирования")
                            else:
                                logging.error(f"Ошибка списания кредитов для пользователя {user_id}")
                    else:
                        logging.warning(f"DEBUG: Не удалось списать - user_id={user_id}, generation_type={generation_type}")

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

                            # Создаем временный файл асинхронно
                            loop = asyncio.get_event_loop()
                            temp_edited_path = await loop.run_in_executor(
                                THREAD_POOL,
                                lambda: tempfile.NamedTemporaryFile(delete=False, suffix='.jpg').name
                            )
                            
                            # Записываем данные в файл асинхронно
                            await loop.run_in_executor(
                                THREAD_POOL,
                                lambda: open(temp_edited_path, 'wb').write(edited_response.content)
                            )

                            

                            logging.info(f"Временный файл создан: {temp_edited_path}")

                            

                            # Отправляем отредактированное изображение из файла (асинхронно)
                            loop = asyncio.get_event_loop()
                            edited_data = await loop.run_in_executor(
                                THREAD_POOL,
                                lambda: open(temp_edited_path, 'rb').read()
                            )

                            await context.bot.send_photo(

                                    chat_id=chat_id,

                                    photo=edited_data,

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

import logging

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



async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):

    """Показывает главное меню"""

    user_id = update.effective_user.id

    

    # Получаем информацию о пользователе

    limits = await analytics_db_get_user_limits_async(user_id)

    credits = await analytics_db_get_user_credits_async(user_id)

    

    # Формируем информацию о статусе

    free_generations_left = await analytics_db_get_free_generations_left_async(user_id)

    

    status_text = ""

    if free_generations_left > 0:

        status_text += f"🆓 **Бесплатные генерации:** {free_generations_left} осталось\n"

    else:

        status_text += f"🆓 **Бесплатные генерации:** закончились\n"

    

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
            output = await replicate_run_async(
                    "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
                {"prompt": "test"},
                timeout=30
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
            output = await replicate_run_async(
                    "ideogram-ai/ideogram-v3-turbo",
                {"prompt": "simple test image"},
                timeout=30
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
        output = await replicate_run_async(
                "ideogram-ai/ideogram-v3-turbo",
            {"prompt": "A simple test image of a red apple on a white background, professional photography"},
            timeout=30
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

    await analytics_db_update_user_activity_async(user_id)

    await analytics_db_log_action_async(user_id, "stats_command")

    

    # Получаем статистику пользователя

    user_stats = await analytics_db_get_user_stats_async(user_id)

    

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

    

    await analytics_db_update_user_activity_async(user_id)

    await analytics_db_log_action_async(user_id, "admin_stats_command")

    

    # Получаем глобальную статистику

    global_stats = await analytics_db_get_global_stats_async(30)

    daily_stats = await analytics_db_get_daily_stats_async(7)

    

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

        # Используем асинхронный вызов для предотвращения блокировки
        loop = asyncio.get_event_loop()
        messages = [
                    {"role": "system", "content": "Ты помощник по созданию визуальных промптов для генерации изображений. НЕ добавляй людей в промпты, если они не упомянуты в сценарии."},
                    {"role": "user", "content": prompt}
        ]
        scenes_text = await openai_chat_completion_async(messages, "gpt-4o-mini", 700, 0.5)

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

    # Проверяем доступ к редактированию изображений
    user_id = None
    generation_type = None  # Инициализируем переменную
    
    if hasattr(update, 'message') and update.message:
        user_id = update.message.from_user.id
    elif hasattr(update, 'callback_query') and update.callback_query:
        user_id = update.callback_query.from_user.id

    if user_id:
        logging.info(f"DEBUG: Найден user_id={user_id}")
        free_generations_left = await analytics_db_get_free_generations_left_async(user_id)
        user_credits = await analytics_db_get_user_credits_async(user_id)
        
        # Редактирование доступно за бесплатные генерации ИЛИ за кредиты
        logging.info(f"DEBUG: free_generations_left={free_generations_left}, user_credits['balance']={user_credits['balance']}")
        if free_generations_left > 0:
            # Доступно за бесплатную генерацию
            generation_type = "free"
            logging.info(f"DEBUG: Установлен generation_type=free для пользователя {user_id}")
        elif user_credits['balance'] >= 12:  # Стоимость редактирования FLUX
            # Доступно за кредиты
            generation_type = "credits"
            logging.info(f"DEBUG: Установлен generation_type=credits для пользователя {user_id}")
        else:
            # Нет доступа - ни бесплатных генераций, ни кредитов
            keyboard = [
                [InlineKeyboardButton("🪙 Купить кредиты", callback_data="credit_packages")],
                [InlineKeyboardButton("🖼️ Создать изображения", callback_data="create_content")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ **Доступ к редактированию заблокирован!**\n\n"
                     "✏️ **Редактирование изображений доступно:**\n"
                     "• За бесплатные генерации (3 раза)\n"
                     "• За кредиты (12 кредитов за редактирование)\n\n"
                     "💡 **Что доступно бесплатно:**\n"
                     "• 🖼️ Создание изображений (3 раза)\n"
                     "• ✏️ Редактирование изображений (3 раза)\n\n"
                     "💰 **Для продолжения нужны кредиты:**\n"
                     "• Купите кредиты для доступа к редактированию\n"
                     "• Или используйте бесплатные генерации для изображений",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return None
    else:
        logging.warning(f"DEBUG: user_id не найден! update.message={hasattr(update, 'message')}, update.callback_query={hasattr(update, 'callback_query')}")

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

            # Используем асинхронный вызов для предотвращения блокировки
            loop = asyncio.get_event_loop()
            # Используем асинхронный HTTP клиент
            session = await init_http_session()
            async with session.get(original_image_url) as response:
                if response.status != 200:
                    logging.error(f"Ошибка загрузки изображения: {response.status}")
                    if send_text:
                        keyboard = [
                            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        await send_text(f"❌ Ошибка загрузки изображения: {response.status}", reply_markup=reply_markup)
                    return
                
                image_data = await response.read()

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

            # Создаем временный файл асинхронно
            loop = asyncio.get_event_loop()
            temp_file_path = await loop.run_in_executor(
                THREAD_POOL,
                lambda: tempfile.NamedTemporaryFile(delete=False, suffix='.png').name
            )
            
            # Записываем данные в файл асинхронно
            await loop.run_in_executor(
                THREAD_POOL,
                lambda: open(temp_file_path, 'wb').write(response.content)
            )

            

            # Открываем изображение с помощью PIL для получения размеров (асинхронно)
            loop = asyncio.get_event_loop()
            width, height = await loop.run_in_executor(
                THREAD_POOL,
                lambda: Image.open(temp_file_path).size
            )

            

            # Генерируем отредактированное изображение через FLUX.1 Kontext Pro

            logging.info(f"Отправляем запрос в FLUX с промптом: {edit_prompt}")

            try:

                # Читаем файл асинхронно
                loop = asyncio.get_event_loop()
                image_data = await loop.run_in_executor(
                    THREAD_POOL,
                    lambda: open(temp_file_path, "rb").read()
                )
                
                # Используем асинхронный вызов для предотвращения блокировки
                output = await replicate_run_async(
                        "black-forest-labs/flux-kontext-pro",
                    {
                            "input_image": image_data,
                                "prompt": edit_prompt,
                                "aspect_ratio": "match_input_image",
                                "output_format": "jpg",
                                "safety_tolerance": 2,
                                "prompt_upsampling": False
                        },
                        timeout=60
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

                    edited_image_url = output.url()

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

                # Используем асинхронный вызов для предотвращения блокировки
                loop = asyncio.get_event_loop()
                # Используем асинхронный HTTP клиент
                session = await init_http_session()
                async with session.get(edited_image_url) as edited_response:
                    if edited_response.status != 200:
                        logging.error(f"Ошибка загрузки отредактированного изображения: {edited_response.status}")
                        if send_text:
                            keyboard = [
                                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                            ]
                            reply_markup = InlineKeyboardMarkup(keyboard)
                            await send_text(f"❌ Ошибка загрузки отредактированного изображения: {edited_response.status}", reply_markup=reply_markup)
                        return
                    
                    edited_image_data = await edited_response.read()

                logging.info(f"Статус загрузки отредактированного изображения: {edited_response.status_code}")

                

                if edited_response.status_code == 200:

                    logging.info(f"Успешно загружено отредактированное изображение, размер: {len(edited_response.content)} байт")

                    # СПИСЫВАЕМ БЕСПЛАТНУЮ ГЕНЕРАЦИЮ ИЛИ КРЕДИТЫ
                    logging.info(f"DEBUG: user_id={user_id}, generation_type={generation_type}")
                    if user_id and generation_type:
                        if generation_type == "free":
                            # Списываем бесплатную генерацию
                            logging.info(f"DEBUG: Списываем бесплатную генерацию для пользователя {user_id}")
                            if await analytics_db_increment_free_generations_async(user_id):
                                logging.info(f"Пользователь {user_id} использовал бесплатную генерацию для редактирования")
                            else:
                                logging.error(f"Ошибка списания бесплатной генерации для пользователя {user_id}")
                        elif generation_type == "credits":
                            # Списываем кредиты
                            logging.info(f"DEBUG: Списываем кредиты для пользователя {user_id}")
                            if await analytics_db_use_credits_async(user_id, 12, "Редактирование изображения через FLUX.1 Kontext Pro"):
                                logging.info(f"Пользователь {user_id} использовал 12 кредитов для редактирования")
                            else:
                                logging.error(f"Ошибка списания кредитов для пользователя {user_id}")
                    else:
                        logging.warning(f"DEBUG: Не удалось списать - user_id={user_id}, generation_type={generation_type}")

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

                            # Создаем временный файл асинхронно
                            loop = asyncio.get_event_loop()
                            temp_edited_path = await loop.run_in_executor(
                                THREAD_POOL,
                                lambda: tempfile.NamedTemporaryFile(delete=False, suffix='.jpg').name
                            )
                            
                            # Записываем данные в файл асинхронно
                            await loop.run_in_executor(
                                THREAD_POOL,
                                lambda: open(temp_edited_path, 'wb').write(edited_response.content)
                            )

                            

                            logging.info(f"Временный файл создан: {temp_edited_path}")

                            

                            # Отправляем отредактированное изображение из файла (асинхронно)
                            loop = asyncio.get_event_loop()
                            edited_data = await loop.run_in_executor(
                                THREAD_POOL,
                                lambda: open(temp_edited_path, 'rb').read()
                            )

                            await context.bot.send_photo(

                                    chat_id=chat_id,

                                    photo=edited_data,

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

    await analytics_db_update_user_activity_async(user_id)

    await analytics_db_log_action_async(user_id, "start_generation", f"format:{state.get('format', 'unknown')}, model:{state.get('image_gen_model', 'unknown')}")

    

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
            loop = asyncio.get_event_loop()
            test_response = await replicate_run_async(
                    "replicate/hello-world",
                {"text": "test"},
                timeout=30
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

    

    # Проверяем лимиты пользователя
    user_id = update.effective_user.id
    free_generations_left = await analytics_db_get_free_generations_left_async(user_id)
    user_credits = await analytics_db_get_user_credits_async(user_id)
    
    # Определяем стоимость генерации
    selected_model = state.get('image_gen_model', 'Ideogram')
    try:
        from pricing_config import get_generation_cost
        generation_cost = get_generation_cost(selected_model, state.get('format', ''))
    except ImportError:
        # Fallback если модуль не импортирован
        generation_cost = 10  # По умолчанию 10 кредитов
    
    # Проверяем, может ли пользователь генерировать
    can_generate = False
    if free_generations_left > 0:
        can_generate = True
        generation_type = "free"
    elif user_credits['balance'] >= generation_cost:
        can_generate = True
        generation_type = "credits"
    else:
        can_generate = False
        generation_type = "none"
    
    # Если пользователь не может генерировать, показываем сообщение
    if not can_generate:
        if send_text:
            keyboard = [
                [InlineKeyboardButton("🪙 Купить кредиты", callback_data="credit_packages")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            text = "❌ **У вас закончились бесплатные генерации и кредиты!**\n\n"
            text += f"🆓 Бесплатных генераций осталось: **{free_generations_left}**\n"
            text += f"🪙 Кредитов на балансе: **{user_credits['balance']}**\n"
            text += f"💰 Стоимость генерации: **{generation_cost} кредитов**\n\n"
            text += "💳 **Купите кредиты для продолжения работы!**"
            
            await send_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        return

    # Определяем максимальное количество изображений

    user_format = state.get('format', '').lower()

    image_count = state.get('image_count', 'default')

    

    # Логируем параметры для отладки (только в логи)

    logging.info(f"Отладка: format='{user_format}', image_count='{image_count}', prompt_type='{prompt_type}', user_prompt='{user_prompt}'")

    logging.info(f"Состояние: {state}")

    

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

        max_scenes = min(image_count, 10)  # Строго соблюдаем выбранное пользователем количество, но не более 10

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

                    # Используем асинхронную функцию для предотвращения блокировки
                    messages = [
                                {"role": "system", "content": "Ты эксперт по созданию промптов для генерации изображений. Создавай детальные, профессиональные промпты на английском языке, которые точно описывают тему и включают конкретные детали. Избегай общих фраз, используй специфичные элементы. НЕ добавляй людей в промпты, если они не упомянуты в теме."},
                                {"role": "user", "content": image_prompts}
                    ]
                    raw_prompts = await openai_chat_completion_async(messages, "gpt-4o-mini", 800, 0.7)

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

    # ПАРАЛЛЕЛЬНАЯ ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЙ
    # Создаем задачи для параллельной генерации всех изображений
    tasks = []
    for idx, prompt in enumerate(safe_prompts, 1):
        if idx > max_scenes:
            break
        # Создаем задачу для генерации одного изображения
        task = generate_single_image_async(idx, prompt, state, send_text)
        tasks.append(task)

    # Запускаем все задачи параллельно
    if tasks:
        if send_text:
            await send_text(f"🚀 Запускаю параллельную генерацию {len(tasks)} изображений...")

        # Ждем завершения всех задач
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Обрабатываем результаты
        for result in results:
            if isinstance(result, Exception):
                logging.error(f"Ошибка в параллельной генерации: {result}")
                if send_text:
                    await send_text(f"❌ Ошибка при генерации: {result}")
                continue

            idx, success, image_url, caption, error = result

            if success and image_url:
                # Успешно сгенерировано изображение
                images.append(image_url)
                media.append(InputMediaPhoto(media=image_url, caption=caption))
                processed_count += 1

                print(f"🔍 Добавлено изображение {idx}:")
                print(f"   image_url: {image_url}")
                print(f"   длина image_url: {len(str(image_url)) if image_url else 'None'}")
                print(f"   последний элемент media: {media[-1].media}")
                print(f"   длина media[-1].media: {len(str(media[-1].media)) if media[-1].media else 'None'}")
            else:
                # Ошибка при генерации
                logging.error(f"Ошибка генерации изображения {idx}: {error}")
                if send_text:
                    await send_text(f"❌ Ошибка при генерации изображения {idx}: {error}")

    # Удаляем старый последовательный код - он заменен на параллельный выше
    # Оставляем только обработку результатов
    if media and send_media:
        print(f"🔍 Попытка отправки media группы...")
        print(f"🔍 Количество изображений: {len(media)}")
        for i, item in enumerate(media):
            print(f"🔍 Изображение {i+1}: {item.media}")
            print(f"🔍 Длина URL: {len(str(item.media)) if item.media else 'None'}")
        
        try:
            # Пытаемся отправить как группу
            await send_media(media=media)
            print(f"✅ Media группа отправлена успешно")
        except Exception as group_error:
            print(f"❌ Ошибка отправки группы: {group_error}")
            # Если группа не отправляется, отправляем по одному
            for i, item in enumerate(media):
                try:
                    if hasattr(update, 'message') and update.message:
                        await update.message.reply_photo(photo=item.media, caption=item.caption)
                    else:
                        await context.bot.send_photo(chat_id=chat_id, photo=item.media, caption=item.caption)
                    print(f"✅ Изображение {i+1} отправлено отдельно")
                except Exception as photo_error:
                    print(f"❌ Ошибка отправки изображения {i+1}: {photo_error}")

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

        await analytics_db_log_generation_async(

            user_id=user_id,

            model_name=selected_model,

            format_type=format_type,

            prompt=state.get('topic', 'unknown'),

            image_count=processed_count,

            success=True,

            generation_time=generation_time

        )

        await analytics_db_log_action_async(user_id, "generation_success", f"count:{processed_count}, time:{generation_time:.1f}s")
        
        # Списываем кредиты или увеличиваем счетчик бесплатных генераций
        if generation_type == "free":
            # Списываем по количеству реально созданных изображений
            for i in range(processed_count):
                if await analytics_db_get_free_generations_left_async(user_id) > 0:
                    await analytics_db_increment_free_generations_async(user_id)
                else:
                    # Если бесплатные закончились, переключаемся на кредиты
                    generation_type = "credits"
                    break
    
            # Если переключились на кредиты, списываем их
            if generation_type == "credits":
                remaining_count = processed_count - i
                total_cost = generation_cost * remaining_count
                await analytics_db_use_credits_async(user_id, total_cost, f"Генерация {remaining_count} изображений через {selected_model}")
                logging.info(f"Пользователь {user_id} использовал {total_cost} кредитов за {remaining_count} изображений")
            else:
                logging.info(f"Пользователь {user_id} использовал {processed_count} бесплатных генераций")
        
        elif generation_type == "credits":
            # Списываем кредиты за каждое изображение
            total_cost = generation_cost * processed_count
            if await analytics_db_use_credits_async(user_id, total_cost, f"Генерация {processed_count} изображений через {selected_model}"):
                logging.info(f"Пользователь {user_id} использовал {total_cost} кредитов за {processed_count} изображений")
            else:
                logging.error(f"Ошибка списания кредитов для пользователя {user_id}")


    else:


        # Логируем неудачную генерацию

        await analytics_db_log_generation_async(

            user_id=user_id,

            model_name=selected_model,

            format_type=format_type,

            prompt=state.get('topic', 'unknown'),

            image_count=0,

            success=False,

            error_message="No images generated",

            generation_time=generation_time

        )

        await analytics_db_log_action_async(user_id, "generation_failed", f"time:{generation_time:.1f}s")

    

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

        await analytics_db_update_user_activity_async(user_id)

        await analytics_db_log_action_async(user_id, "view_stats_button")

        

        # Получаем статистику пользователя

        user_stats = await analytics_db_get_user_stats_async(user_id)

        

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

    # ОБРАБОТЧИКИ ДЛЯ КРЕДИТОВ

    elif data == "subscription_menu":

        await show_subscription_menu(update, context)

    elif data == "credit_packages":

        await show_credit_packages(update, context)

    elif data.startswith("buy_credits:"):

        await handle_credit_purchase(update, context)

    elif data.startswith("check_payment:"):

        await check_payment_status(update, context)

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

                [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")],

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

            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")],

            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]

        ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(

            f'Формат: {state.get("format", "")}\nВыберите ориентацию изображения:',

            reply_markup=reply_markup

        )

    elif data.startswith('simple_orientation:'):
        orientation = data.split(':', 1)[1]
        USER_STATE[user_id]['orientation'] = orientation
        USER_STATE[user_id]['step'] = 'image_gen_model'
        await show_model_selection(update, context)
        return

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

                    state = USER_STATE[user_id]

                    

                    keyboard = [

                        [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],

                        [InlineKeyboardButton("🔙 Назад", callback_data="simple_image_count_back")],

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

                        f"Количество выбрано: {count} изображений\n\nТеперь опишите, что вы хотите видеть на картинке:\n\n{tips}",

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

                    USER_STATE[user_id]['step'] = 'simple_image_prompt'

                    state = USER_STATE[user_id]

                    

                    keyboard = [

                        [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],

                        [InlineKeyboardButton("🔙 Назад", callback_data="simple_image_count_back")],

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

                        f"Количество выбрано: {count} изображений\n\nТеперь опишите, что вы хотите видеть на картинке:\n\n{tips}",

                        reply_markup=reply_markup

                    )

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

    elif data == "simple_image_count_back":

        # Возврат к выбору количества изображений для "Изображения"

        USER_STATE[user_id]['step'] = 'image_count_simple'

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

            [InlineKeyboardButton("🔙 Назад", callback_data="style_gen_back")],

            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]

        ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(

            f"Стиль генерации: {state.get('image_gen_style', '')}\nСколько изображений сгенерировать?",

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

    elif data == "generate_more":

        # Сброс состояния для генерации новых изображений

        USER_STATE[user_id] = {'step': 'main_menu'}

        await show_format_selection(update, context)

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



    # Обработчики для генерации видео проба

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

            [InlineKeyboardButton("🔄 Среднее (720p)", callback_data="video_quality:720p")],

            [InlineKeyboardButton("⭐ Качественное (1080p)", callback_data="video_quality:1080p")],

            [InlineKeyboardButton("🔙 Назад", callback_data="video_generation")]

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

            [InlineKeyboardButton("🔄 Среднее (720p)", callback_data="video_quality:720p")],

            [InlineKeyboardButton("⭐ Качественное (1080p)", callback_data="video_quality:1080p")],

            [InlineKeyboardButton("🔙 Назад", callback_data="video_generation")]

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

            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_video_quality")]

        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(

            f"🎬 **Качество выбрано: {quality}**\n\n"

            "Выберите длительность видео:",

            reply_markup=reply_markup

        )


    elif data == "back_to_video_quality":
        state['step'] = STEP_VIDEO_QUALITY
        keyboard = [
            [InlineKeyboardButton("⚡ Быстрое (480p)", callback_data="video_quality:480p")],
            [InlineKeyboardButton("🔄 Среднее (720p)", callback_data="video_quality:720p")],
            [InlineKeyboardButton("⭐ Качественное (1080p)", callback_data="video_quality:1080p")],
            [InlineKeyboardButton("🔙 Назад", callback_data="video_generation")]
        ]
        await query.edit_message_text(
            "Выберите качество видео:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("video_duration:"):

        # Обработка выбора длительности видео

        duration = int(data.split(":")[1])

        state['video_duration'] = duration

        state['step'] = 'waiting_for_aspect_ratio'

        

        # Запрашиваем выбор пропорции сторон

        keyboard = [

            [InlineKeyboardButton("📱 Instagram Stories/Reels (9:16)", callback_data="aspect_ratio:9:16")],

            [InlineKeyboardButton("📷 Instagram Post (1:1)", callback_data="aspect_ratio:1:1")],

            [InlineKeyboardButton("🖥️ YouTube/Обычное (16:9)", callback_data="aspect_ratio:16:9")],

            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main_options")]

        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(

            f"⏱️ **Длительность выбрана: {duration} сек**\n\n"

            "Выберите пропорцию сторон видео:",

            reply_markup=reply_markup

        )



    elif data.startswith("aspect_ratio:"):

        # Обработка выбора пропорции сторон

        aspect_ratio = data.split(":")[1] + ":" + data.split(":")[2]  # Получаем "9:16", "1:1", "16:9"

        state['aspect_ratio'] = aspect_ratio

        state['step'] = STEP_VIDEO_GENERATION

        

        # Запрашиваем промпт для видео

        if state.get('video_type') == 'text_to_video':

            await query.edit_message_text(

                "🎭 **Создание видео по тексту**\n\n"

                "Опишите, что должно происходить в видео:\n\n"

                "💡 Примеры:\n"

                "• Красивая природа с цветущими деревьями\n"

                "• Космический корабль летит среди звезд\n"

                "• Городской пейзаж с небоскребами\n\n"

                "🌐 **Ваш промпт будет автоматически переведен на английский для лучшего качества видео**",

                reply_markup=InlineKeyboardMarkup([[

                    InlineKeyboardButton("🔙 Назад", callback_data="back_to_main_options")

                ]])

            )

        else:

            # Для image-to-video переходим к загрузке изображения

            state['step'] = 'waiting_for_image'

            await query.edit_message_text(

                "🖼️ **Создание видео из изображения**\n\n"

                "Пожалуйста, загрузите изображение, из которого хотите создать видео.\n\n"

                "💡 Рекомендуется использовать качественные изображения в формате JPG или PNG.",

                reply_markup=InlineKeyboardMarkup([[

                    InlineKeyboardButton("🔙 Назад", callback_data="back_to_main_options")

                ]])

            )



    elif data == "video_text_to_video":

        # Прямая генерация видео по тексту из главного меню

        state['video_type'] = 'text_to_video'

        state['step'] = STEP_VIDEO_QUALITY

        keyboard = [

            [InlineKeyboardButton("⚡ Быстрое (480p)", callback_data="video_quality:480p")],

            [InlineKeyboardButton("🔄 Среднее (720p)", callback_data="video_quality:720p")],

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

            [InlineKeyboardButton("🔄 Среднее (720p)", callback_data="video_quality:720p")],

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



    # Новые обработчики для контроля качества промптов

    elif data == "enhance_prompt":

        # Пользователь хочет улучшить промпт

        await show_enhanced_prompt(update, context, state)

        return

        

    elif data == "generate_as_is":

        # Пользователь хочет генерировать с простым переводом

        # Запускаем генерацию видео в фоне
        asyncio.create_task(generate_video_async(update, context, state))
        
        # Отправляем уведомление о начале обработки
        if hasattr(update, 'callback_query') and update.callback_query:
            chat_id = update.callback_query.message.chat_id
        elif hasattr(update, 'message') and update.message:
            chat_id = update.message.chat_id
        else:
            return
            
        await context.bot.send_message(
            chat_id=chat_id,
            text="🎬 **Видео в обработке...**\n\nГенерация может занять несколько минут. Вы получите уведомление, когда видео будет готово!"
        )

        return

        

    elif data == "use_enhanced":

        # Пользователь выбрал улучшенный промпт

        # Запускаем генерацию видео в фоне
        asyncio.create_task(generate_video_async(update, context, state))
        
        # Отправляем уведомление о начале обработки
        if hasattr(update, 'callback_query') and update.callback_query:
            chat_id = update.callback_query.message.chat_id
        elif hasattr(update, 'message') and update.message:
            chat_id = update.message.chat_id
        else:
            return
            
        await context.bot.send_message(
            chat_id=chat_id,
            text="🎬 **Видео в обработке...**\n\nГенерация может занять несколько минут. Вы получите уведомление, когда видео будет готово!"
        )

        return

        

    elif data == "show_another_enhancement":

        # Пользователь хочет другой вариант улучшения

        enhancement_attempt = state.get('enhancement_attempt', 1) + 1

        if enhancement_attempt <= 3:  # Максимум 3 попытки

            state['enhancement_attempt'] = enhancement_attempt

            await show_enhanced_prompt(update, context, state)

        else:

            # Показываем сообщение о достижении лимита

            keyboard = [

                [InlineKeyboardButton("✅ Использовать текущий", callback_data="use_enhanced")],

                [InlineKeyboardButton("❌ Вернуться к простому", callback_data="use_simple")]

            ]

            state['enhancement_attempt'] = enhancement_attempt  # Обновляем счетчик в состоянии

            await query.edit_message_text(

                "🔄 **Достигнут лимит попыток улучшения**\n\n"

                "Вы можете:\n"

                "• Использовать текущий улучшенный промпт\n"

                "• Вернуться к простому переводу",

                reply_markup=InlineKeyboardMarkup(keyboard)

            )

        return

        

    elif data == "use_simple":

        # Пользователь хочет вернуться к простому переводу

        if 'enhanced_prompt' in state:

            del state['enhanced_prompt']  # Убираем улучшенный промпт

        # Запускаем генерацию видео в фоне
        asyncio.create_task(generate_video_async(update, context, state))
        
        # Отправляем уведомление о начале обработки
        if hasattr(update, 'callback_query') and update.callback_query:
            chat_id = update.callback_query.message.chat_id
        elif hasattr(update, 'message') and update.message:
            chat_id = update.message.chat_id
        else:
            return
            
        await context.bot.send_message(
            chat_id=chat_id,
            text="🎬 **Видео в обработке...**\n\nГенерация может занять несколько минут. Вы получите уведомление, когда видео будет готово!"
        )

        return





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

            USER_STATE[user_id]['step'] = 'image_count_simple'

            state = USER_STATE[user_id]

            

            # Предлагаем выбрать количество изображений

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

            # Используем асинхронный вызов для предотвращения блокировки
            loop = asyncio.get_event_loop()
            messages = [
                        {"role": "system", "content": "Ты эксперт по созданию уникального контента для социальных сетей. Твоя задача - создавать качественный, нешаблонный контент, который точно описывает тему и привлекает внимание. Избегай общих фраз, используй конкретные детали."},
                        {"role": "user", "content": content_prompt}
            ]
            gpt_reply = await openai_chat_completion_async(messages, "gpt-4o-mini", 1000, 0.8)

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

    elif step == 'simple_image_count_selection':

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

            await update.message.reply_text("Пожалуйста, введите корректное число:")

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

    elif step == 'image_count_simple':

        try:

            count = int(update.message.text.strip())

            if 1 <= count <= 10:

                USER_STATE[user_id]['image_count'] = count

                USER_STATE[user_id]['step'] = 'simple_image_prompt'

                keyboard = [

                    [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],

                    [InlineKeyboardButton("🔙 Назад", callback_data="simple_image_prompt_back")],

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

                

                await update.message.reply_text(

                    f"Количество выбрано: {count} изображений\n\nТеперь опишите, что вы хотите видеть на картинке:\n\n{tips}",

                    reply_markup=reply_markup

                )

            else:

                await update.message.reply_text("Пожалуйста, введите число от 1 до 10:")

        except ValueError:

            await update.message.reply_text("Пожалуйста, введите корректное число:")

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

        

        # Сохраняем промпт и показываем рецензию

        state['video_prompt'] = video_prompt

        await show_prompt_review(update, context, state)

    

    elif step == 'waiting_for_video_prompt':

        # Обработка промпта для генерации видео из изображения

        video_prompt = update.message.text.strip()

        

        if not video_prompt:

            await update.message.reply_text(

                "❌ **Ошибка!**\n\n"

                "Пожалуйста, опишите, какое видео вы хотите получить из изображения.",

                reply_markup=InlineKeyboardMarkup([[

                    InlineKeyboardButton("🔙 Назад", callback_data="back_to_main_options")

                ]])

            )

            return

        

        # Сохраняем промпт в состоянии

        state['video_prompt'] = video_prompt

        

        # Показываем рецензию промптов

        await show_prompt_review(update, context, state)

    

    elif step == 'waiting_for_image':

        # Обработка загрузки изображения для генерации видео

        if update.message.photo:

            # Получаем URL изображения

            photo = update.message.photo[-1]  # Берем самое большое изображение

            file = await context.bot.get_file(photo.file_id)

            image_url = file.file_path

            

            # Сохраняем URL изображения в состоянии

            state['selected_image_url'] = image_url

            

            # Переходим к запросу промпта для видео

            state['step'] = 'waiting_for_video_prompt'

            

            # Показываем сообщение о получении изображения и запрашиваем промпт

            await update.message.reply_text(

                "🖼️ **Изображение получено!**\n\n"

                "📝 **Теперь опишите, какое видео вы хотите получить из этого изображения:**\n\n"

                "💡 **Примеры промптов:**\n"

                "• \"Добавить движение и анимацию\"\n"

                "• \"Сделать изображение живым с эффектами\"\n"

                "• \"Добавить камеру и переходы\"\n"

                "• \"Создать динамичную сцену\"\n"

                "• \"Добавить элементы движения\"\n\n"

                "🎬 **После описания начнется генерация видео**\n\n"

                "⚠️ **Важно:** Чем подробнее описание, тем лучше результат!",

                reply_markup=InlineKeyboardMarkup([[

                    InlineKeyboardButton("🔙 Назад", callback_data="back_to_main_options")

                ]])

            )

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

                USER_STATE[user_id]['step'] = 'simple_image_prompt'

                keyboard = [

                    [InlineKeyboardButton("❓ Как пользоваться", callback_data="how_to_use")],

                    [InlineKeyboardButton("🔙 Назад", callback_data="simple_image_count_back")],

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

                

                await update.message.reply_text(

                    f"Количество выбрано: {count} изображений\n\nТеперь опишите, что вы хотите видеть на картинке:\n\n{tips}",

                    reply_markup=reply_markup

                )

            else:

                await update.message.reply_text("Пожалуйста, введите число от 1 до 10:")

        except ValueError:

            await update.message.reply_text("Пожалуйста, введите число от 1 до 10:")

    elif step == STEP_DONE:

        # Обработка для завершенного состояния

        # Если пользователь что-то написал в состоянии STEP_DONE, 

        # это может означать, что он хочет сгенерировать что-то еще

        user_text = update.message.text.strip()

        

        # Проверяем, не хочет ли пользователь сгенерировать еще изображения

        if user_text.lower() in ['еще', 'ещё', 'снова', 'повтори', 'еще раз', 'ещё раз']:

            # Сбрасываем состояние и возвращаемся к выбору формата

            USER_STATE[user_id] = {'step': 'main_menu'}

            await show_format_selection(update, context)

        else:

            # Если пользователь написал что-то другое, предлагаем варианты

            keyboard = [

                [InlineKeyboardButton("🔄 Сгенерировать еще", callback_data="generate_more")],

                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]

            ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(

                "Если хотите сгенерировать еще изображения, нажмите 'Сгенерировать еще' или вернитесь в главное меню.",

                reply_markup=reply_markup

            )

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

            # Используем асинхронный вызов для предотвращения блокировки
            loop = asyncio.get_event_loop()
            messages = [
                        {"role": "system", "content": "Ты - эксперт по редактированию изображений. Переведи запрос на редактирование с русского на английский и улучши его для FLUX.1 Kontext Pro. Используй конкретные, детальные инструкции. Сохрани точный смысл. Отвечай только улучшенным переводом."},
                        {"role": "user", "content": f"Переведи и улучши для редактирования изображения: {edit_prompt}"}
            ]
            english_prompt = await openai_chat_completion_async(messages, "gpt-4o-mini", 200, 0.1)

            

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



async def show_prompt_review(update, context, state):

    """Показывает промпты на рецензию пользователю"""

    try:

        # Получаем параметры из состояния

        video_type = state.get('video_type', 'text_to_video')

        video_prompt = state.get('video_prompt', '')

        english_prompt = state.get('english_prompt', '')

        

        if not english_prompt:

            # Если переведенный промпт еще не готов, переводим

            try:

                import openai

                client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

                # Используем асинхронный вызов для предотвращения блокировки
                loop = asyncio.get_event_loop()
                messages = [
                            {"role": "system", "content": "Translate the user's request from Russian to English. Keep the exact meaning and do not add extra details. If the original is short, keep it short."},
                            {"role": "user", "content": f"Translate this prompt: {video_prompt}"}
                ]
                english_prompt = await openai_chat_completion_async(messages, "gpt-4o-mini", 150, 0.1)

                # Сохраняем в состояние

                state['english_prompt'] = english_prompt

                

                # Логируем оба промпта для прозрачности

                logging.info(f"Original Russian prompt: {video_prompt}")

                logging.info(f"Translated English prompt: {english_prompt}")

                

            except Exception as e:

                logging.error(f"Translation failed: {e}, using original prompt")

                english_prompt = video_prompt

                state['english_prompt'] = english_prompt

        

        # Формируем текст для показа

        if video_type == 'text_to_video':

            prompt_text = f"📝 **Оригинальный промпт:** {video_prompt}\n🌐 **Переведенный промпт:** {english_prompt}"

        else:  # image_to_video

            prompt_text = f"🖼️ **Изображение:** загружено\n📝 **Промпт:** {video_prompt}\n🌐 **Переведенный промпт:** {english_prompt}"

        

        # Создаем клавиатуру с выбором

        keyboard = [

            [

                InlineKeyboardButton("✅ Да, улучшить промпт", callback_data="enhance_prompt"),

                InlineKeyboardButton("❌ Нет, генерировать как есть", callback_data="generate_as_is")

            ]

        ]

        

        # Отправляем сообщение с выбором

        if hasattr(update, 'callback_query') and update.callback_query:

            await update.callback_query.edit_message_text(

                f"🎬 **Готов к генерации видео!**\n\n"

                f"{prompt_text}\n\n"

                f"❓ **Хотите ли вы добавить детали к промпту?**\n\n"

                f"Это может улучшить качество видео, но изменит исходный замысел.",

                reply_markup=InlineKeyboardMarkup(keyboard)

            )

        else:

            await update.message.reply_text(

                f"🎬 **Готов к генерации видео!**\n\n"

                f"{prompt_text}\n\n"

                f"❓ **Хотите ли вы добавить детали к промпту?**\n\n"

                f"Это может улучшить качество видео, но изменит исходный замысел.",

                reply_markup=InlineKeyboardMarkup(keyboard)

            )

        

        # Устанавливаем состояние для ожидания выбора

        state['current_step'] = STEP_PROMPT_REVIEW

        state['enhancement_attempt'] = 1  # Инициализируем счетчик попыток улучшения

        

    except Exception as e:

        logging.error(f"Error in show_prompt_review: {e}")

        # Fallback к прямой генерации

        # Запускаем генерацию видео в фоне
        asyncio.create_task(generate_video_async(update, context, state))
        
        # Отправляем уведомление о начале обработки
        if hasattr(update, 'callback_query') and update.callback_query:
            chat_id = update.callback_query.message.chat_id
        elif hasattr(update, 'message') and update.message:
            chat_id = update.message.chat_id
        else:
            return
            
        await context.bot.send_message(
            chat_id=chat_id,
            text="🎬 **Видео в обработке...**\n\nГенерация может занять несколько минут. Вы получите уведомление, когда видео будет готово!"
        )



async def enhance_prompt_with_gpt(original_prompt, english_prompt, attempt=1):

    """Улучшает промпт с помощью GPT"""

    try:

        import openai

        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        

        # Системный промпт для улучшения

        system_content = f"""You are an expert at creating video generation prompts. 

The user has provided a simple prompt that was translated from Russian to English.

Your task is to enhance it for better video generation results while maintaining the core concept.



Original Russian: {original_prompt}

Current English: {english_prompt}



Enhance the English prompt by adding visual details, scene context, and cinematic elements.

Make it more descriptive and specific for AI video models.

This is attempt #{attempt} - if this is a retry, make it different from previous attempts.



Focus on:

- Visual elements and composition

- Movement and action details

- Scene atmosphere and mood

- Camera angles and perspectives



Keep the enhancement reasonable and don't add completely new elements not implied by the original."""

        

        # Используем асинхронный вызов для предотвращения блокировки
        loop = asyncio.get_event_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(THREAD_POOL, lambda: client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": f"Enhance this prompt for video generation: {english_prompt}"}
                ],
                max_tokens=200,
                temperature=0.7
            )),
            timeout=30.0
        )

        

        enhanced_prompt = response.choices[0].message.content.strip()

        logging.info(f"Enhanced prompt (attempt {attempt}): {enhanced_prompt}")

        

        return enhanced_prompt

        

    except Exception as e:

        logging.error(f"Error enhancing prompt: {e}")

        return english_prompt  # Fallback к оригинальному переводу



async def show_enhanced_prompt(update, context, state):

    """Показывает улучшенный промпт пользователю"""

    try:

        video_prompt = state.get('video_prompt', '')

        english_prompt = state.get('english_prompt', '')

        enhancement_attempt = state.get('enhancement_attempt', 1)

        

        # Улучшаем промпт

        enhanced_prompt = await enhance_prompt_with_gpt(video_prompt, english_prompt, enhancement_attempt)

        state['enhanced_prompt'] = enhanced_prompt

        state['enhancement_attempt'] = enhancement_attempt  # Обновляем счетчик в состоянии

        

        # Формируем текст для показа

        prompt_text = f"📝 **Оригинальный промпт:** {video_prompt}\n🌐 **Переведенный промпт:** {english_prompt}\n✨ **Улучшенный промпт:** {enhanced_prompt}"

        

        # Создаем клавиатуру с выбором

        keyboard = [

            [

                InlineKeyboardButton("✅ Использовать улучшенный", callback_data="use_enhanced"),

                InlineKeyboardButton("🔄 Показать другой вариант", callback_data="show_another_enhancement")

            ],

            [

                InlineKeyboardButton("❌ Вернуться к простому", callback_data="use_simple")

            ]

        ]

        

        # Отправляем сообщение с улучшенным промптом

        if hasattr(update, 'callback_query') and update.callback_query:

            await update.callback_query.edit_message_text(

                f"🔧 **Улучшение промпта**\n\n"

                f"{prompt_text}\n\n"

                f"❓ **Нравится ли вам улучшенная версия?**",

                reply_markup=InlineKeyboardMarkup(keyboard)

            )

        else:

            await update.message.reply_text(

                f"🔧 **Улучшение промпта**\n\n"

                f"{prompt_text}\n\n"

                f"❓ **Нравится ли вам улучшенная версия?**",

                reply_markup=InlineKeyboardMarkup(keyboard)

            )

        

        # Устанавливаем состояние для ожидания выбора

        state['current_step'] = STEP_PROMPT_ENHANCEMENT

        

    except Exception as e:

        logging.error(f"Error in show_enhanced_prompt: {e}")

        # Fallback к прямой генерации

        # Запускаем генерацию видео в фоне
        asyncio.create_task(generate_video_async(update, context, state))
        
        # Отправляем уведомление о начале обработки
        if hasattr(update, 'callback_query') and update.callback_query:
            chat_id = update.callback_query.message.chat_id
        elif hasattr(update, 'message') and update.message:
            chat_id = update.message.chat_id
        else:
            return
            
        await context.bot.send_message(
            chat_id=chat_id,
            text="🎬 **Видео в обработке...**\n\nГенерация может занять несколько минут. Вы получите уведомление, когда видео будет готово!"
        )



async def generate_video_async(update, context, state):
    """Асинхронная обертка для генерации видео"""
    try:
        await generate_video(update, context, state)
    except Exception as e:
        logging.error(f"Ошибка в асинхронной генерации видео: {e}")
        # Отправляем сообщение об ошибке пользователю
        if hasattr(update, 'callback_query') and update.callback_query:
            chat_id = update.callback_query.message.chat_id
        elif hasattr(update, 'message') and update.message:
            chat_id = update.message.chat_id
        else:
            return
            
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ **Ошибка при генерации видео**\n\nПопробуйте еще раз или обратитесь в поддержку."
        )

async def generate_video(update, context, state):

    """Генерирует видео с помощью Replicate API"""

    # Определяем chat_id и user_id

    if hasattr(update, 'callback_query') and update.callback_query:

        chat_id = update.callback_query.message.chat_id

        user_id = update.callback_query.from_user.id

    elif hasattr(update, 'message') and update.message:

        chat_id = update.message.chat_id

        user_id = update.message.from_user.id

    else:

        # Fallback

        chat_id = None

        user_id = None

    

    if not chat_id or not user_id:

        logging.error("Не удалось определить chat_id или user_id")

        return

    # Проверяем доступ к видео (только за кредиты)
    free_generations_left = await analytics_db_get_free_generations_left_async(user_id)
    user_credits = await analytics_db_get_user_credits_async(user_id)

    # Получаем параметры видео для расчета стоимости
    video_type = state.get('video_type', 'text_to_video')
    video_quality = state.get('video_quality', '480p')
    video_duration = state.get('video_duration', 5)
    
    # Рассчитываем стоимость видео
    video_cost = 0
    if video_duration == 5:
        if video_quality == "480p":
            video_cost = 37
        elif video_quality == "720p":
            video_cost = 71
        elif video_quality == "1080p":
            video_cost = 172
    elif video_duration == 10:
        if video_quality == "480p":
            video_cost = 71
        elif video_quality == "720p":
            video_cost = 138
        elif video_quality == "1080p":
            video_cost = 342
    else:
        video_cost = 37  # Базовая цена для других длительностей

    # Видео доступно только за кредиты, НЕ за бесплатные генерации
    if user_credits['balance'] < video_cost:
        # Нет кредитов - доступ к видео заблокирован
        keyboard = [
            [InlineKeyboardButton("🪙 Купить кредиты", callback_data="credit_packages")],
            [InlineKeyboardButton("🖼️ Создать изображения", callback_data="create_content")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ **Недостаточно кредитов для видео!**\n\n"
                 f"🎬 **Выбранное видео:**\n"
                 f"• Качество: {video_quality}\n"
                 f"• Длительность: {video_duration} сек\n"
                 f"• Стоимость: {video_cost} кредитов\n\n"
                 f"🪙 **Ваш баланс:** {user_credits['balance']} кредитов\n"
                 f"❌ **Недостаточно:** {video_cost - user_credits['balance']} кредитов\n\n"
                 "💡 **Что доступно бесплатно:**\n"
                 "• 🖼️ Создание изображений (3 раза)\n"
                 "• ✏️ Редактирование изображений (3 раза)\n\n"
                 "💰 **Для видео нужны кредиты:**\n"
                 "• Купите кредиты для доступа к видео\n"
                 "• Видео от 37 кредитов за 5 секунд",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        # Сбрасываем состояние
        state['step'] = None
        state.pop('video_type', None)
        state.pop('video_quality', None)
        state.pop('video_duration', None)
        state.pop('video_prompt', None)
        return

    try:

        # Получаем параметры из состояния

        video_type = state.get('video_type', 'text_to_video')

        video_quality = state.get('video_quality', '480p')

        video_duration = state.get('video_duration', 5)

        video_prompt = state.get('video_prompt', '')

        

        # Получаем переведенный промпт из состояния (должен быть уже готов)

        english_prompt = state.get('english_prompt', video_prompt)

        

        # Определяем параметры для модели

        if video_type == 'text_to_video':

            # Для text-to-video используем промпт из состояния

            if not video_prompt:

                # Если промпт не задан, это ошибка - пользователь должен был его ввести

                logging.error(f"video_prompt не задан для text-to-video. State: {state}")

                raise Exception("Промпт для видео не задан. Пожалуйста, попробуйте еще раз.")

            

            # Проверяем, есть ли улучшенный промпт

            if 'enhanced_prompt' in state:

                english_prompt = state['enhanced_prompt']

                logging.info(f"Using enhanced prompt: {english_prompt}")

            elif english_prompt != video_prompt:

                logging.info(f"Using translated prompt: {english_prompt}")

            else:

                logging.info(f"Using original prompt: {english_prompt}")

            

            # Параметры для text-to-video с переведенным промптом

            input_data = {

                "prompt": english_prompt,

                "duration": video_duration,

                "resolution": video_quality,

                "aspect_ratio": state.get('aspect_ratio', '16:9'),

                "camera_fixed": False,

                "fps": 24

            }

        else:

            # Для image-to-video нужен URL изображения И промпт

            # Проверяем, есть ли изображение в состоянии

            if 'selected_image_url' not in state:

                # Если изображение не выбрано, это ошибка - пользователь должен был его загрузить

                logging.error(f"selected_image_url не задан для image-to-video. State: {state}")

                raise Exception("Изображение для видео не загружено. Пожалуйста, попробуйте еще раз.")

            

            # Проверяем, есть ли промпт для image-to-video

            if not video_prompt:

                # Если промпт не задан, это ошибка - пользователь должен был его ввести

                logging.error(f"video_prompt не задан для image-to-video. State: {state}")

                raise Exception("Промпт для видео не задан. Пожалуйста, опишите, какое видео вы хотите получить из изображения.")

            

            # Проверяем, есть ли улучшенный промпт

            if 'enhanced_prompt' in state:

                english_prompt = state['enhanced_prompt']

                logging.info(f"Using enhanced prompt for image-to-video: {english_prompt}")

            elif english_prompt != video_prompt:

                logging.info(f"Using translated prompt for image-to-video: {english_prompt}")

            else:

                logging.info(f"Using original prompt for image-to-video: {english_prompt}")

            

            # Параметры для image-to-video с промптом

            input_data = {

                "image": state['selected_image_url'],

                "prompt": english_prompt,  # Добавляем промпт для image-to-video

                "duration": video_duration,

                "resolution": video_quality,

                "aspect_ratio": state.get('aspect_ratio', '16:9'),

                "camera_fixed": False,

                "fps": 24

            }

        

        # Отправляем сообщение о начале генерации

        if video_type == 'text_to_video' and video_prompt:

            # Показываем оба промпта для прозрачности

            prompt_text = f"📝 Оригинальный промпт: {video_prompt}\n🌐 Переведенный промпт: {english_prompt}"

        elif video_type == 'image_to_video' and video_prompt:

            # Показываем промпт для image-to-video

            prompt_text = f"🖼️ Изображение: загружено\n📝 Промпт: {video_prompt}\n🌐 Переведенный промпт: {english_prompt}"

        else:

            # Fallback для случаев, когда что-то пошло не так

            if video_type == 'image_to_video':

                prompt_text = "🖼️ Изображение: загружено\n⚠️ Промпт не указан"

            else:

                prompt_text = "🖼️ Изображение: загружено"

        

        # Предупреждаем о возможных проблемах с размером и стоимости

        size_warning = ""

        if video_quality == "1080p" and video_duration > 5:

            size_warning = "\n⚠️ **Внимание:** Видео 1080p длительностью более 5 сек может быть слишком большим для прямой отправки в Telegram.\n"

        elif video_duration > 10:

            size_warning = "\n⚠️ **Внимание:** Длинные видео могут превышать лимиты Telegram (50 МБ).\n"

        

        # Добавляем информацию о стоимости

        cost_info = ""

        

        if hasattr(update, 'callback_query') and update.callback_query:

            await update.callback_query.edit_message_text(

                f"🎬 **Генерация видео началась!**\n\n"

                f"{prompt_text}\n"

                f"⚡ Качество: {video_quality}\n"

                f"⏱️ Длительность: {video_duration} сек\n\n"

                f"⏳ Пожалуйста, подождите...\n"

                f"Это может занять 1-3 минуты.{size_warning}{cost_info}",

                reply_markup=InlineKeyboardMarkup([[

                    InlineKeyboardButton("⏳ Генерация...", callback_data="waiting")

                ]])

            )

        else:

            # Если это не callback_query (например, загрузка изображения)

            await update.message.reply_text(

                f"🎬 **Генерация видео началась!**\n\n"

                f"{prompt_text}\n"

                f"⚡ Качество: {video_quality}\n"

                f"⏱️ Длительность: {video_duration} сек\n\n"

                f"⏳ Пожалуйста, подождите...\n"

                f"Это может занять 1-3 минуты.{size_warning}{cost_info}"

            )

        

        # Проверяем кредиты Replicate перед генерацией

        try:

            logging.info("Проверяем доступность Replicate API...")

            # Простая проверка через тестовый запрос

            loop = asyncio.get_event_loop()
            test_output = await asyncio.wait_for(
                loop.run_in_executor(THREAD_POOL, lambda: replicate.run(
                    "replicate/hello-world",
                    input={"text": "test"}
                )),
                timeout=30.0  # 30 секунд для теста
            )

            logging.info("Replicate API доступен")

        except Exception as credit_check_error:

            error_str = str(credit_check_error).lower()

            if "insufficient credit" in error_str or "insufficient_credit" in error_str:

                logging.error("Недостаточно кредитов на Replicate")

                # Отправляем сообщение о недостатке кредитов

                keyboard = [

                    [InlineKeyboardButton("💰 Пополнить баланс", url="https://replicate.com/account/billing")],

                    [InlineKeyboardButton("🖼️ Создать изображения", callback_data="create_content")],

                    [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]

                ]

                reply_markup = InlineKeyboardMarkup(keyboard)

                

                await context.bot.send_message(

                    chat_id=chat_id,

                    text="💳 **Недостаточно кредитов для генерации видео**\n\n"

                         "❌ **Причина:** На аккаунте Replicate закончились кредиты\n\n"

                         "💡 **Решения:**\n"

                         "• Пополните баланс на https://replicate.com/account/billing\n"

                         "• Подождите несколько минут после пополнения\n"

                         "• Попробуйте создать видео позже\n\n"

                         "🔄 **Альтернативы:**\n"

                         "• Создайте изображения вместо видео (бесплатно)\n"

                         "• Используйте другие функции бота\n"

                         "• Обратитесь к администратору для пополнения\n\n"

                         "💰 **Стоимость:** Генерация видео стоит кредиты Replicate",

                    reply_markup=reply_markup,

                    parse_mode='Markdown'

                )

                

                # Сбрасываем состояние

                state['step'] = None

                state.pop('video_type', None)

                state.pop('video_quality', None)

                state.pop('video_duration', None)

                state.pop('video_prompt', None)

                return

            else:

                logging.warning(f"Проблема с Replicate API: {credit_check_error}")

                # Продолжаем попытку генерации

        

        # Вызываем Replicate API для генерации видео

        import replicate

        

        # Логируем параметры API для диагностики

        logging.info(f"🎬 Отправляем запрос к Replicate API:")

        logging.info(f"   Модель: bytedance/seedance-1-pro")

        logging.info(f"   Параметры: {input_data}")

        logging.info(f"   Тип видео: {video_type}")

        logging.info(f"   Качество: {video_quality}")

        logging.info(f"   Длительность: {video_duration}")

        logging.info(f"   Aspect ratio: {state.get('aspect_ratio', 'не указан')}")

        

        # Создаем минимальный набор параметров для сравнения

        minimal_input = {"prompt": english_prompt}

        if video_type == 'image_to_video':

            minimal_input["image"] = state['selected_image_url']

        

        logging.info(f"🔍 Минимальные параметры для сравнения: {minimal_input}")

        

        # Валидация параметров

        logging.info(f"🔍 Валидация параметров:")

        logging.info(f"   duration: {video_duration} (тип: {type(video_duration)})")

        logging.info(f"   resolution: {video_quality} (тип: {type(video_quality)})")

        logging.info(f"   aspect_ratio: {state.get('aspect_ratio', 'не указан')} (тип: {type(state.get('aspect_ratio'))})")

        logging.info(f"   camera_fixed: False (тип: {type(False)})")

        logging.info(f"   fps: 24 (тип: {type(24)})")

        

        # Проверяем, что параметры соответствуют ожидаемым типам

        if not isinstance(video_duration, int):

            logging.warning(f"⚠️ duration должен быть int, получен: {type(video_duration)}")

        if not isinstance(video_quality, str):

            logging.warning(f"⚠️ resolution должен быть str, получен: {type(video_quality)}")

        if state.get('aspect_ratio') and not isinstance(state.get('aspect_ratio'), str):

            logging.warning(f"⚠️ aspect_ratio должен быть str, получен: {type(state.get('aspect_ratio'))}")

        

        try:

            # Используем модель Bytedance Seedance 1.0 Pro

            logging.info(f"🚀 Вызываем API с полными параметрами...")

            loop = asyncio.get_event_loop()
            output = await asyncio.wait_for(
                loop.run_in_executor(THREAD_POOL, lambda: replicate.run(
                    "bytedance/seedance-1-pro",
                    input=input_data
                )),
                timeout=300.0  # 5 минут для видео
            )

            

            # Если output - это асинхронный объект, дожидаемся результата

            if hasattr(output, '__await__'):

                logging.info("Получен асинхронный результат, ожидаем...")

                output = await output

                

        except Exception as replicate_error:

            logging.error(f"❌ Ошибка Replicate API: {replicate_error}")

            

            # Попробуем с минимальными параметрами

            logging.info(f"🔄 Пробуем с минимальными параметрами...")

            try:

                output = await asyncio.wait_for(
                    loop.run_in_executor(THREAD_POOL, lambda: replicate.run(
                        "bytedance/seedance-1-pro",
                        input=minimal_input
                    )),
                    timeout=300.0  # 5 минут для видео
                )

                logging.info(f"✅ Минимальные параметры сработали!")

                

                # Если output - это асинхронный объект, дожидаемся результата

                if hasattr(output, '__await__'):

                    logging.info("Получен асинхронный результат, ожидаем...")

                    output = await output

                    

            except Exception as minimal_error:

                logging.error(f"❌ Минимальные параметры тоже не сработали: {minimal_error}")

                raise Exception(f"Ошибка API Replicate: {str(replicate_error)}")

        

        # Обрабатываем результат от Replicate API

        # output может быть списком, строкой или объектом FileOutput

        logging.info(f"🎬 Replicate API вернул результат:")

        logging.info(f"   Тип: {type(output)}")

        logging.info(f"   Значение: {output}")

        logging.info(f"   Длина (если список): {len(output) if isinstance(output, list) else 'N/A'}")

        

        # Детальная диагностика объекта

        if hasattr(output, '__dict__'):

            logging.info(f"   Атрибуты объекта: {output.__dict__}")

        if hasattr(output, 'url'):

            logging.info(f"   Метод .url(): {output.url}")

        if hasattr(output, 'file_path'):

            logging.info(f"   Метод .file_path: {output.file_path}")

        

        if output:

            # Если output - это список, берем первый элемент

            if isinstance(output, list) and len(output) > 0:

                video_url = output[0]

                logging.info(f"Получен URL из списка: {video_url}")

            # Если output - это строка (прямой URL)

            elif isinstance(output, str):

                video_url = output

                logging.info(f"Получен URL строкой: {video_url}")

            # Если output - это объект FileOutput

            elif hasattr(output, 'url'):

                video_url = output.url

                logging.info(f"Получен URL из объекта.url: {video_url}")

            # Если output - это объект с атрибутом file_path

            elif hasattr(output, 'file_path'):

                video_url = output.file_path

                logging.info(f"Получен URL из объекта.file_path: {video_url}")

            else:

                # Пытаемся преобразовать в строку

                video_url = str(output)

                logging.info(f"Преобразован в строку: {video_url}")

        else:

            raise Exception("API не вернул результат")

        

        # Проверяем, что получили валидный URL

        if not video_url or not isinstance(video_url, str):

            raise Exception(f"Получен невалидный URL: {video_url}")

        

        logging.info(f"Финальный URL для видео: {video_url}")

        

        # Проверяем расширение файла для определения формата

        file_extension = video_url.split('.')[-1].lower() if '.' in video_url else ''

        logging.info(f"🎬 Анализ файла:")

        logging.info(f"   URL: {video_url}")

        logging.info(f"   Расширение: {file_extension}")

        logging.info(f"   Содержит 'gif' в URL: {'gif' in video_url.lower()}")

        logging.info(f"   Содержит 'mp4' в URL: {'mp4' in video_url.lower()}")

        

        # Определяем, является ли файл видео

        video_extensions = ['mp4', 'avi', 'mov', 'wmv', 'flv', 'webm', 'mkv', 'm4v']

        is_video_file = file_extension in video_extensions

        logging.info(f"   Расширение видео: {is_video_file}")

        

        # Дополнительная проверка: если URL содержит 'gif', то это не видео

        if 'gif' in video_url.lower():

            is_video_file = False

            logging.warning("⚠️ Обнаружен GIF файл в URL! API вернул GIF вместо MP4!")

        elif 'mp4' in video_url.lower():

            logging.info("✅ Обнаружен MP4 файл в URL")

        else:

            logging.warning(f"⚠️ Неизвестный формат файла: {file_extension}")

        

        # Проверяем доступность файла перед отправкой

        try:

            logging.info("🔍 Проверяем доступность файла...")

            async with aiohttp.ClientSession() as session:
                async with session.head(video_url, timeout=aiohttp.ClientTimeout(total=30)) as head_response:
                    if head_response.status != 200:
                        logging.warning(f"Файл недоступен (статус: {head_response.status})")
                        # Продолжаем попытку отправки, возможно это временная проблема
                    else:
                        # Анализируем заголовки для определения типа файла
                        content_type = head_response.headers.get('content-type', 'unknown')
                        content_length = head_response.headers.get('content-length')

                

                logging.info(f"🔍 HTTP заголовки файла:")

                logging.info(f"   Content-Type: {content_type}")

                logging.info(f"   Content-Length: {content_length}")

                

                # Проверяем, что говорит сервер о типе файла

                if 'gif' in content_type.lower():

                    logging.warning("⚠️ Сервер говорит, что это GIF файл!")

                elif 'mp4' in content_type.lower() or 'video' in content_type.lower():

                    logging.info("✅ Сервер говорит, что это видео файл")

                else:

                    logging.warning(f"⚠️ Неизвестный Content-Type: {content_type}")

                

                if content_length:

                    file_size_mb = int(content_length) / (1024 * 1024)

                    logging.info(f"   Размер файла: {file_size_mb:.1f} МБ")

                    

                    # Предупреждаем о больших файлах

                    if file_size_mb > 50:

                        logging.warning(f"Файл превышает лимит Telegram: {file_size_mb:.1f} МБ")

                    elif file_size_mb > 20:

                        logging.info(f"Файл большой: {file_size_mb:.1f} МБ, могут быть проблемы с отправкой")

        except Exception as check_error:

            logging.warning(f"Не удалось проверить файл: {check_error}")

            # Продолжаем попытку отправки

        

        # Дополнительная проверка: если файл недоступен, отправляем сообщение с ссылкой

        try:

            async with aiohttp.ClientSession() as session:
                async with session.get(video_url, timeout=aiohttp.ClientTimeout(total=10)) as test_response:
                    if test_response.status != 200:

                        logging.error(f"Файл недоступен для скачивания (статус: {test_response.status})")
                        
                        # Отправляем сообщение с инструкциями
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"⚠️ **Файл недоступен для скачивания**\n\n"
                                 f"Статус: {test_response.status}\n"
                                 f"Возможно, файл был удален или недоступен\n\n"
                                 f"🔗 **Попробуйте ссылку:** {video_url}\n\n"
                                 f"💡 **Рекомендации:**\n"
                                 f"• Скопируйте ссылку в браузер\n"
                                 f"• Попробуйте позже\n"
                                 f"• Создайте новое видео",
                            reply_markup=InlineKeyboardMarkup([[

                                InlineKeyboardButton("🔗 Попробовать ссылку", url=video_url)

                            ]])
                        )
                        
                        return  # Выходим из функции

        except Exception as test_error:

            logging.warning(f"Не удалось протестировать файл: {test_error}")

            # Продолжаем попытку отправки

        

        # Дополнительная проверка: проверяем, не заблокирован ли бот пользователем

        try:

            # Пробуем отправить простое сообщение для проверки доступности

            test_msg = await context.bot.send_message(

                chat_id=chat_id,

                text="🔍 Проверяю доступность чата...",

                disable_notification=True

            )

            # Если сообщение отправилось, удаляем его

            await context.bot.delete_message(chat_id=chat_id, message_id=test_msg.message_id)

            logging.info("Чат доступен для отправки сообщений")

        except Exception as chat_error:

            logging.error(f"Проблема с доступом к чату: {chat_error}")

            # Отправляем сообщение с инструкциями

            await context.bot.send_message(

                chat_id=chat_id,

                text=f"⚠️ **Проблема с доступом к чату**\n\n"

                     f"Возможно, бот заблокирован или чат недоступен\n\n"

                     f"🔗 **Ссылка на видео:** {video_url}\n\n"

                     f"💡 **Решения:**\n"

                     f"• Разблокируйте бота\n"

                     f"• Скопируйте ссылку в браузер\n"

                     f"• Создайте новый чат с ботом",

                reply_markup=InlineKeyboardMarkup([[

                    InlineKeyboardButton("🔗 Скачать видео", url=video_url)

                ]])

            )

            return  # Выходим из функции

            

        # Отправляем видео пользователю

        # Функция для сокращения длинного промпта
        def truncate_prompt(prompt, max_length=80):
            if len(prompt) <= max_length:
                return prompt
            return prompt[:max_length] + "..."

        if video_type == 'text_to_video' and video_prompt:

            # Показываем сокращенный промпт для экономии места

            truncated_prompt = truncate_prompt(english_prompt, 80)
            prompt_caption = f"📝 {truncated_prompt}"

        elif video_type == 'image_to_video' and video_prompt:

            # Показываем сокращенный промпт для экономии места

            truncated_prompt = truncate_prompt(english_prompt, 80)
            prompt_caption = f"🖼️ {truncated_prompt}"

        else:

            # Fallback для случаев, когда что-то пошло не так

            if video_type == 'image_to_video':

                prompt_caption = "🖼️ Изображение загружено"

            else:

                prompt_caption = "🎬 Видео готово"

        

        # Улучшенная отправка видео с множественными fallback методами

        video_sent = False

        video_error = None

        doc_error = None

        local_error = None

        anim_error = None

        

        # Метод 1: Пробуем отправить как видео с поддержкой стриминга

        logging.info(f"📤 Отправляем видео в Telegram:")

        logging.info(f"   URL: {video_url}")

        logging.info(f"   Формат файла: {file_extension}")

        logging.info(f"   Content-Type: {content_type if 'content_type' in locals() else 'не определен'}")

        logging.info(f"   Размер: {file_size_mb if 'file_size_mb' in locals() else 'не определен'} МБ")

        logging.info(f"   Метод: send_video")

        

        try:

            await context.bot.send_video(

                chat_id=chat_id,

                video=video_url,

                caption=f"🎬 **Видео готово!**\n\n"

                        f"{prompt_caption}\n"

                        f"⚡ {video_quality} | ⏱️ {video_duration}с\n"

                        f"✨ Bytedance Seedance 1.0 Pro",

                supports_streaming=True,

                has_spoiler=False

            )

            video_sent = True

            logging.info("✅ Видео успешно отправлено как видео с поддержкой стриминга")
            
            # СПИСЫВАЕМ КРЕДИТЫ ЗА ВИДЕО
            if user_id:
                # Определяем стоимость видео на основе качества и длительности
                if video_duration == 5:
                    if video_quality == "480p":
                        base_cost = 37
                    elif video_quality == "720p":
                        base_cost = 71
                    elif video_quality == "1080p":
                        base_cost = 172
                elif video_duration == 10:
                    if video_quality == "480p":
                        base_cost = 71
                    elif video_quality == "720p":
                        base_cost = 138
                    elif video_quality == "1080p":
                        base_cost = 342
                else:
                    # Для других длительностей используем базовую цену 480p 5s
                    base_cost = 37
                
                if await analytics_db_use_credits_async(user_id, base_cost, f"Генерация видео {video_quality} {video_duration}с через Bytedance Seedance 1.0 Pro"):
                    logging.info(f"Пользователь {user_id} использовал {base_cost} кредитов за видео")
                else:
                    logging.error(f"Ошибка списания кредитов для пользователя {user_id}")

            # Очищаем состояние после успешной генерации
            state['step'] = None
            state.pop('video_type', None)
            state.pop('video_quality', None)
            state.pop('video_duration', None)
            state.pop('video_prompt', None)
            state.pop('english_prompt', None)
            state.pop('enhanced_prompt', None)

            # Отправляем дополнительную информацию о файле

            await context.bot.send_message(

                chat_id=chat_id,

                text=f"🎬 **Дополнительная информация:**\n\n"

                     f"🔗 **Скачайте файл через кнопку ниже**\n\n"

                     f"⚠️ **ВАЖНО:** Ссылка временная и может истечь!\n\n"

                     f"💡 **Если видео не воспроизводится:**\n"

                     f"• Нажмите кнопку '🔗 Скачать файл' ниже\n"

                     f"• Или откройте ссылку в браузере\n"

                     f"• Скачайте файл локально\n\n"

                     f"⏰ **Время действия:** ~30 минут",

                reply_markup=InlineKeyboardMarkup([[

                    InlineKeyboardButton("🔗 Скачать файл", url=video_url)

                ]])

            )

            

        except Exception as e:

            video_error = e

            logging.error(f"❌ Не удалось отправить как видео: {video_error}")

            logging.error(f"   Тип ошибки: {type(video_error).__name__}")

            logging.error(f"   Детали ошибки: {str(video_error)}")

            

            # Метод 2: Пробуем отправить как документ для сохранения качества

            try:

                await context.bot.send_document(

                    chat_id=chat_id,

                    document=video_url,

                    caption=f"🎬 **Видео готово!**\n\n"

                            f"{prompt_caption}\n"

                            f"⚡ {video_quality} | ⏱️ {video_duration}с | 📁 MP4\n"

                            f"✨ Bytedance Seedance 1.0 Pro"

                )

                video_sent = True

                logging.info("Видео успешно отправлено как документ (MP4)")
                
                # СПИСЫВАЕМ КРЕДИТЫ ЗА ВИДЕО
                if user_id:
                    # Определяем стоимость видео на основе качества и длительности
                    if video_duration == 5:
                        if video_quality == "480p":
                            base_cost = 37
                        elif video_quality == "720p":
                            base_cost = 71
                        elif video_quality == "1080p":
                            base_cost = 172
                    elif video_duration == 10:
                        if video_quality == "480p":
                            base_cost = 71
                        elif video_quality == "720p":
                            base_cost = 138
                        elif video_quality == "1080p":
                            base_cost = 342
                    else:
                        # Для других длительностей используем базовую цену 480p 5s
                        base_cost = 37
                    
                    if await analytics_db_use_credits_async(user_id, base_cost, f"Генерация видео {video_quality} {video_duration}с через Bytedance Seedance 1.0 Pro"):
                        logging.info(f"Пользователь {user_id} использовал {base_cost} кредитов за видео")
                    else:
                        logging.error(f"Ошибка списания кредитов для пользователя {user_id}")

                # Очищаем состояние после успешной генерации
                state['step'] = None
                state.pop('video_type', None)
                state.pop('video_quality', None)
                state.pop('video_duration', None)
                state.pop('video_prompt', None)
                state.pop('english_prompt', None)
                state.pop('enhanced_prompt', None)

                # Отправляем дополнительную информацию о файле

                await context.bot.send_message(

                    chat_id=chat_id,

                    text=f"🎬 **Дополнительная информация:**\n\n"

                         f"🔗 **Скачайте файл через кнопку ниже**\n\n"

                         f"⚠️ **ВАЖНО:** Ссылка временная и может истечь!\n\n"

                         f"💡 **Если документ не открывается:**\n"

                         f"• Нажмите кнопку '🔗 Скачать файл' ниже\n"

                         f"• Или откройте ссылку в браузере\n"

                         f"• Скачайте файл локально\n\n"

                         f"⏰ **Время действия:** ~30 минут",

                    reply_markup=InlineKeyboardMarkup([[

                        InlineKeyboardButton("🔗 Скачать файл", url=video_url)

                    ]])

                )

                

            except Exception as e:

                doc_error = e

                logging.error(f"Не удалось отправить как документ: {doc_error}")

            

                # Метод 3: Пробуем загрузить файл локально и отправить

                try:

                    logging.info("Пробуем загрузить файл локально и отправить...")

                    

                    # Загружаем видео во временный файл

                    import tempfile

                    import requests

                    

                    # Сначала проверяем размер файла

                    async with aiohttp.ClientSession() as session:
                        async with session.head(video_url, timeout=aiohttp.ClientTimeout(total=30)) as head_response:
                            if head_response.status == 200:
                                content_length = head_response.headers.get('content-length')

                                if content_length:
                                    file_size_mb = int(content_length) / (1024 * 1024)
                                    logging.info(f"Размер файла: {file_size_mb:.1f} МБ")
                                    
                                    # Проверяем лимиты Telegram
                                    if file_size_mb > 50:
                                        logging.warning(f"Файл слишком большой для отправки: {file_size_mb:.1f} МБ")
                                        # Вместо исключения, отправляем сообщение с рекомендациями
                                        await context.bot.send_message(
                                            chat_id=chat_id,
                                            text=(
                                                f"⚠️ **Файл слишком большой!**\n\n"
                                                f"Размер: {file_size_mb:.1f} МБ\n"
                                                f"Лимит Telegram: 50 МБ\n\n"
                                                f"💡 **Рекомендации:**\n"
                                                f"• Выберите качество 480p вместо 1080p\n"
                                                f"• Уменьшите длительность до 5-10 секунд\n"
                                                f"• Создайте новое видео с меньшими параметрами\n\n"
                                                f"🔗 **Ссылка на видео:** {video_url}"
                                            ),
                                            reply_markup=InlineKeyboardMarkup([
                                                [InlineKeyboardButton("🔗 Скачать видео", url=video_url)]
                                            ])
                                        )
                                        video_sent = True
                                        logging.info("Отправлено сообщение о большом файле")
                                        return  # Выходим из функции
                                    elif file_size_mb > 20:
                                        logging.info(f"Файл большой ({file_size_mb:.1f} МБ), могут быть проблемы с отправкой")

                    

                    # Загружаем файл по частям асинхронно
                    async with aiohttp.ClientSession() as session:
                        async with session.get(video_url, timeout=aiohttp.ClientTimeout(total=60)) as response:
                            if response.status == 200:

                                # Создаем временный файл асинхронно
                                loop = asyncio.get_event_loop()
                                temp_file_path = await loop.run_in_executor(
                                    THREAD_POOL,
                                    lambda: tempfile.NamedTemporaryFile(delete=False, suffix='.mp4').name
                                )
                                
                                total_size = 0
                                
                                # Загружаем файл по частям
                                async for chunk in response.content.iter_chunked(8192):

                                        if chunk:
                                            # Записываем chunk в файл асинхронно
                                            await loop.run_in_executor(
                                                THREAD_POOL,
                                                lambda: open(temp_file_path, 'ab').write(chunk)
                                            )
                                            total_size += len(chunk)
                                            
                                            # Проверяем размер во время загрузки
                                            if total_size > 50 * 1024 * 1024:  # 50 МБ
                                                raise Exception("Файл превышает лимит Telegram (50 МБ)")
                                    
                                logging.info(f"Файл загружен локально: {temp_file_path}, размер: {total_size / (1024*1024):.1f} МБ")

                                
                                # Проверяем, что файл действительно создался и имеет размер
                                if not os.path.exists(temp_file_path) or os.path.getsize(temp_file_path) == 0:
                                    raise Exception("Временный файл не создался или пустой")
                                
                                # Отправляем локальный файл
                                try:
                                    # Читаем видео файл асинхронно
                                    loop = asyncio.get_event_loop()
                                    video_data = await loop.run_in_executor(
                                        THREAD_POOL,
                                        lambda: open(temp_file_path, 'rb').read()
                                    )
                                    
                                    await context.bot.send_video(
                                            chat_id=chat_id,

                                            video=video_data,
                                            caption=f"🎬 **Видео готово!**\n\n"

                                            f"{prompt_caption}\n"
                                            f"⚡ {video_quality} | ⏱️ {video_duration}с\n"
                                            f"✨ Bytedance Seedance 1.0 Pro",

                                            supports_streaming=True,
                                            has_spoiler=False

                                        )
                                    
                                    video_sent = True

                                    logging.info("Видео успешно отправлено из локального файла")
                                    
                                    # Очищаем состояние после успешной генерации
                                    state['step'] = None
                                    state.pop('video_type', None)
                                    state.pop('video_quality', None)
                                    state.pop('video_duration', None)
                                    state.pop('video_prompt', None)
                                    state.pop('english_prompt', None)
                                    state.pop('enhanced_prompt', None)

                                except Exception as send_error:

                                    logging.error(f"Ошибка при отправке локального файла: {send_error}")
                                    
                                    # Попробуем отправить как документ
                                    try:
                                        # Читаем видео файл асинхронно
                                        loop = asyncio.get_event_loop()
                                        video_data = await loop.run_in_executor(
                                            THREAD_POOL,
                                            lambda: open(temp_file_path, 'rb').read()
                                        )
                                        
                                        await context.bot.send_document(
                                                chat_id=chat_id,

                                                document=video_data,
                                                caption=f"🎬 **Видео готово!**\n\n"

                                                f"{prompt_caption}\n"
                                                f"⚡ {video_quality} | ⏱️ {video_duration}с | 📁 MP4\n"
                                                f"✨ Bytedance Seedance 1.0 Pro",

                                                filename=f"video_{video_quality}_{video_duration}s.mp4"
                                            )

                                        video_sent = True
                                        logging.info("Видео успешно отправлено как документ из локального файла")
                                            
                                        # Очищаем состояние после успешной генерации
                                        state['step'] = None
                                        state.pop('video_type', None)
                                        state.pop('video_quality', None)
                                        state.pop('video_duration', None)
                                        state.pop('video_prompt', None)
                                        state.pop('english_prompt', None)
                                        state.pop('enhanced_prompt', None)
                                            
                                    except Exception as doc_error:
                                        logging.error(f"Ошибка при отправке как документ: {doc_error}")
                                        # Отправляем ссылку как последний вариант
                                        await context.bot.send_message(
                                            chat_id=chat_id,
                                            text=f"🎬 **Видео готово!**\n\n"
                                                 f"{prompt_caption}\n"
                                                 f"⚡ {video_quality} | ⏱️ {video_duration}с\n"
                                                 f"✨ Bytedance Seedance 1.0 Pro\n\n"
                                                 f"🔗 **Ссылка на видео:** {video_url}",
                                            reply_markup=InlineKeyboardMarkup([
                                                [InlineKeyboardButton("🔗 Скачать видео", url=video_url)]
                                            ])
                                        )
                                        video_sent = True
                                
                                # СПИСЫВАЕМ КРЕДИТЫ ЗА ВИДЕО
                                if user_id:
                                    # Определяем стоимость видео на основе качества и длительности
                                    if video_duration == 5:
                                        if video_quality == "480p":
                                            base_cost = 37
                                        elif video_quality == "720p":
                                            base_cost = 71
                                        elif video_quality == "1080p":
                                            base_cost = 172
                                    elif video_duration == 10:
                                        if video_quality == "480p":
                                            base_cost = 71
                                        elif video_quality == "720p":
                                            base_cost = 138
                                        elif video_quality == "1080p":
                                            base_cost = 342
                                    else:
                                        # Для других длительностей используем базовую цену 480p 5s
                                        base_cost = 37
                                    
                                    if await analytics_db_use_credits_async(user_id, base_cost, f"Генерация видео {video_quality} {video_duration}с через Bytedance Seedance 1.0 Pro"):
                                        logging.info(f"Пользователь {user_id} использовал {base_cost} кредитов за видео")
                                    else:
                                        logging.error(f"Ошибка списания кредитов для пользователя {user_id}")


                        

                        # Удаляем временный файл

                        try:

                            os.unlink(temp_file_path)

                        except Exception as cleanup_error:

                            logging.warning(f"Не удалось удалить временный файл: {cleanup_error}")

                except Exception as e:

                    local_error = e

                    logging.error(f"Не удалось отправить из локального файла: {local_error}")

                    

                    # Метод 4: Пробуем отправить как анимацию (если это GIF)

                    if file_extension == 'gif' or 'gif' in video_url.lower():

                        try:

                            await context.bot.send_animation(

                                chat_id=chat_id,

                                animation=video_url,

                                caption=f"🎬 **Анимация готова!**\n\n"

                                        f"{prompt_caption}\n"

                                        f"⚡ {video_quality} | ⏱️ {video_duration}с\n"

                                        f"✨ Bytedance Seedance 1.0 Pro"

                            )

                            video_sent = True

                            logging.info("Анимация успешно отправлена")
                            
                            # Очищаем состояние после успешной генерации
                            state['step'] = None
                            state.pop('video_type', None)
                            state.pop('video_quality', None)
                            state.pop('video_duration', None)
                            state.pop('video_prompt', None)
                            state.pop('english_prompt', None)
                            state.pop('enhanced_prompt', None)
                            
                            # СПИСЫВАЕМ КРЕДИТЫ ЗА ВИДЕО
                            if user_id:
                                # Определяем стоимость видео на основе качества и длительности
                                if video_duration == 5:
                                    if video_quality == "480p":
                                        base_cost = 37
                                    elif video_quality == "720p":
                                        base_cost = 71
                                    elif video_quality == "1080p":
                                        base_cost = 172
                                elif video_duration == 10:
                                    if video_quality == "480p":
                                        base_cost = 71
                                    elif video_quality == "720p":
                                        base_cost = 138
                                    elif video_quality == "1080p":
                                        base_cost = 342
                                else:
                                    # Для других длительностей используем базовую цену 480p 5s
                                    base_cost = 37
                                
                                if await analytics_db_use_credits_async(user_id, base_cost, f"Генерация видео {video_quality} {video_duration}с через Bytedance Seedance 1.0 Pro"):
                                    logging.info(f"Пользователь {user_id} использовал {base_cost} кредитов за видео")
                                else:
                                    logging.error(f"Ошибка списания кредитов для пользователя {user_id}")

                            # Даже если GIF отправился, отправляем ссылку на MP4

                            await context.bot.send_message(

                                chat_id=chat_id,

                                text=f"🎬 **Видео готово!**\n\n"

                                     f"✅ GIF отправлен в чат\n"

                                     f"🔗 **Скачайте MP4 версию через кнопку ниже**\n\n"

                                     f"⚠️ **ВАЖНО:** Ссылка временная и может истечь!\n\n"

                                     f"💡 **Как использовать:**\n"

                                     f"• Нажмите кнопку '🔗 Скачать MP4' ниже\n"

                                     f"• Или откройте ссылку в браузере\n"

                                     f"• Скачайте MP4 файл\n\n"

                                     f"⏰ **Время действия:** ~30 минут",

                                reply_markup=InlineKeyboardMarkup([[

                                    InlineKeyboardButton("🔗 Скачать MP4", url=video_url)

                                ]])

                            )

                        except Exception as e:

                            anim_error = e

                            logging.error(f"Не удалось отправить как анимацию: {anim_error}")

        

        # Метод 5: В крайнем случае отправляем сообщение с ссылкой и инструкциями

        if not video_sent:

            # Логируем все ошибки для диагностики

            logging.error("Все методы отправки видео не удались:")

            if video_error:

                logging.error(f"Ошибка send_video: {video_error}")

            if doc_error:

                logging.error(f"Ошибка send_document: {doc_error}")

            if local_error:

                logging.error(f"Ошибка локальной отправки: {local_error}")

            if anim_error:

                logging.error(f"Ошибка send_animation: {anim_error}")

            

            # Создаем красивую клавиатуру с кнопкой для скачивания

            keyboard = [

                [InlineKeyboardButton("🔗 Скачать видео", url=video_url)],

                [InlineKeyboardButton("🎬 Создать еще видео", callback_data="video_generation")],

                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]

            ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            

            # Определяем возможную причину ошибки на основе всех попыток

            error_reasons = []

            

            # Анализируем все ошибки

            all_errors = [video_error, doc_error, local_error, anim_error]

            for error in all_errors:

                if error:

                    error_str = str(error).lower()

                    if "too large" in error_str or "file size" in error_str or "large" in error_str:

                        error_reasons.append("Файл слишком большой для Telegram")

                    if "timeout" in error_str:

                        error_reasons.append("Превышено время ожидания")

                    if "network" in error_str or "connection" in error_str:

                        error_reasons.append("Проблемы с сетью")

                    if "format" in error_str or "unsupported" in error_str:

                        error_reasons.append("Неподдерживаемый формат файла")

                    if "bot was blocked" in error_str or "bot was stopped" in error_str:

                        error_reasons.append("Бот заблокирован пользователем")

                    if "file" in error_str and "not found" in error_str:

                        error_reasons.append("Файл не найден на сервере")

                    if "bad request" in error_str:

                        error_reasons.append("Некорректный запрос к Telegram")

                    if "forbidden" in error_str:

                        error_reasons.append("Доступ запрещен")

                    if "internal server error" in error_str:

                        error_reasons.append("Внутренняя ошибка сервера")

            

            # Убираем дубликаты

            error_reasons = list(set(error_reasons))

            

            if not error_reasons:

                error_reasons.append("Техническая ошибка при отправке")

            

            error_reason = " • ".join(error_reasons)

            

            # Добавляем информацию о размере файла, если доступна

            size_info = ""

            try:

                async with aiohttp.ClientSession() as session:
                    async with session.head(video_url, timeout=aiohttp.ClientTimeout(total=10)) as head_response:
                        if head_response.status == 200:
                            content_length = head_response.headers.get('content-length')

                            if content_length:
                                file_size_mb = int(content_length) / (1024 * 1024)

                                size_info = f"\n📏 **Размер файла:** {file_size_mb:.1f} МБ"

            except:

                pass

            

            # Создаем подробную диагностику

            diagnostic_info = f"🎬 **Видео готово!**\n\n"

            diagnostic_info += f"{prompt_caption}\n"

            diagnostic_info += f"⚡ Качество: {video_quality}\n"

            diagnostic_info += f"⏱️ Длительность: {video_duration} сек{size_info}\n\n"

            diagnostic_info += f"✨ Создано с помощью Bytedance Seedance 1.0 Pro\n\n"

            diagnostic_info += f"⚠️ **Не удалось отправить файл напрямую**\n\n"

            diagnostic_info += f"🔍 **Причина:** {error_reason}\n\n"

            

            # Добавляем детальную информацию об ошибках

            if video_error:

                diagnostic_info += f"📹 **Ошибка send_video:** {str(video_error)[:100]}...\n"

            if doc_error:

                diagnostic_info += f"📄 **Ошибка send_document:** {str(doc_error)[:100]}...\n"

            if local_error:

                diagnostic_info += f"💾 **Ошибка локальной отправки:** {str(local_error)[:100]}...\n"

            if anim_error:

                diagnostic_info += f"🎭 **Ошибка send_animation:** {str(anim_error)[:100]}...\n"

            

            diagnostic_info += f"\n💡 **Решения:**\n"

            diagnostic_info += f"• Нажмите кнопку '🔗 Скачать видео' ниже\n"

            diagnostic_info += f"• Откройте ссылку в браузере для просмотра\n\n"

            diagnostic_info += f"📱 **Альтернативные способы:**\n"

            diagnostic_info += f"• Используйте кнопку для скачивания\n"

            diagnostic_info += f"• Попробуйте создать видео меньшего размера\n\n"

            diagnostic_info += f"🔄 **Попробуйте снова:**\n"

            diagnostic_info += f"• Выберите меньшее качество (480p вместо 1080p)\n"

            diagnostic_info += f"• Уменьшите длительность видео\n"

            diagnostic_info += f"• Создайте новое видео\n\n"

            diagnostic_info += f"💬 **Если проблема повторяется:**\n"

            diagnostic_info += f"• Попробуйте позже (возможны временные проблемы)\n"

            diagnostic_info += f"• Обратитесь в поддержку с описанием ошибки\n\n"

            diagnostic_info += f"🔧 **Техническая информация:**\n"

            diagnostic_info += f"• Расширение: {file_extension}\n"

            diagnostic_info += f"• Тип: {video_type}"

            

            await context.bot.send_message(

                chat_id=chat_id,

                text=diagnostic_info,

                reply_markup=reply_markup,

                parse_mode='Markdown'

            )

            logging.info("Отправлена ссылка на видео с инструкциями")

        

        # Показываем кнопки для дальнейших действий

        keyboard = [

            [InlineKeyboardButton("🎬 Создать еще видео", callback_data="video_generation")],

            [InlineKeyboardButton("🎨 Создать изображения", callback_data="create_content")],

            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]

        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        

        await context.bot.send_message(

            chat_id=chat_id,

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

            

    except Exception as e:

        logging.error(f"Ошибка при генерации видео: {e}")

        

        # Анализируем тип ошибки для лучшего пользовательского опыта

        error_str = str(e).lower()

        error_type = "unknown"

        error_solution = ""

        

        if "insufficient credit" in error_str or "insufficient_credit" in error_str:

            error_type = "credit"

            error_solution = """

💳 **Проблема с кредитами Replicate**



❌ **Причина:** На аккаунте Replicate закончились кредиты для генерации видео



💡 **Решения:**

• Пополните баланс на https://replicate.com/account/billing

• Подождите несколько минут после пополнения

• Попробуйте создать видео позже



🔄 **Альтернативы:**

• Создайте изображения вместо видео (бесплатно)

• Используйте другие функции бота

• Обратитесь к администратору для пополнения



💰 **Стоимость:** Генерация видео стоит кредиты Replicate

"""

        elif "api" in error_str and "token" in error_str:

            error_type = "api"

            error_solution = """

🔑 **Проблема с API токеном**



❌ **Причина:** Ошибка авторизации Replicate API



💡 **Решения:**

• Проверьте настройки API токена

• Обратитесь к администратору

• Попробуйте позже



🔄 **Альтернативы:**

• Создайте изображения (работает с Ideogram)

• Используйте другие функции бота

"""

        elif "timeout" in error_str or "timed out" in error_str:

            error_type = "timeout"

            error_solution = """

⏰ **Превышено время ожидания**



❌ **Причина:** Сервер Replicate не ответил вовремя



💡 **Решения:**

• Попробуйте создать видео позже

• Выберите меньшее качество (480p)

• Уменьшите длительность видео



🔄 **Альтернативы:**

• Создайте изображения (быстрее)

• Попробуйте в непиковые часы

"""

        elif "network" in error_str or "connection" in error_str:

            error_type = "network"

            error_solution = """

🌐 **Проблемы с сетью**



❌ **Причина:** Ошибка подключения к Replicate



💡 **Решения:**

• Проверьте интернет-соединение

• Попробуйте позже

• Используйте VPN если необходимо



🔄 **Альтернативы:**

• Создайте изображения

• Попробуйте в другое время

"""

        else:

            error_type = "unknown"

            error_solution = f"""

❌ **Техническая ошибка**



**Описание:** {str(e)[:200]}...



💡 **Решения:**

• Попробуйте создать видео позже

• Выберите другие параметры

• Обратитесь в поддержку



🔄 **Альтернативы:**

• Создайте изображения

• Используйте другие функции бота

"""

        

        # Создаем клавиатуру в зависимости от типа ошибки

        if error_type == "credit":

            keyboard = [

                [InlineKeyboardButton("💰 Пополнить баланс", url="https://replicate.com/account/billing")],

                [InlineKeyboardButton("🖼️ Создать изображения", callback_data="create_content")],

                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]

            ]

        elif error_type == "api":

            keyboard = [

                [InlineKeyboardButton("🖼️ Создать изображения", callback_data="create_content")],

                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]

            ]

        else:

            keyboard = [

                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="video_generation")],

                [InlineKeyboardButton("🖼️ Создать изображения", callback_data="create_content")],

                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]

            ]

        

        reply_markup = InlineKeyboardMarkup(keyboard)

        

        # Формируем заголовок ошибки

        if error_type == "credit":

            error_title = "💳 Недостаточно кредитов для генерации видео"

        elif error_type == "api":

            error_title = "🔑 Ошибка API токена"

        elif error_type == "timeout":

            error_title = "⏰ Превышено время ожидания"

        elif error_type == "network":

            error_title = "🌐 Проблемы с сетью"

        else:

            error_title = "❌ Ошибка при генерации видео"

        

        # Создаем полное сообщение об ошибке

        full_error_message = f"{error_title}\n\n{error_solution}"

        

        if hasattr(update, 'callback_query') and update.callback_query:

            await update.callback_query.edit_message_text(

                full_error_message,

                reply_markup=reply_markup,

                parse_mode='Markdown'

            )

        else:

            await context.bot.send_message(

                chat_id=chat_id,

                text=full_error_message,

                reply_markup=reply_markup,

                parse_mode='Markdown'

            )

        

        # Итоговое логирование результата

        logging.info(f"🎬 ИТОГОВЫЙ РЕЗУЛЬТАТ генерации видео:")

        logging.info(f"   Тип видео: {video_type}")

        logging.info(f"   Качество: {video_quality}")

        logging.info(f"   Длительность: {video_duration}")

        logging.info(f"   Aspect ratio: {state.get('aspect_ratio', 'не указан')}")

        logging.info(f"   URL файла: {video_url if 'video_url' in locals() else 'не определен'}")

        logging.info(f"   Формат файла: {file_extension if 'file_extension' in locals() else 'не определен'}")

        logging.info(f"   Видео отправлено: {video_sent if 'video_sent' in locals() else 'не определен'}")

        if 'video_sent' in locals() and not video_sent:

            logging.error(f"   Ошибки отправки:")

            if 'video_error' in locals() and video_error:

                logging.error(f"     send_video: {video_error}")

            if 'doc_error' in locals() and doc_error:

                logging.error(f"     send_document: {doc_error}")

            if 'local_error' in locals() and local_error:

                logging.error(f"     локальная отправка: {local_error}")

            if 'anim_error' in locals() and anim_error:

                logging.error(f"     send_animation: {anim_error}")

        

        # Сбрасываем состояние

        state['step'] = None

        state.pop('video_type', None)

        state.pop('video_quality', None)

        state.pop('video_duration', None)

        state.pop('video_prompt', None)

        state.pop('english_prompt', None)

        state.pop('enhanced_prompt', None)



# НОВЫЕ ФУНКЦИИ ДЛЯ ПЛАТЕЖНОЙ СИСТЕМЫ



async def show_subscription_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):

    """Показывает меню кредитов"""

    user_id = update.effective_user.id

    

    # Получаем информацию о пользователе

    limits = await analytics_db_get_user_limits_async(user_id)

    credits = await analytics_db_get_user_credits_async(user_id)

    

    # Формируем текст статуса

    free_generations_left = await analytics_db_get_free_generations_left_async(user_id)

    

    status_text = ""

    if free_generations_left > 0:

        status_text = f"🆓 **Бесплатные генерации:** {free_generations_left} осталось\n"

    else:

        status_text += f"🆓 **Бесплатные генерации:** закончились\n"

    

    # Добавляем информацию о кредитах

    if credits['balance'] > 0:

        status_text += f"🪙 **Кредиты:** {credits['balance']} доступно\n\n"

    else:

        status_text += f"🪙 **Кредиты:** не куплены\n\n"

    

    keyboard = [

        [InlineKeyboardButton("🪙 Пакеты кредитов", callback_data="credit_packages")],

        [InlineKeyboardButton("📊 Моя статистика", callback_data="user_stats")],

        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]

    ]

    

    await update.callback_query.edit_message_text(

        f"🪙 **Кредиты и генерации**\n\n{status_text}"

        "Выберите, что хотите сделать:",

        reply_markup=InlineKeyboardMarkup(keyboard)

    )



# Функция show_subscription_plans удалена - планы подписок больше не поддерживаются



async def show_credit_packages(update: Update, context: ContextTypes.DEFAULT_TYPE):

    """Показывает доступные пакеты кредитов"""

    try:

        from pricing_config import CREDIT_PACKAGES, format_price

    except ImportError:

        # Fallback если модуль не импортирован

        CREDIT_PACKAGES = {

            'small': {'name': '🪙 Малый пакет', 'credits': 2000, 'price': 14.0, 'currency': 'UAH', 'description': '2000 кредитов для начала работы'},

            'medium': {'name': '🪙 Средний пакет', 'credits': 5000, 'price': 30.0, 'currency': 'UAH', 'description': '5000 кредитов со скидкой 14%'},

            'large': {'name': '🪙 Большой пакет', 'credits': 10000, 'price': 50.0, 'currency': 'UAH', 'description': '10000 кредитов со скидкой 29%'}

        }

        

        def format_price(amount, currency):

            return f"₴{amount:.2f}" if currency == 'UAH' else f"{amount:.2f}{currency}"

    

    text = "🪙 **Пакеты кредитов (pay-per-use):**\n\n"

    text += "💡 **Как это работает:**\n"

    text += "• Покупаете кредиты один раз\n"

    text += "• Используете их для генераций\n"

    text += "• Кредиты не сгорают\n\n"

    

    for package_type, package in CREDIT_PACKAGES.items():

        text += f"**{package['name']}**\n"

        text += f"• {package['credits']} кредитов за {format_price(package['price'], package['currency'])}\n"

        if package.get('discount_percent', 0) > 0:

            text += f"• Скидка {package['discount_percent']}%\n"

        text += f"• {package['description']}\n\n"

    

    text += "💰 **Стоимость генераций:**\n\n"

    text += "🖼️ **Изображения (за 1 изображение):**\n"

    text += "• Ideogram, Bytedance, Luma: 10 кредитов\n"

    text += "• Bria 3.2: 12 кредитов\n"

    text += "• Google Imagen 4 Ultra: 16 кредитов\n"

    text += "• Recraft AI: 20 кредитов\n\n"

    text += "✏️ **Редактирование изображений (за 1 редактирование):**\n"

    text += "• FLUX.1 Kontext Pro: 12 кредитов\n\n"

    text += "🎬 **Видео (за 1 видео):**\n"

    text += "• 480p 5 секунд: 37 кредитов\n"

    text += "• 720p 5 секунд: 71 кредит\n"

    text += "• 1080p 5 секунд: 172 кредита\n"

    text += "• 480p 10 секунд: 71 кредит\n"

    text += "• 720p 10 секунд: 138 кредитов\n"

    text += "• 1080p 10 секунд: 342 кредита\n\n"

    text += "🔄 **Кредиты не сгорают и доступны всегда!**"

    

    keyboard = []

    for package_type, package in CREDIT_PACKAGES.items():

        keyboard.append([InlineKeyboardButton(

            f"{package['name']} - {format_price(package['price'], package['currency'])}", 

            callback_data=f"buy_credits:{package_type}"

        )])

    

    keyboard.extend([

        [InlineKeyboardButton("🔙 Назад", callback_data="subscription_menu")]

    ])

    

    await update.callback_query.edit_message_text(

        text,

        reply_markup=InlineKeyboardMarkup(keyboard)

    )



# Функция handle_subscription_purchase удалена - планы подписок больше не поддерживаются



async def handle_credit_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):

    """Обрабатывает покупку кредитов"""

    try:

        from pricing_config import get_credit_package_by_type

    except ImportError:

        await update.callback_query.answer("❌ Модуль конфигурации не найден")

        return

    

    # Извлекаем тип пакета из callback_data

    package_type = update.callback_query.data.split(':')[1]

    package = get_credit_package_by_type(package_type)

    

    if not package:

        await update.callback_query.answer("❌ Пакет не найден")

        return

    

    user_id = update.effective_user.id

    

    # Создаем платеж через Betatransfer

    try:

        from betatransfer_api import betatransfer_api

        

        # Создаем платеж

        print(f"🔍 Создаем платеж для пакета: {package}")

        payment_result = betatransfer_api.create_payment(

            amount=package['price'],

            currency=package['currency'],

            description=f"Пакет кредитов: {package['name']} ({package['credits']} кредитов)",

            payer_id=str(user_id)

        )

        print(f"🔍 Результат создания платежа: {payment_result}")

        

        if 'error' in payment_result:

            await update.callback_query.answer(f"❌ Ошибка создания платежа: {payment_result['error']}")

            return

        

        # Проверяем, есть ли payment_id в ответе

        if 'id' not in payment_result:

            print(f"❌ В ответе нет id: {payment_result}")

            await update.callback_query.answer("❌ Ошибка: не получен ID платежа")

            return

        

        # Получаем URL для оплаты

        payment_url = payment_result.get('urlPayment', payment_result.get('url', ''))

        

        # Создаем запись о платеже в базе данных с количеством кредитов
        order_id = payment_result.get('order_id', f"order{int(time.time())}")
        payment_record = await analytics_db_create_payment_with_credits_async(
            user_id=user_id,
            amount=package['price'],
            currency=package['currency'],
            payment_id=payment_result['id'],
            order_id=order_id,
            credit_amount=package['credits']  # Важно! Указываем количество кредитов
        )
        
        if not payment_record:
            logging.error(f"Ошибка создания записи о платеже для пользователя {user_id}")
            await update.callback_query.answer("❌ Ошибка: не удалось создать запись о платеже")
            return
        
        # Показываем информацию о платеже

        text = f"🪙 **Покупка пакета кредитов**\n\n"

        text += f"📦 **Пакет:** {package['name']}\n"

        text += f"🪙 **Кредитов:** {package['credits']}\n"

        text += f"💰 **Сумма:** сом{package['price']:.0f}\n"

        text += f"📝 **Описание:** {package['description']}\n\n"

        text += "🔗 **Для оплаты перейдите по ссылке:**\n"

        text += f"{payment_url}\n\n"

        text += "⚠️ **Важно:** После оплаты нажмите кнопку 'Проверить статус'"

        

        keyboard = [

            [InlineKeyboardButton("🔗 Перейти к оплате", url=payment_url)],

            [InlineKeyboardButton("✅ Проверить статус", callback_data=f"check_payment:{payment_result['id']}")],

            [InlineKeyboardButton("🔙 Назад", callback_data="credit_packages")]

        ]

        

        await update.callback_query.edit_message_text(

            text,

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        

    except Exception as e:

        import traceback

        error_traceback = traceback.format_exc()

        print(f"🔍 Полный traceback ошибки:")

        print(error_traceback)

        logging.error(f"Ошибка создания платежа: {e}")

        logging.error(f"Traceback: {error_traceback}")

        await update.callback_query.answer("❌ Ошибка создания платежа")



async def check_payment_status(update: Update, context: ContextTypes.DEFAULT_TYPE):

    """Проверяет статус платежа"""
    
    print(f"🔍 Вызвана функция check_payment_status")
    print(f"🔍 callback_data: {update.callback_query.data}")
    
    # Извлекаем ID платежа из callback_data

    payment_id = update.callback_query.data.split(':')[1]

    

    try:

        from betatransfer_api import BetatransferAPI
        betatransfer_api = BetatransferAPI()
        
        # Получаем статус платежа
        payment_status = betatransfer_api.get_payment_status(payment_id)

        

        if 'error' in payment_status:

            await update.callback_query.answer(f"❌ Ошибка проверки: {payment_status['error']}")

            return

        

        status = payment_status.get('status', 'unknown')

        

        if status == 'completed' or status == 'success':

            # Платеж успешен - активируем подписку или кредиты

            print(f"✅ Платеж завершен со статусом: {status}")
            await activate_payment(update, context, payment_status)

        elif status == 'pending':

            await update.callback_query.answer("⏳ Платеж в обработке, попробуйте позже")

        elif status == 'failed':

            await update.callback_query.answer("❌ Платеж не прошел")

        else:

            await update.callback_query.answer(f"ℹ️ Статус платежа: {status}")

            

    except Exception as e:

        import traceback
        error_traceback = traceback.format_exc()
        print(f"🔍 Ошибка в check_payment_status:")
        print(f"🔍 {error_traceback}")
        logging.error(f"Ошибка проверки статуса платежа: {e}")
        logging.error(f"Traceback: {error_traceback}")

        await update.callback_query.answer("❌ Ошибка проверки статуса")



async def activate_payment(update: Update, context: ContextTypes.DEFAULT_TYPE, payment_data: dict):

    """Активирует оплаченные кредиты"""

    user_id = update.effective_user.id

    payment_id = payment_data.get('id')

    amount = payment_data.get('amount', 0)
    # Преобразуем amount в число, если это строка
    if isinstance(amount, str):
        try:
            amount = float(amount)
        except ValueError:
            amount = 0.0
    
    print(f"🔍 activate_payment вызвана:")
    print(f"🔍 user_id: {user_id}")
    print(f"🔍 payment_id: {payment_id}")
    print(f"🔍 amount: {amount} (тип: {type(amount)})")
    print(f"🔍 amount после преобразования: {amount} (тип: {type(amount)})")

    

    try:

        # Определяем количество кредитов по сумме

        try:

            from pricing_config import CREDIT_PACKAGES

        except ImportError:

            CREDIT_PACKAGES = {

                'small': {'credits': 2000, 'price': 1129.0},

                'medium': {'credits': 5000, 'price': 2420.0},

                'large': {'credits': 10000, 'price': 4030.0}

            }

        

        # Находим подходящий пакет по цене
        print(f"🔍 Ищем подходящий пакет для суммы: {amount}")

        for package in CREDIT_PACKAGES.values():

            print(f"🔍 Проверяем пакет: {package['credits']} кредитов за {package['price']} сом")
            print(f"🔍 Разница: {abs(package['price'] - amount)}")
            if abs(package['price'] - amount) < 1.0:  # Погрешность 1 сомль

                # Проверяем, не зачислены ли уже кредиты за этот платеж
                existing_transaction = await analytics_db_get_credit_transaction_by_payment_id_async(payment_id)
                
                if existing_transaction:
                    # Кредиты уже зачислены
                    await update.callback_query.answer("✅ Кредиты уже зачислены!")
                    return
                
                # Активируем кредиты
                success = await analytics_db_add_credits_async(
                    user_id=user_id,
                    amount=package['credits'],
                    payment_id=payment_id,
                    description=f"Покупка пакета: {package['credits']} кредитов"
                )
                
                # Создаем транзакцию с привязкой к платежу
                await analytics_db_create_credit_transaction_with_payment_async(user_id, package['credits'], f"Покупка пакета: {package['credits']} кредитов", payment_id)

                

                if success:

                    text = f"✅ **Кредиты начислены!**\n\n"

                    text += f"🪙 **Получено кредитов:** {package['credits']}\n"

                    text += f"💰 **Сумма:** сом{amount:.0f}\n"

                    text += f"📦 **Пакет:** {package['credits']} кредитов\n\n"

                    text += "🎉 Теперь вы можете использовать кредиты для генераций!"

                    

                    keyboard = [

                        [InlineKeyboardButton("🎨 Создать контент", callback_data="create_content")],

                        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]

                    ]

                    

                    await update.callback_query.edit_message_text(

                        text,

                        reply_markup=InlineKeyboardMarkup(keyboard)

                    )

                    return

        

        # Если не удалось определить пакет

        await update.callback_query.answer("❌ Не удалось определить пакет кредитов")

        

    except Exception as e:

        logging.error(f"Ошибка активации кредитов: {e}")

        await update.callback_query.answer("❌ Ошибка активации кредитов")



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

        # Запускаем локально с polling

        print("🚀 Бот запущен локально с polling")
        
        # Инициализируем HTTP сессию для асинхронных запросов
        async def init_http():
            await init_http_session()
            print("✅ HTTP сессия инициализирована")
        
        asyncio.run(init_http())
        
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

        try:
            app.run_polling()
        except KeyboardInterrupt:
            # Закрываем HTTP сессию при завершении
            asyncio.run(close_http_session())
            print("✅ HTTP сессия закрыта")
            print("👋 Бот остановлен")



# ==================== СИСТЕМА ПОДДЕРЖКИ ====================

async def show_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает информацию о поддержке"""
    
    # Получаем информацию о пользователе
    user_id = update.effective_user.id
    user_info = await analytics_db_get_user_info_by_id_async(user_id)
    
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
        user_id = await analytics_db_get_user_id_by_username_async(username)
        if user_id:
            user_info = await analytics_db_get_user_info_by_id_async(user_id)
    else:
        # Попытка поиска по user_id
        try:
            user_id = int(user_identifier)
            user_info = await analytics_db_get_user_info_by_id_async(user_id)
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
    await analytics_db_set_user_credits_async(user_id, new_credits)
    
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
        user_id = await analytics_db_get_user_id_by_username_async(username)
        if user_id:
            user_info = await analytics_db_get_user_info_by_id_async(user_id)
    else:
        # Попытка поиска по user_id
        try:
            user_id = int(user_identifier)
            user_info = await analytics_db_get_user_info_by_id_async(user_id)
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
        user_id = await analytics_db_get_user_id_by_username_async(username)
        if user_id:
            user_info = await analytics_db_get_user_info_by_id_async(user_id)
    else:
        # Попытка поиска по user_id
        try:
            user_id = int(user_identifier)
            user_info = await analytics_db_get_user_info_by_id_async(user_id)
        except ValueError:
            pass
    
    if not user_id or not user_info:
        await update.message.reply_text(f"❌ Пользователь {user_identifier} не найден в базе данных.")
        return
    
    # Получаем старый баланс
    credits_data = analytics_db.get_user_credits(user_id)
    old_credits = credits_data.get('balance', 0)
    
    # Устанавливаем новые кредиты
    await analytics_db_set_user_credits_async(user_id, credits_to_set)
    
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
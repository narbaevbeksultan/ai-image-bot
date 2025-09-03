"""
Интеграция callback сервера в основной бот
"""
import asyncio
import logging
from aiohttp import web
from betatransfer_api import betatransfer_api
from database import analytics_db

def send_telegram_notification(user_id: int, message: str):
    """
    Отправляет уведомление пользователю в Telegram
    """
    try:
        import os
        import requests
        
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
        
        response = requests.post(url, data=data, timeout=10)
        
        if response.status_code == 200:
            logging.info(f"Уведомление отправлено пользователю {user_id}")
            return True
        else:
            logging.error(f"Ошибка отправки уведомления: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logging.error(f"Ошибка отправки уведомления пользователю {user_id}: {e}")
        return False

async def webhook_handler(request):
    """Обработчик webhook с поддержкой callback"""
    try:
        path = request.path
        
        if path == "/payment/ca":
            # Callback от Betatransfer
            form_data = await request.post()
            callback_data = dict(form_data)
            
            logging.info(f"Получен callback: {callback_data}")
            
            # Обрабатываем callback
            result = betatransfer_api.process_callback(callback_data)
            
            if result.get("status") == "success":
                payment_info = result.get("payment_info", {})
                status = payment_info.get("status")
                
                if status == "completed":
                    order_id = payment_info.get("order_id")
                    payment_record = analytics_db.get_payment_by_order_id(order_id)
                    
                    if payment_record:
                        user_id = payment_record.get("user_id")
                        credit_amount = payment_record.get("credit_amount")
                        
                        # Зачисляем кредиты
                        analytics_db.add_credits(user_id, credit_amount)
                        analytics_db.update_payment_status(payment_info.get("payment_id"), "completed")
                        
                        # Отправляем уведомление
                        notification_message = (
                            f"✅ **Кредиты зачислены!**\n\n"
                            f"🪙 **Получено:** {credit_amount:,} кредитов\n"
                            f"💰 **Сумма:** {payment_info.get('amount')} {payment_info.get('currency', 'RUB')}\n"
                            f"📦 **Платеж:** {payment_info.get('payment_id')}\n\n"
                            f"Теперь вы можете использовать кредиты для генерации изображений!"
                        )
                        send_telegram_notification(user_id, notification_message)
                        logging.info(f"Кредиты зачислены пользователю {user_id}: {credit_amount}")
            
            return web.json_response({"status": "success"})
        
        elif path == "/payment/su":
            return web.json_response({"status": "success", "message": "Payment completed successfully"})
        
        elif path == "/payment/fai":
            return web.json_response({"status": "failed", "message": "Payment failed"})
        
        elif path == "/health":
            return web.json_response({"status": "healthy"})
        
        else:
            return web.Response(text="Not Found", status=404)
            
    except Exception as e:
        logging.error(f"Ошибка обработки webhook: {e}")
        return web.Response(text="Internal Server Error", status=500)

def create_callback_app():
    """Создает aiohttp приложение для callback"""
    app = web.Application()
    app.router.add_post("/payment/ca", webhook_handler)
    app.router.add_get("/payment/su", webhook_handler)
    app.router.add_get("/payment/fai", webhook_handler)
    app.router.add_get("/health", webhook_handler)
    return app

async def start_callback_server(port=5000):
    """Запускает callback сервер"""
    app = create_callback_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"Callback сервер запущен на порту {port}")
    return runner

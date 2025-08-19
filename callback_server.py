from flask import Flask, request, jsonify
from betatransfer_api import BetatransferAPI
from database import AnalyticsDB
import os
from dotenv import load_dotenv
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)
betatransfer_api = BetatransferAPI()
db = AnalyticsDB()

@app.route('/payment/callback', methods=['POST'])
def payment_callback():
    """
    Обрабатывает callback уведомления от Betatransfer
    """
    try:
        # Получаем данные callback (формат: application/x-www-form-urlencoded)
        callback_data = request.form.to_dict()
        logger.info(f"Получен callback: {callback_data}")
        
        if not callback_data:
            logger.error("Пустые данные callback")
            return jsonify({"error": "Empty callback data"}), 400
        
        # Обрабатываем callback через API
        result = betatransfer_api.process_callback(callback_data)
        
        if result.get("status") == "error":
            logger.error(f"Ошибка обработки callback: {result.get('error')}")
            return jsonify({"error": result.get("error")}), 400
        
        # Извлекаем информацию о платеже
        payment_info = result.get("payment_info", {})
        payment_id = payment_info.get("payment_id")
        status = payment_info.get("status")
        amount = payment_info.get("amount")
        order_id = payment_info.get("order_id")
        
        logger.info(f"Платеж {payment_id} обработан, статус: {status}")
        
        # Если платеж успешен, зачисляем кредиты
        if status == "completed":
            # Получаем информацию о заказе из базы
            payment_record = db.get_payment_by_order_id(order_id)
            if payment_record:
                user_id = payment_record.get("user_id")
                credit_amount = payment_record.get("credit_amount")
                
                # Зачисляем кредиты пользователю
                db.add_credits(user_id, credit_amount)
                
                # Обновляем статус платежа
                db.update_payment_status(payment_id, "completed")
                
                logger.info(f"Кредиты зачислены пользователю {user_id}: {credit_amount}")
                
                # Отправляем уведомление пользователю (можно реализовать позже)
                # await bot.send_message(user_id, f"✅ Кредиты зачислены: {credit_amount}")
        
        # Возвращаем 200 OK (требование Betatransfer)
        return jsonify({"status": "success"}), 200
        
    except Exception as e:
        logger.error(f"Ошибка обработки callback: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/payment/success', methods=['GET'])
def payment_success():
    """
    Страница успешной оплаты
    """
    return jsonify({
        "status": "success",
        "message": "Payment completed successfully"
    })

@app.route('/payment/fail', methods=['GET'])
def payment_fail():
    """
    Страница неуспешной оплаты
    """
    return jsonify({
        "status": "failed",
        "message": "Payment failed"
    })

@app.route('/health', methods=['GET'])
def health_check():
    """
    Проверка здоровья сервера
    """
    return jsonify({"status": "healthy"})

if __name__ == '__main__':
    # Получаем порт из переменной окружения или используем 5000
    port = int(os.getenv('PORT', 5000))
    
    logger.info(f"Callback сервер запущен на порту {port}")
    logger.info("URL для callback: http://localhost:{}/payment/callback".format(port))
    
    app.run(host='0.0.0.0', port=port, debug=False)

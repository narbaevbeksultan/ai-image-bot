import requests
import hashlib
import time
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
import os
from dotenv import load_dotenv

load_dotenv()

class BetatransferAPI:
    """Класс для работы с Betatransfer API"""
    
    def __init__(self):
        self.api_key = os.getenv('BETATRANSFER_API_KEY')
        self.secret_key = os.getenv('BETATRANSFER_SECRET_KEY')
        self.test_mode = os.getenv('BETATRANSFER_TEST_MODE', 'false').lower() == 'true'
        
        # Используем продакшн URL согласно документации
        self.base_url = "https://merchant.betatransfer.io/api"
    
    def _generate_signature(self, data: Dict) -> str:
        """
        Генерирует подпись для запроса согласно документации Betatransfer
        Алгоритм: md5(implode('', $data) . $secret)
        """
        # Создаем строку из всех значений (без ключей) + секретный ключ
        # Согласно документации: md5(implode('', $data) . $secret)
        # Фильтруем None значения перед созданием подписи
        signature_string = ''.join(str(v) for v in data.values() if v is not None) + self.secret_key
        
        # Создаем MD5 подпись
        signature = hashlib.md5(signature_string.encode('utf-8')).hexdigest()
        
        return signature
    
    def create_payment(self, amount: float, currency: str = "KGS", 
                       description: str = "", order_id: str = None, 
                       payer_email: str = "", payer_name: str = "",
                       payer_id: str = "") -> Dict:
        """
        Создает платеж для покупки кредитов
        
        Args:
            amount: Сумма платежа
            currency: Валюта (KGS, UAH, USD, RUB, KZT, etc.)
            description: Описание платежа
            order_id: Уникальный ID заказа
            payer_email: Email плательщика
            payer_name: Имя плательщика
            payer_id: ID плательщика (для антифрода)
        
        Returns:
            Dict с информацией о платеже
        """
        # Генерируем order_id если не передан
        if not order_id:
            order_id = f"order{int(time.time())}"
        
        # Формируем данные запроса согласно документации Betatransfer
        payload = {
            'amount': str(amount),
            'currency': currency,
            'orderId': order_id,
            'paymentSystem': 'P2R_KGS',
            'payerId': str(payer_id)
        }
        
        # Добавляем параметры пользователя только если они не пустые
        if payer_email:
            payload['payerEmail'] = payer_email
        if payer_name:
            payload['payerName'] = payer_name
        
        # Генерируем подпись ПЕРЕД добавлением в payload
        payload['sign'] = self._generate_signature(payload)
        
        # URL с токеном согласно документации
        endpoint = f"{self.base_url}/payment?token={self.api_key}"
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        try:
            logging.info(f"🔍 Создаем платеж: {amount} {currency}, Order ID: {order_id}")
            
            # Отправляем как form-data согласно документации
            response = requests.post(endpoint, data=payload, headers=headers)
            
            response.raise_for_status()
            result = response.json()
            
            # Логируем результат создания платежа
            if 'id' in result:
                logging.info(f"🔍 Платеж создан успешно:")
                logging.info(f"   ID платежа: {result['id']}")
                logging.info(f"   Сумма: {result.get('amount', amount)} {result.get('currency', currency)}")
                logging.info(f"   Статус: {result.get('status', 'created')}")
            else:
                logging.warning(f"🔍 Платеж создан, но без ID: {result}")
            
            return result
        except requests.exceptions.RequestException as e:
            logging.error(f"❌ Ошибка HTTP запроса при создании платежа: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                logging.error(f"Статус ответа: {e.response.status_code}, Тело: {e.response.text}")
            return {"error": str(e)}
    
    def get_payment_status(self, payment_id: str) -> Dict:
        """
        Получает статус платежа согласно документации Betatransfer
        
        Args:
            payment_id: ID платежа
        
        Returns:
            Dict с информацией о статусе
        """
        logging.info(f"🔍 get_payment_status вызван с ID: {payment_id}")
        
        # Формируем данные для подписи
        data = {'id': payment_id}
        signature = self._generate_signature(data)
        
        # URL с токеном согласно документации
        endpoint = f"{self.base_url}/info?token={self.api_key}"
        
        # Добавляем подпись к данным
        data['sign'] = signature
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        try:
            logging.info(f"🔍 Отправляем запрос статуса платежа {payment_id}")
            response = requests.post(endpoint, data=data, headers=headers)
            
            response.raise_for_status()
            result = response.json()
            
            # Логируем детали ответа
            status = result.get('status', 'unknown')
            amount = result.get('amount', 'N/A')
            currency = result.get('currency', 'N/A')
            order_id = result.get('orderId', 'N/A')
            
            logging.info(f"🔍 Получен ответ для платежа {payment_id}:")
            logging.info(f"   Статус: {status}")
            logging.info(f"   Сумма: {amount} {currency}")
            logging.info(f"   Order ID: {order_id}")
            
            return result
        except requests.exceptions.RequestException as e:
            logging.error(f"❌ Ошибка HTTP запроса статуса платежа {payment_id}: {e}")
            return {"error": str(e)}
        except Exception as e:
            logging.error(f"❌ Общая ошибка при получении статуса платежа {payment_id}: {e}")
            return {"error": str(e)}
    
    def verify_callback_signature(self, data: Dict, signature: str) -> bool:
        """
        Проверяет подпись callback уведомления согласно документации Betatransfer
        Для успешного платежа: md5($amount . $orderId . $secret)
        
        Args:
            data: Данные callback
            signature: Подпись для проверки
        
        Returns:
            True если подпись верна, False иначе
        """
        # Согласно документации для успешного платежа:
        # md5($amount . $orderId . $secret)
        amount = data.get('amount', '')
        order_id = data.get('orderId', '')
        
        # Создаем строку для подписи согласно документации
        signature_string = str(amount) + str(order_id) + self.secret_key
        
        # Создаем MD5 подпись
        expected_signature = hashlib.md5(signature_string.encode('utf-8')).hexdigest()
        
        is_valid = signature == expected_signature
        
        # Логируем только в случае неверной подписи
        if not is_valid:
            logging.warning(f"Неверная подпись callback: ожидалось {expected_signature}, получено {signature}")
        
        return is_valid
    
    def process_callback(self, callback_data: Dict) -> Dict:
        """
        Обрабатывает callback уведомление от Betatransfer
        
        Args:
            callback_data: Данные callback
        
        Returns:
            Dict с результатом обработки
        """
        # Проверяем подпись
        signature = callback_data.get('sign', '')
        if not self.verify_callback_signature(callback_data, signature):
            return {"error": "Invalid signature", "status": "error"}
        
        # Извлекаем данные платежа согласно формату Betatransfer
        payment_info = {
            "payment_id": callback_data.get('id'),
            "payment_system": callback_data.get('paymentSystem'),
            "type": callback_data.get('type'),
            "order_id": callback_data.get('orderId'),
            "order_amount": callback_data.get('orderAmount'),
            "paid_amount": callback_data.get('paidAmount'),
            "amount": callback_data.get('amount'),
            "currency": callback_data.get('currency'),
            "commission": callback_data.get('commission'),
            "status": callback_data.get('status'),
            "created_at": callback_data.get('createdAt'),
            "updated_at": callback_data.get('updatedAt'),
            "exchange_rate": callback_data.get('exchangeRate'),
            "receiver_wallet": callback_data.get('receiverWallet'),
            "beneficiary_name": callback_data.get('beneficiaryName'),
            "beneficiary_bank": callback_data.get('beneficiaryBank')
        }
        
        return {
            "success": True,
            "payment_info": payment_info,
            "status": "success"
        }
    
    def get_payment_url(self, payment_id: str) -> str:
        """
        Получает URL для оплаты
        
        Args:
            payment_id: ID платежа
        
        Returns:
            URL для оплаты
        """
        return f"https://merchant.betatransfer.io/pay/{payment_id}"
    
    def test_connection(self) -> Dict:
        """
        Тестирует подключение к API
        
        Returns:
            Dict с результатом теста
        """
        # Пробуем простой GET запрос к базовому URL
        endpoint = f"{self.base_url}/"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.get(endpoint, headers=headers)
            if response.status_code == 200:
                return {"success": True, "message": "API connection successful"}
            else:
                return {"success": False, "message": f"API error: {response.status_code}"}
        except requests.exceptions.RequestException as e:
            return {"success": False, "message": f"Connection error: {str(e)}"}

# Глобальный экземпляр API
betatransfer_api = BetatransferAPI()




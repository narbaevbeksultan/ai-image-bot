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
        """
        # Сортируем параметры по ключам
        sorted_params = sorted(data.items())
        
        # Создаем строку для подписи: все параметры подряд + секретный ключ
        # Фильтруем None значения и конвертируем в строки
        signature_string = ''.join(str(v) if v is not None else '' for _, v in sorted_params) + self.secret_key
        
        # Создаем MD5 подпись
        return hashlib.md5(signature_string.encode('utf-8')).hexdigest()
    
    def create_payment(self, amount: float, currency: str = "UAH", 
                       description: str = "", order_id: str = None, 
                       payer_email: str = "", payer_name: str = "",
                       payer_id: str = "") -> Dict:
        """
        Создает платеж для покупки кредитов
        
        Args:
            amount: Сумма платежа
            currency: Валюта (UAH, USD, RUB, KZT, etc.)
            description: Описание платежа
            order_id: Уникальный ID заказа
            payer_email: Email плательщика
            payer_name: Имя плательщика
            payer_id: ID плательщика (для антифрода)
        
        Returns:
            Dict с информацией о платеже
        """
        endpoint = f"{self.base_url}/payment"
        
        # Генерируем order_id если не передан
        if not order_id:
            order_id = f"order{int(time.time())}"
        
        # Формируем данные запроса согласно документации
        payload = {
            'amount': str(amount),
            'currency': currency,
            'fullCallback': '1',
            'orderId': order_id,
            'paymentSystem': 'card',  # По умолчанию карта
            'urlFail': os.getenv('WEBHOOK_BASE_URL', '') + "/payment/fail",
            'urlResult': os.getenv('WEBHOOK_BASE_URL', '') + "/payment/callback",
            'urlSuccess': os.getenv('WEBHOOK_BASE_URL', '') + "/payment/success"
        }
        
        # Добавляем параметры пользователя только если они не пустые
        if payer_email:
            payload['payerEmail'] = payer_email
        if payer_id:
            payload['payerId'] = payer_id
        if payer_name:
            payload['payerName'] = payer_name
        
        # Генерируем подпись
        payload['sign'] = self._generate_signature(payload)
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        try:
            print(f"🔍 Детали запроса:")
            print(f"   URL: {endpoint}")
            print(f"   Заголовки: {headers}")
            print(f"   Данные: {payload}")
            
            # Отправляем как form-data согласно документации
            response = requests.post(endpoint, data=payload, headers=headers)
            
            print(f"🔍 Детали ответа:")
            print(f"   Статус: {response.status_code}")
            print(f"   Заголовки ответа: {dict(response.headers)}")
            print(f"   Тело ответа: {response.text}")
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ Ошибка HTTP запроса: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"   Статус ответа: {e.response.status_code}")
                print(f"   Тело ответа: {e.response.text}")
            return {"error": str(e)}
    
    def get_payment_status(self, payment_id: str) -> Dict:
        """
        Получает статус платежа
        
        Args:
            payment_id: ID платежа
        
        Returns:
            Dict с информацией о статусе
        """
        endpoint = f"{self.base_url}/payment/{payment_id}"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.get(endpoint, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}
    
    def verify_callback_signature(self, data: Dict, signature: str) -> bool:
        """
        Проверяет подпись callback уведомления
        
        Args:
            data: Данные callback
            signature: Подпись для проверки
        
        Returns:
            True если подпись верна, False иначе
        """
        # Убираем поле sign из данных для проверки
        params = {k: v for k, v in data.items() if k != 'sign'}
        
        # Сортируем параметры по ключам (как в запросе)
        sorted_params = sorted(params.items())
        
        # Создаем строку для подписи: все параметры подряд + секретный ключ
        # Важно: используем только значения, без ключей
        signature_string = ''.join(str(v) for _, v in sorted_params) + self.secret_key
        
        # Создаем MD5 подпись
        expected_signature = hashlib.md5(signature_string.encode('utf-8')).hexdigest()
        
        # Добавляем отладочную информацию
        print(f"🔍 Отладочная информация:")
        print(f"   Параметры: {sorted_params}")
        print(f"   Строка для подписи: {signature_string}")
        print(f"   Ожидаемая подпись: {expected_signature}")
        print(f"   Полученная подпись: {signature}")
        
        return signature == expected_signature
    
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




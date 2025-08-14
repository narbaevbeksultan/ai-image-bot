import requests
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
import os

class BetatransferAPI:
    """Класс для работы с Betatransfer API"""
    
    def __init__(self, api_key: str = None, secret_key: str = None, is_test: bool = True):
        self.api_key = api_key or os.getenv('BETATRANSFER_API_KEY')
        self.secret_key = secret_key or os.getenv('BETATRANSFER_SECRET_KEY')
        self.is_test = is_test
        
        # Базовые URL для API
        if is_test:
            self.base_url = "https://test-api.betatransfer.com"
        else:
            self.base_url = "https://api.betatransfer.com"
        
        # URL для callback (ваш бот)
        self.callback_base_url = "https://your-bot-domain.com"  # Замените на ваш домен
        
        logging.info(f"Betatransfer API инициализирован: {'тестовый' if is_test else 'продакшн'} режим")
    
    def create_payment(self, amount: float, currency: str = "RUB", description: str = "", 
                      order_id: str = None, user_id: int = None) -> Dict:
        """
        Создание платежа
        
        Args:
            amount: Сумма платежа
            currency: Валюта (RUB, USD, EUR)
            description: Описание платежа
            order_id: Уникальный ID заказа
            user_id: ID пользователя Telegram
        
        Returns:
            Dict с данными платежа или ошибкой
        """
        try:
            if not self.api_key:
                return {"error": "API ключ не настроен"}
            
            # Генерируем уникальный ID заказа если не передан
            if not order_id:
                order_id = f"order_{user_id}_{int(datetime.now().timestamp())}"
            
            # Формируем callback URL
            success_url = f"{self.callback_base_url}/payment_success?order_id={order_id}"
            fail_url = f"{self.callback_base_url}/payment_fail?order_id={order_id}"
            
            payload = {
                "amount": amount,
                "currency": currency,
                "description": description,
                "order_id": order_id,
                "success_url": success_url,
                "fail_url": fail_url,
                "callback_url": f"{self.callback_base_url}/webhook",  # URL для уведомлений
                "metadata": {
                    "user_id": user_id,
                    "bot_type": "telegram",
                    "service": "ai_image_generator"
                }
            }
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            logging.info(f"Создаем платеж: {amount} {currency} для пользователя {user_id}")
            
            response = requests.post(
                f"{self.base_url}/payments",
                json=payload,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                logging.info(f"Платеж создан успешно: {result.get('payment_id')}")
                return result
            else:
                error_msg = f"Ошибка создания платежа: {response.status_code} - {response.text}"
                logging.error(error_msg)
                return {"error": error_msg}
                
        except Exception as e:
            error_msg = f"Исключение при создании платежа: {str(e)}"
            logging.error(error_msg)
            return {"error": error_msg}
    
    def get_payment_status(self, payment_id: str) -> Dict:
        """
        Получение статуса платежа
        
        Args:
            payment_id: ID платежа в Betatransfer
        
        Returns:
            Dict с статусом платежа
        """
        try:
            if not self.api_key:
                return {"error": "API ключ не настроен"}
            
            headers = {"Authorization": f"Bearer {self.api_key}"}
            
            response = requests.get(
                f"{self.base_url}/payments/{payment_id}",
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                logging.info(f"Статус платежа {payment_id}: {result.get('status')}")
                return result
            else:
                error_msg = f"Ошибка получения статуса: {response.status_code} - {response.text}"
                logging.error(error_msg)
                return {"error": error_msg}
                
        except Exception as e:
            error_msg = f"Исключение при получении статуса: {str(e)}"
            logging.error(error_msg)
            return {"error": error_msg}
    
    def verify_webhook(self, data: Dict, signature: str) -> bool:
        """
        Проверка подписи webhook от Betatransfer
        
        Args:
            data: Данные webhook
            signature: Подпись для проверки
        
        Returns:
            True если подпись верна, False иначе
        """
        try:
            if not self.secret_key:
                logging.error("Секретный ключ не настроен для проверки webhook")
                return False
            
            # Создаем подпись из данных
            expected_signature = hmac.new(
                self.secret_key.encode('utf-8'),
                json.dumps(data, separators=(',', ':'), sort_keys=True).encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            # Сравниваем подписи
            is_valid = hmac.compare_digest(signature, expected_signature)
            
            if is_valid:
                logging.info("Webhook подпись проверена успешно")
            else:
                logging.warning("Webhook подпись неверна")
            
            return is_valid
            
        except Exception as e:
            logging.error(f"Ошибка проверки webhook подписи: {str(e)}")
            return False
    
    def process_webhook(self, webhook_data: Dict, signature: str) -> Dict:
        """
        Обработка webhook от Betatransfer
        
        Args:
            webhook_data: Данные webhook
            signature: Подпись webhook
        
        Returns:
            Dict с результатом обработки
        """
        try:
            # Проверяем подпись
            if not self.verify_webhook(webhook_data, signature):
                return {"error": "Неверная подпись webhook"}
            
            # Извлекаем данные
            payment_id = webhook_data.get('payment_id')
            status = webhook_data.get('status')
            order_id = webhook_data.get('order_id')
            amount = webhook_data.get('amount')
            currency = webhook_data.get('currency')
            
            logging.info(f"Обрабатываем webhook: платеж {payment_id}, статус {status}")
            
            # Обрабатываем успешный платеж
            if status == 'completed':
                return {
                    "success": True,
                    "payment_id": payment_id,
                    "order_id": order_id,
                    "amount": amount,
                    "currency": currency,
                    "status": status
                }
            elif status == 'failed':
                return {
                    "success": False,
                    "payment_id": payment_id,
                    "order_id": order_id,
                    "status": status,
                    "error": "Платеж не прошел"
                }
            else:
                return {
                    "success": False,
                    "payment_id": payment_id,
                    "status": status,
                    "error": f"Неизвестный статус: {status}"
                }
                
        except Exception as e:
            error_msg = f"Ошибка обработки webhook: {str(e)}"
            logging.error(error_msg)
            return {"error": error_msg}
    
    def get_payment_url(self, payment_id: str) -> str:
        """
        Получение URL для оплаты
        
        Args:
            payment_id: ID платежа в Betatransfer
        
        Returns:
            URL для перехода к оплате
        """
        return f"{self.base_url}/pay/{payment_id}"
    
    def test_connection(self) -> bool:
        """
        Тестирование подключения к API
        
        Returns:
            True если подключение успешно, False иначе
        """
        try:
            if not self.api_key:
                logging.error("API ключ не настроен")
                return False
            
            # Пробуем получить информацию об аккаунте
            headers = {"Authorization": f"Bearer {self.api_key}"}
            
            response = requests.get(
                f"{self.base_url}/account",
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                logging.info("Подключение к Betatransfer API успешно")
                return True
            else:
                logging.error(f"Ошибка подключения: {response.status_code}")
                return False
                
        except Exception as e:
            logging.error(f"Ошибка тестирования подключения: {str(e)}")
            return False

# Глобальный экземпляр API
betatransfer_api = BetatransferAPI()

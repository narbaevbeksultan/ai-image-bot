# Техническая интеграция с Betatransfer

## 🔧 Архитектура интеграции

### Компоненты системы:
1. **Betatransfer API** - обработка платежей
2. **База данных** - хранение подписок и лимитов
3. **Telegram Bot** - интерфейс пользователя
4. **Система лимитов** - контроль использования

## 📋 План реализации

### Этап 1: Расширение базы данных

#### Новые таблицы:

```sql
-- Таблица подписок
CREATE TABLE subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    plan_type TEXT, -- 'basic', 'pro', 'premium'
    status TEXT, -- 'active', 'expired', 'cancelled'
    start_date TIMESTAMP,
    end_date TIMESTAMP,
    monthly_generations INTEGER,
    used_generations INTEGER DEFAULT 0,
    payment_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);

-- Таблица платежей
CREATE TABLE payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    subscription_id INTEGER,
    amount DECIMAL(10,2),
    currency TEXT DEFAULT 'RUB',
    status TEXT, -- 'pending', 'completed', 'failed'
    betatransfer_id TEXT,
    payment_method TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (user_id),
    FOREIGN KEY (subscription_id) REFERENCES subscriptions (id)
);

-- Таблица лимитов пользователей
CREATE TABLE user_limits (
    user_id INTEGER PRIMARY KEY,
    daily_generations INTEGER DEFAULT 5,
    monthly_generations INTEGER DEFAULT 50,
    used_daily INTEGER DEFAULT 0,
    used_monthly INTEGER DEFAULT 0,
    last_daily_reset DATE,
    last_monthly_reset DATE,
    is_premium BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);
```

### Этап 2: Интеграция с Betatransfer API

#### Основные функции:

```python
import requests
import hashlib
import hmac
import json
from datetime import datetime, timedelta

class BetatransferAPI:
    def __init__(self, api_key, secret_key, is_test=True):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = "https://api.betatransfer.com" if not is_test else "https://test-api.betatransfer.com"
    
    def create_payment(self, amount, currency="RUB", description="", order_id=None):
        """Создание платежа"""
        payload = {
            "amount": amount,
            "currency": currency,
            "description": description,
            "order_id": order_id or f"order_{datetime.now().timestamp()}",
            "success_url": "https://t.me/your_bot_username?start=payment_success",
            "fail_url": "https://t.me/your_bot_username?start=payment_fail"
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(f"{self.base_url}/payments", json=payload, headers=headers)
        return response.json()
    
    def verify_webhook(self, data, signature):
        """Проверка webhook подписи"""
        expected_signature = hmac.new(
            self.secret_key.encode(),
            json.dumps(data, separators=(',', ':')).encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(signature, expected_signature)
    
    def get_payment_status(self, payment_id):
        """Получение статуса платежа"""
        headers = {"Authorization": f"Bearer {self.api_key}"}
        response = requests.get(f"{self.base_url}/payments/{payment_id}", headers=headers)
        return response.json()
```

### Этап 3: Система подписок

#### Класс управления подписками:

```python
class SubscriptionManager:
    def __init__(self, db):
        self.db = db
    
    def get_user_plan(self, user_id):
        """Получение текущего плана пользователя"""
        # Логика получения активной подписки
        pass
    
    def check_generation_limit(self, user_id):
        """Проверка лимита генераций"""
        # Проверка дневных и месячных лимитов
        pass
    
    def increment_generation_count(self, user_id):
        """Увеличение счетчика генераций"""
        # Обновление счетчиков
        pass
    
    def create_subscription(self, user_id, plan_type, payment_id):
        """Создание новой подписки"""
        # Создание записи в базе данных
        pass
```

### Этап 4: Обновление интерфейса бота

#### Новые команды и кнопки:

```python
# Команда для просмотра подписки
async def subscription_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    subscription = subscription_manager.get_user_plan(user_id)
    
    if subscription:
        text = f"""
💎 Ваша подписка: {subscription['plan_type']}
📅 Действует до: {subscription['end_date']}
🎨 Осталось генераций: {subscription['monthly_generations'] - subscription['used_generations']}
        """
    else:
        text = """
🆓 У вас бесплатный план
🎨 Генераций в день: 5
📅 Генераций в месяц: 50

💡 Перейдите на платный план для большего количества генераций!
        """
    
    keyboard = [
        [InlineKeyboardButton("💎 Планы подписки", callback_data="subscription_plans")],
        [InlineKeyboardButton("📊 Статистика", callback_data="user_stats")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# Обработчик выбора плана
async def show_subscription_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎯 Базовый - 299₽/мес", callback_data="subscribe_basic")],
        [InlineKeyboardButton("🚀 Продвинутый - 599₽/мес", callback_data="subscribe_pro")],
        [InlineKeyboardButton("💎 Премиум - 999₽/мес", callback_data="subscribe_premium")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    text = """
💎 Выберите план подписки:

🎯 **Базовый план - 299₽/месяц**
• 100 генераций в месяц
• Все модели генерации
• Все форматы
• Приоритетная поддержка

🚀 **Продвинутый план - 599₽/месяц**
• 300 генераций в месяц
• Редактирование изображений
• Экспорт в высоком качестве
• API доступ

💎 **Премиум план - 999₽/месяц**
• 1000 генераций в месяц
• Приоритетная генерация
• Персональный менеджер
• Кастомные модели
    """
    
    await update.callback_query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard)
    )
```

### Этап 5: Webhook обработчик

```python
# Webhook для Betatransfer
async def betatransfer_webhook(request):
    """Обработка webhook от Betatransfer"""
    try:
        data = await request.json()
        signature = request.headers.get('X-Signature')
        
        # Проверяем подпись
        if not betatransfer_api.verify_webhook(data, signature):
            return web.Response(status=400, text="Invalid signature")
        
        payment_id = data.get('payment_id')
        status = data.get('status')
        order_id = data.get('order_id')
        
        if status == 'completed':
            # Активируем подписку
            user_id = extract_user_id_from_order(order_id)
            plan_type = extract_plan_from_order(order_id)
            
            subscription_manager.create_subscription(user_id, plan_type, payment_id)
            
            # Уведомляем пользователя
            await context.bot.send_message(
                chat_id=user_id,
                text="✅ Оплата прошла успешно! Ваша подписка активирована."
            )
        
        return web.Response(status=200, text="OK")
        
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return web.Response(status=500, text="Internal error")
```

## 🔐 Безопасность

### Меры безопасности:
1. **Проверка подписи webhook** - защита от подделки
2. **Валидация данных** - проверка всех входящих данных
3. **Логирование** - запись всех операций
4. **Rate limiting** - ограничение частоты запросов
5. **Шифрование** - защита чувствительных данных

### Переменные окружения:
```env
BETATRANSFER_API_KEY=your_api_key
BETATRANSFER_SECRET_KEY=your_secret_key
BETATRANSFER_TEST_MODE=true
WEBHOOK_SECRET=your_webhook_secret
```

## 📊 Мониторинг

### Метрики для отслеживания:
- Количество успешных/неуспешных платежей
- Конверсия в платные планы
- Средний чек
- Время обработки платежей
- Ошибки интеграции

### Логирование:
```python
def log_payment_event(event_type, user_id, amount, status, error=None):
    """Логирование событий платежей"""
    log_data = {
        "event_type": event_type,
        "user_id": user_id,
        "amount": amount,
        "status": status,
        "timestamp": datetime.now().isoformat(),
        "error": error
    }
    logging.info(f"Payment event: {json.dumps(log_data)}")
```

## 🚀 План развертывания

### Этап 1: Тестирование (1 неделя)
- [ ] Настройка тестового окружения Betatransfer
- [ ] Создание тестовых платежей
- [ ] Проверка webhook обработчиков
- [ ] Тестирование системы лимитов

### Этап 2: Пробный запуск (1 неделя)
- [ ] Запуск для ограниченной группы пользователей
- [ ] Мониторинг ошибок
- [ ] Корректировка тарифов
- [ ] Оптимизация UX

### Этап 3: Полный запуск (1 неделя)
- [ ] Переключение на продакшн Betatransfer
- [ ] Обновление всех пользователей
- [ ] Маркетинговая кампания
- [ ] Мониторинг и поддержка

## 💡 Рекомендации

1. **Начните с тестового режима** - протестируйте все сценарии
2. **Используйте webhook** - для мгновенного обновления статуса
3. **Логируйте все операции** - для отладки и аналитики
4. **Предусмотрите fallback** - на случай недоступности Betatransfer
5. **Создайте FAQ** - для пользователей по вопросам оплаты
6. **Настройте уведомления** - о важных событиях платежей

---

*Данный план обеспечивает безопасную и надежную интеграцию с Betatransfer для монетизации Telegram бота.*


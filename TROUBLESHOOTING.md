# 🔧 Диагностика и устранение проблем с ботом

## 🚨 Проблема: Ни одна функция бота не работает, нет генерации

### 📋 Шаг 1: Проверка переменных окружения

Убедитесь, что в Railway Dashboard установлены все необходимые переменные:

**Обязательные переменные:**
- `TELEGRAM_BOT_TOKEN` - токен вашего Telegram бота
- `REPLICATE_API_TOKEN` - токен Replicate API  
- `OPENAI_API_KEY` - ключ OpenAI API

### 📋 Шаг 2: Запуск диагностического скрипта

1. Запустите тестовый скрипт локально:
```bash
python test_api.py
```

2. Или проверьте в Railway Dashboard:
   - Перейдите в раздел "Variables"
   - Убедитесь, что все переменные установлены
   - Проверьте логи на наличие ошибок

### 📋 Шаг 3: Проверка API ключей

#### Replicate API
1. Перейдите на https://replicate.com/account/billing
2. Убедитесь, что у вас есть кредиты
3. Проверьте API токен на https://replicate.com/account/api-tokens

#### OpenAI API
1. Перейдите на https://platform.openai.com/account/billing
2. Убедитесь, что у вас есть кредиты
3. Проверьте API ключ на https://platform.openai.com/api-keys

#### Telegram Bot
1. Убедитесь, что бот не заблокирован
2. Проверьте токен у @BotFather

### 📋 Шаг 4: Проверка логов Railway

1. В Railway Dashboard перейдите в раздел "Deployments"
2. Выберите последний деплой
3. Проверьте логи на наличие ошибок

### 📋 Шаг 5: Тестирование команд

Отправьте боту следующие команды для диагностики:

- `/start` - проверка базовой работы
- `/check_replicate` - проверка Replicate API
- `/test_ideogram` - тест генерации изображений
- `/help` - проверка меню

### 🐛 Частые проблемы и решения

#### 1. "REPLICATE_API_TOKEN не найден"
**Решение:** Добавьте переменную в Railway Dashboard

#### 2. "Недостаточно кредитов на Replicate"
**Решение:** Пополните баланс на https://replicate.com/account/billing

#### 3. "Ошибка авторизации OpenAI"
**Решение:** Проверьте API ключ и баланс на https://platform.openai.com/account/billing

#### 4. Бот не отвечает на команды
**Решение:** 
- Проверьте логи Railway
- Убедитесь, что webhook настроен правильно
- Проверьте, что бот не заблокирован

### 🔍 Дополнительная диагностика

#### Проверка webhook
```bash
curl -X GET "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

#### Проверка статуса бота
```bash
curl -X GET "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getMe"
```

### 📞 Получение помощи

Если проблема не решается:

1. Проверьте логи Railway Dashboard
2. Запустите `test_api.py` локально
3. Убедитесь, что все API ключи действительны
4. Проверьте балансы всех сервисов

### 💡 Профилактика

1. Регулярно проверяйте балансы API сервисов
2. Мониторьте логи Railway
3. Используйте команду `/check_replicate` для проверки статуса
4. Следите за обновлениями API сервисов


# 📋 Инструкция по добавлению команды `/credits_stats`

## 🎯 **Что нужно сделать:**

Добавить команду `/credits_stats` в бота, которая будет показывать статистику по кредитам.

## 📝 **Шаг 1: Добавить функцию в bot.py**

Найдите в файле `bot.py` функцию `my_id_command` (примерно строка 1502) и после неё добавьте:

```python
async def credits_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для просмотра статистики по кредитам (только для админа)"""
    
    # Проверяем, что это вы (замените на ваш Telegram ID)
    ADMIN_USER_ID = 7735323051  # Замените на ваш ID
    
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("❌ У вас нет доступа к этой команде.")
        return
    
    try:
        # Получаем общую статистику по кредитам
        stats = analytics_db.get_total_credits_statistics()
        
        # Формируем текст статистики
        stats_text = f"""🪙 **СТАТИСТИКА КРЕДИТОВ БОТА**

📊 **ОБЩАЯ СТАТИСТИКА:**
• 👥 Пользователей с кредитами: {stats['total_users']}
• 🪙 Всего куплено кредитов: {stats['total_purchased']:,}
• 💸 Всего использовано кредитов: {stats['total_used']:,}
• 💰 Текущий баланс кредитов: {stats['total_balance']:,}

💰 **ФИНАНСОВАЯ СТАТИСТИКА:**
• 📈 Всего платежей: {stats['total_payments']}
• ✅ Завершенных платежей: {stats['completed_payments']}
• 💵 Общая выручка: ₽{stats['total_revenue']:,.2f}
• 💵 Выручка с завершенных: ₽{stats['completed_revenue']:,.2f}

🔄 **ТРАНЗАКЦИИ:**
• 📝 Всего транзакций: {stats['total_transactions']}
• ➕ Покупки: {stats['total_purchased_transactions']:,}
• ➖ Использование: {stats['total_used_transactions']:,}

💡 **ДЛЯ ПОПОЛНЕНИЯ REPLICATE/OPENAI:**
🔥 Общее количество купленных кредитов: **{stats['total_purchased']:,}**
💰 Необходимо пополнить на сумму: **₽{stats['completed_revenue']:,.2f}**

⚠️ **ВАЖНО:** Пополняйте Replicate и OpenAI на сумму, соответствующую общему количеству купленных кредитов, чтобы все пользователи могли использовать свои кредиты!"""
        
        await update.message.reply_text(stats_text, parse_mode='Markdown')
        
    except Exception as e:
        logging.error(f"Ошибка получения статистики кредитов: {e}")
        await update.message.reply_text("❌ Ошибка получения статистики. Попробуйте позже.")
```

## 🔧 **Шаг 2: Зарегистрировать команду**

Найдите в файле `bot.py` регистрацию команд (примерно строка 30814) и после строки:

```python
app.add_handler(CommandHandler('admin_stats', admin_stats_command))
```

Добавьте:

```python
app.add_handler(CommandHandler('credits_stats', credits_stats_command))  # Статистика по кредитам
```

## ✅ **Шаг 3: Проверить ID пользователя**

В функции замените `ADMIN_USER_ID = 7735323051` на ваш реальный Telegram ID.

## 🎉 **Результат:**

После добавления вы сможете:
- Написать в бота `/credits_stats`
- Получить полную статистику по кредитам
- Увидеть, сколько кредитов нужно пополнить в Replicate/OpenAI

## 📍 **Где искать:**

1. **Функция `my_id_command`** - примерно строка 1502
2. **Регистрация команд** - примерно строка 30814
3. **Ваш Telegram ID** - используйте команду `/my_id` в боте

## ⚠️ **Важно:**

- Команда доступна только вам
- Пользователи не видят эту статистику
- Функция работает только на Railway (где развернут бот)

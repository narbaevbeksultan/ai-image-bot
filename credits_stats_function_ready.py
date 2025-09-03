# КОПИРУЙТЕ ЭТУ ФУНКЦИЮ В bot.py ПОСЛЕ ФУНКЦИИ my_id_command

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

# И ДОБАВЬТЕ ЭТУ СТРОКУ В РЕГИСТРАЦИЮ КОМАНД (после admin_stats):
# app.add_handler(CommandHandler('credits_stats', credits_stats_command))


# Исправления для Google Imagen 4 Ultra
# Добавить в bot.py после строки с "timeout=60.0"

# 🔍 ОТЛАДКА В TELEGRAM - что получили от API
if send_text:
    await send_text(f"🔍 **Google Imagen вернул:**\n\n"
                  f"📊 **Тип:** `{type(output).__name__}`\n"
                  f"📋 **Содержимое:** `{str(output)[:100]}...`\n"
                  f"🔗 **Есть .url():** {'✅' if hasattr(output, 'url') else '❌'}\n"
                  f"🆔 **Есть .id:** {'✅' if hasattr(output, 'id') else '❌'}\n"
                  f"📈 **Есть .status:** {'✅' if hasattr(output, 'status') else '❌'}\n"
                  f"📤 **Есть .output:** {'✅' if hasattr(output, 'output') else '❌'}\n"
                  f"📥 **Есть .result:** {'✅' if hasattr(output, 'result') else '❌'}", parse_mode='Markdown')

# Также добавить в конец функции Google Imagen перед проверками:

# 🔍 ОТЛАДКА В TELEGRAM - финальный результат
if send_text:
    final_msg = f"🔍 **ФИНАЛЬНЫЙ РЕЗУЛЬТАТ Google Imagen:**\n\n"
    final_msg += f"📊 **image_url:** `{str(image_url)[:100] if image_url else 'None'}...`\n"
    final_msg += f"🔗 **Тип:** `{type(image_url).__name__}`\n"
    if image_url:
        final_msg += f"📏 **Длина:** `{len(str(image_url))}`\n"
        final_msg += f"🌐 **Начинается с http:** `{str(image_url).startswith(('http://', 'https://'))}`\n"
    await send_text(final_msg, parse_mode='Markdown')


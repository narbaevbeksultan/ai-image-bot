from dotenv import load_dotenv
import os

load_dotenv()

print("Проверка переменных окружения:")
print(f"TELEGRAM_BOT_TOKEN: {'ЕСТЬ' if os.getenv('TELEGRAM_BOT_TOKEN') else 'НЕТ'}")
print(f"REPLICATE_API_TOKEN: {'ЕСТЬ' if os.getenv('REPLICATE_API_TOKEN') else 'НЕТ'}")
print(f"OPENAI_API_KEY: {'ЕСТЬ' if os.getenv('OPENAI_API_KEY') else 'НЕТ'}")

# Проверим длину токенов
token = os.getenv('TELEGRAM_BOT_TOKEN')
if token:
    print(f"Длина TELEGRAM_BOT_TOKEN: {len(token)}")
else:
    print("TELEGRAM_BOT_TOKEN не найден")

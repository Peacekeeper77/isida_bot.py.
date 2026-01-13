import os
import asyncio
from isida_bot import IsidaTelegramBot

async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Переменная TELEGRAM_BOT_TOKEN обязательна!")

    admin_ids_raw = os.getenv("ADMIN_IDS", "")
    admin_ids = []
    if admin_ids_raw:
        try:
            admin_ids = [int(x.strip()) for x in admin_ids_raw.split(",") if x.strip().isdigit()]
        except Exception as e:
            print(f"Ошибка парсинга ADMIN_IDS: {e}")

    bot = IsidaTelegramBot(token, admin_ids)

    port = int(os.getenv("PORT", 8000))
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if not render_url:
        raise RuntimeError("Переменная RENDER_EXTERNAL_URL не установлена. Убедитесь, что сервис активен на Render.")

    webhook_url = f"{render_url}/{token}"

    await bot.run_webhook(webhook_url=webhook_url, port=port)

if __name__ == "__main__":
    asyncio.run(main())
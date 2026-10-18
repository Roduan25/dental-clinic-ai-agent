import logging

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from settings import settings
from Telegram.telegram_handlers import (
    handle_approval_callback,
    handle_text_message,
    reset_command,
    start_command,
)


logging.basicConfig(
    format=(
        "%(asctime)s - %(name)s - "
        "%(levelname)s - %(message)s"
    ),
    level=logging.INFO,
)


def create_telegram_application() -> Application:
    application = (ApplicationBuilder().token(settings.telegram_bot_token).build())

    application.add_handler(CommandHandler("start", start_command))

    application.add_handler(CommandHandler("reset", reset_command))

    application.add_handler(CallbackQueryHandler(handle_approval_callback, pattern=r"^approval:(yes|no)$"))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    return application


def run_telegram_bot() -> None:
    application = create_telegram_application()

    print("بدأ تشغيل مساعد العيادة على Telegram.")

    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    run_telegram_bot()
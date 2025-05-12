import logging
from logger import get_logger
from config import BOT_TOKEN
from database import Database
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
from datetime import datetime, time
import pytz

# Импорт обработчиков
from handlers.bath import start, register_bath, create_bath_event, button_callback, confirm_bath_registration, handle_payment_confirmation, admin_confirm_payment, admin_decline_payment, handle_deep_link
from handlers.profile import profile, handle_profile_update, handle_full_name, handle_birth_date, handle_occupation, handle_instagram, handle_skills, start_profile_callback, export_profiles, cancel, history, handle_profile_update_text, PROFILE, FULL_NAME, BIRTH_DATE, OCCUPATION, INSTAGRAM, SKILLS
from handlers.admin import mark_paid, add_subscriber, remove_subscriber, update_commands, mention_all, mark_visit, clear_db, remove_registration, cash_list

logger = get_logger(__name__)
db = Database()

if __name__ == "__main__":
    application = Application.builder().token(BOT_TOKEN).build()

    # Регистрация команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("register", register_bath))
    application.add_handler(CommandHandler("create_bath", create_bath_event))
    application.add_handler(CommandHandler("cash_list", cash_list))
    application.add_handler(CommandHandler("mark_paid", mark_paid))
    application.add_handler(CommandHandler("add_subscriber", add_subscriber))
    application.add_handler(CommandHandler("remove_subscriber", remove_subscriber))
    application.add_handler(CommandHandler("update_commands", update_commands))
    application.add_handler(CommandHandler("export_profiles", export_profiles))
    application.add_handler(CommandHandler("mention_all", mention_all))
    application.add_handler(CommandHandler("mark_visit", mark_visit))
    application.add_handler(CommandHandler("remove_registration", remove_registration))
    application.add_handler(CommandHandler("history", history))

    # ConversationHandler для профиля
    profile_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("profile", profile)],
        states={
            PROFILE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_profile_update_text),
                CallbackQueryHandler(handle_profile_update, pattern="^update_profile_"),
                CommandHandler("profile", profile),
                CommandHandler("start", profile),
            ],
            FULL_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_full_name),
                CommandHandler("profile", profile),
                CommandHandler("start", profile),
            ],
            BIRTH_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_birth_date),
                CommandHandler("profile", profile),
                CommandHandler("start", profile),
            ],
            OCCUPATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_occupation),
                CommandHandler("profile", profile),
                CommandHandler("start", profile),
            ],
            INSTAGRAM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_instagram),
                CommandHandler("profile", profile),
                CommandHandler("start", profile),
            ],
            SKILLS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_skills),
                CommandHandler("profile", profile),
                CommandHandler("start", profile),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(profile_conv_handler)

    # Callback-и
    application.add_handler(CallbackQueryHandler(confirm_bath_registration, pattern="^confirm_bath_"))
    application.add_handler(CallbackQueryHandler(handle_payment_confirmation, pattern="^paid_bath_"))
    application.add_handler(CallbackQueryHandler(handle_payment_confirmation, pattern="^cash_bath_"))
    application.add_handler(CallbackQueryHandler(admin_confirm_payment, pattern="^admin_confirm_"))
    application.add_handler(CallbackQueryHandler(admin_decline_payment, pattern="^admin_decline_"))
    application.add_handler(CallbackQueryHandler(button_callback))

    # Неизвестная команда
    def unknown_command(update, context):
        logger.warning(f"Неизвестная команда: {update.message.text}")
        return update.message.reply_text("Неизвестная команда. Пожалуйста, используйте меню.")
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # Автоматическая отправка cash_list по воскресеньям в 10:00
    warsaw_tz = pytz.timezone('Europe/Warsaw')
    application.job_queue.run_daily(
        lambda context: cash_list(None, context, silent=True),
        time=time(hour=10, minute=0, tzinfo=warsaw_tz),
        name="cash_list_auto"
    )

    logger.info("Запуск бота")
    application.run_polling()

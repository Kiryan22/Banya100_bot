import logging
from datetime import datetime, timedelta
from telegram import Update, BotCommand
from telegram.ext import ContextTypes
from config import ADMIN_IDS, BATH_CHAT_ID
from database import Database
from telegram.ext import ConversationHandler

db = Database()
logger = logging.getLogger(__name__)

async def add_subscriber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_chat.type != "private":
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только в личном чате с ботом.")
            logger.warning("[add_subscriber] Command used in non-private chat")
            return
            
        admin_id = update.effective_user.id
        if admin_id not in ADMIN_IDS:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("У вас нет прав для выполнения этой команды.")
            logger.warning(f"[add_subscriber] Non-admin user {admin_id} attempted to add subscriber")
            return
            
        if len(context.args) != 2:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Использование: /add_subscriber <user_id> <days>")
            logger.warning("[add_subscriber] Invalid number of arguments")
            return
            
        target = context.args[0]
        days = int(context.args[1])
        
        try:
            target_id = int(target)
            user = await context.bot.get_chat(target_id)
            username = user.username or f"{user.first_name} {user.last_name or ''}"
            logger.info(f"[add_subscriber] Adding subscription for user {username} (ID: {target_id}) for {days} days")
        except ValueError:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Пожалуйста, используйте user_id вместо username.")
            logger.warning("[add_subscriber] Invalid user_id format")
            return
        except Exception as e:
            logger.error(f"[add_subscriber] Error getting user info: {e}", exc_info=True)
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Не удалось получить информацию о пользователе.")
            return
            
        paid_until = (datetime.now() + timedelta(days=days)).timestamp()
        try:
            db.add_subscriber(target_id, username, paid_until)
            logger.info(f"[add_subscriber] Successfully added subscription for {username} (ID: {target_id})")
            
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text(f"Подписка для {username} (ID: {target_id}) добавлена на {days} дней.")
                
            # Уведомляем пользователя
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=f"Вам добавлена подписка на {days} дней. Спасибо за поддержку!"
                )
                logger.info(f"[add_subscriber] Sent notification to user {target_id}")
            except Exception as e:
                logger.error(f"[add_subscriber] Error sending notification to user: {e}", exc_info=True)
                
        except Exception as e:
            logger.error(f"[add_subscriber] Error adding subscription: {e}", exc_info=True)
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Произошла ошибка при добавлении подписки.")
                
    except Exception as e:
        logger.error(f"[add_subscriber] Unexpected error: {e}", exc_info=True)
        try:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Произошла непредвиденная ошибка при добавлении подписки.")
        except Exception as inner_e:
            logger.error(f"[add_subscriber] Error sending error message: {inner_e}", exc_info=True)

async def remove_subscriber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info("[remove_subscriber] Command received")
        
        if not context.args:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Пожалуйста, укажите user_id пользователя.")
            logger.warning("[remove_subscriber] No user_id provided")
            return
            
        try:
            target_id = int(context.args[0])
            logger.info(f"[remove_subscriber] Attempting to remove subscriber {target_id}")
            
            result = db.remove_subscriber(target_id)
            message = update.message or (update.callback_query and update.callback_query.message)
            
            if result:
                if message:
                    await message.reply_text(f"Подписка для пользователя с ID {target_id} удалена.")
                logger.info(f"[remove_subscriber] Successfully removed subscriber {target_id}")
            else:
                if message:
                    await message.reply_text(f"Пользователь с ID {target_id} не найден в базе подписчиков.")
                logger.warning(f"[remove_subscriber] User {target_id} not found in subscribers")
                
        except ValueError:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Пожалуйста, укажите корректный user_id.")
            logger.warning(f"[remove_subscriber] Invalid user_id provided: {context.args[0]}")
            
    except Exception as e:
        logger.error(f"[remove_subscriber] Unexpected error: {e}", exc_info=True)
        try:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Произошла непредвиденная ошибка при удалении подписчика.")
        except Exception as inner_e:
            logger.error(f"[remove_subscriber] Error sending error message: {inner_e}", exc_info=True)

async def check_subscriptions(context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info("[check_subscriptions] Starting subscription check")
        expired_subscribers = db.get_expired_subscribers()
        
        if not expired_subscribers:
            logger.info("[check_subscriptions] No expired subscriptions found")
            return
            
        logger.info(f"[check_subscriptions] Found {len(expired_subscribers)} expired subscriptions")
        
        for subscriber in expired_subscribers:
            try:
                user_id = subscriber['user_id']
                username = subscriber['username']
                
                # Уведомляем пользователя
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="Ваша подписка истекла. Пожалуйста, продлите подписку для продолжения использования бота."
                    )
                    logger.info(f"[check_subscriptions] Sent expiration notification to user {user_id}")
                except Exception as e:
                    logger.error(f"[check_subscriptions] Error sending notification to user {user_id}: {e}", exc_info=True)
                    
                # Уведомляем администраторов
                for admin_id in ADMIN_IDS:
                    try:
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=f"Подписка пользователя {username} (ID: {user_id}) истекла."
                        )
                        logger.info(f"[check_subscriptions] Sent admin notification about user {user_id}")
                    except Exception as e:
                        logger.error(f"[check_subscriptions] Error sending admin notification: {e}", exc_info=True)
                        
            except Exception as e:
                logger.error(f"[check_subscriptions] Error processing subscriber {subscriber}: {e}", exc_info=True)
                continue
                
        # Удаляем истекшие подписки
        try:
            db.remove_expired_subscribers()
            logger.info("[check_subscriptions] Removed expired subscriptions")
        except Exception as e:
            logger.error(f"[check_subscriptions] Error removing expired subscriptions: {e}", exc_info=True)
            
    except Exception as e:
        logger.error(f"[check_subscriptions] Unexpected error: {e}", exc_info=True)

async def handle_message_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_chat.type != "private":
            logger.warning("[handle_message_to_user] Command used in non-private chat")
            return
            
        if update.callback_query:
            query = update.callback_query
            await query.answer()
        else:
            query = None
            
        admin_id = update.effective_user.id
        logger.info(f"[handle_message_to_user] Admin {admin_id} attempting to send message")
        
        if context.user_data.get('messaging_user_id'):
            pass
        elif query and query.data.startswith("message_user_"):
            pass
        else:
            logger.warning("[handle_message_to_user] No target user specified")
            return ConversationHandler.END
            
        if admin_id not in ADMIN_IDS:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("У вас нет прав для выполнения этой операции.")
            logger.warning(f"[handle_message_to_user] Non-admin user {admin_id} attempted to send message")
            return ConversationHandler.END
            
        if query:
            # ... (оставить обработку callback message_user_) ...
            pass
            
        # ... (оставить обработку отправки сообщения пользователю) ...
        
    except Exception as e:
        logger.error(f"[handle_message_to_user] Unexpected error: {e}", exc_info=True)
        try:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Произошла непредвиденная ошибка при отправке сообщения.")
        except Exception as inner_e:
            logger.error(f"[handle_message_to_user] Error sending error message: {inner_e}", exc_info=True)
        return ConversationHandler.END

async def mark_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_chat.type != "private":
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только в личном чате с ботом.")
            logger.warning("[mark_paid] Command used in non-private chat")
            return

        admin_id = update.effective_user.id
        if admin_id not in ADMIN_IDS:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("У вас нет прав для выполнения этой команды.")
            logger.warning(f"[mark_paid] Non-admin user {admin_id} attempted to mark payment")
            return

        if len(context.args) != 2:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Использование: /mark_paid <username> <DD.MM.YYYY>")
            logger.warning("[mark_paid] Invalid number of arguments")
            return

        username = context.args[0].lstrip('@')
        date_str = context.args[1]

        # Найти user_id по username
        user_id = db.get_user_id_by_username(username)
        if not user_id:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text(f"Пользователь @{username} не найден.")
            logger.warning(f"[mark_paid] User @{username} not found")
            return

        # Отметить оплату в базе
        result = db.mark_participant_paid(date_str, user_id)
        message = update.message or (update.callback_query and update.callback_query.message)
        if result:
            if message:
                await message.reply_text(f"Оплата пользователя @{username} за {date_str} отмечена как подтверждённая.")
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"Ваша оплата за баню {date_str} подтверждена администратором!"
                )
            except Exception as e:
                logger.error(f"[mark_paid] Error sending notification to user: {e}", exc_info=True)
            logger.info(f"[mark_paid] Payment marked as paid for @{username} ({user_id}) on {date_str}")
        else:
            if message:
                await message.reply_text(f"Не удалось отметить оплату пользователя @{username} за {date_str}. Проверьте данные.")
            logger.warning(f"[mark_paid] Failed to mark payment for @{username} on {date_str}")
    except Exception as e:
        logger.error(f"[mark_paid] Unexpected error: {e}", exc_info=True)
        try:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Произошла непредвиденная ошибка при подтверждении оплаты.")
        except Exception as inner_e:
            logger.error(f"[mark_paid] Error sending error message: {inner_e}", exc_info=True)

async def update_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    commands = [
        BotCommand("start", "Начать работу с ботом"),
        BotCommand("register", "Записаться на баню"),
        BotCommand("profile", "Просмотр/обновление информации о себе"),
        BotCommand("cash_list", "Список участников с оплатой наличными (только для админа)"),
        BotCommand("create_bath", "Создать новую запись на ближайшее воскресенье"),
        BotCommand("mark_paid", "Отметить оплату пользователя (/mark_paid username DD.MM.YYYY)"),
        BotCommand("add_subscriber", "Добавить подписчика (/add_subscriber user_id days)"),
        BotCommand("remove_subscriber", "Удалить подписчика (/remove_subscriber user_id)"),
        BotCommand("update_commands", "Обновить меню команд (только для админа)"),
        BotCommand("export_profiles", "Экспорт всех профилей пользователей"),
        BotCommand("mention_all", "Упомянуть всех активных пользователей"),
        BotCommand("mark_visit", "Отметить посещение бани"),
        BotCommand("clear_db", "Полная очистка базы данных (только для админа)"),
        BotCommand("remove_registration", "Удалить регистрацию пользователя на баню (/remove_registration username DD.MM.YYYY")
    ]
    await context.bot.set_my_commands(commands)
    await update.message.reply_text("Меню команд обновлено.")

async def mention_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        admin_id = update.effective_user.id
        if admin_id not in ADMIN_IDS:
            await update.message.reply_text("У вас нет прав для выполнения этой команды.")
            return

        # Получаем всех активных пользователей
        users = db.get_all_active_users()
        if not users:
            await update.message.reply_text("Нет активных пользователей для упоминания.")
            return

        mentions = []
        for user in users:
            username = user.get('username')
            if username:
                mentions.append(f"@{username}")
            else:
                mentions.append(user.get('full_name', ''))
        text = " ".join(mentions)
        if not text.strip():
            await update.message.reply_text("Нет пользователей для упоминания.")
            return
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"[mention_all] Unexpected error: {e}", exc_info=True)
        await update.message.reply_text("Произошла ошибка при упоминании пользователей.")

async def mark_visit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_chat.type != "private":
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только в личном чате с ботом.")
            logger.warning("[mark_visit] Command used in non-private chat")
            return

        admin_id = update.effective_user.id
        if admin_id not in ADMIN_IDS:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("У вас нет прав для выполнения этой команды.")
            logger.warning(f"[mark_visit] Non-admin user {admin_id} attempted to mark visit")
            return

        if len(context.args) != 2:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Использование: /mark_visit <username> <DD.MM.YYYY>")
            logger.warning("[mark_visit] Invalid number of arguments")
            return

        username = context.args[0].lstrip('@')
        date_str = context.args[1]

        # Найти user_id по username
        user_id = db.get_user_id_by_username(username)
        if not user_id:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text(f"Пользователь @{username} не найден.")
            logger.warning(f"[mark_visit] User @{username} not found")
            return

        # Отметить посещение в базе
        result = db.mark_user_visit(date_str, user_id)
        message = update.message or (update.callback_query and update.callback_query.message)
        if result:
            if message:
                await message.reply_text(f"Посещение пользователя @{username} за {date_str} отмечено.")
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"Ваше посещение бани {date_str} отмечено администратором!"
                )
            except Exception as e:
                logger.error(f"[mark_visit] Error sending notification to user: {e}", exc_info=True)
            logger.info(f"[mark_visit] Visit marked for @{username} ({user_id}) on {date_str}")
        else:
            if message:
                await message.reply_text(f"Не удалось отметить посещение пользователя @{username} за {date_str}. Проверьте данные.")
            logger.warning(f"[mark_visit] Failed to mark visit for @{username} on {date_str}")
    except Exception as e:
        logger.error(f"[mark_visit] Unexpected error: {e}", exc_info=True)
        try:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Произошла непредвиденная ошибка при отметке посещения.")
        except Exception as inner_e:
            logger.error(f"[mark_visit] Error sending error message: {inner_e}", exc_info=True)

async def clear_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_chat.type != "private":
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только в личном чате с ботом.")
            logger.warning("[clear_db] Command used in non-private chat")
            return

        admin_id = update.effective_user.id
        if admin_id not in ADMIN_IDS:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("У вас нет прав для выполнения этой команды.")
            logger.warning(f"[clear_db] Non-admin user {admin_id} attempted to clear DB")
            return

        db.clear_all_data()
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text("База данных полностью очищена.")
        logger.info(f"[clear_db] Database cleared by admin {admin_id}")
    except Exception as e:
        logger.error(f"[clear_db] Unexpected error: {e}", exc_info=True)
        try:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Произошла ошибка при очистке базы данных.")
        except Exception as inner_e:
            logger.error(f"[clear_db] Error sending error message: {inner_e}", exc_info=True)

async def remove_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_chat.type != "private":
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только в личном чате с ботом.")
            logger.warning("[remove_registration] Command used in non-private chat")
            return

        admin_id = update.effective_user.id
        if admin_id not in ADMIN_IDS:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("У вас нет прав для выполнения этой команды.")
            logger.warning(f"[remove_registration] Non-admin user {admin_id} attempted to remove registration")
            return

        if len(context.args) != 2:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Использование: /remove_registration <username> <DD.MM.YYYY>")
            logger.warning("[remove_registration] Invalid number of arguments")
            return

        username = context.args[0].lstrip('@')
        date_str = context.args[1]

        # Найти user_id по username
        user_id = db.get_user_id_by_username(username)
        if not user_id:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text(f"Пользователь @{username} не найден.")
            logger.warning(f"[remove_registration] User @{username} not found")
            return

        # Удалить пользователя из участников на дату
        result = db.remove_bath_participant(date_str, user_id)
        message = update.message or (update.callback_query and update.callback_query.message)
        if result:
            if message:
                await message.reply_text(f"Регистрация пользователя @{username} на {date_str} удалена.")
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"Ваша регистрация на баню {date_str} была удалена администратором."
                )
            except Exception as e:
                logger.error(f"[remove_registration] Error sending notification to user: {e}", exc_info=True)
            logger.info(f"[remove_registration] Registration removed for @{username} ({user_id}) on {date_str}")
        else:
            if message:
                await message.reply_text(f"Не удалось удалить регистрацию пользователя @{username} на {date_str}. Проверьте данные.")
            logger.warning(f"[remove_registration] Failed to remove registration for @{username} on {date_str}")
    except Exception as e:
        logger.error(f"[remove_registration] Unexpected error: {e}", exc_info=True)
        try:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Произошла непредвиденная ошибка при удалении регистрации.")
        except Exception as inner_e:
            logger.error(f"[remove_registration] Error sending error message: {inner_e}", exc_info=True)

async def cash_list(update: Update = None, context: ContextTypes.DEFAULT_TYPE = None, silent: bool = False):
    """
    Отправляет администраторам список участников с оплатой наличными на ближайшую баню.
    Если silent=True, не отвечает в чат, а только отправляет админам (для JobQueue).
    """
    try:
        # Проверка на администратора, если вызвано вручную
        if update:
            user_id = update.effective_user.id
            if user_id not in ADMIN_IDS:
                await update.message.reply_text("У вас нет прав для выполнения этой команды.")
                logger.warning(f"[cash_list] Non-admin user {user_id} attempted to get cash list")
                return
        # Получаем ближайшую дату бани
        from handlers.bath import get_next_sunday
        date_str = get_next_sunday()
        participants = db.get_bath_participants(date_str)
        cash_participants = [p for p in participants if p.get('cash')]
        if not cash_participants:
            text = f"На баню {date_str} нет участников с оплатой наличными."
        else:
            text = f"Список участников с оплатой наличными на баню {date_str} (всего: {len(cash_participants)}):\n\n"
            for i, p in enumerate(cash_participants, 1):
                username = p['username'] or f"ID: {p['user_id']}"
                text += f"{i}. {username}\n"
        # Отправляем всем администраторам, кроме того, кто вызвал команду в личке
        for admin_id in ADMIN_IDS:
            if update and not silent and admin_id == update.effective_user.id and update.effective_chat.type == "private":
                continue
            try:
                await context.bot.send_message(chat_id=admin_id, text=text)
            except Exception as e:
                logger.error(f"[cash_list] Error sending to admin {admin_id}: {e}")
        # Если вызвано вручную, выводим список только в чат, где вызвали команду
        if update and not silent:
            await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"[cash_list] Unexpected error: {e}", exc_info=True)
        if update and not silent:
            await update.message.reply_text("Произошла ошибка при получении списка наличных.")

async def admin_confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id, date_str, payment_type):
    try:
        query = update.callback_query
        user = query.from_user
        logger.info(f"[admin_confirm_payment] CallbackQuery received: data={query.data}, chat_type={update.effective_chat.type}, user_id={user.id}")
        await query.answer()
        if user.id not in ADMIN_IDS:
            logger.warning(f"[admin_confirm_payment] Non-admin user {user.id} attempted to confirm payment")
            await query.edit_message_text("У вас нет прав для выполнения этой операции.")
            return
        callback_data = query.data
        parts = callback_data.split("_")
        if parts[0] == "admin" and parts[1] == "confirm":
            user_id = int(parts[2])
            date_str = parts[3]
            payment_type = parts[4] if len(parts) > 4 else None
            user_data = db.get_pending_payment(user_id, date_str, payment_type)
            logger.info(f"[admin_confirm_payment] Looking for payment: user_id={user_id}, date_str={date_str}, payment_type={payment_type}")
            logger.info(f"[admin_confirm_payment] Found payment data: {user_data}")
            if user_data:
                profile = db.get_user_profile(user_id)
                if not profile:
                    logger.warning(f"[admin_confirm_payment] No profile found for user {user_id}")
                    await query.edit_message_text(
                        text="Пользователь не заполнил профиль. Сначала нужно заполнить профиль, а затем подтвердить оплату."
                    )
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text="Пожалуйста, заполните профиль командой /profile, чтобы администратор мог подтвердить вашу оплату."
                        )
                    except Exception as e:
                        logger.error(f"[admin_confirm_payment] Error sending profile request to user: {e}", exc_info=True)
                    return
                # Подтверждаем оплату
                try:
                    if payment_type == 'cash':
                        username = profile['username'] or profile['full_name']
                        db.add_bath_participant(date_str, user_id, username, paid=False, cash=True)
                    else:
                        db.confirm_payment(user_id, date_str, payment_type)
                    logger.info(f"[admin_confirm_payment] Payment confirmed for user {user_id}")
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=f"Ваша оплата за баню {date_str} подтверждена администратором."
                        )
                        logger.info(f"[admin_confirm_payment] Sent confirmation to user {user_id}")
                    except Exception as e:
                        logger.error(f"[admin_confirm_payment] Error sending confirmation to user: {e}", exc_info=True)
                    await query.edit_message_text(
                        text=f"Оплата пользователя {user_data['username']} подтверждена."
                    )
                except Exception as e:
                    logger.error(f"[admin_confirm_payment] Error confirming payment: {e}", exc_info=True)
                    await query.edit_message_text(
                        text="Произошла ошибка при подтверждении оплаты."
                    )
            else:
                logger.warning(f"[admin_confirm_payment] No payment found for user {user_id}")
                await query.edit_message_text(
                    text="Заявка на оплату не найдена."
                )
    except Exception as e:
        logger.error(f"[admin_confirm_payment] Unexpected error: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                text="Произошла непредвиденная ошибка при подтверждении оплаты."
            )
        except Exception as inner_e:
            logger.error(f"[admin_confirm_payment] Error sending error message: {inner_e}", exc_info=True)

# ... (оставить остальные функции, которые были в bot.py, связанные с админскими действиями) ...

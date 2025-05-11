import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_IDS, BATH_CHAT_ID
from database import Database

db = Database()
logger = logging.getLogger(__name__)

async def add_subscriber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("[add_subscriber] Вход в команду /add_subscriber")
    try:
        if update.effective_chat.type != "private":
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только в личном чате с ботом.")
            logger.warning("[add_subscriber] Попытка запуска не в личном чате")
            return
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("У вас нет прав для выполнения этой команды.")
            logger.warning(f"[add_subscriber] Пользователь {user_id} не админ")
            return
        if not context.args or len(context.args) < 2:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Использование: /add_subscriber <username или user_id> <срок в днях>")
            logger.info("[add_subscriber] Не переданы аргументы")
            return
        target = context.args[0]
        days = int(context.args[1])
        try:
            target_id = int(target)
            user = await context.bot.get_chat(target_id)
            username = user.username or f"{user.first_name} {user.last_name or ''}"
        except ValueError:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Пожалуйста, используйте user_id вместо username.")
            logger.warning("[add_subscriber] Передан не user_id")
            return
        paid_until = (datetime.now() + timedelta(days=days)).timestamp()
        db.add_subscriber(target_id, username, paid_until)
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text(f"Подписка для {username} (ID: {target_id}) добавлена на {days} дней.")
        logger.info(f"[add_subscriber] Подписка добавлена для {username} (ID: {target_id}) на {days} дней")
    except Exception as e:
        logger.error(f"Ошибка в функции add_subscriber: {e}")
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text("Произошла ошибка при добавлении подписчика.")

async def remove_subscriber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("[remove_subscriber] Вход в команду /remove_subscriber")
    try:
        if update.effective_chat.type != "private":
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только в личном чате с ботом.")
            logger.warning("[remove_subscriber] Попытка запуска не в личном чате")
            return
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("У вас нет прав для выполнения этой команды.")
            logger.warning(f"[remove_subscriber] Пользователь {user_id} не админ")
            return
        if not context.args:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Использование: /remove_subscriber <user_id>")
            logger.info("[remove_subscriber] Не переданы аргументы")
            return
        try:
            target_id = int(context.args[0])
            result = db.remove_subscriber(target_id)
            message = update.message or (update.callback_query and update.callback_query.message)
            if result:
                if message:
                    await message.reply_text(f"Подписка для пользователя с ID {target_id} удалена.")
                logger.info(f"[remove_subscriber] Подписка удалена для пользователя {target_id}")
            else:
                if message:
                    await message.reply_text(f"Пользователь с ID {target_id} не найден в базе подписчиков.")
                logger.warning(f"[remove_subscriber] Пользователь {target_id} не найден в базе подписчиков")
        except ValueError:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Пожалуйста, укажите корректный user_id.")
            logger.warning("[remove_subscriber] Передан некорректный user_id")
    except Exception as e:
        logger.error(f"Ошибка в функции remove_subscriber: {e}")
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text("Произошла ошибка при удалении подписчика.")

async def check_subscriptions(context: ContextTypes.DEFAULT_TYPE):
    expired_users = db.get_expired_subscribers()
    for user_id in expired_users:
        try:
            await context.bot.ban_chat_member(
                chat_id=BATH_CHAT_ID,
                user_id=user_id
            )
            await context.bot.unban_chat_member(
                chat_id=BATH_CHAT_ID,
                user_id=user_id,
                only_if_banned=True
            )
            logger.info(f"Пользователь {user_id} удален из-за истекшей подписки")
            db.remove_subscriber(user_id)
        except Exception as e:
            logger.error(f"Ошибка при удалении пользователя {user_id}: {e}")

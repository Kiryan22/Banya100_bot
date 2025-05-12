import logging
from datetime import datetime, timedelta
from telegram import Update
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

# ... (оставить остальные функции, которые были в bot.py, связанные с админскими действиями) ...

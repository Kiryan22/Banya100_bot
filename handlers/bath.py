import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import BATH_TIME, BATH_COST, MAX_BATH_PARTICIPANTS, ADMIN_IDS, BATH_CHAT_ID, CARD_PAYMENT_LINK, REVOLUT_PAYMENT_LINK
from utils.formatting import format_bath_message
from database import Database
from utils.logging import setup_logging

# get_next_sunday и handle_deep_link тоже переносятся сюда
import pytz
from datetime import datetime, timedelta

db = Database()
logger = setup_logging()

def get_next_sunday():
    try:
        tz = pytz.timezone('Europe/Warsaw')
        today = datetime.now(tz)
        days_until_sunday = (6 - today.weekday()) % 7
        if days_until_sunday == 0:
            days_until_sunday = 7
        next_sunday = today + timedelta(days=days_until_sunday)
        return next_sunday.strftime("%d.%m.%Y")
    except Exception as e:
        logging.error(f"Ошибка при получении даты следующего воскресенья: {e}")
        raise

async def handle_deep_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].startswith("bath_"):
        return
    date_str = context.args[0].replace("bath_", "")
    bath_info = f"Вы хотите записаться на баню в воскресенье {date_str}.\n\n"
    bath_info += f"Время: {BATH_TIME} ‼️\n\n"
    bath_info += f"Cтоимость: {BATH_COST} карта либо наличка при входе📍\n\n"
    bath_info += f"Для продолжения записи, нажмите кнопку ниже:"
    keyboard = [
        [InlineKeyboardButton("Подтвердить запись", callback_data=f"confirm_bath_{date_str}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        text=bath_info,
        reply_markup=reply_markup
    )

async def register_bath(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("[register_bath] Вход в команду /register")
    try:
        if update.effective_chat.type != "private":
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только в личном чате с ботом.")
            logger.warning("[register_bath] Попытка запуска не в личном чате")
            return
        user = update.effective_user
        logger.debug(f"[register_bath] Пользователь {user.id} инициировал регистрацию")
        if not context.args:
            next_sunday = get_next_sunday()
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text(
                    f"Чтобы записаться на баню, используйте команду с датой в формате /register DD.MM.YYYY\n\n"
                    f"Например: /register {next_sunday}"
                )
            logger.info("[register_bath] Не передана дата, отправлена инструкция")
            return
        date_str = context.args[0]
        logger.debug(f"[register_bath] Дата для регистрации: {date_str}")
        bath_info = f"Вы хотите записаться на баню в воскресенье {date_str}.\n\n"
        bath_info += f"Время: {BATH_TIME} ‼️\n\n"
        bath_info += f"Cтоимость: {BATH_COST} карта либо наличка при входе📍\n\n"
        bath_info += f"Для продолжения записи, нажмите кнопку ниже:"
        keyboard = [
            [InlineKeyboardButton("Подтвердить запись", callback_data=f"confirm_bath_{date_str}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text(
                text=bath_info,
                reply_markup=reply_markup
            )
        logger.info(f"[register_bath] Отправлено приглашение на регистрацию на {date_str} пользователю {user.id}")
    except Exception as e:
        logger.error(f"Ошибка в функции register_bath: {e}")
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text("Произошла ошибка при регистрации. Пожалуйста, попробуйте позже.")

async def create_bath_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info("[create_bath_event] Command received")
        
        if update.effective_chat.type != "private":
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только в личном чате с ботом.")
            logger.warning("[create_bath_event] Command used in non-private chat")
            return
            
        admin_id = update.effective_user.id
        if admin_id not in ADMIN_IDS:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("У вас нет прав для выполнения этой команды.")
            logger.warning(f"[create_bath_event] Non-admin user {admin_id} attempted to create event")
            return
            
        next_sunday = get_next_sunday()
        logger.info(f"[create_bath_event] Creating bath event for {next_sunday}")
        
        # Очищаем старые события
        cleared_events = db.clear_old_events()
        logger.info(f"[create_bath_event] Cleared {cleared_events} old events")
        
        # Создаем новое событие
        participants = db.get_bath_participants(next_sunday)
        message_text = format_bath_message(next_sunday, participants)
        reply_markup = create_bath_keyboard(next_sunday)
        
        # Открепляем старое сообщение
        old_pinned_id = db.get_pinned_message_id()
        if old_pinned_id:
            try:
                await context.bot.unpin_chat_message(chat_id=BATH_CHAT_ID, message_id=old_pinned_id)
                db.delete_pinned_message_id(old_pinned_id)
                logger.info(f"[create_bath_event] Unpinned old message {old_pinned_id}")
            except Exception as e:
                logger.warning(f"[create_bath_event] Failed to unpin old message: {e}")
                
        # Отправляем новое сообщение
        try:
            sent_message = await context.bot.send_message(
                chat_id=BATH_CHAT_ID,
                text=message_text,
                reply_markup=reply_markup
            )
            logger.info(f"[create_bath_event] Sent new message: {sent_message.message_id}")
            
            # Проверяем текущее закрепленное сообщение
            pinned_messages = await context.bot.get_chat(BATH_CHAT_ID)
            if pinned_messages.pinned_message:
                current_message = pinned_messages.pinned_message.text
                current_markup = pinned_messages.pinned_message.reply_markup
                
                def markup_to_str(markup):
                    if not markup:
                        return ''
                    return str([[btn.text for btn in row] for row in markup.inline_keyboard])
                    
                markup_changed = markup_to_str(current_markup) != markup_to_str(reply_markup)
                
                if current_message != message_text or markup_changed:
                    try:
                        await context.bot.edit_message_text(
                            chat_id=BATH_CHAT_ID,
                            message_id=pinned_messages.pinned_message.message_id,
                            text=message_text,
                            reply_markup=reply_markup
                        )
                        logger.info(f"[create_bath_event] Updated pinned message")
                    except Exception as e:
                        logger.error(f"[create_bath_event] Error updating pinned message: {e}", exc_info=True)
                else:
                    logger.info(f"[create_bath_event] Message and buttons unchanged")
            else:
                try:
                    await context.bot.pin_chat_message(
                        chat_id=BATH_CHAT_ID,
                        message_id=sent_message.message_id,
                        disable_notification=False
                    )
                    db.set_pinned_message_id(next_sunday, sent_message.message_id)
                    logger.info(f"[create_bath_event] Pinned new message: {sent_message.message_id}")
                except Exception as e:
                    logger.error(f"[create_bath_event] Error pinning message: {e}", exc_info=True)
                    
            if cleared_events > 0:
                await context.bot.send_message(
                    chat_id=BATH_CHAT_ID,
                    text=f"Создана новая запись на баню {next_sunday}. Список участников предыдущей бани очищен."
                )
                logger.info(f"[create_bath_event] Sent cleanup notification")
                
        except Exception as e:
            logger.error(f"[create_bath_event] Error sending/updating message: {e}", exc_info=True)
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Произошла ошибка при создании события бани.")
                
    except Exception as e:
        logger.error(f"[create_bath_event] Unexpected error: {e}", exc_info=True)
        try:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Произошла непредвиденная ошибка при создании события бани.")
        except Exception as inner_e:
            logger.error(f"[create_bath_event] Error sending error message: {inner_e}", exc_info=True)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        user = query.from_user
        logger.info(f"[button_callback] CallbackQuery received: data={query.data}, chat_type={update.effective_chat.type}, user_id={user.id}")
        db.add_active_user(user.id, user.username or user.first_name)
        callback_data = query.data
        logger.debug(f"Получен callback от пользователя {user.id}: {callback_data}")

        if callback_data.startswith("join_bath_"):
            logger.info("[button_callback] Ветка join_bath_")
            date_str = callback_data.replace("join_bath_", "")
            logger.info(f"[button_callback] join_bath_ для даты {date_str}")
            logger.info(f"Пользователь {user.id} пытается записаться на баню {date_str}")

            if not db.try_add_bath_invite(user.id, date_str, hours=2):
                await query.answer("Вам уже отправлено приглашение на регистрацию. Проверьте личные сообщения.", show_alert=True)
                return

            if 'bath_registrations' in context.user_data and date_str in context.user_data['bath_registrations']:
                await query.answer("Вы уже начали процесс записи на эту дату.", show_alert=True)
                return

            participants = db.get_bath_participants(date_str)
            if len(participants) >= MAX_BATH_PARTICIPANTS:
                logger.warning(f"Пользователь {user.id} не смог записаться - достигнут лимит участников")
                await query.answer("К сожалению, баня уже занята. Вы можете записаться в следующий раз!", show_alert=True)
                return

            try:
                bath_info = f"Вы хотите записаться на баню в воскресенье {date_str}.\n\n"
                bath_info += f"Время: {BATH_TIME} ‼️\n\n"
                bath_info += f"Cтоимость: {BATH_COST} карта либо наличка при входе📍\n\n"
                bath_info += f"Для продолжения записи, нажмите кнопку ниже:"

                keyboard = [
                    [InlineKeyboardButton("Подтвердить запись", callback_data=f"confirm_bath_{date_str}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await context.bot.send_message(
                    chat_id=user.id,
                    text=bath_info,
                    reply_markup=reply_markup
                )
                logger.info(f"Отправлено сообщение с подтверждением записи пользователю {user.id}")

                await query.message.reply_text(
                    f"@{user.username or user.first_name}, проверьте личные сообщения от бота.",
                    reply_to_message_id=query.message.message_id
                )

            except Exception as e:
                logger.error(f"Ошибка при отправке сообщения пользователю {user.id}: {e}")
                bot_username = context.bot.username
                start_link = f"https://t.me/{bot_username}?start=bath_{date_str}"
                # ... (оставить обработку ссылки, если нужно) ...
    except Exception as e:
        logger.error(f"Ошибка в функции button_callback: {e}")

async def confirm_bath_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        user = query.from_user
        logger.info(f"[confirm_bath_registration] CallbackQuery received: data={query.data}, chat_type={update.effective_chat.type}, user_id={user.id}")
        db.add_active_user(user.id, user.username or user.first_name)
        callback_data = query.data
        logger.info(f"Пользователь {user.id} подтверждает запись на баню: {callback_data}")

        if callback_data.startswith("confirm_bath_"):
            date_str = callback_data.replace("confirm_bath_", "")

            participants = db.get_bath_participants(date_str)
            if len(participants) >= MAX_BATH_PARTICIPANTS:
                logger.warning(f"Пользователь {user.id} не смог подтвердить запись - достигнут лимит участников")
                await query.edit_message_text(
                    text="К сожалению, баня уже занята. Вы можете записаться в следующий раз!"
                )
                return

            if 'bath_registrations' not in context.user_data:
                context.user_data['bath_registrations'] = {}

            username = user.username or f"{user.first_name} {user.last_name or ''}"
            context.user_data['bath_registrations'][date_str] = {
                'user_id': user.id,
                'username': username,
                'status': 'pending_payment'
            }
            logger.info(f"Сохранена информация о регистрации пользователя {user.id} на {date_str}")

            payment_info = f"Отлично! Для завершения записи на баню ({date_str}), пожалуйста, выполните оплату:\n\n"
            payment_info += f"Cтоимость: {BATH_COST}\n\n"
            payment_info += f"Способы оплаты:\n"
            payment_info += f"1. КАРТА: {CARD_PAYMENT_LINK}\n"
            payment_info += f"2. Revolut: {REVOLUT_PAYMENT_LINK}\n\n"
            payment_info += f"После совершения оплаты, выберите способ ниже."

            keyboard = [
                [
                    InlineKeyboardButton("Я оплатил(а) онлайн", callback_data=f"paid_bath_{date_str}"),
                    InlineKeyboardButton("Буду платить наличными", callback_data=f"cash_bath_{date_str}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text=payment_info,
                reply_markup=reply_markup
            )
            logger.info(f"Отправлены инструкции по оплате пользователю {user.id}")
    except Exception as e:
        logger.error(f"Ошибка в функции confirm_bath_registration: {e}")
        await query.edit_message_text("Произошла ошибка. Пожалуйста, попробуйте позже.")

async def handle_payment_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        user = query.from_user
        logger.info(f"[handle_payment_confirmation] CallbackQuery received: data={query.data}, chat_type={update.effective_chat.type}, user_id={user.id}")
        db.add_active_user(user.id, user.username or user.first_name)
        callback_data = query.data
        logger.info(f"Пользователь {user.id} подтверждает оплату: {callback_data}")

        if callback_data.startswith("paid_bath_"):
            date_str = callback_data.replace("paid_bath_", "")

            if ('bath_registrations' in context.user_data and
                    date_str in context.user_data['bath_registrations']):

                context.user_data['bath_registrations'][date_str]['status'] = 'payment_claimed'
                logger.info(f"Обновлен статус регистрации пользователя {user.id} на {date_str}")

                username = user.username or f"{user.first_name} {user.last_name or ''}"

                user_data = {
                    'user_id': user.id,
                    'username': username,
                    'date_str': date_str
                }
                logger.info(f"Добавляю заявку: user_id={user.id}, username={username}, date_str={date_str}, payment_type=online")
                db.add_pending_payment(user.id, username, date_str, payment_type='online')
                logger.info(f"Добавлена заявка на подтверждение оплаты от пользователя {user.id}")

                await query.edit_message_text(
                    text=f"Спасибо! Ваша заявка об оплате отправлена администратору.\n"
                         f"После подтверждения оплаты, вы будете добавлены в список участников бани на {date_str}.\n"
                         f"Пожалуйста, ожидайте подтверждения."
                )

                for admin_id in ADMIN_IDS:
                    try:
                        callback_data_confirm = f"admin_confirm_{user.id}_{date_str}_online"
                        callback_data_decline = f"admin_decline_{user.id}_{date_str}_online"
                        logger.info(f"Формирую callback_data: confirm={callback_data_confirm}, decline={callback_data_decline}")
                        keyboard = [
                            [
                                InlineKeyboardButton("Оплатил онлайн", callback_data=callback_data_confirm),
                                InlineKeyboardButton("Отклонить", callback_data=callback_data_decline)
                            ]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=f"Пользователь @{username} (ID: {user.id}) утверждает, что оплатил баню на {date_str}.\nПожалуйста, подтвердите или отклоните оплату.",
                            reply_markup=reply_markup
                        )
                        logger.info(f"Отправлено уведомление администратору {admin_id} о новой заявке на оплату (online)")
                    except Exception as e:
                        logger.error(f"Ошибка при отправке уведомления администратору {admin_id}: {e}")
                        continue
            else:
                logger.warning(f"Пользователь {user.id} пытается подтвердить оплату без предварительной регистрации")
                await query.edit_message_text(
                    text="Произошла ошибка. Пожалуйста, начните процесс записи заново."
                )
    except Exception as e:
        logger.error(f"Ошибка в функции handle_payment_confirmation: {e}")
        await query.edit_message_text("Произошла ошибка. Пожалуйста, попробуйте позже.")

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
                    return
                    
                # Подтверждаем оплату
                try:
                    db.confirm_payment(user_id, date_str, payment_type)
                    logger.info(f"[admin_confirm_payment] Payment confirmed for user {user_id}")
                    
                    # Уведомляем пользователя
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

async def admin_decline_payment(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id, date_str, payment_type):
    try:
        query = update.callback_query
        user = query.from_user
        logger.info(f"[admin_decline_payment] CallbackQuery received: data={query.data}, chat_type={update.effective_chat.type}, user_id={user.id}")
        
        await query.answer()
        
        if user.id not in ADMIN_IDS:
            logger.warning(f"[admin_decline_payment] Non-admin user {user.id} attempted to decline payment")
            await query.edit_message_text("У вас нет прав для выполнения этой операции.")
            return
            
        callback_data = query.data
        parts = callback_data.split("_")
        
        if parts[0] == "admin" and parts[1] == "decline":
            user_id = int(parts[2])
            date_str = parts[3]
            payment_type = parts[4] if len(parts) > 4 else None
            
            user_data = db.get_pending_payment(user_id, date_str, payment_type)
            logger.info(f"[admin_decline_payment] Looking for payment: user_id={user_id}, date_str={date_str}, payment_type={payment_type}")
            logger.info(f"[admin_decline_payment] Found payment data: {user_data}")
            
            if user_data:
                # Отклоняем оплату
                try:
                    db.decline_payment(user_id, date_str, payment_type)
                    logger.info(f"[admin_decline_payment] Payment declined for user {user_id}")
                    
                    # Уведомляем пользователя
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=f"Ваша оплата за баню {date_str} отклонена администратором. Пожалуйста, проверьте детали оплаты и попробуйте снова."
                        )
                        logger.info(f"[admin_decline_payment] Sent decline notification to user {user_id}")
                    except Exception as e:
                        logger.error(f"[admin_decline_payment] Error sending decline notification to user: {e}", exc_info=True)
                        
                    await query.edit_message_text(
                        text=f"Оплата пользователя {user_data['username']} отклонена."
                    )
                    
                except Exception as e:
                    logger.error(f"[admin_decline_payment] Error declining payment: {e}", exc_info=True)
                    await query.edit_message_text(
                        text="Произошла ошибка при отклонении оплаты."
                    )
            else:
                logger.warning(f"[admin_decline_payment] No payment found for user {user_id}")
                await query.edit_message_text(
                    text="Заявка на оплату не найдена."
                )
                
    except Exception as e:
        logger.error(f"[admin_decline_payment] Unexpected error: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                text="Произошла непредвиденная ошибка при отклонении оплаты."
            )
        except Exception as inner_e:
            logger.error(f"[admin_decline_payment] Error sending error message: {inner_e}", exc_info=True)

async def handle_message_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    if update.callback_query:
        query = update.callback_query
        await query.answer()
    else:
        query = None

    admin_id = update.effective_user.id

    if context.user_data.get('messaging_user_id'):
        pass
    elif query and query.data.startswith("message_user_"):
        pass
    else:
        return

    if admin_id not in ADMIN_IDS:
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text("У вас нет прав для выполнения этой операции.")
        return ConversationHandler.END

    if query:
        # ... (оставить обработку callback message_user_) ...
        pass
    # ... (оставить обработку отправки сообщения пользователю) ... 

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if context.args and context.args[0].startswith("bath_"):
        # Deep link: записаться на баню
        date_str = context.args[0].replace("bath_", "")
        bath_info = f"Вы хотите записаться на баню в воскресенье {date_str}.\n\n"
        bath_info += f"Время: {BATH_TIME} ‼️\n\n"
        bath_info += f"Cтоимость: {BATH_COST} карта либо наличка при входе📍\n\n"
        bath_info += f"Для продолжения записи, нажмите кнопку ниже:"
        keyboard = [
            [InlineKeyboardButton("Подтвердить запись", callback_data=f"confirm_bath_{date_str}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            text=bath_info,
            reply_markup=reply_markup
        )
        return
    # Обычный /start
    text = (
        f"Привет, {user.first_name or user.username}! 👋\n\n"
        "Я — бот для записи в баню и управления посещениями.\n\n"
        "Что я умею:\n"
        "• Записывать на ближайшую баню\n"
        "• Вести список участников и оплат\n"
        "• Показывать ваш профиль и историю посещений\n"
        "• Админам — управлять участниками, отмечать оплаты и посещения\n\n"
        "Воспользуйтесь меню команд или напишите /register, чтобы записаться!"
    )
    await update.message.reply_text(text) 
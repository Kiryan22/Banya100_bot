import logging
import re
import csv
import tempfile
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS
from database import Database

db = Database()
logger = logging.getLogger(__name__)

PROFILE, FULL_NAME, BIRTH_DATE, OCCUPATION, INSTAGRAM, SKILLS = range(6)

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat = update.effective_chat
    if chat.type != "private":
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text("Профиль можно заполнять только в личном чате с ботом.")
        return ConversationHandler.END
    user_id = update.effective_user.id
    username = update.effective_user.username or "Не указан"
    profile = db.get_user_profile(user_id)
    message = update.message or (update.callback_query and update.callback_query.message)
    if profile:
        text = "📋 Ваш текущий профиль:\n\n"
        text += f"👤 Имя: {profile['full_name']}\n"
        text += f"🎂 Дата рождения: {profile['birth_date']}\n"
        text += f"💼 Род деятельности: {profile['occupation']}\n"
        text += f"📸 Instagram: {profile['instagram']}\n"
        text += f"🎯 Чем может быть полезен: {profile['skills']}\n"
        text += f"🏆 Всего посещений: {profile['total_visits']}\n"
        if profile['first_visit_date']:
            text += f"📅 Первое посещение: {profile['first_visit_date']}\n"
        if profile['last_visit_date']:
            text += f"📅 Последнее посещение: {profile['last_visit_date']}\n"
        text += "\nХотите обновить информацию? (да/нет)"
        if message:
            await message.reply_text(text)
        return PROFILE
    else:
        if message:
            await message.reply_text(
                "Давайте заполним информацию о вас.\n"
                "Как вас зовут? (Имя и Фамилия)"
            )
        return FULL_NAME

async def handle_profile_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        user = query.from_user
        logger.info(f"[handle_profile_update] CallbackQuery received: data={query.data}, chat_type={update.effective_chat.type}, user_id={user.id}")
        
        await query.answer()
        
        if update.effective_chat.type != "private":
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только в личном чате с ботом.")
            logger.warning(f"[handle_profile_update] Command used in non-private chat by user {user.id}")
            return
            
        message = update.message or (update.callback_query and update.callback_query.message)
        
        if query.data == "update_profile_yes":
            if message:
                await message.reply_text(
                    "Пожалуйста, введите ваше полное имя:"
                )
                logger.info(f"[handle_profile_update] Started profile update for user {user.id}")
                context.user_data['updating_profile'] = True
                context.user_data['profile_step'] = 'full_name'
        elif query.data == "update_profile_no":
            if message:
                await message.reply_text(
                    "Хорошо, если захотите обновить профиль позже, используйте команду /profile"
                )
                logger.info(f"[handle_profile_update] User {user.id} declined profile update")
                
    except Exception as e:
        logger.error(f"[handle_profile_update] Unexpected error: {e}", exc_info=True)
        try:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text(
                    "Произошла непредвиденная ошибка при обновлении профиля. Пожалуйста, попробуйте позже."
                )
        except Exception as inner_e:
            logger.error(f"[handle_profile_update] Error sending error message: {inner_e}", exc_info=True)

async def handle_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.text:
            logger.warning("[handle_full_name] No message or text received")
            return
            
        user = update.effective_user
        full_name = update.message.text.strip()
        logger.info(f"[handle_full_name] Received full name for user {user.id}: {full_name}")
        
        if not context.user_data.get('updating_profile'):
            logger.warning(f"[handle_full_name] User {user.id} not in profile update mode")
            return
            
        context.user_data['full_name'] = full_name
        context.user_data['profile_step'] = 'birth_date'
        logger.info(f"[handle_full_name] Saved full name for user {user.id}")
        
        await update.message.reply_text(
            "Пожалуйста, введите вашу дату рождения в формате ДД.ММ:"
        )
        
    except Exception as e:
        logger.error(f"[handle_full_name] Unexpected error: {e}", exc_info=True)
        try:
            await update.message.reply_text(
                "Произошла непредвиденная ошибка при сохранении имени. Пожалуйста, попробуйте позже."
            )
        except Exception as inner_e:
            logger.error(f"[handle_full_name] Error sending error message: {inner_e}", exc_info=True)

async def handle_birth_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.text:
            logger.warning("[handle_birth_date] No message or text received")
            return
            
        user = update.effective_user
        birth_date = update.message.text.strip()
        logger.info(f"[handle_birth_date] Received birth date for user {user.id}: {birth_date}")
        
        if not context.user_data.get('updating_profile'):
            logger.warning(f"[handle_birth_date] User {user.id} not in profile update mode")
            return
            
        # Проверяем формат даты
        if not re.match(r"^\d{1,2}\.\d{1,2}$", birth_date):
            logger.warning(f"[handle_birth_date] Invalid date format from user {user.id}: {birth_date}")
            await update.message.reply_text(
                "Пожалуйста, введите дату в формате ДД.ММ (например, 01.01):"
            )
            return
            
        context.user_data['birth_date'] = birth_date
        context.user_data['profile_step'] = 'occupation'
        logger.info(f"[handle_birth_date] Saved birth date for user {user.id}")
        
        await update.message.reply_text(
            "Пожалуйста, введите вашу профессию:"
        )
        
    except Exception as e:
        logger.error(f"[handle_birth_date] Unexpected error: {e}", exc_info=True)
        try:
            await update.message.reply_text(
                "Произошла непредвиденная ошибка при сохранении даты рождения. Пожалуйста, попробуйте позже."
            )
        except Exception as inner_e:
            logger.error(f"[handle_birth_date] Error sending error message: {inner_e}", exc_info=True)

async def handle_occupation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.text:
            logger.warning("[handle_occupation] No message or text received")
            return
            
        user = update.effective_user
        occupation = update.message.text.strip()
        logger.info(f"[handle_occupation] Received occupation for user {user.id}: {occupation}")
        
        if not context.user_data.get('updating_profile'):
            logger.warning(f"[handle_occupation] User {user.id} not in profile update mode")
            return
            
        context.user_data['occupation'] = occupation
        context.user_data['profile_step'] = 'instagram'
        logger.info(f"[handle_occupation] Saved occupation for user {user.id}")
        
        await update.message.reply_text(
            "Пожалуйста, введите ваш Instagram (без @):"
        )
        
    except Exception as e:
        logger.error(f"[handle_occupation] Unexpected error: {e}", exc_info=True)
        try:
            await update.message.reply_text(
                "Произошла непредвиденная ошибка при сохранении профессии. Пожалуйста, попробуйте позже."
            )
        except Exception as inner_e:
            logger.error(f"[handle_occupation] Error sending error message: {inner_e}", exc_info=True)

async def handle_instagram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.text:
            logger.warning("[handle_instagram] No message or text received")
            return
            
        user = update.effective_user
        instagram = update.message.text.strip()
        logger.info(f"[handle_instagram] Received Instagram for user {user.id}: {instagram}")
        
        if not context.user_data.get('updating_profile'):
            logger.warning(f"[handle_instagram] User {user.id} not in profile update mode")
            return
            
        context.user_data['instagram'] = instagram
        context.user_data['profile_step'] = 'skills'
        logger.info(f"[handle_instagram] Saved Instagram for user {user.id}")
        
        await update.message.reply_text(
            "Пожалуйста, расскажите о своих навыках и увлечениях:"
        )
        
    except Exception as e:
        logger.error(f"[handle_instagram] Unexpected error: {e}", exc_info=True)
        try:
            await update.message.reply_text(
                "Произошла непредвиденная ошибка при сохранении Instagram. Пожалуйста, попробуйте позже."
            )
        except Exception as inner_e:
            logger.error(f"[handle_instagram] Error sending error message: {inner_e}", exc_info=True)

async def handle_skills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data['skills'] = update.message.text
    message = update.message or (update.callback_query and update.callback_query.message)
    
    # Сохраняем профиль
    success = db.save_user_profile(
        user_id=user.id,
        username=user.username or user.first_name,
        full_name=context.user_data['full_name'],
        birth_date=context.user_data['birth_date'],
        occupation=context.user_data['occupation'],
        instagram=context.user_data['instagram'],
        skills=context.user_data['skills']
    )
    
    if success:
        if message:
            await message.reply_text(
                "Спасибо! Ваш профиль успешно сохранен.\n"
                "Вы можете обновить информацию в любой момент, используя команду /profile"
            )
            
        # Проверяем, есть ли ожидающие подтверждения оплаты для этого пользователя
        pending_payments = db.get_pending_payments(user.id)
        if pending_payments:
            for payment in pending_payments:
                for admin_id in ADMIN_IDS:
                    try:
                        keyboard = [
                            [
                                InlineKeyboardButton("Оплатил онлайн", callback_data=f"admin_confirm_{user.id}_{payment['date_str']}_online"),
                                InlineKeyboardButton("Отклонить", callback_data=f"admin_decline_{user.id}_{payment['date_str']}_online")
                            ]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        profile_info = (
                            f"Пользователь @{user.username or user.first_name} заполнил профиль:\n\n"
                            f"👤 Имя: {context.user_data['full_name']}\n"
                            f"🎂 Дата рождения: {context.user_data['birth_date']}\n"
                            f"💼 Род деятельности: {context.user_data['occupation']}\n"
                            f"📸 Instagram: {context.user_data['instagram']}\n"
                            f"🎯 Сфера бизнеса, область работы, тип услуг которые предоставляет: {context.user_data['skills']}\n\n"
                            f"Теперь можно подтвердить оплату бани на {payment['date_str']}."
                        )
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=profile_info,
                            reply_markup=reply_markup
                        )
                        logger.info(f"Отправлено уведомление администратору {admin_id} о заполненном профиле пользователя {user.id}")
                    except Exception as e:
                        logger.error(f"Ошибка при отправке уведомления администратору {admin_id}: {e}")
    else:
        if message:
            await message.reply_text(
                "Произошла ошибка при сохранении профиля. Пожалуйста, попробуйте позже."
            )
    return ConversationHandler.END

async def start_profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        user = query.from_user
        logger.info(f"[start_profile_callback] CallbackQuery received: data={query.data}, chat_type={update.effective_chat.type}, user_id={user.id}")
        
        await query.answer()
        
        if update.effective_chat.type != "private":
            logger.warning(f"[start_profile_callback] User {user.id} tried to start profile in non-private chat")
            await query.edit_message_text("Профиль можно заполнять только в личном чате с ботом.")
            return
            
        await query.edit_message_text("Давайте заполним информацию о вас.\nКак вас зовут? (Имя и Фамилия)")
        logger.info(f"[start_profile_callback] Started profile creation for user {user.id}")
        return FULL_NAME
        
    except Exception as e:
        logger.error(f"[start_profile_callback] Unexpected error: {e}", exc_info=True)
        try:
            await query.edit_message_text("Произошла непредвиденная ошибка. Пожалуйста, попробуйте позже.")
        except Exception as inner_e:
            logger.error(f"[start_profile_callback] Error sending error message: {inner_e}", exc_info=True)
        return ConversationHandler.END

async def export_profiles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("[export_profiles] Вход в команду /export_profiles")
    try:
        if update.effective_chat.type != "private":
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только в личном чате с ботом.")
            logger.warning("[export_profiles] Попытка запуска не в личном чате")
            return
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("У вас нет прав для выполнения этой команды.")
            logger.warning(f"[export_profiles] Пользователь {user_id} не админ")
            return
        profiles = db.get_all_user_profiles()
        if not profiles:
            await update.message.reply_text("Нет данных о пользователях.")
            return
        with tempfile.NamedTemporaryFile(mode='w+', newline='', delete=False, suffix='.csv') as tmpfile:
            fieldnames = [
                'user_id', 'username', 'full_name', 'birth_date', 'occupation',
                'instagram', 'skills', 'total_visits', 'first_visit_date', 'last_visit_date'
            ]
            writer = csv.DictWriter(tmpfile, fieldnames=fieldnames)
            writer.writeheader()
            for profile in profiles:
                writer.writerow({k: profile.get(k, '') for k in fieldnames})
            tmpfile_path = tmpfile.name
        with open(tmpfile_path, 'rb') as f:
            await context.bot.send_document(
                chat_id=user_id,
                document=f,
                filename='bath_users.csv',
                caption='Экспорт всех профилей пользователей.'
            )
        logger.info(f"[export_profiles] Файл с профилями отправлен администратору {user_id}")
    except Exception as e:
        logger.error(f"Ошибка в функции export_profiles: {e}")
        await update.message.reply_text("Произошла ошибка при экспорте профилей.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отменяет и завершает разговор."""
    message = update.message or (update.callback_query and update.callback_query.message)
    if message:
        await message.reply_text('Операция отменена.')
    return ConversationHandler.END

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        history = db.get_user_bath_history(user.id)
        if not history:
            await update.message.reply_text("У вас пока нет истории посещения бани.")
            return
        text = "Ваша история посещения бани:\n\n"
        for entry in history:
            date = entry['date']
            paid = "✅ Оплачено" if entry['paid'] else "❌ Не оплачено"
            visited = "🛁 Был" if entry.get('visited') else "—"
            text += f"{date}: {paid} {visited}\n"
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"[history] Ошибка при получении истории: {e}", exc_info=True)
        await update.message.reply_text("Произошла ошибка при получении истории. Попробуйте позже.")

async def handle_profile_update_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        text = update.message.text.strip().lower()
        message = update.message
        if text in ["да", "yes", "y", "д"]:
            context.user_data['updating_profile'] = True
            context.user_data['profile_step'] = 'full_name'
            await message.reply_text("Пожалуйста, введите ваше полное имя:")
            logger.info(f"[handle_profile_update_text] Started profile update for user {user.id}")
            return FULL_NAME
        elif text in ["нет", "no", "n", "н"]:
            await message.reply_text("Спасибо! Ваши данные сохранены. Если захотите обновить профиль позже, используйте команду /profile")
            logger.info(f"[handle_profile_update_text] User {user.id} declined profile update")
            return ConversationHandler.END
        else:
            await message.reply_text("Пожалуйста, ответьте 'да' или 'нет'.")
            return PROFILE
    except Exception as e:
        logger.error(f"[handle_profile_update_text] Unexpected error: {e}", exc_info=True)
        await update.message.reply_text("Произошла ошибка. Попробуйте позже.")
        return ConversationHandler.END

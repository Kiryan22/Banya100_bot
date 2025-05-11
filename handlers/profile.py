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
    query = update.callback_query
    await query.answer()
    message = update.message or (update.callback_query and update.callback_query.message)
    if query.data == "update_profile_yes":
        if message:
            await message.reply_text(
                "Пожалуйста, введите ваше полное имя:"
            )
        return FULL_NAME
    else:
        if message:
            await message.reply_text("Хорошо, профиль останется без изменений.")
        return ConversationHandler.END

async def handle_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['full_name'] = update.message.text
        await update.message.reply_text(
            "Введите дату рождения (например, 15 марта):"
        )
        return BIRTH_DATE
    except Exception as e:
        logger.error(f"Ошибка в функции handle_full_name: {e}")
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте снова."
        )
        return ConversationHandler.END

async def handle_birth_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        date_text = update.message.text.strip()
        if not re.match(r"^\d{1,2}\.\d{1,2}$", date_text):
            await update.message.reply_text(
                "Пожалуйста, введите дату рождения в формате ДД.ММ (например, 15.03)"
            )
            return BIRTH_DATE
        context.user_data['birth_date'] = date_text
        await update.message.reply_text(
            "Чем вы занимаетесь? (род деятельности):"
        )
        return OCCUPATION
    except Exception as e:
        logger.error(f"Ошибка в функции handle_birth_date: {e}")
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте снова."
        )
        return ConversationHandler.END

async def handle_occupation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['occupation'] = update.message.text
        await update.message.reply_text(
            "Введите ссылку на ваш Instagram (или 'нет', если не хотите указывать):"
        )
        return INSTAGRAM
    except Exception as e:
        logger.error(f"Ошибка в функции handle_occupation: {e}")
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте снова."
        )
        return ConversationHandler.END

async def handle_instagram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['instagram'] = update.message.text
        await update.message.reply_text(
            "Сфера бизнеса, область работы, тип услуг которые предоставляете и т.д."
        )
        return SKILLS
    except Exception as e:
        logger.error(f"Ошибка в функции handle_instagram: {e}")
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте снова."
        )
        return ConversationHandler.END

async def handle_skills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data['skills'] = update.message.text
    message = update.message or (update.callback_query and update.callback_query.message)
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
        user_pending = None
        for date_str in [p['date_str'] for p in db.get_all_user_profiles() if p['user_id'] == user.id]:
            pending = db.get_pending_payment(user.id, date_str)
            if pending:
                user_pending = pending
                break
        if user_pending:
            for admin_id in ADMIN_IDS:
                try:
                    keyboard = [
                        [
                            InlineKeyboardButton("Оплатил онлайн", callback_data=f"admin_confirm_{user.id}_{user_pending['date_str']}_online"),
                            InlineKeyboardButton("Отклонить", callback_data=f"admin_decline_{user.id}_{user_pending['date_str']}_online")
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
                        f"Теперь можно подтвердить оплату бани на {user_pending['date_str']}."
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
    query = update.callback_query
    user = query.from_user
    logger.info(f"[start_profile_callback] CallbackQuery received: data={query.data}, chat_type={update.effective_chat.type}, user_id={user.id}")
    try:
        await query.answer()
        if update.effective_chat.type != "private":
            await query.edit_message_text("Профиль можно заполнять только в личном чате с ботом.")
            return
        await query.edit_message_text("Давайте заполним информацию о вас.\nКак вас зовут? (Имя и Фамилия)")
        logger.info(f"Начат диалог заполнения профиля для пользователя {user.id}")
        return FULL_NAME
    except Exception as e:
        logger.error(f"Ошибка в функции start_profile_callback: {e}")
        try:
            await query.edit_message_text("Произошла ошибка. Пожалуйста, попробуйте снова.")
        except:
            pass
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

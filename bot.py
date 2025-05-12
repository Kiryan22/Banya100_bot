import logging
from datetime import datetime, timedelta, time
import pytz
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeChat, Message
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, ConversationHandler
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
import os
import re
import csv
import tempfile
from logger import get_logger

from config import *
from database import Database
from handlers.profile import (
    profile, handle_profile_update, handle_full_name, handle_birth_date,
    handle_occupation, handle_instagram, handle_skills, start_profile_callback,
    export_profiles, cancel
)

# Настройка логирования
def setup_logging():
    # Создаем директорию для логов, если её нет
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Настраиваем форматтер для логов с более подробной информацией
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
    )

    # Настраиваем корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Устанавливаем уровень DEBUG для более подробного логирования

    # Создаем обработчики для разных уровней логирования
    def create_file_handler(filename, level):
        handler = logging.FileHandler(os.path.join(log_dir, filename), encoding='utf-8')
        handler.setLevel(level)
        handler.setFormatter(formatter)
        return handler
    
    # Добавляем обработчики для разных уровней логирования
    root_logger.addHandler(create_file_handler('info.log', logging.INFO))
    root_logger.addHandler(create_file_handler('error.log', logging.ERROR))
    root_logger.addHandler(create_file_handler('debug.log', logging.DEBUG))
    root_logger.addHandler(create_file_handler('warning.log', logging.WARNING))

    # Добавляем обработчик для вывода в консоль
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Настраиваем логирование для сторонних библиотек
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    logging.getLogger('telegram').setLevel(logging.INFO)

    # Запускаем очистку старых логов
    cleanup_old_logs(log_dir)

    logger = get_logger(__name__)
    logger.info("Логирование успешно настроено")

def cleanup_old_logs(log_dir):
    """Очищает логи старше 6 месяцев.
    Примечание: История посещений бани в базе данных хранится бессрочно."""
    try:
        current_time = datetime.now()
        for filename in os.listdir(log_dir):
            # Пропускаем файлы базы данных
            if filename.endswith('.db'):
                continue
                
            if filename.endswith('.log'):
                file_path = os.path.join(log_dir, filename)
                file_time = datetime.fromtimestamp(os.path.getctime(file_path))
                if (current_time - file_time).days > 180:  # 6 месяцев = ~180 дней
                    os.remove(file_path)
                    logging.info(f"Удален старый лог: {filename}")
    except Exception as e:
        logging.error(f"Ошибка при очистке старых логов: {e}")

# Инициализация логирования
setup_logging()
logger = logging.getLogger(__name__)

# Инициализация базы данных
db = Database()


# Функция получения даты следующего воскресенья
def get_next_sunday():
    try:
        tz = pytz.timezone('Europe/Warsaw')
        today = datetime.now(tz)
        days_until_sunday = (6 - today.weekday()) % 7
        if days_until_sunday == 0:  # Если сегодня воскресенье, берем следующее
            days_until_sunday = 7
        next_sunday = today + timedelta(days=days_until_sunday)
        logger.info(f"Получена дата следующего воскресенья: {next_sunday.strftime('%d.%m.%Y')}")
        return next_sunday.strftime("%d.%m.%Y")
    except Exception as e:
        logger.error(f"Ошибка при получении даты следующего воскресенья: {e}")
        raise


# Функция форматирования сообщения о бане
def format_bath_message(date_str):
    try:
        participants = db.get_bath_participants(date_str)
        logger.info(f"Форматирование сообщения о бане на {date_str}. Участников: {len(participants)}")

        message = f"НОВАЯ ЗАПИСЬ В БАНЮ👇\n\n"
        message += f"Время: {BATH_TIME} ‼️\n\n"
        message += f"Дата: ВОСКРЕСЕНЬЕ {date_str}\n\n"
        message += f"Cтоимость: {BATH_COST} карта либо наличка при входе📍\n\n"
        message += f"Список участников (максимум {MAX_BATH_PARTICIPANTS} человек):\n"

        for i, participant in enumerate(participants, 1):
            paid_status = "✅" if participant["paid"] else "❌"
            message += f"{i}. {participant['username']} {paid_status}\n"

        if len(participants) == 0:
            message += "Пока никто не записался\n"

        message += f"\nОплата:\n"
        message += f"КАРТА\n{CARD_PAYMENT_LINK}\n"
        message += f"Revolut\n{REVOLUT_PAYMENT_LINK}\n\n"
        message += f"Локация: {BATH_LOCATION}\n\n"

        # Добавляем инструкции по записи только если лимит не достигнут
        if len(participants) < MAX_BATH_PARTICIPANTS:
            message += f"Для записи:\n"
            message += f"1. Нажмите кнопку 'Записаться' ниже\n"
            message += f"2. Следуйте инструкциям бота в личном чате\n"
            message += f"3. Оплатите участие и подтвердите оплату через бота\n"
            message += f"4. Ожидайте подтверждения от администратора"
        else:
            message += f"\n❗️Лимит участников достигнут. Запись закрыта.\n"

        logger.debug(f"Сформировано сообщение о бане: {message[:100]}...")
        return message
    except Exception as e:
        logger.error(f"Ошибка при форматировании сообщения о бане: {e}")
        raise


# Добавим эту функцию для обработки глубоких ссылок
async def handle_deep_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Получаем аргументы из глубокой ссылки
    if not context.args or not context.args[0].startswith("bath_"):
        return

    date_str = context.args[0].replace("bath_", "")

    # Автоматически запускаем процесс регистрации
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

# Команда для старта бота
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"[start] Вход в команду /start. User: {update.effective_user.id}, Chat: {update.effective_chat.id}, Type: {update.effective_chat.type}")
    try:
        if update.effective_chat.type != "private":
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только в личном чате с ботом.")
            logger.warning(f"[start] Попытка запуска не в личном чате. User: {update.effective_user.id}, Chat: {update.effective_chat.id}")
            return

        user = update.effective_user
        logger.debug(f"[start] Данные пользователя: id={user.id}, username={user.username}, first_name={user.first_name}, last_name={user.last_name}")
        
        db.add_active_user(user.id, user.username or user.first_name)
        logger.info(f"[start] Пользователь {user.id} (@{user.username}) запустил бота")

        welcome_message = f"Привет, {user.first_name}! Я бот для управления подписками и записью в баню."
        if context.args:
            arg = context.args[0]
            logger.debug(f"[start] Получены аргументы запуска: {arg}")
            if arg.startswith("bath_"):
                logger.info(f"[start] Пользователь {user.id} пришел по ссылке записи в баню")
                await handle_deep_link(update, context)
                return

        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text(welcome_message)
            logger.debug(f"[start] Отправлено приветственное сообщение пользователю {user.id}")

    except Exception as e:
        logger.error(f"[start] Ошибка в функции start: {e}", exc_info=True)
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text("Произошла ошибка при запуске бота. Пожалуйста, попробуйте позже.")

# Команда для администраторов - создать запись в баню
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
    logger.info("[create_bath_event] Вход в команду /create_bath")
    try:
        if update.effective_chat.type != "private":
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только в личном чате с ботом.")
            logger.warning("[create_bath_event] Попытка запуска не в личном чате")
            return
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("У вас нет прав для выполнения этой команды.")
            logger.warning(f"[create_bath_event] Пользователь {user_id} не админ")
            return
        next_sunday = get_next_sunday()
        cleared_events = db.clear_previous_bath_events(except_date_str=next_sunday)
        db.create_bath_event(next_sunday)
        logger.info(f"[create_bath_event] Создано событие на {next_sunday}")
        message_text = format_bath_message(next_sunday)
        participants = db.get_bath_participants(next_sunday)
        if len(participants) < MAX_BATH_PARTICIPANTS:
            keyboard = [
                [InlineKeyboardButton("Записаться", callback_data=f"join_bath_{next_sunday}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
        else:
            reply_markup = None
        old_pinned_id = db.get_last_pinned_message_id(BATH_CHAT_ID)
        if old_pinned_id:
            try:
                await context.bot.unpin_chat_message(chat_id=BATH_CHAT_ID, message_id=old_pinned_id)
                db.delete_pinned_message_id(old_pinned_id, BATH_CHAT_ID)
                logger.info(f"[create_bath_event] Откреплено старое сообщение {old_pinned_id}")
            except Exception as e:
                logger.warning(f'[create_bath_event] Не удалось открепить старое сообщение: {e}')
        sent_message = await context.bot.send_message(
            chat_id=BATH_CHAT_ID,
            text=message_text,
            reply_markup=reply_markup
        )
        # Проверяем, есть ли уже закрепленное сообщение
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
                    logger.info(f"[create_bath_event] Закрепленное сообщение обновлено")
                except Exception as e:
                    logger.error(f"[create_bath_event] Ошибка при обновлении закрепленного сообщения: {e}")
            else:
                logger.info(f"[create_bath_event] Сообщение и кнопки не требуют обновления")
        else:
            await context.bot.pin_chat_message(
                chat_id=BATH_CHAT_ID,
                message_id=sent_message.message_id,
                disable_notification=False
            )
            db.set_pinned_message_id(next_sunday, sent_message.message_id, BATH_CHAT_ID)
            logger.info(f"[create_bath_event] Сообщение закреплено: {sent_message.message_id}")
        if cleared_events > 0:
            await context.bot.send_message(
                chat_id=BATH_CHAT_ID,
                text=f"Создана новая запись на баню {next_sunday}. Список участников предыдущей бани очищен."
            )
            logger.info(f"[create_bath_event] Очищено {cleared_events} старых событий")
        # Обновляем закреплённое сообщение через универсальную функцию
        await update_pinned_bath_message(context, next_sunday, participants, message_text, reply_markup)
    except Exception as e:
        logger.error(f"Ошибка в функции create_bath_event: {e}")

# Обработка кнопки "Записаться"
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        user = query.from_user
        logger.info(f"[button_callback] Получен callback: data={query.data}, chat_type={update.effective_chat.type}, user_id={user.id}")
        
        # Добавляем пользователя в активные
        db.add_active_user(user.id, user.username or user.first_name)
        logger.debug(f"[button_callback] Пользователь {user.id} добавлен в активные")
        
        # Обработка различных типов callback_data
        if query.data.startswith("join_bath_"):
            try:
                date_str = query.data.replace("join_bath_", "")
                logger.info(f"[button_callback] Пользователь {user.id} хочет записаться на баню {date_str}")
                
                # Проверяем, не достигнут ли лимит участников
                participants = db.get_bath_participants(date_str)
                logger.debug(f"[button_callback] Текущее количество участников: {len(participants)}")
                
                if len(participants) >= MAX_BATH_PARTICIPANTS:
                    logger.warning(f"[button_callback] Баня на {date_str} уже заполнена")
                    await query.edit_message_text(
                        text="К сожалению, баня уже занята. Вы можете записаться в следующий раз!"
                    )
                    return

                # Проверяем, не записан ли уже пользователь
                if any(p['user_id'] == user.id for p in participants):
                    logger.warning(f"[button_callback] Пользователь {user.id} уже записан на {date_str}")
                    await query.edit_message_text(
                        text="Вы уже записаны на эту баню!"
                    )
                    return

                # Отправляем сообщение с подтверждением
                keyboard = [
                    [InlineKeyboardButton("Подтвердить запись", callback_data=f"confirm_bath_{date_str}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    text=f"Вы хотите записаться на баню {date_str}?\n\n"
                         f"Стоимость: {BATH_COST}\n"
                         f"Время: {BATH_TIME}\n\n"
                         f"Нажмите 'Подтвердить запись' для продолжения.",
                    reply_markup=reply_markup
                )
                logger.info(f"[button_callback] Отправлено сообщение с подтверждением пользователю {user.id}")
                
            except Exception as e:
                logger.error(f"[button_callback] Ошибка при обработке join_bath: {e}", exc_info=True)
                await query.edit_message_text(
                    text="Произошла ошибка при обработке запроса. Пожалуйста, попробуйте позже."
                )
                
        elif query.data.startswith("confirm_bath_"):
            try:
                date_str = query.data.replace("confirm_bath_", "")
                logger.info(f"[button_callback] User {user.id} confirmed bath registration for {date_str}")
                
                # Проверяем, не достигнут ли лимит участников
                participants = db.get_bath_participants(date_str)
                if len(participants) >= MAX_BATH_PARTICIPANTS:
                    logger.warning(f"[button_callback] Bath {date_str} is full")
                    await query.edit_message_text(
                        text="К сожалению, все места уже заняты."
                    )
                    return
                
                # Сохраняем информацию о регистрации
                username = user.username or f"{user.first_name} {user.last_name or ''}"
                if 'bath_registrations' not in context.user_data:
                    context.user_data['bath_registrations'] = {}
                context.user_data['bath_registrations'][date_str] = {
                    'user_id': user.id,
                    'username': username,
                    'status': 'confirmed'
                }
                logger.info(f"[button_callback] Saved registration info for user {user.id}")
                
                try:
                    # Отправляем инструкции по оплате
                    keyboard = [
                        [
                            InlineKeyboardButton("💳 Оплатить онлайн", callback_data=f"pay_bath_{date_str}"),
                            InlineKeyboardButton("💵 Буду платить наличными", callback_data=f"cash_bath_{date_str}")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await query.edit_message_text(
                        text=f"Отлично! Вы записаны на баню {date_str}.\n\n"
                             f"Выберите способ оплаты:",
                        reply_markup=reply_markup
                    )
                    logger.info(f"[button_callback] Sent payment instructions to user {user.id}")
                    
                except Exception as e:
                    logger.error(f"[button_callback] Error sending payment instructions: {e}", exc_info=True)
                    await query.edit_message_text(
                        text="Произошла ошибка при отправке инструкций по оплате. Пожалуйста, попробуйте позже."
                    )
                
            except Exception as e:
                logger.error(f"[button_callback] Error processing confirm_bath: {e}", exc_info=True)
                await query.edit_message_text(
                    text="Произошла ошибка при обработке запроса. Пожалуйста, попробуйте позже."
                )
                
        elif query.data.startswith("paid_bath_"):
            try:
                date_str = query.data.replace("paid_bath_", "")
                logger.info(f"[button_callback] User {user.id} marked payment as paid for {date_str}")
                
                # Проверяем, есть ли запись о регистрации
                if ('bath_registrations' not in context.user_data or
                        date_str not in context.user_data['bath_registrations']):
                    logger.warning(f"[button_callback] No registration found for user {user.id} on {date_str}")
                    await query.edit_message_text(
                        text="Ошибка: сначала нужно подтвердить запись на баню."
                    )
                    return
                
                # Обновляем статус
                username = user.username or f"{user.first_name} {user.last_name or ''}"
                context.user_data['bath_registrations'][date_str] = {
                    'user_id': user.id,
                    'username': username,
                    'status': 'pending_confirmation'
                }
                logger.info(f"[button_callback] Updated registration status for user {user.id}")
                
                # Добавляем заявку на подтверждение оплаты
                db.add_pending_payment(user.id, username, date_str, payment_type='online')
                logger.info(f"[button_callback] Added pending payment for user {user.id}")
                
                # Отправляем подтверждение пользователю
                await query.edit_message_text(
                    text=f"Спасибо! Ваша заявка на оплату отправлена администратору.\n"
                         f"После подтверждения вы получите уведомление."
                )
                
                # Уведомляем администраторов
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
            except Exception as e:
                logger.error(f"[button_callback] Error processing paid_bath: {e}", exc_info=True)
                await query.edit_message_text(
                    text="Произошла ошибка при обработке запроса. Пожалуйста, попробуйте позже."
                )
                
        elif query.data.startswith("cash_bath_"):
            try:
                date_str = query.data.replace("cash_bath_", "")
                logger.info(f"[button_callback] User {user.id} chose cash payment for {date_str}")
                
                # Проверяем, есть ли запись о регистрации
                if ('bath_registrations' not in context.user_data or
                        date_str not in context.user_data['bath_registrations']):
                    logger.warning(f"[button_callback] No registration found for user {user.id} on {date_str}")
                    await query.edit_message_text(
                        text="Ошибка: сначала нужно подтвердить запись на баню."
                    )
                    return
                
                # Обновляем статус
                username = user.username or f"{user.first_name} {user.last_name or ''}"
                context.user_data['bath_registrations'][date_str] = {
                    'user_id': user.id,
                    'username': username,
                    'status': 'pending_cash'
                }
                logger.info(f"[button_callback] Updated registration status for user {user.id}")
                
                try:
                    # Добавляем запись с cash=True
                    db.add_bath_participant(date_str, user.id, username, paid=False)
                    
                    # Обновляем поле cash вручную
                    conn = db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute('UPDATE bath_participants SET cash = 1 WHERE date_str = ? AND user_id = ?', (date_str, user.id))
                    conn.commit()
                    conn.close()
                    
                    # Удаляем старую заявку, если была
                    db.delete_pending_payment(user.id, date_str)
                    
                    # Добавляем заявку на подтверждение оплаты наличными
                    db.add_pending_payment(user.id, username, date_str, payment_type='cash')
                    logger.info(f"[button_callback] Added cash payment request for user {user.id}")
                    
                    # Отправляем подтверждение пользователю
                    await query.edit_message_text(
                        text=f"Вы выбрали оплату наличными при входе.\n\n"
                             f"Ваша заявка отправлена администратору на подтверждение.\n"
                             f"После подтверждения вы получите уведомление."
                    )
                    
                    # Уведомляем администраторов
                    for admin_id in ADMIN_IDS:
                        try:
                            keyboard = [
                                [
                                    InlineKeyboardButton("✅ Подтвердить", callback_data=f"admin_confirm_{user.id}_{date_str}_cash"),
                                    InlineKeyboardButton("❌ Отклонить", callback_data=f"admin_decline_{user.id}_{date_str}_cash")
                                ]
                            ]
                            reply_markup = InlineKeyboardMarkup(keyboard)
                            
                            await context.bot.send_message(
                                chat_id=admin_id,
                                text=f"Новая заявка на оплату наличными:\n"
                                     f"Пользователь: @{username}\n"
                                     f"Дата: {date_str}",
                                reply_markup=reply_markup
                            )
                            logger.info(f"[button_callback] Sent notification to admin {admin_id}")
                        except Exception as e:
                            logger.error(f"[button_callback] Error sending notification to admin {admin_id}: {e}", exc_info=True)
                            
                except Exception as e:
                    logger.error(f"[button_callback] Error processing cash payment: {e}", exc_info=True)
                    await query.edit_message_text(
                        text="Произошла ошибка при обработке оплаты. Пожалуйста, попробуйте позже."
                    )
                    
            except Exception as e:
                logger.error(f"[button_callback] Error processing cash_bath: {e}", exc_info=True)
                await query.edit_message_text(
                    text="Произошла ошибка при обработке запроса. Пожалуйста, попробуйте позже."
                )
                
        elif query.data.startswith("admin_confirm_"):
            try:
                parts = query.data.split("_")
                user_id = int(parts[2])
                date_str = parts[3]
                payment_type = parts[4]
                logger.info(f"[button_callback] Admin {user.id} confirming payment for user {user_id} on {date_str}")
                
                # Проверяем права администратора
                if user.id not in ADMIN_IDS:
                    logger.warning(f"[button_callback] Non-admin user {user.id} tried to confirm payment")
                    await query.edit_message_text(
                        text="У вас нет прав для выполнения этой операции."
                    )
                    return
                
                # Подтверждаем оплату
                if db.mark_participant_paid(date_str, user_id):
                    # Удаляем заявку из pending_payments
                    db.delete_pending_payment(user_id, date_str)
                    
                    # Отправляем уведомление пользователю
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=f"✅ Ваша оплата на баню {date_str} подтверждена!"
                        )
                        logger.info(f"[button_callback] Sent confirmation to user {user_id}")
                    except Exception as e:
                        logger.error(f"[button_callback] Error sending confirmation to user {user_id}: {e}", exc_info=True)
                    
                    # Обновляем сообщение для администратора
                    await query.edit_message_text(
                        text=f"✅ Оплата пользователя подтверждена.\n"
                             f"Дата: {date_str}"
                    )
                    logger.info(f"[button_callback] Payment confirmed for user {user_id}")
                else:
                    logger.error(f"[button_callback] Failed to mark payment as paid for user {user_id}")
                    await query.edit_message_text(
                        text="❌ Не удалось подтвердить оплату. Пожалуйста, попробуйте позже."
                    )
                    
            except Exception as e:
                logger.error(f"[button_callback] Error processing admin_confirm: {e}", exc_info=True)
                await query.edit_message_text(
                    text="Произошла ошибка при обработке запроса. Пожалуйста, попробуйте позже."
                )
                
        elif query.data.startswith("admin_decline_"):
            try:
                parts = query.data.split("_")
                user_id = int(parts[2])
                date_str = parts[3]
                payment_type = parts[4]
                logger.info(f"[button_callback] Admin {user.id} declining payment for user {user_id} on {date_str}")
                
                # Проверяем права администратора
                if user.id not in ADMIN_IDS:
                    logger.warning(f"[button_callback] Non-admin user {user.id} tried to decline payment")
                    await query.edit_message_text(
                        text="У вас нет прав для выполнения этой операции."
                    )
                    return
                
                # Получаем информацию о пользователе
                user_data = db.get_pending_payment(user_id, date_str, payment_type)
                if user_data:
                    username = user_data.get('username')
                    db.delete_pending_payment(user_id, date_str)
                    
                    # Отправляем уведомление пользователю
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=f"❌ К сожалению, ваша оплата на баню {date_str} не подтверждена. "
                                 f"Пожалуйста, свяжитесь с администратором для выяснения деталей."
                        )
                        logger.info(f"[button_callback] Sent decline notification to user {user_id}")
                    except Exception as e:
                        logger.error(f"[button_callback] Error sending decline notification to user {user_id}: {e}", exc_info=True)
                    
                    # Обновляем сообщение для администратора
                    keyboard = [
                        [InlineKeyboardButton("Отправить сообщение", callback_data=f"message_user_{user_id}_{date_str}")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await query.edit_message_text(
                        text=f"Вы отклонили оплату пользователя @{username} на {date_str}. "
                             f"Вы можете отправить пользователю сообщение с объяснением.",
                        reply_markup=reply_markup
                    )
                    logger.info(f"[button_callback] Payment declined for user {user_id}")
                else:
                    logger.warning(f"[button_callback] No pending payment found for user {user_id}")
                    await query.edit_message_text(
                        text="Информация о пользователе не найдена. Возможно, запрос устарел."
                    )
                    
            except Exception as e:
                logger.error(f"[button_callback] Error processing admin_decline: {e}", exc_info=True)
                await query.edit_message_text(
                    text="Произошла ошибка при обработке запроса. Пожалуйста, попробуйте позже."
                )
                
        else:
            logger.warning(f"[button_callback] Unknown callback data: {query.data}")
            await query.answer("Неизвестная команда")
            
    except Exception as e:
        logger.error(f"[button_callback] Непредвиденная ошибка: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                text="Произошла непредвиденная ошибка. Пожалуйста, попробуйте позже."
            )
        except Exception as inner_e:
            logger.error(f"[button_callback] Ошибка при отправке сообщения об ошибке: {inner_e}", exc_info=True)

# Обработка кнопки "Подтвердить запись" в личном чате
async def confirm_bath_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        user = query.from_user
        logger.info(f"[confirm_bath_registration] CallbackQuery received: data={query.data}, chat_type={update.effective_chat.type}, user_id={user.id}")
        
        # Добавляем пользователя в активные
        db.add_active_user(user.id, user.username or user.first_name)
        
        if query.data.startswith("confirm_bath_"):
            date_str = query.data.replace("confirm_bath_", "")
            logger.info(f"[confirm_bath_registration] User {user.id} confirmed registration for {date_str}")
            
            # Проверяем лимит участников
            participants = db.get_bath_participants(date_str)
            if len(participants) >= 6:
                logger.warning(f"[confirm_bath_registration] Bath {date_str} is full")
                await query.edit_message_text(
                    text="К сожалению, все места уже заняты."
                )
                return
            
            # Сохраняем информацию о регистрации
            username = user.username or f"{user.first_name} {user.last_name or ''}"
            if 'bath_registrations' not in context.user_data:
                context.user_data['bath_registrations'] = {}
            context.user_data['bath_registrations'][date_str] = {
                'user_id': user.id,
                'username': username,
                'status': 'confirmed'
            }
            logger.info(f"[confirm_bath_registration] Saved registration info for user {user.id}")
            
            try:
                # Отправляем инструкции по оплате
                keyboard = [
                    [
                        InlineKeyboardButton("💳 Оплатить онлайн", callback_data=f"pay_bath_{date_str}"),
                        InlineKeyboardButton("💵 Буду платить наличными", callback_data=f"cash_bath_{date_str}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    text=f"Отлично! Вы записаны на баню {date_str}.\n\n"
                         f"Выберите способ оплаты:",
                    reply_markup=reply_markup
                )
                logger.info(f"[confirm_bath_registration] Sent payment instructions to user {user.id}")
                
            except Exception as e:
                logger.error(f"[confirm_bath_registration] Error sending payment instructions: {e}", exc_info=True)
                await query.edit_message_text(
                    text="Произошла ошибка при отправке инструкций по оплате. Пожалуйста, попробуйте позже."
                )
                
    except Exception as e:
        logger.error(f"[confirm_bath_registration] Unexpected error: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                text="Произошла непредвиденная ошибка. Пожалуйста, попробуйте позже."
            )
        except Exception as inner_e:
            logger.error(f"[confirm_bath_registration] Error sending error message: {inner_e}", exc_info=True)


# Обработка кнопки "Я оплатил(а)"
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

            # Проверяем, есть ли запись о регистрации
            if ('bath_registrations' in context.user_data and
                    date_str in context.user_data['bath_registrations']):

                # Обновляем статус
                context.user_data['bath_registrations'][date_str]['status'] = 'payment_claimed'
                logger.info(f"Обновлен статус регистрации пользователя {user.id} на {date_str}")

                # Получаем данные пользователя
                username = user.username or f"{user.first_name} {user.last_name or ''}"

                # Сохраняем в базе данных как ожидающего подтверждения администратором
                user_data = {
                    'user_id': user.id,
                    'username': username,
                    'date_str': date_str
                }
                logger.info(f"Добавляю заявку: user_id={user.id}, username={username}, date_str={date_str}, payment_type=online")
                db.add_pending_payment(user.id, username, date_str, payment_type='online')
                logger.info(f"Добавлена заявка на подтверждение оплаты от пользователя {user.id}")

                # Отправляем сообщение пользователю
                await query.edit_message_text(
                    text=f"Спасибо! Ваша заявка об оплате отправлена администратору.\n"
                         f"После подтверждения оплаты, вы будете добавлены в список участников бани на {date_str}.\n"
                         f"Пожалуйста, ожидайте подтверждения."
                )

                # Отправляем уведомление администраторам
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


# Обработка подтверждения оплаты администратором
async def admin_confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id, date_str, payment_type):
    query = update.callback_query
    await query.answer()

    admin_id = update.effective_user.id

    # Проверяем, является ли пользователь администратором
    if admin_id not in ADMIN_IDS:
        await query.edit_message_text("У вас нет прав для выполнения этой операции.")
        return

    callback_data = query.data
    parts = callback_data.split("_")

    # Исправлено: убираем проверку на len(parts), просто проверяем тип действия
    if parts[0] == "admin" and parts[1] == "confirm":
        # Корректно разбираем user_id, date_str, payment_type
        user_id = int(parts[2])
        date_str = parts[3]
        payment_type = parts[4] if len(parts) > 4 else None

        user_data = db.get_pending_payment(user_id, date_str, payment_type)
        logger.info(f"[admin_confirm_payment] Ищу заявку: user_id={user_id}, date_str={date_str}, payment_type={payment_type}")
        logger.info(f"[admin_confirm_payment] Результат поиска: {user_data}")
        if user_data:
            profile = db.get_user_profile(user_id)
            if not profile:
                await query.edit_message_text(
                    text="Пользователь не заполнил профиль. Сначала нужно заполнить профиль, а затем подтвердить оплату."
                )
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="Для записи в баню необходимо заполнить информацию о себе. Пожалуйста, заполните профиль:",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("Заполнить профиль", callback_data="start_profile")]
                        ])
                    )
                except Exception as e:
                    logger.error(f"[admin_confirm_payment] Ошибка при отправке приглашения заполнить профиль пользователю {user_id}: {e}")
                return

            username = user_data.get('username')
            # Проверяем, есть ли участник в таблице
            participants = db.get_bath_participants(date_str)
            user_in_participants = any(p['user_id'] == user_id for p in participants)
            if not user_in_participants:
                db.add_bath_participant(date_str, user_id, username, paid=False)
                # Если оплата наличными, обновляем cash
                if payment_type == 'cash':
                    try:
                        conn = db.get_connection()
                        cursor = conn.cursor()
                        cursor.execute('UPDATE bath_participants SET cash = 1 WHERE date_str = ? AND user_id = ?', (date_str, user_id))
                        conn.commit()
                    finally:
                        conn.close()
            # Теперь отмечаем оплату
            db.mark_participant_paid(date_str, user_id)
            db.delete_pending_payment(user_id, date_str)
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"Поздравляем! Ваша оплата на баню {date_str} подтверждена. Вы добавлены в список участников."
                )
                logger.info(f"[admin_confirm_payment] Уведомление отправлено пользователю {user_id}")
            except Exception as e:
                logger.error(f"[admin_confirm_payment] Ошибка при отправке подтверждения пользователю {user_id}: {e}")
            try:
                await query.edit_message_text(
                    text=f"Вы подтвердили оплату пользователя @{username} на {date_str}. Пользователь добавлен в список участников."
                )
                logger.info(f"[admin_confirm_payment] Сообщение для админа обновлено")
            except Exception as e:
                logger.error(f"[admin_confirm_payment] Ошибка при обновлении сообщения для админа: {e}")
            # --- ГАРАНТИРОВАННО обновляем и отправляем список участников в группу ---
            try:
                logger.info(f"[admin_confirm_payment] Обновляю и отправляю список участников в группу {BATH_CHAT_ID} для даты {date_str}")
                participants = db.get_bath_participants(date_str)  # повторно получаем актуальный список
                participants_list = f"Обновленный список участников бани на {date_str}:\n\n"
                for i, participant in enumerate(participants, 1):
                    paid_status = "✅" if participant.get("paid") else "❌"
                    cash_status = "💵" if participant.get("cash") else ""
                    participants_list += f"{i}. {participant['username']} {paid_status}{cash_status}\n"
                if len(participants) == 0:
                    participants_list += "Пока никто не записался\n"
                await context.bot.send_message(
                    chat_id=BATH_CHAT_ID,
                    text=f"@{username} успешно записался(ась) на баню {date_str} ✅\n\n{participants_list}"
                )
                # --- Обновляем закреплённое сообщение, если нужно ---
                message = format_bath_message(date_str)
                pinned_messages = await context.bot.get_chat(BATH_CHAT_ID)
                logger.info(f"[admin_confirm_payment] Закреплённый message_id в чате: {pinned_messages.pinned_message.message_id if pinned_messages.pinned_message else 'None'}")
                # Формируем reply_markup в зависимости от лимита участников
                if len(participants) < MAX_BATH_PARTICIPANTS:
                    keyboard = [
                        [InlineKeyboardButton("Записаться", callback_data=f"join_bath_{date_str}")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                else:
                    reply_markup = None
                current_message = pinned_messages.pinned_message.text if pinned_messages.pinned_message else None
                current_markup = pinned_messages.pinned_message.reply_markup if pinned_messages.pinned_message else None
                logger.info(f"[admin_confirm_payment] Пытаюсь обновить закреплённое сообщение: message_id={pinned_messages.pinned_message.message_id if pinned_messages.pinned_message else 'None'}")
                logger.info(f"[admin_confirm_payment] Текущий текст: {current_message}")
                logger.info(f"[admin_confirm_payment] Новый текст: {message}")
                logger.info(f"[admin_confirm_payment] Текущие кнопки: {current_markup}")
                logger.info(f"[admin_confirm_payment] Новые кнопки: {reply_markup}")
                def markup_to_str(markup):
                    if not markup:
                        return ''
                    return str([[btn.text for btn in row] for row in markup.inline_keyboard])
                markup_changed = markup_to_str(current_markup) != markup_to_str(reply_markup)
                # Если message_id не совпадает с ожидаемым или текст отличается, открепляем все и закрепляем новое сообщение
                expected_message = message
                if not pinned_messages.pinned_message or current_message != expected_message:
                    logger.info(f"[admin_confirm_payment] Открепляю старое и закрепляю новое сообщение!")
                    try:
                        await context.bot.unpin_all_chat_messages(BATH_CHAT_ID)
                    except Exception as e:
                        logger.warning(f"[admin_confirm_payment] Не удалось открепить все сообщения: {e}")
                    # Отправляем и закрепляем новое
                    sent_message = await context.bot.send_message(
                        chat_id=BATH_CHAT_ID,
                        text=message,
                        reply_markup=reply_markup
                    )
                    await context.bot.pin_chat_message(
                        chat_id=BATH_CHAT_ID,
                        message_id=sent_message.message_id,
                        disable_notification=False
                    )
                    logger.info(f"[admin_confirm_payment] Новое сообщение закреплено: {sent_message.message_id}")
                elif current_message != message or markup_changed:
                    try:
                        await context.bot.edit_message_text(
                            chat_id=BATH_CHAT_ID,
                            message_id=pinned_messages.pinned_message.message_id,
                            text=message,
                            reply_markup=reply_markup
                        )
                        logger.info(f"[admin_confirm_payment] Закрепленное сообщение обновлено после подтверждения оплаты")
                    except Exception as e:
                        logger.error(f"[admin_confirm_payment] Ошибка при обновлении закрепленного сообщения: {e}")
                else:
                    logger.info(f"[admin_confirm_payment] Закрепленное сообщение не требует обновления после подтверждения оплаты")
                logger.info(f"[admin_confirm_payment] Список участников обновлен и отправлен в группу")
            except Exception as e:
                logger.error(f"[admin_confirm_payment] Ошибка при обновлении списка участников в группе: {e}")
            # --- КОНЕЦ ДОБАВЛЕНИЯ ---
        else:
            try:
                await query.edit_message_text(
                    text="Информация о пользователе не найдена. Возможно, запрос устарел."
                )
                logger.info(f"[admin_confirm_payment] Заявка не найдена для user_id={user_id}, date_str={date_str}, payment_type={payment_type}")
            except Exception as e:
                logger.error(f"[admin_confirm_payment] Ошибка при уведомлении админа об отсутствии заявки: {e}")

# Обработка отклонения оплаты администратором
async def admin_decline_payment(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id, date_str, payment_type):
    query = update.callback_query
    await query.answer()

    admin_id = update.effective_user.id

    if admin_id not in ADMIN_IDS:
        await query.edit_message_text("У вас нет прав для выполнения этой операции.")
        return

    callback_data = query.data
    parts = callback_data.split("_")

    # Исправлено: убираем проверку на len(parts), просто проверяем тип действия
    if parts[0] == "admin" and parts[1] == "decline":
        user_id = int(parts[2])
        date_str = parts[3]
        payment_type = parts[4] if len(parts) > 4 else None

async def handle_skills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.text:
            logger.warning("[handle_skills] No message or text received")
            return ConversationHandler.END
            
        user = update.message.from_user
        skills = update.message.text
        logger.info(f"[handle_skills] User {user.id} entered skills: {skills}")
        
        # Сохраняем навыки в контексте
        context.user_data['skills'] = skills
        logger.info(f"[handle_skills] Saved skills for user {user.id}")
        
        try:
            # Сохраняем профиль пользователя
            profile_data = {
                'user_id': user.id,
                'username': user.username or f"{user.first_name} {user.last_name or ''}",
                'full_name': f"{user.first_name} {user.last_name or ''}",
                'birth_date': context.user_data.get('birth_date'),
                'occupation': context.user_data.get('occupation'),
                'instagram': context.user_data.get('instagram'),
                'skills': skills
            }
            
            db.save_user_profile(profile_data)
            logger.info(f"[handle_skills] Saved user profile for user {user.id}")
            
            # Отправляем подтверждение
            await update.message.reply_text(
                "Спасибо! Ваш профиль успешно сохранен.\n\n"
                "Вы можете обновить информацию о себе в любой момент, используя команду /profile"
            )
            
            # Проверяем наличие ожидающих оплат
            try:
                pending_payments = db.get_pending_payments(user.id)
                if pending_payments:
                    logger.info(f"[handle_skills] Found {len(pending_payments)} pending payments for user {user.id}")
                    
                    # Уведомляем администраторов
                    for admin_id in ADMIN_IDS:
                        try:
                            profile_info = (
                                f"Профиль пользователя:\n"
                                f"Имя: {profile_data['full_name']}\n"
                                f"Дата рождения: {profile_data['birth_date']}\n"
                                f"Профессия: {profile_data['occupation']}\n"
                                f"Instagram: {profile_data['instagram']}\n"
                                f"Навыки: {profile_data['skills']}\n\n"
                                f"Ожидающие оплаты:"
                            )
                            
                            for payment in pending_payments:
                                profile_info += f"\n- {payment['date_str']} ({payment['payment_type']})"
                                
                            keyboard = [
                                [
                                    InlineKeyboardButton("✅ Подтвердить", callback_data=f"admin_confirm_{user.id}_{payment['date_str']}_{payment['payment_type']}"),
                                    InlineKeyboardButton("❌ Отклонить", callback_data=f"admin_decline_{user.id}_{payment['date_str']}_{payment['payment_type']}")
                                ]
                                for payment in pending_payments
                            ]
                            reply_markup = InlineKeyboardMarkup(keyboard)
                            
                            await context.bot.send_message(
                                chat_id=admin_id,
                                text=profile_info,
                                reply_markup=reply_markup
                            )
                            logger.info(f"[handle_skills] Sent profile info to admin {admin_id}")
                        except Exception as e:
                            logger.error(f"[handle_skills] Error sending profile info to admin {admin_id}: {e}", exc_info=True)
                            
            except Exception as e:
                logger.error(f"[handle_skills] Error checking pending payments: {e}", exc_info=True)
                
        except Exception as e:
            logger.error(f"[handle_skills] Error saving profile: {e}", exc_info=True)
            await update.message.reply_text(
                "Произошла ошибка при сохранении профиля. Пожалуйста, попробуйте позже."
            )
            
    except Exception as e:
        logger.error(f"[handle_skills] Unexpected error: {e}", exc_info=True)
        try:
            await update.message.reply_text(
                "Произошла непредвиденная ошибка. Пожалуйста, попробуйте позже."
            )
        except Exception as inner_e:
            logger.error(f"[handle_skills] Error sending error message: {inner_e}", exc_info=True)
            
    return ConversationHandler.END

async def handle_cash_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        user = query.from_user
        logger.info(f"[handle_cash_payment] CallbackQuery received: data={query.data}, chat_type={update.effective_chat.type}, user_id={user.id}")
        
        # Добавляем пользователя в активные
        db.add_active_user(user.id, user.username or user.first_name)
        
        if query.data.startswith("cash_bath_"):
            date_str = query.data.replace("cash_bath_", "")
            logger.info(f"[handle_cash_payment] User {user.id} chose cash payment for {date_str}")
            
            # Проверяем, есть ли запись о регистрации
            if ('bath_registrations' not in context.user_data or
                    date_str not in context.user_data['bath_registrations']):
                logger.warning(f"[handle_cash_payment] No registration found for user {user.id} on {date_str}")
                await query.edit_message_text(
                    text="Ошибка: сначала нужно подтвердить запись на баню."
                )
                return
            
            # Обновляем статус
            username = user.username or f"{user.first_name} {user.last_name or ''}"
            context.user_data['bath_registrations'][date_str] = {
                'user_id': user.id,
                'username': username,
                'status': 'pending_cash'
            }
            logger.info(f"[handle_cash_payment] Updated registration status for user {user.id}")
            
            try:
                # Добавляем запись с cash=True
                db.add_bath_participant(date_str, user.id, username, paid=False)
                
                # Обновляем поле cash вручную
                conn = db.get_connection()
                cursor = conn.cursor()
                cursor.execute('UPDATE bath_participants SET cash = 1 WHERE date_str = ? AND user_id = ?', (date_str, user.id))
                conn.commit()
                conn.close()
                
                # Удаляем старую заявку, если была
                db.delete_pending_payment(user.id, date_str)
                
                # Добавляем заявку на подтверждение оплаты наличными
                db.add_pending_payment(user.id, username, date_str, payment_type='cash')
                logger.info(f"[handle_cash_payment] Added cash payment request for user {user.id}")
                
                # Отправляем подтверждение пользователю
                await query.edit_message_text(
                    text=f"Вы выбрали оплату наличными при входе.\n\n"
                         f"Ваша заявка отправлена администратору на подтверждение.\n"
                         f"После подтверждения вы получите уведомление."
                )
                
                # Уведомляем администраторов
                for admin_id in ADMIN_IDS:
                    try:
                        keyboard = [
                            [
                                InlineKeyboardButton("✅ Подтвердить", callback_data=f"admin_confirm_{user.id}_{date_str}_cash"),
                                InlineKeyboardButton("❌ Отклонить", callback_data=f"admin_decline_{user.id}_{date_str}_cash")
                            ]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=f"Новая заявка на оплату наличными:\n"
                                 f"Пользователь: @{username}\n"
                                 f"Дата: {date_str}",
                            reply_markup=reply_markup
                        )
                        logger.info(f"[handle_cash_payment] Sent notification to admin {admin_id}")
                    except Exception as e:
                        logger.error(f"[handle_cash_payment] Error sending notification to admin {admin_id}: {e}", exc_info=True)
                            
            except Exception as e:
                logger.error(f"[handle_cash_payment] Error processing cash payment: {e}", exc_info=True)
                await query.edit_message_text(
                    text="Произошла ошибка при обработке оплаты. Пожалуйста, попробуйте позже."
                )
                
    except Exception as e:
        logger.error(f"[handle_cash_payment] Unexpected error: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                text="Произошла непредвиденная ошибка. Пожалуйста, попробуйте позже."
            )
        except Exception as inner_e:
            logger.error(f"[handle_cash_payment] Error sending error message: {inner_e}", exc_info=True)

if __name__ == "__main__":
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
    
    application = Application.builder().token(BOT_TOKEN).build()

    # Базовые команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("register", register_bath))
    application.add_handler(CommandHandler("create_bath", create_bath_event))
    
    # Обработчики кнопок
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(CallbackQueryHandler(confirm_bath_registration, pattern="^confirm_bath_"))
    application.add_handler(CallbackQueryHandler(handle_payment_confirmation, pattern="^paid_bath_"))
    application.add_handler(CallbackQueryHandler(handle_cash_payment, pattern="^cash_bath_"))
    application.add_handler(CallbackQueryHandler(admin_confirm_payment, pattern="^admin_confirm_"))
    application.add_handler(CallbackQueryHandler(admin_decline_payment, pattern="^admin_decline_"))
    
    # Обработчик глубоких ссылок
    application.add_handler(CommandHandler("start", handle_deep_link, filters=filters.Regex("^bath_")))

    logger.info("Запуск бота")
    application.run_polling()

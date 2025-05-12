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

    # Настраиваем формат логов
    log_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Настраиваем ротацию логов по времени (каждый месяц)
    def create_file_handler(filename, level):
        log_file = os.path.join(log_dir, filename)
        handler = TimedRotatingFileHandler(
            log_file,
            when='midnight',
            interval=30,  # ротация каждые 30 дней
            backupCount=6,  # хранить 6 месяцев логов
            encoding='utf-8'
        )
        handler.setFormatter(log_format)
        handler.setLevel(level)
        return handler
    
    # Создаем обработчики для разных уровней логирования
    error_handler = create_file_handler('error.log', logging.ERROR)
    warning_handler = create_file_handler('warning.log', logging.WARNING)
    info_handler = create_file_handler('info.log', logging.INFO)
    debug_handler = create_file_handler('debug.log', logging.DEBUG)
    
    # Настраиваем вывод в консоль
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    console_handler.setLevel(logging.INFO)
    
    # Настраиваем корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Устанавливаем самый низкий уровень для корневого логгера
    
    # Добавляем обработчики
    root_logger.addHandler(error_handler)
    root_logger.addHandler(warning_handler)
    root_logger.addHandler(info_handler)
    root_logger.addHandler(debug_handler)
    root_logger.addHandler(console_handler)
    
    # Создаем логгер для бота
    logger = logging.getLogger(__name__)
    
    # Очищаем старые логи при запуске
    cleanup_old_logs(log_dir)
    
    return logger

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
logger = setup_logging()

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
    logger.info("[start] Вход в команду /start")
    try:
        if update.effective_chat.type != "private":
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только в личном чате с ботом.")
            logger.warning("[start] Попытка запуска не в личном чате")
            return
        user = update.effective_user
        db.add_active_user(user.id, user.username or user.first_name)
        logger.info(f"Пользователь {user.id} (@{user.username}) запустил бота")
        welcome_message = f"Привет, {user.first_name}! Я бот для управления подписками и записью в баню."
        if context.args:
            arg = context.args[0]
            logger.debug(f"Получены аргументы запуска: {arg}")
            if arg.startswith("bath_"):
                logger.info(f"Пользователь {user.id} пришел по ссылке записи в баню")
                await handle_deep_link(update, context)
                return
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text(welcome_message)
        logger.debug(f"Отправлено приветственное сообщение пользователю {user.id}")
    except Exception as e:
        logger.error(f"Ошибка в функции start: {e}")
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
        logger.info(f"[button_callback] CallbackQuery received: data={query.data}, chat_type={update.effective_chat.type}, user_id={user.id}")
        db.add_active_user(user.id, user.username or user.first_name)
        callback_data = query.data
        logger.debug(f"Получен callback от пользователя {user.id}: {callback_data}")

        if callback_data.startswith("join_bath_"):
            logger.info("[button_callback] Ветка join_bath_")
            date_str = callback_data.replace("join_bath_", "")
            logger.info(f"[button_callback] join_bath_ для даты {date_str}")
            logger.info(f"Пользователь {user.id} пытается записаться на баню {date_str}")

            # Атомарно пытаемся добавить приглашение (валидно 2 часа)
            if not db.try_add_bath_invite(user.id, date_str, hours=2):
                await query.answer("Вам уже отправлено приглашение на регистрацию. Проверьте личные сообщения.", show_alert=True)
                return

            # Проверка: уже ли пользователь начал регистрацию на эту дату (старый способ)
            if 'bath_registrations' in context.user_data and date_str in context.user_data['bath_registrations']:
                await query.answer("Вы уже начали процесс записи на эту дату.", show_alert=True)
                return

            # Проверка лимита участников
            participants = db.get_bath_participants(date_str)
            if len(participants) >= MAX_BATH_PARTICIPANTS:
                logger.warning(f"Пользователь {user.id} не смог записаться - достигнут лимит участников")
                await query.answer("К сожалению, баня уже занята. Вы можете записаться в следующий раз!", show_alert=True)
                return

            try:
                # Пробуем отправить сообщение в личный чат
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

                # Успешно отправили сообщение, информируем в группе
                await query.message.reply_text(
                    f"@{user.username or user.first_name}, проверьте личные сообщения от бота.",
                    reply_to_message_id=query.message.message_id
                )

            except Exception as e:
                logger.error(f"Ошибка при отправке сообщения пользователю {user.id}: {e}")

                # Создаем ссылку на бота
                bot_username = context.bot.username
                start_link = f"https://t.me/{bot_username}?start=bath_{date_str}"

                # Отправляем всплывающее уведомление пользователю
                await query.answer("Необходимо начать диалог с ботом", show_alert=True)

                # Отправляем информативное сообщение в группу
                username = user.username or user.first_name
                await query.message.reply_text(
                    f"@{username}, для записи на баню необходимо сначала начать диалог с ботом.\n\n"
                    f"1. [Нажмите здесь для перехода в чат с ботом]({start_link})\n"
                    f"2. Отправьте команду /start\n"
                    f"3. Затем используйте команду /register {date_str}\n\n"
                    f"После этого вы сможете продолжить процесс записи.",
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                    reply_to_message_id=query.message.message_id
                )
        elif callback_data.startswith("confirm_bath_"):
            logger.info("[button_callback] Ветка confirm_bath_")
            date_str = callback_data.replace("confirm_bath_", "")
            logger.info(f"[button_callback] confirm_bath_ для даты {date_str}")
            # Здесь можно вызвать confirm_bath_registration напрямую, если нужно
            await confirm_bath_registration(update, context)
        elif callback_data.startswith("paid_bath_"):
            logger.info("[button_callback] Ветка paid_bath_")
            date_str = callback_data.replace("paid_bath_", "")
            logger.info(f"[button_callback] paid_bath_ для даты {date_str}")
            await handle_payment_confirmation(update, context)
        elif callback_data.startswith("admin_confirm_"):
            logger.info("[button_callback] Ветка admin_confirm_")
            # Разбираем payment_type
            parts = callback_data.split("_")
            if len(parts) == 5:
                user_id = int(parts[2])
                date_str = parts[3]
                payment_type = parts[4]
            else:
                user_id = int(parts[2])
                date_str = parts[3]
                payment_type = None
            await admin_confirm_payment(update, context, user_id=user_id, date_str=date_str, payment_type=payment_type)
        elif callback_data.startswith("admin_decline_"):
            logger.info("[button_callback] Ветка admin_decline_")
            # Разбираем payment_type
            parts = callback_data.split("_")
            if len(parts) == 5:
                user_id = int(parts[2])
                date_str = parts[3]
                payment_type = parts[4]
            else:
                user_id = int(parts[2])
                date_str = parts[3]
                payment_type = None
            await admin_decline_payment(update, context, user_id=user_id, date_str=date_str, payment_type=payment_type)
        elif callback_data.startswith("message_user_"):
            logger.info("[button_callback] Ветка message_user_")
            await handle_message_to_user(update, context)
        elif callback_data.startswith("start_profile"):
            logger.info("[button_callback] Ветка start_profile")
            await start_profile_callback(update, context)
        elif callback_data.startswith("cash_bath_"):
            logger.info("[button_callback] Ветка cash_bath_")
            await handle_cash_payment(update, context)
        else:
            logger.info(f"[button_callback] Неизвестный callback_data: {callback_data}")
    except Exception as e:
        logger.error(f"Ошибка в функции button_callback: {e}")
        await query.answer("Произошла ошибка. Пожалуйста, попробуйте позже.", show_alert=True)

# Обработка кнопки "Подтвердить запись" в личном чате
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

            # Проверка лимита участников
            participants = db.get_bath_participants(date_str)
            if len(participants) >= MAX_BATH_PARTICIPANTS:
                logger.warning(f"Пользователь {user.id} не смог подтвердить запись - достигнут лимит участников")
                await query.edit_message_text(
                    text="К сожалению, баня уже занята. Вы можете записаться в следующий раз!"
                )
                return

            # Сохраняем информацию о намерении записаться в контексте пользователя
            if 'bath_registrations' not in context.user_data:
                context.user_data['bath_registrations'] = {}

            username = user.username or f"{user.first_name} {user.last_name or ''}"
            context.user_data['bath_registrations'][date_str] = {
                'user_id': user.id,
                'username': username,
                'status': 'pending_payment'
            }
            logger.info(f"Сохранена информация о регистрации пользователя {user.id} на {date_str}")

            # Отправляем инструкции по оплате с двумя кнопками
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

        user_data = db.get_pending_payment(user_id, date_str, payment_type)
        logger.info(f"[admin_decline_payment] Ищу заявку: user_id={user_id}, date_str={date_str}, payment_type={payment_type}")
        logger.info(f"[admin_decline_payment] Результат поиска: {user_data}")
        if user_data:
            username = user_data.get('username')
            db.delete_pending_payment(user_id, date_str)
            keyboard = [
                [InlineKeyboardButton("Отправить сообщение", callback_data=f"message_user_{user_id}_{date_str}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            try:
                await query.edit_message_text(
                    text=f"Вы отклонили оплату пользователя @{username} на {date_str}. Вы можете отправить пользователю сообщение с объяснением.",
                    reply_markup=reply_markup
                )
                logger.info(f"[admin_decline_payment] Сообщение для админа обновлено")
            except Exception as e:
                logger.error(f"[admin_decline_payment] Ошибка при обновлении сообщения для админа: {e}")
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"К сожалению, ваша оплата на баню {date_str} не подтверждена. Пожалуйста, свяжитесь с администратором для выяснения деталей."
                )
                logger.info(f"[admin_decline_payment] Уведомление отправлено пользователю {user_id}")
            except Exception as e:
                logger.error(f"[admin_decline_payment] Ошибка при отправке уведомления пользователю {user_id}: {e}")
        else:
            try:
                await query.edit_message_text(
                    text="Информация о пользователе не найдена. Возможно, запрос устарел."
                )
                logger.info(f"[admin_decline_payment] Заявка не найдена для user_id={user_id}, date_str={date_str}, payment_type={payment_type}")
            except Exception as e:
                logger.error(f"[admin_decline_payment] Ошибка при уведомлении админа об отсутствии заявки: {e}")

# Обработка "Отправить сообщение" после отклонения
async def handle_message_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Не реагировать на сообщения вне личного чата
    if update.effective_chat.type != "private":
        return
    # Проверяем, является ли это callback query
    if update.callback_query:
        query = update.callback_query
        await query.answer()
    else:
        query = None

    admin_id = update.effective_user.id

    # Если ожидается сообщение для пользователя (WAITING_ADMIN_MESSAGE), разрешаем
    if context.user_data.get('messaging_user_id'):
        pass  # обработка ниже
    # Если это callback query на отправку сообщения — разрешаем
    elif query and query.data.startswith("message_user_"):
        pass  # обработка ниже
    # В остальных случаях — не отвечаем (чтобы не мешать диалогам профиля и т.д.)
    else:
        return

    # Проверяем, является ли пользователь администратором
    if admin_id not in ADMIN_IDS:
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text("У вас нет прав для выполнения этой операции.")
        return ConversationHandler.END

    # Если это callback query, обрабатываем его
    if query:
        callback_data = query.data
        parts = callback_data.split("_")

        if len(parts) >= 3 and parts[0] == "message" and parts[1] == "user":
            user_id = int(parts[2])

            # Сохраняем информацию в контексте
            context.user_data['messaging_user_id'] = user_id

            # Запрашиваем у администратора сообщение
            await query.edit_message_text(
                text="Пожалуйста, отправьте сообщение, которое вы хотите передать пользователю."
            )

            # Устанавливаем состояние для ожидания сообщения от администратора
            return "WAITING_ADMIN_MESSAGE"

    return ConversationHandler.END


# Обработчик для получения сообщения от администратора
async def get_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_message = update.message.text
    user_id = context.user_data.get('messaging_user_id')

    if user_id:
        try:
            # Отправляем сообщение пользователю
            await context.bot.send_message(
                chat_id=user_id,
                text=f"Сообщение от администратора: {admin_message}"
            )

            # Подтверждаем отправку администратору
            await update.message.reply_text(
                text="Ваше сообщение отправлено пользователю."
            )
        except Exception as e:
            await update.message.reply_text(
                text=f"Ошибка при отправке сообщения: {e}"
            )

        # Очищаем данные
        if 'messaging_user_id' in context.user_data:
            del context.user_data['messaging_user_id']
    else:
        await update.message.reply_text(
            text="Ошибка: пользователь не найден. Пожалуйста, начните процесс заново."
        )

    return ConversationHandler.END

# Команда для администраторов - отметить оплату
async def mark_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("[mark_paid] Вход в команду /mark_paid")
    try:
        if update.effective_chat.type != "private":
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только в личном чате с ботом.")
            logger.warning("[mark_paid] Попытка запуска не в личном чате")
            return
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("У вас нет прав для выполнения этой команды.")
            logger.warning(f"[mark_paid] Пользователь {user_id} не админ")
            return
        if not context.args or len(context.args) < 2:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Использование: /mark_paid <username> <дата в формате DD.MM.YYYY>")
            logger.info("[mark_paid] Не переданы аргументы")
            return
        username = context.args[0].replace("@", "")
        date_str = context.args[1]
        participants = db.get_bath_participants(date_str)
        user_found = False
        for participant in participants:
            if participant["username"].lower() == username.lower():
                user_id_to_mark = participant["user_id"]
                if db.mark_participant_paid(date_str, user_id_to_mark):
                    message = update.message or (update.callback_query and update.callback_query.message)
                    if message:
                        await message.reply_text(f"Оплата для @{username} на {date_str} подтверждена.")
                    logger.info(f"[mark_paid] Оплата подтверждена для {username} на {date_str}")
                    # Обновление сообщения со списком и т.д. (оставить как есть)
                user_found = True
                break
        if not user_found:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text(f"Пользователь @{username} не найден в списке участников на {date_str}.")
            logger.warning(f"[mark_paid] Пользователь @{username} не найден на {date_str}")
    except Exception as e:
        logger.error(f"Ошибка в функции mark_paid: {e}")
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text("Произошла ошибка при подтверждении оплаты.")

# Функция, которая будет запускаться каждый понедельник
async def monday_notification(context: ContextTypes.DEFAULT_TYPE):
    next_sunday = get_next_sunday()
    cleared_events = db.clear_previous_bath_events(except_date_str=next_sunday)
    db.create_bath_event(next_sunday)
    message = format_bath_message(next_sunday)
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
        except Exception as e:
            logger.warning(f'Не удалось открепить старое закрепленное сообщение: {e}')
    sent_message = await context.bot.send_message(
        chat_id=BATH_CHAT_ID,
        text=message,
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
        if current_message != message or markup_changed:
            try:
                await context.bot.edit_message_text(
                    chat_id=BATH_CHAT_ID,
                    message_id=pinned_messages.pinned_message.message_id,
                    text=message,
                    reply_markup=reply_markup
                )
                logger.info(f"[monday_notification] Закрепленное сообщение обновлено")
            except Exception as e:
                logger.error(f"[monday_notification] Ошибка при обновлении закрепленного сообщения: {e}")
        else:
            logger.info(f"[monday_notification] Сообщение и кнопки не требуют обновления")
    else:
        await context.bot.pin_chat_message(
            chat_id=BATH_CHAT_ID,
            message_id=sent_message.message_id,
            disable_notification=False
        )
        db.set_pinned_message_id(next_sunday, sent_message.message_id, BATH_CHAT_ID)
        logger.info(f"[monday_notification] Сообщение закреплено: {sent_message.message_id}")
    if cleared_events > 0:
        await context.bot.send_message(
            chat_id=BATH_CHAT_ID,
            text=f"🔄 Создана новая запись на баню {next_sunday}. Список участников предыдущей бани очищен."
        )

# Команда для администраторов - управление подписками
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

# Команда для администраторов - удаление подписки
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

# Функция для проверки и удаления пользователей с истекшей подпиской
async def check_subscriptions(context: ContextTypes.DEFAULT_TYPE):
    expired_users = db.get_expired_subscribers()

    for user_id in expired_users:
        try:
            # Удаляем пользователя из чата
            await context.bot.ban_chat_member(
                chat_id=BATH_CHAT_ID,
                user_id=user_id
            )

            # И сразу разбаниваем, чтобы он мог вернуться, если продлит подписку
            await context.bot.unban_chat_member(
                chat_id=BATH_CHAT_ID,
                user_id=user_id,
                only_if_banned=True
            )

            logger.info(f"Пользователь {user_id} удален из-за истекшей подписки")

            # Удаляем из базы данных
            db.remove_subscriber(user_id)
        except Exception as e:
            logger.error(f"Ошибка при удалении пользователя {user_id}: {e}")


# Функция для настройки меню команд бота
async def post_init(application: Application) -> None:
    """Вызывается после инициализации приложения"""
    # Команды для обычных пользователей
    user_commands = [
        BotCommand("start", "Начать работу с ботом"),
        BotCommand("register", "Записаться на баню (например: /register 12.05.2025)"),
        BotCommand("history", "Ваша история посещений бани"),
        BotCommand("visits", "Количество посещений и даты"),
        BotCommand("profile", "Просмотр/обновление информации о себе")
    ]

    # Все команды для администраторов
    admin_commands = user_commands + [
        BotCommand("cash_list", "Список участников с оплатой наличными (только для админа)"),
        BotCommand("create_bath", "Создать новую запись на ближайшее воскресенье"),
        BotCommand("mark_paid", "Отметить оплату пользователя (/mark_paid username DD.MM.YYYY)"),
        BotCommand("add_subscriber", "Добавить подписчика (/add_subscriber user_id days)"),
        BotCommand("remove_subscriber", "Удалить подписчика (/remove_subscriber user_id)"),
        BotCommand("update_commands", "Обновить меню команд (только для админа)"),
        BotCommand("export_profiles", "Экспорт всех профилей пользователей"),
        BotCommand("mention_all", "Упомянуть всех активных пользователей"),
        BotCommand("stats", "Статистика посещений бани"),
        BotCommand("mark_visit", "Отметить посещение бани"),
        BotCommand("clear_db", "Полная очистка базы данных (только для админа)")
    ]

    # Установка меню для всех пользователей
    await application.bot.set_my_commands(user_commands)

    # Установка расширенного меню только для администраторов
    for admin_id in ADMIN_IDS:
        try:
            await application.bot.set_my_commands(
                admin_commands,
                scope=BotCommandScopeChat(chat_id=admin_id)
            )
        except Exception as e:
            logger.error(f"Ошибка при настройке меню команд для администратора {admin_id}: {e}")

def escape_markdown(text):
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join(['\\' + c if c in escape_chars else c for c in str(text)])

async def mention_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("[mention_all] Вход в команду /mention_all")
    try:
        user_id = update.effective_user.id
        if update.effective_chat.type != "private":
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эту команду можно использовать только в личном чате с ботом.")
            logger.warning("[mention_all] Попытка запуска не в личном чате")
            return
        if user_id not in ADMIN_IDS:
            logger.warning(f"[mention_all] Пользователь {user_id} не админ")
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только администраторам.")
            return
        conn = db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT user_id, username FROM active_users')
            all_users = cursor.fetchall()
        finally:
            conn.close()
        if not all_users:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Нет пользователей для упоминания.")
            logger.info("[mention_all] Нет пользователей для упоминания")
            return
        mentions = []
        for uid, username in all_users:
            if username:
                mentions.append(f"@{escape_markdown(username)}")
            else:
                mentions.append(f"[user](tg://user?id={uid})")
        mention_text = " ".join(mentions)
        if len(mention_text) > 4000:
            mention_text = mention_text[:4000] + " ..."
        custom_message = " ".join(context.args) if context.args else "Внимание всем активным участникам!"
        custom_message = escape_markdown(custom_message)
        await context.bot.send_message(
            chat_id=BATH_CHAT_ID,
            text=f"📢 {custom_message}\n\n{mention_text}",
            parse_mode="MarkdownV2"
        )
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text("Сообщение отправлено в группу.")
        logger.info(f"[mention_all] Сообщение отправлено для {len(all_users)} пользователей.")
    except Exception as e:
        logger.error(f"Ошибка в функции mention_all: {e}")
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text("Произошла ошибка при выполнении команды.")

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("[history] Вход в команду /history")
    try:
        if update.effective_chat.type != "private":
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только в личном чате с ботом.")
            logger.warning("[history] Попытка запуска не в личном чате")
            return
        user_id = update.effective_user.id
        db.add_active_user(user_id, update.effective_user.username or update.effective_user.first_name)
        history = db.get_user_bath_history(user_id)
        if not history:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("У вас пока нет истории посещений бани.")
            logger.info(f"[history] Нет истории для пользователя {user_id}")
            return
        message_text = "📅 Ваша история посещений бани:\n\n"
        for entry in history:
            status = "✅" if entry["visited"] else "❌"
            paid = "💰" if entry["paid"] else "💸"
            message_text += f"{entry['date']} {status} {paid}\n"
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text(message_text)
        logger.info(f"[history] История отправлена пользователю {user_id}")
    except Exception as e:
        logger.error(f"Ошибка в функции history: {e}")
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text("Произошла ошибка при получении истории.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("[stats] Вход в команду /stats")
    try:
        if update.effective_chat.type != "private":
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только в личном чате с ботом.")
            logger.warning("[stats] Попытка запуска не в личном чате")
            return
        if update.effective_user.id not in ADMIN_IDS:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только администраторам.")
            logger.warning(f"[stats] Пользователь {update.effective_user.id} не админ")
            return
        end_date = datetime.now().strftime("%d.%m.%Y")
        start_date = (datetime.now() - timedelta(days=90)).strftime("%d.%m.%Y")
        stats = db.get_bath_statistics(start_date, end_date)
        if not stats:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("За последние 3 месяца нет данных о посещениях.")
            logger.info("[stats] Нет данных о посещениях за период")
            return
        message_text = "📊 Статистика посещений бани за последние 3 месяца:\n\n"
        for entry in stats:
            message_text += f"Дата: {entry['date']}\n"
            message_text += f"Всего участников: {entry['total']}\n"
            message_text += f"Оплатили: {entry['paid']}\n"
            message_text += f"Посетили: {entry['visited']}\n\n"
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text(message_text)
        logger.info("[stats] Статистика отправлена")
    except Exception as e:
        logger.error(f"Ошибка в функции stats: {e}")
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text("Произошла ошибка при получении статистики.")

async def mark_visit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("[mark_visit] Вход в команду /mark_visit")
    try:
        if update.effective_chat.type != "private":
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только в личном чате с ботом.")
            logger.warning("[mark_visit] Попытка запуска не в личном чате")
            return
        if not context.args:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Пожалуйста, укажите дату в формате ДД.ММ.ГГГГ")
            logger.info("[mark_visit] Не передана дата")
            return
        date_str = context.args[0]
        user_id = update.effective_user.id
        if db.mark_visit(date_str, user_id):
            db.update_visit_statistics(user_id, date_str)
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text(f"✅ Посещение бани {date_str} отмечено!")
            logger.info(f"[mark_visit] Посещение отмечено для пользователя {user_id} на {date_str}")
        else:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("❌ Не удалось отметить посещение. Проверьте дату и попробуйте снова.")
            logger.warning(f"[mark_visit] Не удалось отметить посещение для пользователя {user_id} на {date_str}")
    except Exception as e:
        logger.error(f"Ошибка в функции mark_visit: {e}")
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text("Произошла ошибка при отметке посещения.")

async def visits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("[visits] Вход в команду /visits")
    try:
        if update.effective_chat.type != "private":
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только в личном чате с ботом.")
            logger.warning("[visits] Попытка запуска не в личном чате")
            return
        user_id = update.effective_user.id
        db.add_active_user(user_id, update.effective_user.username or update.effective_user.first_name)
        visits_count = db.get_user_visits_count(user_id)
        history = db.get_user_bath_history(user_id)
        if visits_count == 0:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Вы еще не посещали баню.")
            logger.info(f"[visits] Нет посещений для пользователя {user_id}")
            return
        message_text = f"Вы посетили баню {visits_count} раз(а):\n\n"
        visited_dates = [entry for entry in history if entry["visited"]]
        visited_dates.sort(key=lambda x: datetime.strptime(x["date"], "%d.%m.%Y"), reverse=True)
        for entry in visited_dates:
            message_text += f"📅 {entry['date']}\n"
        logger.info(f"[visits] Пользователь {user_id} checked their visits count: {visits_count}")
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text(message_text)
    except Exception as e:
        logger.error(f"Ошибка в функции visits: {e}")
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text("Произошла ошибка при получении информации о посещениях.")

# ВРЕМЕННО: команда для полной очистки базы данных (только для администратора)
async def clear_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("[clear_db] Вход в команду /clear_db")
    try:
        user_id = update.effective_user.id
        if update.effective_chat.type != "private":
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только в личном чате с ботом.")
            logger.warning("[clear_db] Попытка запуска не в личном чате")
            return
        if user_id not in ADMIN_IDS:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда только для администраторов.")
            logger.warning(f"[clear_db] Пользователь {user_id} не админ")
            return
        db.clear_all_data()
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text("База данных полностью очищена.")
        logger.info("[clear_db] База данных очищена")
    except Exception as e:
        logger.error(f"Ошибка в функции clear_db: {e}")
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text("Произошла ошибка при очистке базы данных.")

async def update_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("[update_commands] Вход в команду /update_commands")
    try:
        user_id = update.effective_user.id
        if update.effective_chat.type != "private":
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только в личном чате с ботом.")
            logger.warning("[update_commands] Попытка запуска не в личном чате")
            return
        if user_id not in ADMIN_IDS:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда только для администраторов.")
            logger.warning(f"[update_commands] Пользователь {user_id} не админ")
            return
        await post_init(context.application)
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text("Меню команд обновлено!")
        logger.info("[update_commands] Меню команд обновлено")
    except Exception as e:
        logger.error(f"Ошибка в функции update_commands: {e}")
        message = update.message or (update.callback_query and update.callback_query.message)
        if message:
            await message.reply_text("Произошла ошибка при обновлении меню команд.")

# Добавляем в список состояний для ConversationHandler
PROFILE = 0
FULL_NAME = 1
BIRTH_DATE = 2
OCCUPATION = 3
INSTAGRAM = 4
SKILLS = 5

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
        # Показываем текущую информацию
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
        # Проверяем формат ДД.ММ
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
        user_pending = None
        for date_str in [p['date_str'] for p in db.get_all_user_profiles() if p['user_id'] == user.id]:
            pending = db.get_pending_payment(user.id, date_str)
            if pending:
                user_pending = pending
                break
        if user_pending:
            # Отправляем уведомление всем администраторам
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

async def send_bath_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет сводку участников бани всем участникам."""
    today = datetime.now().strftime("%d.%m.%Y")
    
    # Получаем список участников текущей бани
    participants = db.get_bath_participants(today)
    if not participants:
        return

    # Формируем сообщение
    message = f"📊 Сводка участников бани {today}:\n\n"
    
    for participant in participants:
        profile = db.get_user_profile(participant['user_id'])
        if profile:
            message += f"👤 {profile['full_name']}\n"
            if profile['birth_date']:
                message += f"🎂 {profile['birth_date']}\n"
            if profile['occupation']:
                message += f"💼 {profile['occupation']}\n"
            if profile['instagram']:
                message += f"📸 {profile['instagram']}\n"
            if profile['skills']:
                message += f"🎯 Чем может быть полезен: {profile['skills']}\n"
            # Не добавляем строку с количеством посещений
            message += "\n"
    
    # Отправляем сообщение всем участникам
    for participant in participants:
        try:
            await context.bot.send_message(
                chat_id=participant['user_id'],
                text=message,
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке сводки пользователю {participant['user_id']}: {e}")

# Handler for the 'Заполнить профиль' button
async def start_profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    logger.info(f"[start_profile_callback] CallbackQuery received: data={query.data}, chat_type={update.effective_chat.type}, user_id={user.id}")
    
    try:
        await query.answer()
        
        # Запускаем диалог профиля только если в личном чате
        if update.effective_chat.type != "private":
            await query.edit_message_text("Профиль можно заполнять только в личном чате с ботом.")
            return
        
        # Запускаем диалог профиля
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
        # Получаем все профили
        profiles = db.get_all_user_profiles()  # Предполагается, что функция возвращает список словарей
        if not profiles:
            await update.message.reply_text("Нет данных о пользователях.")
            return
        # Создаем временный CSV-файл
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
        # Отправляем файл администратору
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

# Обработка кнопки "Буду платить наличными"
async def handle_cash_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        user = query.from_user
        logger.info(f"[handle_cash_payment] CallbackQuery received: data={query.data}, chat_type={update.effective_chat.type}, user_id={user.id}")
        db.add_active_user(user.id, user.username or user.first_name)
        callback_data = query.data
        if callback_data.startswith("cash_bath_"):
            date_str = callback_data.replace("cash_bath_", "")

            # Сохраняем в контексте, что пользователь выбрал наличные
            if 'bath_registrations' not in context.user_data:
                context.user_data['bath_registrations'] = {}
            username = user.username or f"{user.first_name} {user.last_name or ''}"
            context.user_data['bath_registrations'][date_str] = {
                'user_id': user.id,
                'username': username,
                'status': 'pending_cash'
            }
            logger.info(f"Пользователь {user.id} выбрал оплату наличными на {date_str}")

            # Добавляем в базу bath_participants с cash=True (или аналогично)
            # Для этого нужно добавить поле cash в таблицу bath_participants, если его нет
            try:
                conn = db.get_connection()
                cursor = conn.cursor()
                cursor.execute('ALTER TABLE bath_participants ADD COLUMN cash BOOLEAN DEFAULT 0')
                conn.commit()
            except Exception as e:
                pass  # поле уже есть
            finally:
                conn.close()
            # Добавляем запись с cash=True
            db.add_bath_participant(date_str, user.id, username, paid=False)  # paid=False, cash=True
            # Обновляем поле cash вручную
            try:
                conn = db.get_connection()
                cursor = conn.cursor()
                cursor.execute('UPDATE bath_participants SET cash = 1 WHERE date_str = ? AND user_id = ?', (date_str, user.id))
                conn.commit()
            finally:
                conn.close()

            # Удаляем старую заявку, если была
            db.delete_pending_payment(user.id, date_str)
            # Добавляем заявку на подтверждение оплаты наличными в pending_payments
            db.add_pending_payment(user.id, username, date_str, payment_type='cash')
            logger.info(f"[handle_cash_payment] Добавлена заявка на подтверждение оплаты наличными: user_id={user.id}, username={username}, date_str={date_str}, payment_type=cash")

            # Отправляем пользователю подтверждение
            await query.edit_message_text(
                text=f"Спасибо! Ваша заявка на оплату наличными отправлена администратору. Ожидайте подтверждения."
            )

            # Отправляем уведомление администраторам
            for admin_id in ADMIN_IDS:
                try:
                    callback_data_confirm = f"admin_confirm_{user.id}_{date_str}_cash"
                    callback_data_decline = f"admin_decline_{user.id}_{date_str}_cash"
                    logger.info(f"Формирую callback_data: confirm={callback_data_confirm}, decline={callback_data_decline}")
                    keyboard = [
                        [
                            InlineKeyboardButton("да, наличные", callback_data=callback_data_confirm),
                            InlineKeyboardButton("Отклонить", callback_data=callback_data_decline)
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=(
                            f"Пользователь @{username} (ID: {user.id}) выбрал оплату наличными на {date_str}. "
                            f"Согласны ли вы, что пользователь заплатит наличкой?\n"
                            f"В воскресенье я отправлю вам список всех участников с наличной оплатой."
                        ),
                        reply_markup=reply_markup
                    )
                    logger.info(f"[handle_cash_payment] Уведомление отправлено админу {admin_id} (cash)")
                except Exception as e:
                    logger.error(f"[handle_cash_payment] Ошибка при отправке админу {admin_id}: {e}")
    except Exception as e:
        logger.error(f"Ошибка в функции handle_cash_payment: {e}")
        await update.callback_query.edit_message_text("Произошла ошибка. Пожалуйста, попробуйте позже.")

# Добавить задачу для рассылки списка наличных в 10:00 по воскресеньям
async def send_cash_payments_list(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет список пользователей, выбравших оплату наличными, всем администраторам."""
    today = datetime.now().strftime("%d.%m.%Y")
    conn = db.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT bp.user_id, bp.username, up.full_name FROM bath_participants bp
            LEFT JOIN user_profiles up ON bp.user_id = up.user_id
            WHERE bp.date_str = ? AND bp.cash = 1
        ''', (today,))
        rows = cursor.fetchall()
        if not rows:
            return
        message = f"Список участников, выбравших оплату наличными на {today}:\n\n"
        for row in rows:
            message += f"@{row[1]} | {row[2] or ''}\n"
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=message
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке списка наличных админу {admin_id}: {e}")
    finally:
        conn.close()

async def cash_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("[cash_list] Вход в команду /cash_list")
    try:
        if update.effective_chat.type != "private":
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("Эта команда доступна только в личном чате с ботом.")
            logger.warning("[cash_list] Попытка запуска не в личном чате")
            return
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            message = update.message or (update.callback_query and update.callback_query.message)
            if message:
                await message.reply_text("У вас нет прав для выполнения этой команды.")
            logger.warning(f"[cash_list] Пользователь {user_id} не админ")
            return
        conn = db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT username, date_str FROM bath_participants WHERE cash = 1
            ''')
            rows = cursor.fetchall()
        finally:
            conn.close()
        if not rows:
            await update.message.reply_text("Нет участников с оплатой наличными.")
            return
        message = "Список участников с оплатой наличными:\n\n"
        for row in rows:
            message += f"@{row[0]} — {row[1]}\n"
        await update.message.reply_text(message)
    except Exception as e:
        logger.error(f"Ошибка в функции cash_list: {e}")
        await update.message.reply_text("Произошла ошибка при получении списка.")

async def notify_pending_payments(context: ContextTypes.DEFAULT_TYPE):
    """Уведомляет администраторов о всех висящих заявках в pending_payments."""
    conn = db.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT username, date_str FROM pending_payments')
        rows = cursor.fetchall()
    finally:
        conn.close()
    if not rows:
        return
    message = "Висят неподтверждённые заявки:\n\n"
    for row in rows:
        message += f"@{row[0]} — {row[1]}\n"
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=message)
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления о pending_payments админу {admin_id}: {e}")

async def remind_pending_payments(context: ContextTypes.DEFAULT_TYPE):
    """Раз в час напоминает администраторам о неподтверждённых заявках, если с последнего уведомления прошло 4 часа."""
    reminders = db.get_pending_payments_for_reminder(hours=4)
    if not reminders:
        return
    for user_id, username, date_str, payment_type in reminders:
        if payment_type == 'cash':
            confirm_text = "да, наличные"
        else:
            confirm_text = "Оплатил онлайн"
        message = (
            f"Висят неподтверждённые заявки:\n\n"
            f"@{username} — {date_str}\n\n"
            f"Пожалуйста, подтвердите или отклоните заявку."
        )
        for admin_id in ADMIN_IDS:
            try:
                keyboard = [
                    [
                        InlineKeyboardButton(confirm_text, callback_data=f"admin_confirm_{user_id}_{date_str}_{payment_type}"),
                        InlineKeyboardButton("Отклонить", callback_data=f"admin_decline_{user_id}_{date_str}_{payment_type}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await context.bot.send_message(chat_id=admin_id, text=message, reply_markup=reply_markup)
            except Exception as e:
                logger.error(f"Ошибка при отправке напоминания админу {admin_id}: {e}")
        db.update_last_notified(user_id, date_str)

# Универсальная функция для обновления закреплённого сообщения о бане
async def update_pinned_bath_message(context, date_str, participants, message, reply_markup):
    pinned_messages = await context.bot.get_chat(BATH_CHAT_ID)
    logger.info(f"[update_pinned_bath_message] Закреплённый message_id в чате: {pinned_messages.pinned_message.message_id if pinned_messages.pinned_message else 'None'}")
    current_message = pinned_messages.pinned_message.text if pinned_messages.pinned_message else None
    current_markup = pinned_messages.pinned_message.reply_markup if pinned_messages.pinned_message else None
    logger.info(f"[update_pinned_bath_message] Пытаюсь обновить закреплённое сообщение: message_id={pinned_messages.pinned_message.message_id if pinned_messages.pinned_message else 'None'}")
    logger.info(f"[update_pinned_bath_message] Текущий текст: {current_message}")
    logger.info(f"[update_pinned_bath_message] Новый текст: {message}")
    logger.info(f"[update_pinned_bath_message] Текущие кнопки: {current_markup}")
    logger.info(f"[update_pinned_bath_message] Новые кнопки: {reply_markup}")
    def markup_to_str(markup):
        if not markup:
            return ''
        return str([[btn.text for btn in row] for row in markup.inline_keyboard])
    markup_changed = markup_to_str(current_markup) != markup_to_str(reply_markup)
    # Если message_id не совпадает с ожидаемым или текст отличается, открепляем все и закрепляем новое сообщение
    expected_message = message
    if not pinned_messages.pinned_message or current_message != expected_message:
        logger.info(f"[update_pinned_bath_message] Открепляю старое и закрепляю новое сообщение!")
        try:
            await context.bot.unpin_all_chat_messages(BATH_CHAT_ID)
        except Exception as e:
            logger.warning(f"[update_pinned_bath_message] Не удалось открепить все сообщения: {e}")
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
        logger.info(f"[update_pinned_bath_message] Новое сообщение закреплено: {sent_message.message_id}")
    elif current_message != message or markup_changed:
        try:
            await context.bot.edit_message_text(
                chat_id=BATH_CHAT_ID,
                message_id=pinned_messages.pinned_message.message_id,
                text=message,
                reply_markup=reply_markup
            )
            logger.info(f"[update_pinned_bath_message] Закрепленное сообщение обновлено")
        except Exception as e:
            logger.error(f"[update_pinned_bath_message] Ошибка при обновлении закрепленного сообщения: {e}")
    else:
        logger.info(f"[update_pinned_bath_message] Закрепленное сообщение не требует обновления")

def main():
    """Запускает бота."""
    try:
        # Создаем приложение
        application = Application.builder().token(BOT_TOKEN).build()

        # Добавляем обработчик для профиля (должен быть первым!)
        profile_handler = ConversationHandler(
            entry_points=[
                CommandHandler("profile", profile),
                CallbackQueryHandler(start_profile_callback, pattern="^start_profile$"),
            ],
            states={
                PROFILE: [
                    CallbackQueryHandler(handle_profile_update, pattern="^update_profile_"),
                ],
                FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_full_name)],
                BIRTH_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_birth_date)],
                OCCUPATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_occupation)],
                INSTAGRAM: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_instagram)],
                SKILLS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_skills)]
            },
            fallbacks=[CommandHandler("cancel", cancel)]
        )
        application.add_handler(profile_handler)

        # Регистрируем обработчики команд
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("register", register_bath))
        application.add_handler(CommandHandler("create_bath", create_bath_event))
        application.add_handler(CommandHandler("mark_paid", mark_paid))
        application.add_handler(CommandHandler("add_subscriber", add_subscriber))
        application.add_handler(CommandHandler("remove_subscriber", remove_subscriber))
        application.add_handler(CommandHandler("mention_all", mention_all))
        application.add_handler(CommandHandler("history", history))
        application.add_handler(CommandHandler("stats", stats))
        application.add_handler(CommandHandler("mark_visit", mark_visit))
        application.add_handler(CommandHandler("visits", visits))
        application.add_handler(CommandHandler("clear_db", clear_db))
        application.add_handler(CommandHandler("update_commands", update_commands))
        application.add_handler(CommandHandler("export_profiles", export_profiles))
        application.add_handler(CommandHandler("cash_list", cash_list))

        # Регистрируем обработчики callback-запросов
        application.add_handler(CallbackQueryHandler(button_callback))

        # Регистрируем обработчики сообщений (должен быть последним!)
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message_to_user))

        # Настраиваем команды бота
        application.post_init = post_init
        
        # Добавляем задачу для отправки сводки после бани
        job_queue = application.job_queue
        if job_queue:
            # Автоматически создаём новую баню по понедельникам утром в 8:00
            job_queue.run_daily(
                 monday_notification,
                 time=time(hour=8, minute=0),
                 days=(0,)  # 0 = Monday
            )
            # Отправляем сводку каждый воскресный вечер в 20:00
            job_queue.run_daily(
                send_bath_summary,
                time=time(hour=20, minute=0),
                days=(6,)  # 6 = Sunday
            )
        
        # Добавить задачу для рассылки списка наличных в 10:00 по воскресеньям
        job_queue.run_daily(
            send_cash_payments_list,
            time=time(hour=10, minute=0),
            days=(6,)  # 6 = Sunday
        )
        
        # Добавить задачу для очистки старых заявок каждое воскресенье утром
        job_queue.run_daily(
            lambda context: db.cleanup_old_pending_payments(days=7),
            time=time(hour=10, minute=0),
            days=(6,)
        )
        
        # Добавить задачу для уведомления администраторов о pending_payments каждое воскресенье утром
        job_queue.run_daily(
            notify_pending_payments,
            time=time(hour=10, minute=0),
            days=(6,)
        )
        
        # Добавить задачу для напоминания администраторам о неподтверждённых заявках каждый час
        job_queue.run_repeating(remind_pending_payments, interval=3600, first=0)
        
        # Запуск через polling
        application.run_polling()

    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
        raise

if __name__ == '__main__':
    main()

from config import BATH_TIME, BATH_COST, MAX_BATH_PARTICIPANTS, CARD_PAYMENT_LINK, REVOLUT_PAYMENT_LINK, BATH_LOCATION
import logging

logger = logging.getLogger(__name__)


def format_bath_message(date_str, db):
    try:
        participants = db.get_bath_participants(date_str)

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

        if len(participants) < MAX_BATH_PARTICIPANTS:
            message += f"Для записи:\n"
            message += f"1. Нажмите кнопку 'Записаться' ниже\n"
            message += f"2. Следуйте инструкциям бота в личном чате\n"
            message += f"3. Оплатите участие и подтвердите оплату через бота\n"
            message += f"4. Ожидайте подтверждения от администратора"
        else:
            message += f"\n❗️Лимит участников достигнут. Запись закрыта.\n"

        return message
    except Exception as e:
        logger.error(f"Ошибка при форматировании сообщения о бане: {e}", exc_info=True)
        raise 
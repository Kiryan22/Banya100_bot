import pytest
from datetime import datetime, timedelta
import pytz
from unittest.mock import Mock, patch, AsyncMock
from telegram import Update, User, Chat, Message, CallbackQuery
from telegram.ext import ContextTypes

from bot import (
    get_next_sunday,
    format_bath_message,
    button_callback,
    confirm_bath_registration,
    handle_payment_confirmation,
    admin_confirm_payment,
    admin_decline_payment,
    mark_paid
)
from config import MAX_BATH_PARTICIPANTS, BATH_TIME, BATH_COST, CARD_PAYMENT_LINK, REVOLUT_PAYMENT_LINK, BATH_LOCATION
from database import Database

# Мок для базы данных
@pytest.fixture
def mock_db():
    with patch('bot.db') as mock:
        yield mock

# Фикстура для создания тестового пользователя
@pytest.fixture
def test_user():
    return User(
        id=123456789,
        is_bot=False,
        first_name="Test",
        last_name="User",
        username="testuser"
    )

# Фикстура для создания тестового чата
@pytest.fixture
def test_chat():
    return Chat(
        id=123456789,
        type="private"
    )

# Фикстура для создания тестового сообщения
@pytest.fixture
def test_message(test_user, test_chat):
    return Message(
        message_id=1,
        date=datetime.now(),
        chat=test_chat,
        from_user=test_user
    )

# Фикстура для создания тестового callback query
@pytest.fixture
def test_callback_query(test_user, test_chat):
    return CallbackQuery(
        id="test_callback_id",
        from_user=test_user,
        chat_instance="test_chat_instance",
        message=Message(
            message_id=1,
            date=datetime.now(),
            chat=test_chat,
            from_user=test_user
        )
    )

# Фикстура для создания тестового update
@pytest.fixture
def test_update(test_message, test_callback_query):
    update = Update(
        update_id=1,
        message=test_message,
        callback_query=test_callback_query
    )
    return update

# Фикстура для создания тестового context
@pytest.fixture
def test_context():
    context = Mock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot = AsyncMock()
    context.user_data = {}
    context.bot_data = {}
    return context

def test_get_next_sunday():
    """Тест функции получения даты следующего воскресенья"""
    next_sunday = get_next_sunday()
    assert isinstance(next_sunday, str)
    assert len(next_sunday.split('.')) == 3  # Проверяем формат DD.MM.YYYY

def test_format_bath_message(mock_db):
    """Тест форматирования сообщения о бане"""
    date_str = "01.01.2024"
    mock_participants = [
        {"username": "user1", "paid": True},
        {"username": "user2", "paid": False}
    ]
    mock_db.get_bath_participants.return_value = mock_participants

    message = format_bath_message(date_str)

    assert "НОВАЯ ЗАПИСЬ В БАНЮ" in message
    assert BATH_TIME in message
    assert BATH_COST in message
    assert "user1 ✅" in message
    assert "user2 ❌" in message
    assert CARD_PAYMENT_LINK in message
    assert REVOLUT_PAYMENT_LINK in message
    assert BATH_LOCATION in message

@pytest.mark.asyncio
async def test_button_callback_max_participants(mock_db, test_update, test_context):
    """Тест обработки кнопки 'Записаться' при достижении лимита участников"""
    date_str = "01.01.2024"
    test_update.callback_query.data = f"join_bath_{date_str}"
    
    # Мокаем максимальное количество участников
    mock_participants = [{"username": f"user{i}", "paid": True} for i in range(MAX_BATH_PARTICIPANTS)]
    mock_db.get_bath_participants.return_value = mock_participants

    await button_callback(test_update, test_context)

    # Проверяем, что было отправлено сообщение о достижении лимита
    test_update.callback_query.answer.assert_called_with(
        "К сожалению, баня уже занята. Вы можете записаться в следующий раз!",
        show_alert=True
    )

@pytest.mark.asyncio
async def test_confirm_bath_registration(mock_db, test_update, test_context):
    """Тест подтверждения регистрации на баню"""
    date_str = "01.01.2024"
    test_update.callback_query.data = f"confirm_bath_{date_str}"
    
    # Мокаем пустой список участников
    mock_db.get_bath_participants.return_value = []

    await confirm_bath_registration(test_update, test_context)

    # Проверяем, что информация о регистрации сохранена
    assert 'bath_registrations' in test_context.user_data
    assert date_str in test_context.user_data['bath_registrations']
    assert test_context.user_data['bath_registrations'][date_str]['status'] == 'pending_payment'

@pytest.mark.asyncio
async def test_handle_payment_confirmation(mock_db, test_update, test_context):
    """Тест обработки подтверждения оплаты"""
    date_str = "01.01.2024"
    test_update.callback_query.data = f"paid_bath_{date_str}"
    
    # Устанавливаем начальное состояние
    test_context.user_data['bath_registrations'] = {
        date_str: {
            'user_id': test_update.effective_user.id,
            'username': test_update.effective_user.username,
            'status': 'pending_payment'
        }
    }

    await handle_payment_confirmation(test_update, test_context)

    # Проверяем, что статус обновлен
    assert test_context.user_data['bath_registrations'][date_str]['status'] == 'payment_claimed'
    # Проверяем, что заявка добавлена в список ожидающих подтверждения
    assert 'pending_payments' in test_context.bot_data
    assert len(test_context.bot_data['pending_payments']) == 1

@pytest.mark.asyncio
async def test_admin_confirm_payment(mock_db, test_update, test_context):
    """Тест подтверждения оплаты администратором"""
    date_str = "01.01.2024"
    user_id = 123456789
    test_update.callback_query.data = f"admin_confirm_{user_id}_{date_str}"
    
    # Устанавливаем начальное состояние
    test_context.bot_data['pending_payments'] = [{
        'user_id': user_id,
        'username': 'testuser',
        'date_str': date_str
    }]

    await admin_confirm_payment(test_update, test_context)

    # Проверяем, что участник добавлен в базу данных
    mock_db.add_bath_participant.assert_called_once()
    # Проверяем, что заявка удалена из списка ожидающих
    assert len(test_context.bot_data['pending_payments']) == 0

@pytest.mark.asyncio
async def test_mark_paid(mock_db, test_update, test_context):
    """Тест отметки оплаты администратором"""
    date_str = "01.01.2024"
    username = "testuser"
    test_context.args = [username, date_str]
    
    # Мокаем существующего участника
    mock_db.get_bath_participants.return_value = [{
        "username": username,
        "user_id": 123456789,
        "paid": False
    }]
    mock_db.mark_participant_paid.return_value = True

    await mark_paid(test_update, test_context)

    # Проверяем, что статус оплаты обновлен
    mock_db.mark_participant_paid.assert_called_once() 
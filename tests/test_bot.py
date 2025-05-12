import unittest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from datetime import datetime, timedelta
import pytz
from telegram import Update, User, Chat, Message, CallbackQuery, Bot
from telegram.ext import ContextTypes
from bot import (
    start,
    register_bath,
    create_bath_event,
    button_callback,
    confirm_bath_registration,
    handle_payment_confirmation,
    handle_cash_payment,
    admin_confirm_payment,
    admin_decline_payment,
    handle_deep_link,
    format_bath_message
)
from config import ADMIN_IDS, BATH_COST, BATH_TIME, MAX_BATH_PARTICIPANTS, BATH_CHAT_ID

class TestBot(unittest.TestCase):
    def setUp(self):
        """Подготовка тестового окружения"""
        self.user = User(
            id=123456789,
            is_bot=False,
            first_name="Test",
            last_name="User",
            username="testuser"
        )
        self.chat = Chat(
            id=123456789,
            type="private"
        )
        self.message = Message(
            message_id=1,
            date=datetime.now(),
            chat=self.chat,
            from_user=self.user
        )
        self.update = Update(
            update_id=1,
            message=self.message
        )
        self.context = ContextTypes.DEFAULT_TYPE()
        self.context.user_data = {}
        self.context.bot = AsyncMock(spec=Bot)

    @patch('bot.db')
    async def test_start_command(self, mock_db):
        """Тест команды /start"""
        # Настраиваем мок
        mock_db.add_active_user = AsyncMock()
        
        # Вызываем функцию
        await start(self.update, self.context)
        
        # Проверяем, что пользователь добавлен в активные
        mock_db.add_active_user.assert_called_once_with(
            self.user.id,
            self.user.username
        )

    @patch('bot.db')
    async def test_start_command_with_deep_link(self, mock_db):
        """Тест команды /start с глубокой ссылкой"""
        # Настраиваем мок
        mock_db.add_active_user = AsyncMock()
        
        # Добавляем аргументы команды
        self.context.args = ["bath_12.05.2024"]
        
        # Вызываем функцию
        await start(self.update, self.context)
        
        # Проверяем, что пользователь добавлен в активные
        mock_db.add_active_user.assert_called_once()

    @patch('bot.db')
    async def test_start_command_in_group(self, mock_db):
        """Тест команды /start в групповом чате"""
        # Меняем тип чата на групповой
        self.chat.type = "group"
        
        # Вызываем функцию
        await start(self.update, self.context)
        
        # Проверяем, что сообщение отправлено
        self.context.bot.send_message.assert_called_once()

    @patch('bot.db')
    async def test_register_bath(self, mock_db):
        """Тест команды /register"""
        # Настраиваем мок
        mock_db.get_bath_participants = AsyncMock(return_value=[])
        
        # Добавляем аргументы команды
        self.context.args = ["12.05.2024"]
        
        # Вызываем функцию
        await register_bath(self.update, self.context)
        
        # Проверяем, что функция вызвала правильные методы
        mock_db.get_bath_participants.assert_called_once()

    @patch('bot.db')
    async def test_register_bath_without_date(self, mock_db):
        """Тест команды /register без даты"""
        # Вызываем функцию без аргументов
        await register_bath(self.update, self.context)
        
        # Проверяем, что отправлено сообщение с инструкцией
        self.context.bot.send_message.assert_called_once()

    @patch('bot.db')
    async def test_create_bath_event(self, mock_db):
        """Тест команды /create_bath"""
        # Настраиваем мок
        mock_db.clear_previous_bath_events = AsyncMock(return_value=0)
        mock_db.create_bath_event = AsyncMock()
        mock_db.get_bath_participants = AsyncMock(return_value=[])
        mock_db.get_last_pinned_message_id = AsyncMock(return_value=None)
        mock_db.set_pinned_message_id = AsyncMock()
        
        # Устанавливаем пользователя как админа
        self.user.id = ADMIN_IDS[0]
        
        # Вызываем функцию
        await create_bath_event(self.update, self.context)
        
        # Проверяем, что функция вызвала правильные методы
        mock_db.create_bath_event.assert_called_once()
        mock_db.set_pinned_message_id.assert_called_once()

    @patch('bot.db')
    async def test_create_bath_event_non_admin(self, mock_db):
        """Тест команды /create_bath от не-админа"""
        # Вызываем функцию
        await create_bath_event(self.update, self.context)
        
        # Проверяем, что отправлено сообщение об отказе
        self.context.bot.send_message.assert_called_once()

    @patch('bot.db')
    async def test_button_callback_join_bath(self, mock_db):
        """Тест обработки кнопки 'Записаться'"""
        # Настраиваем мок
        mock_db.get_bath_participants = AsyncMock(return_value=[])
        mock_db.add_active_user = AsyncMock()
        
        # Создаем callback query
        callback_query = CallbackQuery(
            id="test_callback",
            from_user=self.user,
            chat_instance="test_chat",
            data="join_bath_12.05.2024"
        )
        self.update.callback_query = callback_query
        
        # Вызываем функцию
        await button_callback(self.update, self.context)
        
        # Проверяем, что функция вызвала правильные методы
        mock_db.get_bath_participants.assert_called_once()
        mock_db.add_active_user.assert_called_once()

    @patch('bot.db')
    async def test_button_callback_full_bath(self, mock_db):
        """Тест обработки кнопки 'Записаться' когда баня заполнена"""
        # Настраиваем мок с полным списком участников
        mock_db.get_bath_participants = AsyncMock(return_value=[
            {'user_id': i, 'username': f'user{i}', 'paid': True} 
            for i in range(MAX_BATH_PARTICIPANTS)
        ])
        
        # Создаем callback query
        callback_query = CallbackQuery(
            id="test_callback",
            from_user=self.user,
            chat_instance="test_chat",
            data="join_bath_12.05.2024"
        )
        self.update.callback_query = callback_query
        
        # Вызываем функцию
        await button_callback(self.update, self.context)
        
        # Проверяем, что отправлено сообщение о заполненной бане
        callback_query.edit_message_text.assert_called_once()

    @patch('bot.db')
    async def test_handle_payment_confirmation(self, mock_db):
        """Тест обработки подтверждения оплаты"""
        # Настраиваем мок
        mock_db.add_pending_payment = AsyncMock()
        mock_db.add_active_user = AsyncMock()
        
        # Создаем callback query
        callback_query = CallbackQuery(
            id="test_callback",
            from_user=self.user,
            chat_instance="test_chat",
            data="paid_bath_12.05.2024"
        )
        self.update.callback_query = callback_query
        
        # Добавляем данные о регистрации
        self.context.user_data['bath_registrations'] = {
            '12.05.2024': {
                'user_id': self.user.id,
                'username': self.user.username,
                'status': 'confirmed'
            }
        }
        
        # Вызываем функцию
        await handle_payment_confirmation(self.update, self.context)
        
        # Проверяем, что функция вызвала правильные методы
        mock_db.add_pending_payment.assert_called_once()

    @patch('bot.db')
    async def test_admin_confirm_payment(self, mock_db):
        """Тест подтверждения оплаты администратором"""
        # Настраиваем мок
        mock_db.mark_participant_paid = AsyncMock(return_value=True)
        mock_db.delete_pending_payment = AsyncMock()
        mock_db.get_pending_payment = AsyncMock(return_value={
            'user_id': 987654321,
            'username': 'testuser2',
            'date_str': '12.05.2024'
        })
        mock_db.get_user_profile = AsyncMock(return_value={
            'user_id': 987654321,
            'full_name': 'Test User 2',
            'birth_date': '01.01.1990',
            'occupation': 'Developer',
            'instagram': '@testuser2',
            'skills': 'Python, Testing'
        })
        
        # Устанавливаем пользователя как админа
        self.user.id = ADMIN_IDS[0]
        
        # Создаем callback query
        callback_query = CallbackQuery(
            id="test_callback",
            from_user=self.user,
            chat_instance="test_chat",
            data="admin_confirm_987654321_12.05.2024_online"
        )
        self.update.callback_query = callback_query
        
        # Вызываем функцию
        await admin_confirm_payment(self.update, self.context, 987654321, '12.05.2024', 'online')
        
        # Проверяем, что функция вызвала правильные методы
        mock_db.mark_participant_paid.assert_called_once()
        mock_db.delete_pending_payment.assert_called_once()

    @patch('bot.db')
    async def test_admin_decline_payment(self, mock_db):
        """Тест отклонения оплаты администратором"""
        # Настраиваем мок
        mock_db.get_pending_payment = AsyncMock(return_value={
            'user_id': 987654321,
            'username': 'testuser2',
            'date_str': '12.05.2024'
        })
        mock_db.delete_pending_payment = AsyncMock()
        
        # Устанавливаем пользователя как админа
        self.user.id = ADMIN_IDS[0]
        
        # Создаем callback query
        callback_query = CallbackQuery(
            id="test_callback",
            from_user=self.user,
            chat_instance="test_chat",
            data="admin_decline_987654321_12.05.2024_online"
        )
        self.update.callback_query = callback_query
        
        # Вызываем функцию
        await admin_decline_payment(self.update, self.context, 987654321, '12.05.2024', 'online')
        
        # Проверяем, что функция вызвала правильные методы
        mock_db.delete_pending_payment.assert_called_once()

    def test_format_bath_message(self):
        """Тест форматирования сообщения о бане"""
        # Создаем тестовые данные
        date_str = "12.05.2024"
        participants = [
            {'user_id': 1, 'username': 'user1', 'paid': True},
            {'user_id': 2, 'username': 'user2', 'paid': False}
        ]
        
        # Вызываем функцию
        message = format_bath_message(date_str)
        
        # Проверяем, что сообщение содержит все необходимые элементы
        self.assertIn(date_str, message)
        self.assertIn(BATH_TIME, message)
        self.assertIn(BATH_COST, message)
        self.assertIn("Список участников", message)

if __name__ == '__main__':
    unittest.main() 
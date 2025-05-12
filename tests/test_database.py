import unittest
import os
import sqlite3
from database import Database

class TestDatabase(unittest.TestCase):
    def setUp(self):
        """Подготовка тестового окружения"""
        # Создаем тестовую базу данных
        self.test_db_path = 'test_bath_bot.db'
        self.db = Database(self.test_db_path)
        
        # Создаем тестовые данные
        self.test_user = {
            'user_id': 123456789,
            'username': 'testuser',
            'full_name': 'Test User',
            'birth_date': '01.01.1990',
            'occupation': 'Developer',
            'instagram': '@testuser',
            'skills': 'Python, Testing'
        }
        
        self.test_date = "12.05.2024"

    def tearDown(self):
        """Очистка после тестов"""
        # Закрываем соединение с базой данных
        self.db.close()
        
        # Удаляем тестовую базу данных
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)

    def test_add_active_user(self):
        """Тест добавления активного пользователя"""
        # Добавляем пользователя
        self.db.add_active_user(self.test_user['user_id'], self.test_user['username'])
        
        # Проверяем, что пользователь добавлен
        conn = sqlite3.connect(self.test_db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM active_users WHERE user_id = ?', (self.test_user['user_id'],))
        result = cursor.fetchone()
        conn.close()
        
        self.assertIsNotNone(result)
        self.assertEqual(result[0], self.test_user['user_id'])
        self.assertEqual(result[1], self.test_user['username'])

    def test_save_user_profile(self):
        """Тест сохранения профиля пользователя"""
        # Сохраняем профиль
        self.db.save_user_profile(self.test_user)
        
        # Проверяем, что профиль сохранен
        conn = sqlite3.connect(self.test_db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM user_profiles WHERE user_id = ?', (self.test_user['user_id'],))
        result = cursor.fetchone()
        conn.close()
        
        self.assertIsNotNone(result)
        self.assertEqual(result[0], self.test_user['user_id'])
        self.assertEqual(result[1], self.test_user['username'])
        self.assertEqual(result[2], self.test_user['full_name'])
        self.assertEqual(result[3], self.test_user['birth_date'])
        self.assertEqual(result[4], self.test_user['occupation'])
        self.assertEqual(result[5], self.test_user['instagram'])
        self.assertEqual(result[6], self.test_user['skills'])

    def test_create_bath_event(self):
        """Тест создания события бани"""
        # Создаем событие
        self.db.create_bath_event(self.test_date)
        
        # Проверяем, что событие создано
        conn = sqlite3.connect(self.test_db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM bath_events WHERE date_str = ?', (self.test_date,))
        result = cursor.fetchone()
        conn.close()
        
        self.assertIsNotNone(result)
        self.assertEqual(result[0], self.test_date)

    def test_add_bath_participant(self):
        """Тест добавления участника бани"""
        # Создаем событие
        self.db.create_bath_event(self.test_date)
        
        # Добавляем участника
        self.db.add_bath_participant(
            self.test_date,
            self.test_user['user_id'],
            self.test_user['username'],
            paid=False
        )
        
        # Проверяем, что участник добавлен
        conn = sqlite3.connect(self.test_db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM bath_participants WHERE date_str = ? AND user_id = ?',
                      (self.test_date, self.test_user['user_id']))
        result = cursor.fetchone()
        conn.close()
        
        self.assertIsNotNone(result)
        self.assertEqual(result[0], self.test_date)
        self.assertEqual(result[1], self.test_user['user_id'])
        self.assertEqual(result[2], self.test_user['username'])
        self.assertEqual(result[3], 0)  # paid = False

    def test_mark_participant_paid(self):
        """Тест отметки об оплате участника"""
        # Создаем событие и добавляем участника
        self.db.create_bath_event(self.test_date)
        self.db.add_bath_participant(
            self.test_date,
            self.test_user['user_id'],
            self.test_user['username'],
            paid=False
        )
        
        # Отмечаем оплату
        result = self.db.mark_participant_paid(self.test_date, self.test_user['user_id'])
        
        # Проверяем результат
        self.assertTrue(result)
        
        # Проверяем в базе данных
        conn = sqlite3.connect(self.test_db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT paid FROM bath_participants WHERE date_str = ? AND user_id = ?',
                      (self.test_date, self.test_user['user_id']))
        result = cursor.fetchone()
        conn.close()
        
        self.assertEqual(result[0], 1)  # paid = True

    def test_get_bath_participants(self):
        """Тест получения списка участников бани"""
        # Создаем событие и добавляем участников
        self.db.create_bath_event(self.test_date)
        self.db.add_bath_participant(
            self.test_date,
            self.test_user['user_id'],
            self.test_user['username'],
            paid=True
        )
        
        # Получаем список участников
        participants = self.db.get_bath_participants(self.test_date)
        
        # Проверяем результат
        self.assertEqual(len(participants), 1)
        self.assertEqual(participants[0]['user_id'], self.test_user['user_id'])
        self.assertEqual(participants[0]['username'], self.test_user['username'])
        self.assertTrue(participants[0]['paid'])

    def test_add_pending_payment(self):
        """Тест добавления ожидающей оплаты"""
        # Добавляем ожидающую оплату
        self.db.add_pending_payment(
            self.test_user['user_id'],
            self.test_user['username'],
            self.test_date,
            payment_type='online'
        )
        
        # Проверяем в базе данных
        conn = sqlite3.connect(self.test_db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM pending_payments WHERE user_id = ? AND date_str = ?',
                      (self.test_user['user_id'], self.test_date))
        result = cursor.fetchone()
        conn.close()
        
        self.assertIsNotNone(result)
        self.assertEqual(result[0], self.test_user['user_id'])
        self.assertEqual(result[1], self.test_user['username'])
        self.assertEqual(result[2], self.test_date)
        self.assertEqual(result[3], 'online')

    def test_delete_pending_payment(self):
        """Тест удаления ожидающей оплаты"""
        # Добавляем ожидающую оплату
        self.db.add_pending_payment(
            self.test_user['user_id'],
            self.test_user['username'],
            self.test_date,
            payment_type='online'
        )
        
        # Удаляем ожидающую оплату
        self.db.delete_pending_payment(self.test_user['user_id'], self.test_date)
        
        # Проверяем в базе данных
        conn = sqlite3.connect(self.test_db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM pending_payments WHERE user_id = ? AND date_str = ?',
                      (self.test_user['user_id'], self.test_date))
        result = cursor.fetchone()
        conn.close()
        
        self.assertIsNone(result)

if __name__ == '__main__':
    unittest.main() 
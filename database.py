import json
import os
from datetime import datetime, timedelta, time
import sqlite3
import logging
import mysql.connector
from config import RDS_CONFIG
from typing import List, Dict

logger = logging.getLogger(__name__)

class Database:
    """Класс для работы с базой данных.
    
    Особенности:
    - История посещений бани хранится бессрочно
    - Логи ротируются каждые 6 месяцев
    - Подписки хранятся до истечения срока
    """
    def __init__(self, file_path="data.json", db_file="bath_history.db"):
        self.file_path = file_path
        self.data = self._load_data()
        self.db_file = db_file
        self.config = RDS_CONFIG
        self.init_db()

    def _load_data(self):
        """Загрузка данных из файла"""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r', encoding='utf-8') as file:
                    return json.load(file)
            except json.JSONDecodeError:
                return self._create_default_data()
        else:
            return self._create_default_data()

    def _create_default_data(self):
        """Создание структуры данных по умолчанию"""
        return {
            "subscribers": {},  # user_id: {"paid_until": timestamp, "username": "name"}
            "bath_events": {}  # date: {"participants": [{"user_id": id, "username": "name", "paid": bool}]}
        }

    def _save_data(self):
        """Сохранение данных в файл"""
        with open(self.file_path, 'w', encoding='utf-8') as file:
            json.dump(self.data, file, ensure_ascii=False, indent=2)

    # Методы для работы с подписками
    def add_subscriber(self, user_id, username, paid_until):
        """Добавление или обновление подписчика"""
        self.data["subscribers"][str(user_id)] = {
            "paid_until": paid_until,
            "username": username
        }
        self._save_data()

    def remove_subscriber(self, user_id):
        """Удаление подписчика"""
        if str(user_id) in self.data["subscribers"]:
            del self.data["subscribers"][str(user_id)]
            self._save_data()
            return True
        return False

    def check_subscription(self, user_id):
        """Проверка активной подписки"""
        if str(user_id) in self.data["subscribers"]:
            paid_until = self.data["subscribers"][str(user_id)]["paid_until"]
            return paid_until > datetime.now().timestamp()
        return False

    def get_expired_subscribers(self):
        """Получение списка пользователей с истекшей подпиской"""
        expired = []
        now = datetime.now().timestamp()
        for user_id, data in self.data["subscribers"].items():
            if data["paid_until"] < now:
                expired.append(int(user_id))
        return expired

    # Методы для бани
    def create_bath_event(self, date_str):
        """Создает новое событие бани"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            # Проверяем, существует ли уже запись на эту дату
            cursor.execute('SELECT COUNT(*) FROM bath_participants WHERE date_str = %s', (date_str,))
            if cursor.fetchone()[0] == 0:
                conn.commit()
        except mysql.connector.Error as e:
            logger.error(f"Ошибка при создании события бани: {e}")
            raise
        finally:
            conn.close()

    def clear_previous_bath_events(self, except_date_str=None):
        """Очищает предыдущие события бани, сохраняя историю и удаляя записи с cash=1 для старых дат."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            # Получаем все записи, которые нужно перенести в историю
            if except_date_str:
                cursor.execute('''
                    SELECT date_str, user_id, username, paid 
                    FROM bath_participants 
                    WHERE date_str != %s
                ''', (except_date_str,))
            else:
                cursor.execute('SELECT date_str, user_id, username, paid FROM bath_participants')
            records = cursor.fetchall()
            # Переносим записи в историю
            for record in records:
                cursor.execute('''
                    INSERT INTO bath_history (date_str, user_id, username, paid)
                    VALUES (%s, %s, %s, %s)
                ''', record)
            # Очищаем таблицу участников
            if except_date_str:
                cursor.execute('DELETE FROM bath_participants WHERE date_str != %s', (except_date_str,))
                # Удаляем все cash=1 для всех дат, кроме новой
                cursor.execute('DELETE FROM bath_participants WHERE date_str != %s AND cash = 1', (except_date_str,))
            else:
                cursor.execute('DELETE FROM bath_participants')
            conn.commit()
            return len(records)
        except mysql.connector.Error as e:
            logger.error(f"Ошибка при очистке предыдущих событий: {e}")
            raise
        finally:
            conn.close()

    def add_bath_participant(self, date_str, user_id, username, paid=False):
        """Добавляет участника в список"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO bath_participants (date_str, user_id, username, paid)
                VALUES (%s, %s, %s, %s)
            ''', (date_str, user_id, username, paid))
            conn.commit()
            return True
        except mysql.connector.Error as e:
            logger.error(f"Ошибка при добавлении участника: {e}")
            return False
        finally:
            conn.close()

    def get_bath_participants(self, date_str):
        """Получает список участников на определенную дату"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id, username, paid, cash 
                FROM bath_participants 
                WHERE date_str = %s
            ''', (date_str,))
            return [{"user_id": row[0], "username": row[1], "paid": bool(row[2]), "cash": bool(row[3])} 
                   for row in cursor.fetchall()]
        except mysql.connector.Error as e:
            logger.error(f"Ошибка при получении списка участников: {e}")
            return []
        finally:
            conn.close()

    def mark_participant_paid(self, date_str, user_id):
        """Отмечает участника как оплатившего"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE bath_participants 
                SET paid = 1 
                WHERE date_str = %s AND user_id = %s
            ''', (date_str, user_id))
            conn.commit()
            return cursor.rowcount > 0
        except mysql.connector.Error as e:
            logger.error(f"Ошибка при отметке оплаты: {e}")
            return False
        finally:
            conn.close()

    def get_user_bath_history(self, user_id):
        """Получает историю посещений бани для конкретного пользователя"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT date_str, paid, visited 
                FROM bath_history 
                WHERE user_id = %s 
                ORDER BY date_str DESC
            ''', (user_id,))
            return [{"date": row[0], "paid": bool(row[1]), "visited": bool(row[2])} 
                   for row in cursor.fetchall()]
        except mysql.connector.Error as e:
            logger.error(f"Ошибка при получении истории пользователя: {e}")
            return []
        finally:
            conn.close()

    def get_bath_statistics(self, start_date=None, end_date=None):
        """Получает статистику посещений бани за период"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            query = '''
                SELECT date_str, 
                       COUNT(*) as total_participants,
                       SUM(CASE WHEN paid = 1 THEN 1 ELSE 0 END) as paid_participants,
                       SUM(CASE WHEN visited = 1 THEN 1 ELSE 0 END) as visited_participants
                FROM bath_history
            '''
            params = []
            
            if start_date and end_date:
                query += ' WHERE date_str BETWEEN %s AND %s'
                params.extend([start_date, end_date])
            elif start_date:
                query += ' WHERE date_str >= %s'
                params.append(start_date)
            elif end_date:
                query += ' WHERE date_str <= %s'
                params.append(end_date)
            
            query += ' GROUP BY date_str ORDER BY date_str DESC'
            
            cursor.execute(query, params)
            return [{
                "date": row[0],
                "total": row[1],
                "paid": row[2],
                "visited": row[3]
            } for row in cursor.fetchall()]
        except mysql.connector.Error as e:
            logger.error(f"Ошибка при получении статистики: {e}")
            return []
        finally:
            conn.close()

    def mark_visit(self, date_str, user_id, visited=True):
        """Отмечает посещение бани пользователем"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE bath_history 
                SET visited = %s 
                WHERE date_str = %s AND user_id = %s
            ''', (visited, date_str, user_id))
            conn.commit()
            return cursor.rowcount > 0
        except mysql.connector.Error as e:
            logger.error(f"Ошибка при отметке посещения: {e}")
            return False
        finally:
            conn.close()

    def get_connection(self):
        """Получение соединения с базой данных."""
        try:
            connection = mysql.connector.connect(
                **self.config,
                ssl_verify_cert=True
            )
            return connection
        except mysql.connector.Error as err:
            logger.error(f"Ошибка подключения к MySQL: {err}")
            raise

    def init_db(self):
        """Инициализирует базу данных, создает необходимые таблицы"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Создаем таблицу участников бани
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS bath_participants (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        username VARCHAR(255),
                        date_str VARCHAR(10) NOT NULL,
                        paid BOOLEAN DEFAULT FALSE,
                        cash BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY unique_participant (user_id, date_str),
                        INDEX idx_date_str (date_str),
                        INDEX idx_user_id (user_id),
                        INDEX idx_paid (paid),
                        INDEX idx_cash (cash)
                    )
                """)
                
                # Создаем таблицу истории бани
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS bath_history (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        username VARCHAR(255),
                        date_str VARCHAR(10) NOT NULL,
                        paid BOOLEAN DEFAULT FALSE,
                        visited BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_date_str (date_str),
                        INDEX idx_user_id (user_id),
                        INDEX idx_paid (paid),
                        INDEX idx_visited (visited)
                    )
                """)
                
                # Создаем таблицу закрепленных сообщений
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS pinned_messages (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        message_id BIGINT NOT NULL,
                        chat_id BIGINT NOT NULL,
                        date_str VARCHAR(10) NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY unique_pinned_message (message_id, chat_id, date_str),
                        INDEX idx_chat_id (chat_id),
                        INDEX idx_date_str (date_str)
                    )
                """)
                
                # Создаем таблицу активных пользователей
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS active_users (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        username VARCHAR(255),
                        last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY unique_user (user_id),
                        INDEX idx_last_active (last_active)
                    )
                """)
                
                # Создаем таблицу отслеживаемых сообщений
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS tracked_messages (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        message_id BIGINT NOT NULL,
                        chat_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        username VARCHAR(255),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY unique_message (message_id, chat_id),
                        INDEX idx_user_id (user_id),
                        INDEX idx_chat_id (chat_id)
                    )
                """)
                
                # Создаем таблицу подписчиков
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS subscribers (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        username VARCHAR(255),
                        subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY unique_subscriber (user_id),
                        INDEX idx_subscribed_at (subscribed_at)
                    )
                """)
                
                # Создаем таблицу приглашений в баню
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS bath_invites (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        inviter_id BIGINT NOT NULL,
                        invitee_id BIGINT NOT NULL,
                        inviter_username VARCHAR(255),
                        invitee_username VARCHAR(255),
                        date_str VARCHAR(10) NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY unique_invite (inviter_id, invitee_id, date_str),
                        INDEX idx_invitee_id (invitee_id),
                        INDEX idx_date_str (date_str),
                        INDEX idx_created_at (created_at)
                    )
                """)
                
                # Создаем таблицу профилей пользователей
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_profiles (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        username VARCHAR(255),
                        full_name VARCHAR(255),
                        birth_date VARCHAR(10),
                        occupation VARCHAR(255),
                        instagram VARCHAR(255),
                        skills TEXT,
                        total_visits INT DEFAULT 0,
                        first_visit_date DATE,
                        last_visit_date DATE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        UNIQUE KEY unique_user_profile (user_id),
                        INDEX idx_username (username),
                        INDEX idx_total_visits (total_visits),
                        INDEX idx_last_visit_date (last_visit_date)
                    )
                """)
                
                # Создаем таблицу ожидающих оплат
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS pending_payments (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        username VARCHAR(255),
                        date_str VARCHAR(10) NOT NULL,
                        payment_type VARCHAR(20) DEFAULT 'online',
                        amount DECIMAL(10,2) NOT NULL,
                        status VARCHAR(20) DEFAULT 'pending',
                        last_notified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        UNIQUE KEY unique_pending_payment (user_id, date_str),
                        INDEX idx_username (username),
                        INDEX idx_date_str (date_str),
                        INDEX idx_status (status),
                        INDEX idx_last_notified (last_notified)
                    )
                """)
                
                conn.commit()
                logging.info("Database initialized successfully")
        except mysql.connector.Error as e:
            logger.error(f"Ошибка при инициализации базы данных: {e}")
            raise

    def get_user_visits_count(self, user_id: int) -> int:
        """Получает общее количество посещений бани пользователем"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM bath_history 
                WHERE user_id = %s AND visited = 1
            ''', (user_id,))
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def add_active_user(self, user_id, username):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO active_users (user_id, username, last_active)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE
                    username=VALUES(username),
                    last_active=CURRENT_TIMESTAMP
            ''', (user_id, username))
            conn.commit()
        finally:
            conn.close()

    def set_pinned_message_id(self, date_str, message_id, chat_id):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO pinned_messages (date_str, message_id, chat_id)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE message_id=VALUES(message_id)
            ''', (date_str, message_id, chat_id))
            conn.commit()
        finally:
            conn.close()

    def get_last_pinned_message_id(self, chat_id):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT message_id 
                FROM pinned_messages 
                WHERE chat_id = %s 
                ORDER BY date_str DESC LIMIT 1
            ''', (chat_id,))
            row = cursor.fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def delete_pinned_message_id(self, message_id, chat_id):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM pinned_messages 
                WHERE message_id = %s AND chat_id = %s
            ''', (message_id, chat_id))
            conn.commit()
        finally:
            conn.close()

    def clear_all_data(self):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            # Очищаем все основные таблицы
            cursor.execute('DELETE FROM bath_participants')
            cursor.execute('DELETE FROM bath_history')
            cursor.execute('DELETE FROM active_users')
            cursor.execute('DELETE FROM pinned_messages')
            cursor.execute('DELETE FROM subscribers')
            cursor.execute('DELETE FROM tracked_messages')
            conn.commit()
        finally:
            conn.close()

    def add_bath_invite(self, user_id, username, date_str):
        """Добавляет временное приглашение на регистрацию (на 2 часа)"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO bath_invites 
                (inviter_id, invitee_id, inviter_username, invitee_username, date_str, created_at)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE 
                    inviter_username=VALUES(inviter_username),
                    invitee_username=VALUES(invitee_username),
                    created_at=CURRENT_TIMESTAMP
            ''', (user_id, user_id, username, username, date_str))
            conn.commit()
        finally:
            conn.close()

    def check_bath_invite(self, user_id, date_str, hours=2):
        """Проверяет, есть ли активное приглашение для пользователя на дату"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT created_at, invitee_username 
                FROM bath_invites 
                WHERE invitee_id = %s AND date_str = %s
            ''', (user_id, date_str))
            row = cursor.fetchone()
            if not row:
                return False
            created_at = row[0]
            return (datetime.now() - created_at) < timedelta(hours=hours)
        finally:
            conn.close()

    def cleanup_old_bath_invites(self, hours=2):
        """Удаляет устаревшие приглашения (старше N часов)"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM bath_invites 
                WHERE created_at < DATE_SUB(NOW(), INTERVAL %s HOUR)
            ''', (hours,))
            conn.commit()
        finally:
            conn.close()

    def try_add_bath_invite(self, user_id, username, date_str, hours=2):
        """Пытается добавить приглашение. Возвращает True, если приглашение новое, иначе False."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            # Удаляем устаревшие приглашения для этого пользователя и даты
            cursor.execute('''
                DELETE FROM bath_invites
                WHERE invitee_id = %s AND date_str = %s 
                AND created_at < DATE_SUB(NOW(), INTERVAL %s HOUR)
            ''', (user_id, date_str, hours))
            # Пытаемся вставить новое приглашение
            cursor.execute('''
                INSERT IGNORE INTO bath_invites 
                (inviter_id, invitee_id, inviter_username, invitee_username, date_str, created_at)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ''', (user_id, user_id, username, username, date_str))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def save_user_profile(self, user_id: int, username: str, full_name: str, birth_date: str, 
                         occupation: str, instagram: str, skills: str) -> bool:
        """Сохраняет или обновляет профиль пользователя."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO user_profiles 
                (user_id, username, full_name, birth_date, occupation, instagram, skills, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE
                    username=VALUES(username),
                    full_name=VALUES(full_name),
                    birth_date=VALUES(birth_date),
                    occupation=VALUES(occupation),
                    instagram=VALUES(instagram),
                    skills=VALUES(skills),
                    updated_at=CURRENT_TIMESTAMP
            ''', (user_id, username, full_name, birth_date, occupation, instagram, skills))
            conn.commit()
            return True
        except mysql.connector.Error as e:
            logger.error(f"Ошибка при сохранении профиля пользователя: {e}")
            return False
        finally:
            conn.close()

    def get_user_profile(self, user_id: int) -> dict:
        """Получает профиль пользователя."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    id,
                    user_id,
                    username,
                    full_name,
                    birth_date,
                    occupation,
                    instagram,
                    skills,
                    total_visits,
                    first_visit_date,
                    last_visit_date,
                    created_at,
                    updated_at
                FROM user_profiles 
                WHERE user_id = %s
            ''', (user_id,))
            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'user_id': row[1],
                    'username': row[2],
                    'full_name': row[3],
                    'birth_date': row[4],
                    'occupation': row[5],
                    'instagram': row[6],
                    'skills': row[7],
                    'total_visits': row[8],
                    'first_visit_date': row[9],
                    'last_visit_date': row[10],
                    'created_at': row[11],
                    'updated_at': row[12]
                }
            return None
        finally:
            conn.close()

    def get_bath_participants_profiles(self, date_str: str) -> list:
        """Получает профили всех участников бани на определенную дату."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    p.user_id,
                    p.username,
                    up.full_name,
                    up.birth_date,
                    up.occupation,
                    up.instagram,
                    up.skills
                FROM bath_participants p
                LEFT JOIN user_profiles up ON p.user_id = up.user_id
                WHERE p.date_str = %s
            ''', (date_str,))
            rows = cursor.fetchall()
            return [{
                'user_id': row[0],
                'username': row[1],
                'full_name': row[2],
                'birth_date': row[3],
                'occupation': row[4],
                'instagram': row[5],
                'skills': row[6]
            } for row in rows]
        finally:
            conn.close()

    def get_all_user_profiles(self) -> list:
        """Возвращает список всех профилей пользователей для экспорта."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    up.user_id,
                    up.username,
                    up.full_name,
                    up.birth_date,
                    up.occupation,
                    up.instagram,
                    up.skills,
                    up.total_visits,
                    up.first_visit_date,
                    up.last_visit_date,
                    bp.date_str
                FROM user_profiles up
                LEFT JOIN bath_participants bp ON up.user_id = bp.user_id
            ''')
            rows = cursor.fetchall()
            profiles = []
            for row in rows:
                profiles.append({
                    'user_id': row[0],
                    'username': row[1],
                    'full_name': row[2],
                    'birth_date': row[3],
                    'occupation': row[4],
                    'instagram': row[5],
                    'skills': row[6],
                    'total_visits': row[7],
                    'first_visit_date': row[8],
                    'last_visit_date': row[9],
                    'date_str': row[10] if row[10] else None
                })
            return profiles
        finally:
            conn.close()

    def add_pending_payment(self, user_id, username, date_str, payment_type='online'):
        """Добавляет запись об ожидающей оплате."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            # Получаем стоимость бани из конфига
            from config import BATH_COST
            cursor.execute('''
                INSERT INTO pending_payments 
                (user_id, username, date_str, payment_type, amount, created_at, last_notified)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE
                    username=VALUES(username),
                    payment_type=VALUES(payment_type),
                    amount=VALUES(amount),
                    created_at=CURRENT_TIMESTAMP,
                    last_notified=CURRENT_TIMESTAMP
            ''', (user_id, username, date_str, payment_type, BATH_COST))
            conn.commit()
        finally:
            conn.close()

    def get_pending_payment(self, user_id, date_str, payment_type=None):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            if payment_type:
                cursor.execute('''
                    SELECT user_id, username, date_str, payment_type 
                    FROM pending_payments 
                    WHERE user_id = %s AND date_str = %s AND payment_type = %s
                ''', (user_id, date_str, payment_type))
            else:
                cursor.execute('''
                    SELECT user_id, username, date_str, payment_type 
                    FROM pending_payments 
                    WHERE user_id = %s AND date_str = %s
                ''', (user_id, date_str))
            row = cursor.fetchone()
            if row:
                return {'user_id': row[0], 'username': row[1], 'date_str': row[2], 'payment_type': row[3]}
            return None
        finally:
            conn.close()

    def get_pending_payments_for_reminder(self, hours=4):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id, username, date_str, payment_type 
                FROM pending_payments
                WHERE TIMESTAMPDIFF(HOUR, last_notified, NOW()) >= %s
            ''', (hours,))
            return cursor.fetchall()
        finally:
            conn.close()

    def delete_pending_payment(self, user_id, date_str):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM pending_payments WHERE user_id = %s AND date_str = %s',
                (user_id, date_str)
            )
            conn.commit()
        finally:
            conn.close()

    def get_pending_payments(self, user_id: int) -> List[Dict]:
        """Получает список ожидающих подтверждения оплат для пользователя."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT date_str, payment_type
                FROM pending_payments
                WHERE user_id = ?
            ''', (user_id,))
            payments = cursor.fetchall()
            return [{'date_str': p[0], 'payment_type': p[1]} for p in payments]
        except Exception as e:
            logger.error(f"Ошибка при получении ожидающих оплат: {e}")
            return []
        finally:
            conn.close()
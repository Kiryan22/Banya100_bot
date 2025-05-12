import json
import os
from datetime import datetime, timedelta, time
import sqlite3
import logging
import mysql.connector
from config import RDS_CONFIG

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
                
                # Проверяем существование таблицы user_profiles
                cursor.execute("SHOW TABLES LIKE 'user_profiles'")
                if cursor.fetchone():
                    # Если таблица существует, удаляем её
                    cursor.execute("DROP TABLE user_profiles")
                    logger.info("Dropped existing user_profiles table for migration")
                
                # Создаем таблицу участников бани
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS bath_participants (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        username VARCHAR(255),
                        date_str VARCHAR(10) NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY unique_participant (user_id, date_str)
                    )
                """)
                
                # Создаем таблицу истории бани
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS bath_history (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        username VARCHAR(255),
                        date_str VARCHAR(10) NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                        UNIQUE KEY unique_pinned_message (message_id, chat_id, date_str)
                    )
                """)
                
                # Создаем таблицу активных пользователей
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS active_users (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        username VARCHAR(255),
                        last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY unique_user (user_id)
                    )
                """)
                
                # Создаем таблицу отслеживаемых сообщений
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS tracked_messages (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        message_id BIGINT NOT NULL,
                        chat_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY unique_message (message_id, chat_id)
                    )
                """)
                
                # Создаем таблицу подписчиков
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS subscribers (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        username VARCHAR(255),
                        subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY unique_subscriber (user_id)
                    )
                """)
                
                # Создаем таблицу приглашений в баню
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS bath_invites (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        inviter_id BIGINT NOT NULL,
                        invitee_id BIGINT NOT NULL,
                        date_str VARCHAR(10) NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY unique_invite (inviter_id, invitee_id, date_str)
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
                        UNIQUE KEY unique_user_profile (user_id)
                    )
                """)
                
                # Создаем таблицу ожидающих оплат
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS pending_payments (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        amount DECIMAL(10,2) NOT NULL,
                        status VARCHAR(20) DEFAULT 'pending',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        UNIQUE KEY unique_pending_payment (user_id, created_at)
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

    def set_pinned_message_id(self, date_str, message_id):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO pinned_messages (date_str, message_id)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE message_id=VALUES(message_id)
            ''', (date_str, message_id))
            conn.commit()
        finally:
            conn.close()

    def get_last_pinned_message_id(self):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT message_id FROM pinned_messages ORDER BY date_str DESC LIMIT 1')
            row = cursor.fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def delete_pinned_message_id(self, message_id):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM pinned_messages WHERE message_id = %s', (message_id,))
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

    def add_bath_invite(self, user_id, date_str):
        """Добавляет временное приглашение на регистрацию (на 2 часа)"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO bath_invites (user_id, date_str, created_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE created_at=CURRENT_TIMESTAMP
            ''', (user_id, date_str))
            conn.commit()
        finally:
            conn.close()

    def check_bath_invite(self, user_id, date_str, hours=2):
        """Проверяет, есть ли активное приглашение для пользователя на дату"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT created_at FROM bath_invites WHERE user_id = %s AND date_str = %s
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
                DELETE FROM bath_invites WHERE created_at < DATE_SUB(NOW(), INTERVAL %s HOUR)
            ''', (hours,))
            conn.commit()
        finally:
            conn.close()

    def try_add_bath_invite(self, user_id, date_str, hours=2):
        """Пытается добавить приглашение. Возвращает True, если приглашение новое, иначе False."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            # Удаляем устаревшие приглашения для этого пользователя и даты
            cursor.execute('''
                DELETE FROM bath_invites
                WHERE user_id = %s AND date_str = %s AND created_at < DATE_SUB(NOW(), INTERVAL %s HOUR)
            ''', (user_id, date_str, hours))
            # Пытаемся вставить новое приглашение
            cursor.execute('''
                INSERT IGNORE INTO bath_invites (user_id, date_str, created_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
            ''', (user_id, date_str))
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
                (user_id, username, full_name, birth_date, occupation, instagram, skills, last_updated)
                VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE
                    username=VALUES(username),
                    full_name=VALUES(full_name),
                    birth_date=VALUES(birth_date),
                    occupation=VALUES(occupation),
                    instagram=VALUES(instagram),
                    skills=VALUES(skills),
                    last_updated=CURRENT_TIMESTAMP
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
            cursor.execute('SELECT * FROM user_profiles WHERE user_id = %s', (user_id,))
            row = cursor.fetchone()
            if row:
                return {
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
                    'last_updated': row[10]
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
                SELECT p.*, up.* 
                FROM bath_participants p
                LEFT JOIN user_profiles up ON p.user_id = up.user_id
                WHERE p.date_str = %s AND p.visited = 1
            ''', (date_str,))
            rows = cursor.fetchall()
            return [{
                'user_id': row[0],
                'username': row[1],
                'full_name': row[7],
                'birth_date': row[8],
                'occupation': row[9],
                'instagram': row[10],
                'skills': row[11]
            } for row in rows]
        finally:
            conn.close()

    def get_all_user_profiles(self) -> list:
        """Возвращает список всех профилей пользователей для экспорта."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id, username, full_name, birth_date, occupation, instagram, skills, 
                       total_visits, first_visit_date, last_visit_date
                FROM user_profiles
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
                    'last_visit_date': row[9]
                })
            return profiles
        finally:
            conn.close()

    def add_pending_payment(self, user_id, username, date_str, payment_type='online'):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO pending_payments (user_id, username, date_str, payment_type, created_at, last_notified)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE
                    username=VALUES(username),
                    payment_type=VALUES(payment_type),
                    created_at=CURRENT_TIMESTAMP,
                    last_notified=CURRENT_TIMESTAMP
            ''', (user_id, username, date_str, payment_type))
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
import sqlite3
import mysql.connector
import logging
from config import RDS_CONFIG
import os
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_sqlite_connection():
    """Получение соединения с SQLite базой данных."""
    try:
        return sqlite3.connect('bath_history.db')
    except sqlite3.Error as e:
        logger.error(f"Ошибка подключения к SQLite: {e}")
        raise

def get_mysql_connection():
    """Получение соединения с MySQL базой данных."""
    try:
        config = RDS_CONFIG.copy()
        config['ssl_verify_cert'] = True
        return mysql.connector.connect(**config)
    except mysql.connector.Error as e:
        logger.error(f"Ошибка подключения к MySQL: {e}")
        raise

def migrate_table(sqlite_conn, mysql_conn, table_name):
    """Миграция данных из SQLite в MySQL для указанной таблицы."""
    try:
        sqlite_cursor = sqlite_conn.cursor()
        mysql_cursor = mysql_conn.cursor()

        # Получаем данные из SQLite
        sqlite_cursor.execute(f"SELECT * FROM {table_name}")
        rows = sqlite_cursor.fetchall()

        if not rows:
            logger.info(f"Таблица {table_name} пуста, пропускаем")
            return

        # Получаем имена колонок
        sqlite_cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [column[1] for column in sqlite_cursor.fetchall()]

        # Создаем плейсхолдеры для MySQL запроса
        placeholders = ", ".join(["%s"] * len(columns))
        columns_str = ", ".join(columns)

        # Подготавливаем и выполняем INSERT запрос
        insert_query = f"INSERT INTO {table_name} ({columns_str}) VALUES ({placeholders})"
        
        for row in rows:
            try:
                mysql_cursor.execute(insert_query, row)
            except mysql.connector.Error as e:
                if e.errno == 1062:  # Duplicate entry error
                    logger.warning(f"Пропуск дубликата в таблице {table_name}: {row}")
                    continue
                raise

        mysql_conn.commit()
        logger.info(f"Успешно мигрирована таблица {table_name}: {len(rows)} записей")

    except Exception as e:
        logger.error(f"Ошибка при миграции таблицы {table_name}: {e}")
        raise

def main():
    """Основная функция миграции."""
    try:
        # Подключение к базам данных
        sqlite_conn = get_sqlite_connection()
        mysql_conn = get_mysql_connection()

        # Список таблиц для миграции (актуальный)
        tables = [
            'active_users',
            'bath_participants',
            'bath_history',
            'bath_invites',
            'pending_payments',
            'pinned_messages',
            'subscribers',
            'tracked_messages',
            'user_profiles',
        ]

        # Миграция каждой таблицы
        for table in tables:
            migrate_table(sqlite_conn, mysql_conn, table)

        logger.info("Миграция успешно завершена")

    except Exception as e:
        logger.error(f"Ошибка при миграции: {e}")
        raise
    finally:
        if 'sqlite_conn' in locals():
            sqlite_conn.close()
        if 'mysql_conn' in locals():
            mysql_conn.close()

if __name__ == "__main__":
    main() 
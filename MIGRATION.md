# Инструкция по миграции на MySQL

## Предварительные требования

1. Установленный MySQL сервер
2. Python пакеты:
   - mysql-connector-python
   - python-dotenv

## Шаги миграции

1. Создайте базу данных MySQL:
```sql
CREATE DATABASE bath_bot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

2. Настройте параметры подключения в файле `.env`:
```
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=your_username
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=bath_bot
```

3. Сделайте резервную копию текущей SQLite базы данных:
```bash
cp bath_bot.db bath_bot.db.backup
```

4. Запустите скрипт миграции:
```bash
python migrate_to_mysql.py
```

5. После успешной миграции проверьте работу бота с новой базой данных.

## Откат изменений

В случае проблем, вы можете вернуться к SQLite:

1. Остановите бота
2. Восстановите резервную копию SQLite базы:
```bash
cp bath_bot.db.backup bath_bot.db
```
3. Удалите или закомментируйте настройки MySQL в файле `.env`
4. Запустите бота

## Примечания

- Все данные из SQLite будут перенесены в MySQL
- Структура таблиц будет автоматически создана при первом запуске бота
- Рекомендуется сделать резервную копию данных перед миграцией
- После миграции проверьте работу всех функций бота 
import logging
import os
from datetime import datetime

# Создаем директорию для логов, если она не существует
if not os.path.exists('logs'):
    os.makedirs('logs')

# Настраиваем формат логов
log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
date_format = '%Y-%m-%d %H:%M:%S'

# Создаем логгер
logger = logging.getLogger('bath_bot')
logger.setLevel(logging.DEBUG)

# Создаем обработчик для файла
log_file = f'logs/bath_bot_{datetime.now().strftime("%Y%m%d")}.log'
file_handler = logging.FileHandler(log_file, encoding='utf-8')
file_handler.setLevel(logging.DEBUG)

# Создаем обработчик для консоли
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# Создаем форматтер
formatter = logging.Formatter(log_format, date_format)
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Добавляем обработчики к логгеру
logger.addHandler(file_handler)
logger.addHandler(console_handler)

def get_logger(name):
    """Получение логгера с указанным именем"""
    return logging.getLogger(f'bath_bot.{name}') 
import logging
import os
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler


def setup_logging():
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    def create_file_handler(filename, level):
        log_file = os.path.join(log_dir, filename)
        handler = TimedRotatingFileHandler(
            log_file,
            when='midnight',
            interval=30,
            backupCount=6,
            encoding='utf-8'
        )
        handler.setFormatter(log_format)
        handler.setLevel(level)
        return handler

    error_handler = create_file_handler('error.log', logging.ERROR)
    warning_handler = create_file_handler('warning.log', logging.WARNING)
    info_handler = create_file_handler('info.log', logging.INFO)
    debug_handler = create_file_handler('debug.log', logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    console_handler.setLevel(logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    root_logger.addHandler(error_handler)
    root_logger.addHandler(warning_handler)
    root_logger.addHandler(info_handler)
    root_logger.addHandler(debug_handler)
    root_logger.addHandler(console_handler)

    logger = logging.getLogger(__name__)
    cleanup_old_logs(log_dir)
    return logger


def cleanup_old_logs(log_dir):
    try:
        current_time = datetime.now()
        for filename in os.listdir(log_dir):
            if filename.endswith('.db'):
                continue
            if filename.endswith('.log'):
                file_path = os.path.join(log_dir, filename)
                file_time = datetime.fromtimestamp(os.path.getctime(file_path))
                if (current_time - file_time).days > 180:
                    os.remove(file_path)
                    logging.info(f"Удален старый лог: {filename}")
    except Exception as e:
        logging.error(f"Ошибка при очистке старых логов: {e}") 
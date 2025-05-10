import shutil
import os
from datetime import datetime, timedelta

DB_PATH = "bath_bot.db"  # путь к вашей базе
BACKUP_DIR = "backups"
BACKUP_DAYS = 7

os.makedirs(BACKUP_DIR, exist_ok=True)
backup_name = f"bath_bot_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
backup_path = os.path.join(BACKUP_DIR, backup_name)

# Копируем базу
shutil.copy2(DB_PATH, backup_path)
print(f"Бэкап базы сохранён: {backup_path}")

# Удаляем старые бэкапы
now = datetime.now()
for fname in os.listdir(BACKUP_DIR):
    if fname.startswith("bath_bot_backup_") and fname.endswith(".db"):
        fpath = os.path.join(BACKUP_DIR, fname)
        ftime = datetime.fromtimestamp(os.path.getmtime(fpath))
        if (now - ftime).days > BACKUP_DAYS:
            os.remove(fpath)
            print(f"Удалён старый бэкап: {fpath}") 
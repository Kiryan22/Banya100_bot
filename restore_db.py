import os
import shutil

DB_PATH = "bath_bot.db"
BACKUP_DIR = "backups"

# Находим самый свежий бэкап
backups = [f for f in os.listdir(BACKUP_DIR) if f.startswith("bath_bot_backup_") and f.endswith(".db")]
if not backups:
    print("Нет доступных бэкапов!")
    exit(1)

backups.sort(reverse=True)
latest_backup = backups[0]
backup_path = os.path.join(BACKUP_DIR, latest_backup)

# Восстанавливаем базу
shutil.copy2(backup_path, DB_PATH)
print(f"База данных восстановлена из бэкапа: {backup_path}") 
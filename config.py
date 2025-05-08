import os
from dotenv import load_dotenv

# Загрузка переменных из .env файла
load_dotenv()

# Токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ID чата бани
BATH_CHAT_ID = os.getenv("BATH_CHAT_ID")

# ID администраторов
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))

# Максимальное количество участников бани
MAX_BATH_PARTICIPANTS = 2

# Стоимость бани
BATH_COST = "150 zl"

# Время бани
BATH_TIME = "8:00 - 11:30"

# Ссылки на оплату
CARD_PAYMENT_LINK = "https://secure.wayforpay.com/button/b0d488e991d4b"
REVOLUT_PAYMENT_LINK = "https://revolut.me/vitali169l"

# Локация бани
BATH_LOCATION = "https://maps.app.goo.gl/nPevCHWLFA8dVjeV8?g_st=ic"

# Webhook URL (должен быть HTTPS)
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
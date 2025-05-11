import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bot configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
BATH_CHAT_ID = os.getenv('BATH_CHAT_ID')
ADMIN_IDS = list(map(int, os.getenv('ADMIN_IDS', '').split(','))) if os.getenv('ADMIN_IDS') else []
MAX_BATH_PARTICIPANTS = int(os.getenv('MAX_BATH_PARTICIPANTS', '6'))
BATH_COST = int(os.getenv('BATH_COST', '1000'))
WEBHOOK_URL = os.getenv('WEBHOOK_URL')

# AWS RDS Configuration
RDS_CONFIG = {
    'host': os.getenv('RDS_HOST'),
    'port': int(os.getenv('RDS_PORT', '3306')),
    'user': os.getenv('RDS_USER'),
    'password': os.getenv('RDS_PASSWORD'),
    'database': os.getenv('RDS_DATABASE'),
    'ssl_ca': os.getenv('RDS_SSL_CA', '/etc/ssl/certs/global-bundle.pem'),
}

# Ensure warnings are raised as errors
import warnings
warnings.filterwarnings('error')

# Время бани
BATH_TIME = "8:00 - 11:30"

# Ссылки на оплату
CARD_PAYMENT_LINK = "https://secure.wayforpay.com/button/b0d488e991d4b"
REVOLUT_PAYMENT_LINK = "https://revolut.me/vitali169l"

# Локация бани
BATH_LOCATION = "https://maps.app.goo.gl/nPevCHWLFA8dVjeV8?g_st=ic"

# MySQL конфигурация
MYSQL_CONFIG = {
    'host': os.getenv('MYSQL_HOST', 'localhost'),
    'port': int(os.getenv('MYSQL_PORT', '3306')),
    'user': os.getenv('MYSQL_USER', 'root'),
    'password': os.getenv('MYSQL_PASSWORD', ''),
    'database': os.getenv('MYSQL_DATABASE', 'bath_bot'),
    'raise_on_warnings': True
}
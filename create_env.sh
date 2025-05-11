#!/bin/bash

# Скрипт для создания .env на основе .env.example с ручным вводом ключевых переменных

if [ -f .env ]; then
  echo ".env уже существует. Удалите или переименуйте его, если хотите создать заново."
  exit 1
fi

cp .env.example .env

echo "\nВведите значения для ключевых переменных (оставьте пустым для значения по умолчанию):"

read -p "BOT_TOKEN: " BOT_TOKEN
read -p "BATH_CHAT_ID: " BATH_CHAT_ID
read -p "ADMIN_IDS (через запятую): " ADMIN_IDS
read -p "RDS_HOST (127.0.0.1 для локали или endpoint RDS для сервера): " RDS_HOST
read -p "RDS_PORT (3306 или 3307): " RDS_PORT
read -p "RDS_USER: " RDS_USER
read -p "RDS_PASSWORD: " RDS_PASSWORD
read -p "RDS_DATABASE: " RDS_DATABASE
read -p "RDS_SSL_CA (путь к сертификату): " RDS_SSL_CA

# Используем sed для замены значений в .env
[ -n "$BOT_TOKEN" ] && sed -i '' "s|^BOT_TOKEN=.*|BOT_TOKEN=$BOT_TOKEN|" .env
[ -n "$BATH_CHAT_ID" ] && sed -i '' "s|^BATH_CHAT_ID=.*|BATH_CHAT_ID=$BATH_CHAT_ID|" .env
[ -n "$ADMIN_IDS" ] && sed -i '' "s|^ADMIN_IDS=.*|ADMIN_IDS=$ADMIN_IDS|" .env
[ -n "$RDS_HOST" ] && sed -i '' "s|^RDS_HOST=.*|RDS_HOST=$RDS_HOST|" .env
[ -n "$RDS_PORT" ] && sed -i '' "s|^RDS_PORT=.*|RDS_PORT=$RDS_PORT|" .env
[ -n "$RDS_USER" ] && sed -i '' "s|^RDS_USER=.*|RDS_USER=$RDS_USER|" .env
[ -n "$RDS_PASSWORD" ] && sed -i '' "s|^RDS_PASSWORD=.*|RDS_PASSWORD=$RDS_PASSWORD|" .env
[ -n "$RDS_DATABASE" ] && sed -i '' "s|^RDS_DATABASE=.*|RDS_DATABASE=$RDS_DATABASE|" .env
[ -n "$RDS_SSL_CA" ] && sed -i '' "s|^RDS_SSL_CA=.*|RDS_SSL_CA=$RDS_SSL_CA|" .env

echo ".env успешно создан! Проверьте его содержимое:"
cat .env 
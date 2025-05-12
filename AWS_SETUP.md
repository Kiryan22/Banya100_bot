# Настройка AWS RDS для Telegram Bath Bot

## 1. Создание экземпляра RDS

1. Войдите в консоль AWS
2. Перейдите в сервис RDS
3. Нажмите "Create database"
4. Выберите следующие параметры:
   - Engine type: MySQL
   - Edition: MySQL Community
   - Version: 8.0.35 (или новее)
   - Templates: Free tier
   - DB instance identifier: bath-bot-db
   - Master username: bath_bot_admin
   - Master password: [создайте надежный пароль]
   - Instance configuration: db.t3.micro
   - Storage: 20 GB
   - VPC: default
   - Public access: Yes
   - VPC security group: Create new
   - New VPC security group name: bath-bot-sg
   - Availability Zone: No preference
   - Database port: 3306

## 2. Настройка безопасности

1. В консоли RDS перейдите к созданному экземпляру
2. В разделе "Security" найдите "VPC security groups"
3. Нажмите на группу безопасности
4. Добавьте входящее правило:
   - Type: MySQL/Aurora
   - Port: 3306
   - Source: Anywhere (0.0.0.0/0)

## 3. Получение SSL сертификата

1. Скачайте SSL сертификат AWS RDS:
```bash
wget https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
```

2. Переместите сертификат в безопасное место:
```bash
sudo mkdir -p /etc/ssl/certs
sudo mv global-bundle.pem /etc/ssl/certs/ca-certificates.crt
```

## 4. Обновление конфигурации

1. Обновите файл `   RDS_SSL_CA=/Users/kshamanskiy/global-bundle.pem.env`:
```
# AWS RDS Configuration
RDS_HOST=your-db-instance.xxxxx.region.rds.amazonaws.com
RDS_PORT=3306
RDS_USER=bath_bot_admin
RDS_PASSWORD=your_password
RDS_DATABASE=bath_bot
RDS_SSL_CA=/etc/ssl/certs/ca-certificates.crt
```

## 5. Проверка подключения

1. Установите MySQL клиент:
```bash
brew install mysql-client
```

2. Проверьте подключение:
```bash
mysql -h your-db-instance.xxxxx.region.rds.amazonaws.com -u bath_bot_admin -p --ssl-ca=/etc/ssl/certs/ca-certificates.crt
```

## 6. Миграция данных

1. Запустите скрипт миграции:
```bash
python migrate_to_mysql.py
```

## 7. Мониторинг и обслуживание

1. Настройте CloudWatch для мониторинга:
   - CPU Utilization
   - Freeable Memory
   - Free Storage Space
   - Database Connections

2. Настройте автоматическое резервное копирование:
   - Backup retention period: 7 days
   - Backup window: 03:00-04:00 UTC

## 8. Рекомендации по безопасности

1. Регулярно обновляйте пароли
2. Используйте IAM аутентификацию для продакшена
3. Ограничьте доступ к базе данных только необходимыми IP-адресами
4. Включите шифрование данных
5. Настройте аудит базы данных

## 9. Масштабирование

1. Мониторинг производительности
2. Настройка параметров базы данных
3. Оптимизация запросов
4. Настройка репликации при необходимости 
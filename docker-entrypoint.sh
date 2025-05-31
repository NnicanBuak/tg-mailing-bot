#!/bin/bash
set -e

# Проверка соединения с базой данных
python -c "
import time
import os
import psycopg2

host = os.environ.get('DB_HOST', 'postgres')
port = os.environ.get('DB_PORT', '5432')
db_name = os.environ.get('DB_NAME', 'telegram_broadcast')
user = os.environ.get('DB_USER')
password = os.environ.get('DB_PASSWORD')

max_retries = 30
retry_count = 0

while retry_count < max_retries:
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=db_name,
            user=user,
            password=password
        )
        conn.close()
        print('Соединение с базой данных установлено.')
        break
    except psycopg2.OperationalError:
        retry_count += 1
        print(f'Ожидание базы данных... {retry_count}/{max_retries}')
        time.sleep(1)

if retry_count == max_retries:
    raise Exception('Не удалось подключиться к базе данных')
"

# Применяем миграции к базе данных
python fix_database.py

# Запускаем приложение в зависимости от переданного параметра
if [ "$1" = "bot" ]; then
    echo "Запуск Telegram бота..."
    exec python bot.py
elif [ "$1" = "web" ]; then
    echo "Запуск веб-сервера..."
    exec uvicorn app:app --host 0.0.0.0 --port 5000
else
    echo "Используйте 'bot' или 'web' в качестве аргумента запуска"
    exit 1
fi
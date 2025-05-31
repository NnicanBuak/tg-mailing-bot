# Telegram Mailing Bot с Mini App

Бот для управления рассылками сообщений в Telegram с использованием Mini App для выбора получателей.

## Настройка проекта

### 1. Клонирование репозитория

```bash
git clone https://github.com/yourusername/telegram-mailing-bot.git
cd telegram-mailing-bot
```

### 2. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 3. Настройка переменных окружения

Скопируйте файл `.env.sample` в `.env` и заполните необходимые параметры:

```bash
cp .env.sample .env
nano .env
```

Заполните следующие параметры:
- `TELEGRAM_BOT_TOKEN` - токен вашего бота, полученный от @BotFather
- `ADMIN_IDS` - список ID администраторов, которые могут управлять ботом (через запятую)
- `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME` - настройки подключения к PostgreSQL
- `MINI_APP_URL` - URL, где размещено ваше приложение (с протоколом, например https://your-domain.com/mini_app)
- `PORT` - порт для FastAPI (по умолчанию 5000)

### 4. Настройка базы данных

Создайте базу данных PostgreSQL:

```bash
createdb telegram_mailing
```

### 5. Настройка мини-приложения в BotFather

1. Откройте чат с @BotFather в Telegram
2. Отправьте команду `/mybots`
3. Выберите вашего бота из списка
4. Нажмите "Bot Settings"
5. Выберите "Menu Button"
6. Выберите "Configure menu button"
7. Введите URL вашего мини-приложения (тот же, что указали в .env)
8. Введите текст для кнопки (например, "Управление рассылками")

### 6. Запуск проекта

Запустите бота:

```bash
python bot.py
```

В отдельном терминале запустите веб-сервер:

```bash
python app.py
```

## Использование

### Основные команды бота

- `/start` - начало работы с ботом, показ доступных команд
- `/help` - показать справку по командам
- `/create_mailing` - создать новую рассылку
- `/set_message ID текст` - установить текст сообщения для рассылки
- `/set_schedule ID время` - установить расписание (формат: YYYY-MM-DD HH:MM или 'daily/weekly HH:MM')
- `/select_recipients ID` - выбрать получателей через Mini App
- `/send_mailing ID` - отправить рассылку сейчас
- `/mailing_list` - список рассылок
- `/mailing_status ID` - статус рассылки
- `/mailing_stats` - общая статистика
- `/import_recipients ID список_ID` - импорт получателей по списку ID через запятую

### Работа с мини-приложением

1. Нажмите на кнопку "Выбрать получателей" в сообщении от бота или используйте меню кнопку
2. В открывшемся мини-приложении выберите чаты, которым нужно отправить рассылку
3. Нажмите кнопку "Сохранить" или "Готово"
4. Бот подтвердит сохранение получателей

### Создание рассылки

1. Отправьте команду `/create_mailing` боту
2. Бот создаст новую рассылку и вернет ее ID
3. Установите текст рассылки с помощью `/set_message ID текст`
4. Выберите получателей с помощью кнопки "Выбрать получателей" или команды `/select_recipients ID`
5. При необходимости установите расписание с помощью `/set_schedule ID время`
6. Отправьте рассылку с помощью `/send_mailing ID`

### Проверка статуса рассылки

Для проверки статуса рассылки отправьте команду `/mailing_status ID`, где ID - идентификатор рассылки.

## Деплой на сервер

### Настройка Nginx

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Настройка SSL с Certbot

```bash
sudo certbot --nginx -d your-domain.com
```

### Запуск с помощью Supervisor

Создайте файл конфигурации `/etc/supervisor/conf.d/telegram-mailing.conf`:

```ini
[program:telegram-mailing-bot]
command=/path/to/venv/bin/python /path/to/bot.py
directory=/path/to/project
user=username
autostart=true
autorestart=true
stderr_logfile=/var/log/telegram-mailing-bot.err.log
stdout_logfile=/var/log/telegram-mailing-bot.out.log

[program:telegram-mailing-api]
command=/path/to/venv/bin/python /path/to/app.py
directory=/path/to/project
user=username
autostart=true
autorestart=true
stderr_logfile=/var/log/telegram-mailing-api.err.log
stdout_logfile=/var/log/telegram-mailing-api.out.log
```

Применить конфигурацию:

```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start telegram-mailing-bot telegram-mailing-api
```

## Устранение неполадок

### Проблемы с подключением к базе данных

Убедитесь, что PostgreSQL запущен и доступен:

```bash
sudo systemctl status postgresql
psql -h localhost -U your_username -d telegram_mailing
```

### Проблемы с доступом к боту

Убедитесь, что вы добавили свой ID в список `ADMIN_IDS` в файле `.env`.

### Проблемы с мини-приложением

1. Проверьте, что URL в BotFather и в `.env` совпадают
2. Убедитесь, что сервер доступен извне и имеет корректный SSL-сертификат (HTTPS)
3. Проверьте логи веб-сервера на наличие ошибок
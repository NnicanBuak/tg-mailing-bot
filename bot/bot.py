import os
import asyncio
import json
import logging
from datetime import datetime, timedelta
import pathlib
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ApplicationBuilder,
    Defaults,
    MessageHandler,
    filters,
    ConversationHandler,
)
from telegram.error import TelegramError
from database import Chat, Mailing, SendLog, db_session

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получаем абсолютный путь к текущей директории
base_dir = pathlib.Path(__file__).parent.absolute()
env_path = base_dir / ".env"

# Очищаем кэшированные переменные окружения перед загрузкой
keys_to_clear = ["ADMIN_IDS", "MINI_APP_URL", "TELEGRAM_BOT_TOKEN"]
for key in keys_to_clear:
    if key in os.environ:
        print(f"Удаление кэшированной переменной: {key}")
        del os.environ[key]

# Проверяем существование файла .env
if env_path.exists():
    print(f"Файл .env найден: {env_path}")

    # Читаем файл .env напрямую
    try:
        print("Чтение .env файла напрямую...")
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                if "=" in line:
                    key, value = line.split("=", 1)
                    # Устанавливаем переменную окружения напрямую
                    os.environ[key] = value
                    print(f"Установлена переменная {key} = {value}")

        print("Файл .env успешно загружен напрямую")
    except Exception as e:
        print(f"Ошибка при чтении .env файла напрямую: {e}")

        # Пробуем загрузить через python-dotenv как запасной вариант
        try:
            from dotenv import load_dotenv

            load_dotenv(dotenv_path=env_path, override=True)
            print("Файл .env загружен через python-dotenv с override=True")
        except ImportError:
            print("Модуль python-dotenv не установлен")
        except Exception as e:
            print(f"Ошибка при загрузке .env через python-dotenv: {e}")
else:
    print(f"Файл .env не найден по пути: {env_path}")
    # Пробуем загрузить через python-dotenv как запасной вариант
    try:
        from dotenv import load_dotenv

        load_dotenv(override=True)
        print("Попытка загрузки .env через python-dotenv по умолчанию")
    except Exception as e:
        print(f"Ошибка при загрузке .env: {e}")

# Получаем список ID администраторов с логированием
admin_ids_str = os.environ.get("ADMIN_IDS", "")
print(f"Получено значение ADMIN_IDS из переменных окружения: '{admin_ids_str}'")

# Преобразуем строку с ID в список чисел
try:
    ADMIN_IDS = [int(id.strip()) for id in admin_ids_str.split(",") if id.strip()]
    print(f"Обработанный список ADMIN_IDS: {ADMIN_IDS}")
except Exception as e:
    print(f"Ошибка при обработке ADMIN_IDS: {e}")
    ADMIN_IDS = []

# URL вашего Mini App
MINI_APP_URL = os.environ.get("MINI_APP_URL", "https://example.com/mini_app")
print(f"Получено значение MINI_APP_URL: '{MINI_APP_URL}'")

# Состояния диалога создания рассылки
ENTER_MESSAGE, ENTER_SCHEDULE, SELECT_RECIPIENTS = range(3)

# Состояния пагинации
PAGE_SIZE = 5


async def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором бота"""
    print(f"Проверка admin для ID {user_id}. Список админов: {ADMIN_IDS}")
    return user_id in ADMIN_IDS


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    user_id = update.effective_user.id

    if await is_admin(user_id):
        # Создаем клавиатуру с кнопками основных команд
        keyboard = [
            [InlineKeyboardButton("📝 Создать рассылку", callback_data="start_create")],
            [InlineKeyboardButton("📋 Список рассылок", callback_data="show_list")],
            [InlineKeyboardButton("📊 Статистика", callback_data="show_stats")],
        ]

        markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "Добро пожаловать в бот для рассылки. " "Выберите действие из меню ниже:",
            parse_mode=None,
            reply_markup=markup,
        )
    else:
        await update.message.reply_text(
            f"ID админов: {ADMIN_IDS}\n"
            f"Ваш ID: {user_id}\n"
            "Этот бот предназначен для рассылки сообщений. "
            "Вы не являетесь администратором этого бота.",
            parse_mode=None,
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /help"""
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("У вас нет доступа к этой команде.")
        return

    await update.message.reply_text(
        "Команды бота:\n"
        "/create - создать новую рассылку\n"
        "/list - список рассылок\n"
        "/stats - общая статистика"
    )


# СОЗДАНИЕ РАССЫЛКИ - НОВЫЙ ИНТЕРАКТИВНЫЙ ФОРМАТ
async def start_create_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Начало создания новой рассылки через callback"""
    query = update.callback_query
    await query.answer()

    # Инициализируем данные новой рассылки
    context.user_data["temp_mailing"] = {
        "message_text": None,
        "schedule_type": None,
        "next_run_time": None,
        "is_recurring": False,
        "recurrence_interval": None,
    }

    # Сообщение с инструкцией и кнопкой отмены
    keyboard = [
        [InlineKeyboardButton("❌ Отменить создание", callback_data="cancel_create")]
    ]

    await query.edit_message_text(
        "Создание новой рассылки\n\n" "Шаг 1/3: Введите текст сообщения для рассылки:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    # Устанавливаем флаг ожидания ввода
    context.user_data["awaiting_input"] = "create_message"

    return ENTER_MESSAGE


async def create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало создания новой рассылки через команду"""
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("У вас нет доступа к этой команде.")
        return ConversationHandler.END

    # Инициализируем данные новой рассылки
    context.user_data["temp_mailing"] = {
        "message_text": None,
        "schedule_type": None,
        "next_run_time": None,
        "is_recurring": False,
        "recurrence_interval": None,
    }

    # Сообщение с инструкцией и кнопкой отмены
    keyboard = [
        [InlineKeyboardButton("❌ Отменить создание", callback_data="cancel_create")]
    ]

    await update.message.reply_text(
        "Создание новой рассылки\n\n" "Шаг 1/3: Введите текст сообщения для рассылки:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    # Устанавливаем флаг ожидания ввода
    context.user_data["awaiting_input"] = "create_message"

    return ENTER_MESSAGE


async def cancel_create_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Отмена создания рассылки"""
    query = update.callback_query
    await query.answer()

    # Очищаем данные
    if "temp_mailing" in context.user_data:
        del context.user_data["temp_mailing"]
    if "awaiting_input" in context.user_data:
        del context.user_data["awaiting_input"]

    # Возвращаемся в главное меню
    await main_menu_handler(update, context)

    return ConversationHandler.END


async def enter_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка ввода текста сообщения"""
    # Проверяем, что это ввод текста, а не команда или callback
    if update.callback_query:
        # Если это callback, значит нажата кнопка отмены
        # Это уже должно быть обработано через cancel_create_handler
        return ENTER_MESSAGE

    # Получаем текст сообщения
    message_text = update.message.text

    # Проверяем, не является ли сообщение командой
    if message_text.startswith("/"):
        # Это команда, прерываем процесс создания
        await update.message.reply_text(
            "Процесс создания рассылки прерван командой. "
            "Для создания новой рассылки используйте /create."
        )

        # Очищаем данные
        if "temp_mailing" in context.user_data:
            del context.user_data["temp_mailing"]
        if "awaiting_input" in context.user_data:
            del context.user_data["awaiting_input"]

        return ConversationHandler.END

    # Сохраняем введенный текст
    context.user_data["temp_mailing"]["message_text"] = message_text

    # Переходим к выбору расписания с кнопками
    keyboard = [
        [InlineKeyboardButton("📅 Отправить сейчас", callback_data="schedule_now")],
        [
            InlineKeyboardButton(
                "🕒 Запланировать отправку", callback_data="schedule_once"
            )
        ],
        [
            InlineKeyboardButton(
                "🔄 Отправлять ежедневно", callback_data="schedule_daily"
            )
        ],
        [
            InlineKeyboardButton(
                "📆 Отправлять в выбранные дни", callback_data="schedule_weekly"
            )
        ],
        [InlineKeyboardButton("❌ Отменить создание", callback_data="cancel_create")],
    ]

    await update.message.reply_text(
        f"Шаг 2/3: Выберите тип расписания рассылки:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    # Обновляем флаг ожидания выбора
    context.user_data["awaiting_input"] = "create_schedule"

    return ENTER_SCHEDULE


async def enter_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора расписания"""
    # Проверяем, что это ввод текста, а не команда или callback
    if update.callback_query:
        # Если это callback, значит нажата кнопка отмены
        # Это уже должно быть обработано через cancel_create_handler
        return ENTER_SCHEDULE

    # Получаем введенное расписание
    schedule_input = update.message.text

    # Проверяем, не является ли сообщение командой
    if schedule_input.startswith("/"):
        # Это команда, прерываем процесс создания
        await update.message.reply_text(
            "Процесс создания рассылки прерван командой. "
            "Для создания новой рассылки используйте /create."
        )

        # Очищаем данные
        if "temp_mailing" in context.user_data:
            del context.user_data["temp_mailing"]
        if "awaiting_input" in context.user_data:
            del context.user_data["awaiting_input"]

        return ConversationHandler.END

    try:
        parts = schedule_input.split(maxsplit=1)
        schedule_type = int(parts[0])

        now = datetime.now()
        temp_mailing = context.user_data["temp_mailing"]

        if schedule_type == 1:  # Отправить сейчас
            temp_mailing["next_run_time"] = now
            temp_mailing["is_recurring"] = False

        elif schedule_type == 2:  # Конкретное время
            try:
                time_str = parts[1]
                next_run = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
                temp_mailing["next_run_time"] = next_run
                temp_mailing["is_recurring"] = False
            except ValueError:
                await update.message.reply_text(
                    "Неверный формат времени. Используйте ГГГГ-ММ-ДД ЧЧ:ММ.\n"
                    "Пожалуйста, введите расписание снова:"
                )
                return ENTER_SCHEDULE

        elif schedule_type == 3:  # Ежедневно
            try:
                time_str = parts[1]
                hours, minutes = map(int, time_str.split(":"))
                next_run = datetime(now.year, now.month, now.day, hours, minutes)

                if next_run < now:
                    next_run = next_run + timedelta(days=1)

                temp_mailing["next_run_time"] = next_run
                temp_mailing["is_recurring"] = True
                temp_mailing["recurrence_interval"] = "daily"
            except ValueError:
                await update.message.reply_text(
                    "Неверный формат времени. Используйте ЧЧ:ММ.\n"
                    "Пожалуйста, введите расписание снова:"
                )
                return ENTER_SCHEDULE

        elif schedule_type == 4:  # Еженедельно
            try:
                time_str = parts[1]
                hours, minutes = map(int, time_str.split(":"))
                next_run = datetime(now.year, now.month, now.day, hours, minutes)

                if next_run < now:
                    next_run = next_run + timedelta(days=1)

                temp_mailing["next_run_time"] = next_run
                temp_mailing["is_recurring"] = True
                temp_mailing["recurrence_interval"] = "weekly"
            except ValueError:
                await update.message.reply_text(
                    "Неверный формат времени. Используйте ЧЧ:ММ.\n"
                    "Пожалуйста, введите расписание снова:"
                )
                return ENTER_SCHEDULE
        else:
            await update.message.reply_text(
                "Неверный тип расписания. Пожалуйста, выберите 1, 2, 3 или 4.\n"
                "Введите тип и время снова:"
            )
            return ENTER_SCHEDULE

    except Exception as e:
        logger.error(f"Ошибка при установке расписания: {e}")
        await update.message.reply_text(
            f"Произошла ошибка: {str(e)}\n" f"Пожалуйста, введите тип и время снова:"
        )
        return ENTER_SCHEDULE

    # Создаем кнопку для выбора получателей
    keyboard = [
        [
            InlineKeyboardButton(
                "Выбрать получателей",
                web_app={"url": f"{MINI_APP_URL}?mailing_id=temp"},
            )
        ],
        [InlineKeyboardButton("❌ Отменить создание", callback_data="cancel_create")],
    ]

    # Обновляем флаг ожидания ввода
    context.user_data["awaiting_input"] = "create_recipients"

    await update.message.reply_text(
        f"Шаг 3/3: Выберите получателей для рассылки:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    return SELECT_RECIPIENTS


async def finish_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Завершение создания рассылки после выбора получателей"""
    # Создаем рассылку в БД на основе собранных данных
    temp_mailing = context.user_data.get("temp_mailing", {})
    user_id = update.effective_user.id

    with db_session() as session:
        # Создаем новую рассылку
        mailing = Mailing(
            created_by=user_id,
            message_text=temp_mailing.get("message_text"),
            next_run_time=temp_mailing.get("next_run_time"),
            is_recurring=temp_mailing.get("is_recurring", False),
            recurrence_interval=temp_mailing.get("recurrence_interval"),
        )
        session.add(mailing)
        session.commit()
        mailing_id = mailing.mailing_id

        # Теперь добавляем получателей (если они уже были выбраны)
        selected_chats = temp_mailing.get("selected_chats", [])
        if selected_chats:
            for chat_id in selected_chats:
                chat = session.query(Chat).filter_by(chat_id=chat_id).first()
                if chat:
                    mailing.recipients.append(chat)
            session.commit()

    # Очищаем временные данные
    if "temp_mailing" in context.user_data:
        del context.user_data["temp_mailing"]
    if "awaiting_input" in context.user_data:
        del context.user_data["awaiting_input"]

    # Показываем меню рассылки
    # В данном случае у нас нет callback_query, поэтому создаем его вручную
    context.user_data["last_mailing_id"] = mailing_id

    # Сообщаем о успешном создании и показываем меню
    await update.message.reply_text(f"Рассылка успешно создана (ID: {mailing_id})!")

    # Создаем фиктивный update для вызова меню
    class FakeCallback:
        def __init__(self, data):
            self.data = data

        async def answer(self):
            pass

        async def edit_message_text(self, text, reply_markup=None):
            await update.message.reply_text(text, reply_markup=reply_markup)

    # Создаем фиктивный update.callback_query для show_mailing_menu
    update.callback_query = FakeCallback(f"mailing:{mailing_id}")
    await show_mailing_menu(update, context, mailing_id)
    update.callback_query = None

    return ConversationHandler.END


# СПИСОК РАССЫЛОК С ПАГИНАЦИЕЙ И КНОПКАМИ
async def list_mailings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Список рассылок с пагинацией и кнопками выбора"""
    if not await is_admin(update.effective_user.id):
        # Проверяем, откуда пришел запрос - из сообщения или callback_query
        if update.message:
            await update.message.reply_text("У вас нет доступа к этой команде.")
        elif update.callback_query:
            await update.callback_query.answer("У вас нет доступа к этой команде.")
        return

    # Устанавливаем начальную страницу
    context.user_data["page"] = 0

    # Показываем список рассылок
    # Если вызов из callback_query, предаем edit=True
    await show_mailings_page(update, context, edit=bool(update.callback_query))


async def show_mailings_page(
    update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False
) -> None:
    """Отображение страницы списка рассылок"""
    page = context.user_data.get("page", 0)

    with db_session() as session:
        # Получаем общее количество рассылок для пагинации
        total_mailings = session.query(Mailing).count()

        # Получаем рассылки для текущей страницы
        mailings = (
            session.query(Mailing)
            .order_by(Mailing.mailing_id.desc())
            .offset(page * PAGE_SIZE)
            .limit(PAGE_SIZE)
            .all()
        )

        if not mailings and total_mailings > 0:
            # Если страница пуста, но есть другие рассылки, возвращаемся на предыдущую страницу
            context.user_data["page"] = max(0, page - 1)
            await show_mailings_page(update, context, edit)
            return

        # Формируем текст списка
        if total_mailings == 0:
            list_text = "Рассылки не найдены."
            keyboard = [
                [
                    InlineKeyboardButton(
                        "📝 Создать рассылку", callback_data="start_create"
                    )
                ],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
            ]
        else:
            list_text = f"Список рассылок (страница {page + 1}/{(total_mailings + PAGE_SIZE - 1) // PAGE_SIZE}):\n\n"

            # Создаем кнопки для каждой рассылки
            keyboard = []
            for mailing in mailings:
                # Краткая информация о рассылке
                m_text = f"ID: {mailing.mailing_id} | "

                if mailing.next_run_time:
                    if mailing.is_recurring:
                        m_text += f"{mailing.recurrence_interval} в {mailing.next_run_time.strftime('%H:%M')}"
                    else:
                        m_text += f"{mailing.next_run_time.strftime('%Y-%m-%d %H:%M')}"
                else:
                    m_text += "Не запланирована"

                # Добавляем кнопку для этой рассылки
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            m_text, callback_data=f"mailing:{mailing.mailing_id}"
                        )
                    ]
                )

            # Добавляем кнопки пагинации
            pagination_buttons = []

            if page > 0:
                pagination_buttons.append(
                    InlineKeyboardButton("⬅️ Назад", callback_data="page:prev")
                )

            if (page + 1) * PAGE_SIZE < total_mailings:
                pagination_buttons.append(
                    InlineKeyboardButton("Вперед ➡️", callback_data="page:next")
                )

            if pagination_buttons:
                keyboard.append(pagination_buttons)

            # Добавляем кнопки для создания и возврата в главное меню
            keyboard.append(
                [
                    InlineKeyboardButton(
                        "📝 Создать рассылку", callback_data="start_create"
                    )
                ]
            )
            keyboard.append(
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            )

    # Отправляем или редактируем сообщение
    markup = InlineKeyboardMarkup(keyboard)

    # Проверяем, как вызвана функция - через callback или через команду
    if edit or update.callback_query:
        # Если есть callback_query, используем его для edit_message_text
        if hasattr(update, "callback_query") and update.callback_query:
            await update.callback_query.edit_message_text(
                text=list_text, reply_markup=markup
            )
        else:
            # Это непрямой вызов с edit=True, но без callback_query
            # В этом случае должен быть доступ к контексту предыдущего сообщения
            # Используем подход из других обработчиков
            pass
    else:
        # Обычный вызов через команду - отправляем новое сообщение
        await update.message.reply_text(text=list_text, reply_markup=markup)


async def show_mailing_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отображение меню рассылки с детальной информацией и кнопками"""
    try:
        if hasattr(update, "callback_query") and update.callback_query:
            query = update.callback_query
            await query.answer()
            data = query.data
            mailing_id = int(data.split(":")[1])
        elif update.message:
            data = update.message.text
            # Пытаемся извлечь ID из разных форматов сообщений
            try:
                mailing_id = int(data.split(":")[1])
            except (ValueError, IndexError):
                # Если ID не найден в типичном формате, пробуем достать из user_data
                mailing_id = context.user_data.get("last_mailing_id")
                if not mailing_id:
                    await update.message.reply_text(
                        "Не удалось определить ID рассылки."
                    )
                    return
        else:
            return

        with db_session() as session:
            mailing = session.query(Mailing).filter_by(mailing_id=mailing_id).first()

            if not mailing:
                if hasattr(update, "callback_query") and update.callback_query:
                    await update.callback_query.edit_message_text(
                        "Рассылка не найдена."
                    )
                else:
                    await update.message.reply_text("Рассылка не найдена.")
                return

            # Основная информация
            text = f"📨 <b>Меню рассылки ID {mailing_id}</b>\n\n"
            text += f"📝 <b>Текст:</b> {mailing.message_text[:100]}{'...' if len(mailing.message_text) > 100 else ''}\n"

            if mailing.next_run_time:
                schedule = mailing.next_run_time.strftime("%Y-%m-%d %H:%M")
                if mailing.is_recurring:
                    if mailing.recurrence_interval == "daily":
                        text += f"🕒 <b>Расписание:</b> Ежедневно в {mailing.next_run_time.strftime('%H:%M')}\n"
                    elif mailing.recurrence_interval == "weekly":
                        # Получаем дни недели
                        if mailing.recurrence_days:
                            days_list = mailing.recurrence_days.split(",")
                            weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
                            selected_days = [
                                weekdays[int(d)]
                                for d in days_list
                                if d.isdigit() and 0 <= int(d) < 7
                            ]
                            days_str = ", ".join(selected_days)
                            text += f"🕒 <b>Расписание:</b> Еженедельно ({days_str}) в {mailing.next_run_time.strftime('%H:%M')}\n"
                        else:
                            text += f"🕒 <b>Расписание:</b> Еженедельно в {mailing.next_run_time.strftime('%H:%M')}\n"
                else:
                    text += f"🕒 <b>Запланировано на:</b> {schedule}\n"
            else:
                text += "🕒 <b>Расписание:</b> не задано\n"

            # Статистика по получателям - используем правильные запросы ORM
            user_recipients = 0
            group_recipients = 0

            # Получаем все чаты, связанные с этой рассылкой
            for chat in mailing.recipients:
                if chat.type == "private":
                    user_recipients += 1
                elif chat.type in ["group", "supergroup", "channel"]:
                    group_recipients += 1

            total_recipients = user_recipients + group_recipients

            text += f"👥 <b>Получателей:</b> {total_recipients} (👤 {user_recipients} / 👥 {group_recipients})\n\n"

            # Статистика отправки
            logs = session.query(SendLog).filter_by(mailing_id=mailing_id).all()
            successful = sum(1 for log in logs if log.status == "success")
            failed = sum(1 for log in logs if log.status == "failed")

            text += "📊 <b>Статистика отправки:</b>\n"
            text += f"✅ Успешно: {successful}\n"
            text += f"❌ Ошибок: {failed}\n"

            if total_recipients > 0:
                rate = (successful / total_recipients) * 100
                text += f"📈 Успешность: {rate:.1f}%\n"

            # Кнопки управления
            keyboard = []

            if total_recipients > 0 and mailing.message_text:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            "📤 Отправить сейчас", callback_data=f"send:{mailing_id}"
                        )
                    ]
                )

            keyboard.append(
                [
                    InlineKeyboardButton(
                        "✏️ Ред. текст", callback_data=f"edit_message:{mailing_id}"
                    ),
                    InlineKeyboardButton(
                        "🕒 Ред. расписание",
                        callback_data=f"edit_schedule:{mailing_id}",
                    ),
                ]
            )
            keyboard.append(
                [
                    InlineKeyboardButton(
                        "👥 Получатели",
                        web_app={"url": f"{MINI_APP_URL}?mailing_id={mailing_id}"},
                    )
                ]
            )
            keyboard.append(
                [InlineKeyboardButton("⬅️ Назад к списку", callback_data="back_to_list")]
            )

            markup = InlineKeyboardMarkup(keyboard)

            # Отправка/редактирование сообщения
            if hasattr(update, "callback_query") and update.callback_query:
                await update.callback_query.edit_message_text(
                    text=text, reply_markup=markup, parse_mode="HTML"
                )
            else:
                await update.message.reply_text(
                    text=text, reply_markup=markup, parse_mode="HTML"
                )

    except Exception as e:
        logger.error(f"Ошибка в show_mailing_menu: {e}")
        try:
            if hasattr(update, "callback_query") and update.callback_query:
                await update.callback_query.edit_message_text(
                    f"Произошла ошибка при открытии меню рассылки: {str(e)}",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "⬅️ Назад к списку", callback_data="back_to_list"
                                )
                            ]
                        ]
                    ),
                )
            elif update.message:
                await update.message.reply_text(
                    f"Произошла ошибка при открытии меню рассылки: {str(e)}",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "⬅️ Назад к списку", callback_data="back_to_list"
                                )
                            ]
                        ]
                    ),
                )
        except Exception as inner_e:
            logger.error(f"Критическая ошибка в show_mailing_menu: {inner_e}")


async def handle_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка нажатий на кнопки пагинации"""
    query = update.callback_query
    await query.answer()

    action = query.data.split(":")[1]

    if action == "prev":
        context.user_data["page"] = max(0, context.user_data.get("page", 0) - 1)
    elif action == "next":
        context.user_data["page"] = context.user_data.get("page", 0) + 1

    await show_mailings_page(update, context, edit=True)


async def finish_create_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Обработчик нажатия кнопки завершения создания рассылки"""
    query = update.callback_query
    await query.answer()

    # Вызываем функцию завершения создания
    return await finish_create(update, context)


# Универсальная функция для прерывания команд и очистки состояния
async def handle_command_during_conversation(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Прерывает текущий диалог и открывает меню рассылки, если возможно"""
    mailing_id = None  # Инициализация переменной, чтобы избежать UnboundLocalError

    # Если был активный шаг, отменяем его
    if "awaiting_input" in context.user_data:
        awaiting_type = context.user_data.pop("awaiting_input", None)
        logger.info(f"Диалог '{awaiting_type}' прерван командой: {update.message.text}")

        # Удаляем временные данные
        context.user_data.pop("temp_mailing", None)

        await update.message.reply_text("Предыдущее действие прервано новой командой.")

    # Пытаемся извлечь mailing_id из callback_query, если он есть
    if hasattr(update, "callback_query") and update.callback_query:
        try:
            mailing_id = int(update.callback_query.data.split(":")[1])
            await update.callback_query.answer()
        except (ValueError, IndexError):
            await update.callback_query.answer("Ошибка при получении ID рассылки.")
            return

    # Если ID рассылки не удалось извлечь — ничего не делаем
    if mailing_id is None:
        return

    with db_session() as session:
        mailing = session.query(Mailing).filter_by(mailing_id=mailing_id).first()

        if not mailing:
            await update.message.reply_text("Рассылка не найдена.")
            return

        # Сохраняем ID для дальнейшего использования
        context.user_data["last_mailing_id"] = mailing_id

    # Открываем меню рассылки
    await show_mailing_menu(update, context)


# ОТПРАВКА РАССЫЛКИ
async def send_mailing_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправить рассылку сейчас"""
    query = update.callback_query
    await query.answer()

    try:
        mailing_id = int(query.data.split(":")[1])

        with db_session() as session:
            mailing = session.query(Mailing).filter_by(mailing_id=mailing_id).first()

            if not mailing:
                await query.edit_message_text("Ошибка: рассылка не найдена.")
                return

            if not mailing.message_text:
                await query.edit_message_text(
                    "Для рассылки не установлен текст сообщения.",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "⬅️ Назад к меню",
                                    callback_data=f"mailing:{mailing_id}",
                                )
                            ]
                        ]
                    ),
                )
                return

            recipients = [
                (chat.chat_id, chat.title or str(chat.chat_id))
                for chat in mailing.recipients
            ]

            if not recipients:
                await query.edit_message_text(
                    "Для рассылки не выбраны получатели.",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "⬅️ Назад к меню",
                                    callback_data=f"mailing:{mailing_id}",
                                )
                            ]
                        ]
                    ),
                )
                return

        # Отправляем сообщение о начале рассылки
        status_text = (
            f"Начинаю отправку рассылки ID {mailing_id}...\n"
            f"Всего получателей: {len(recipients)}\n"
            f"Отправлено: 0\n"
            f"Ошибок: 0\n"
            f"Прогресс: 0%"
        )

        status_msg = await query.edit_message_text(
            text=status_text,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔄 Обновить статус",
                            callback_data=f"refresh_status:{mailing_id}",
                        )
                    ]
                ]
            ),
        )

        # Запускаем отправку в фоновом режиме
        context.application.create_task(
            perform_mailing(context.bot, mailing_id, status_msg)
        )

    except Exception as e:
        logger.error(f"Ошибка при отправке рассылки: {e}")
        await query.edit_message_text(
            f"Произошла ошибка: {str(e)}",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Назад к списку", callback_data="back_to_list"
                        )
                    ]
                ]
            ),
        )


async def refresh_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обновить статус отправки рассылки"""
    query = update.callback_query
    await query.answer()

    try:
        mailing_id = int(query.data.split(":")[1])

        with db_session() as session:
            mailing = session.query(Mailing).filter_by(mailing_id=mailing_id).first()

            if not mailing:
                await query.edit_message_text("Ошибка: рассылка не найдена.")
                return

            # Получаем статистику отправки
            total_recipients = len(mailing.recipients)

            logs = session.query(SendLog).filter_by(mailing_id=mailing_id).all()
            successful = sum(1 for log in logs if log.status == "success")
            failed = sum(1 for log in logs if log.status == "failed")

            progress = (
                ((successful + failed) / total_recipients * 100)
                if total_recipients > 0
                else 0
            )

            status_text = (
                f"Отправка рассылки ID {mailing_id}...\n"
                f"Всего получателей: {total_recipients}\n"
                f"Отправлено: {successful}\n"
                f"Ошибок: {failed}\n"
                f"Прогресс: {progress:.1f}%"
            )

            # Определяем кнопки в зависимости от прогресса
            keyboard = []
            if successful + failed < total_recipients:
                # Рассылка еще не завершена
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            "🔄 Обновить статус",
                            callback_data=f"refresh_status:{mailing_id}",
                        )
                    ]
                )
            else:
                # Рассылка завершена
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            "⬅️ К меню рассылки", callback_data=f"mailing:{mailing_id}"
                        )
                    ]
                )

            await query.edit_message_text(
                text=status_text, reply_markup=InlineKeyboardMarkup(keyboard)
            )

    except Exception as e:
        logger.error(f"Ошибка при обновлении статуса: {e}")
        await query.edit_message_text(
            f"Произошла ошибка: {str(e)}",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Назад к списку", callback_data="back_to_list"
                        )
                    ]
                ]
            ),
        )


async def handle_webapp_data(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Обработка данных, отправленных из Mini App"""
    if not await is_admin(update.effective_user.id):
        return

    data = json.loads(update.effective_message.web_app_data.data)
    mailing_id = data.get("mailing_id")
    selected_chats = data.get("selected_chats", [])

    if not isinstance(selected_chats, list):
        await update.message.reply_text("Получены некорректные данные от Mini App.")
        return

    # Проверяем, идет ли создание новой рассылки или редактирование существующей
    if mailing_id == "temp":
        # Это создание новой рассылки - сохраняем выбранных получателей во временные данные
        if "temp_mailing" in context.user_data:
            context.user_data["temp_mailing"]["selected_chats"] = selected_chats

            # Показываем интерфейс выбора типов получателей
            keyboard = [
                [
                    InlineKeyboardButton(
                        "👤 Типы получателей", callback_data="select_recipient_types"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "✅ Завершить создание", callback_data="finish_create"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ Отменить создание", callback_data="cancel_create"
                    )
                ],
            ]

            await update.message.reply_text(
                f"Получатели для новой рассылки выбраны.\n"
                f"Выбрано {len(selected_chats)} получателей.\n\n"
                f"Вы можете указать, каким типам получателей отправлять рассылку "
                f"(по умолчанию отправляется всем), или завершить создание:",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

        else:
            await update.message.reply_text(
                "Ошибка: данные рассылки не найдены. Возможно, сессия создания истекла."
            )


async def show_recipients_types_selector(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Показать селектор типов получателей"""
    query = update.callback_query
    await query.answer()

    # Получаем текущие настройки или используем значения по умолчанию
    mailing_id = context.user_data.get("edit_mailing_id")

    if mailing_id:
        # Редактирование существующей рассылки
        with db_session() as session:
            mailing = session.query(Mailing).filter_by(mailing_id=mailing_id).first()
            if mailing:
                send_to_users = getattr(mailing, "send_to_users", True)
                send_to_groups = getattr(mailing, "send_to_groups", True)
            else:
                send_to_users = True
                send_to_groups = True
    else:
        # Новая рассылка
        temp_mailing = context.user_data.get("temp_mailing", {})
        send_to_users = temp_mailing.get("send_to_users", True)
        send_to_groups = temp_mailing.get("send_to_groups", True)

    # Создаем чекбоксы
    users_checkbox = "✅" if send_to_users else "☐"
    groups_checkbox = "✅" if send_to_groups else "☐"

    keyboard = [
        [
            InlineKeyboardButton(
                f"{users_checkbox} Отправлять пользователям",
                callback_data="toggle_users",
            )
        ],
        [
            InlineKeyboardButton(
                f"{groups_checkbox} Отправлять в группы и каналы",
                callback_data="toggle_groups",
            )
        ],
        [
            InlineKeyboardButton(
                "✅ Подтвердить", callback_data="recipients_types_confirmed"
            )
        ],
        [
            InlineKeyboardButton(
                "❌ Отмена",
                callback_data=(
                    "cancel_create" if not mailing_id else f"mailing:{mailing_id}"
                ),
            )
        ],
    ]

    await query.edit_message_text(
        "Выберите типы получателей для рассылки:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def process_schedule_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Обработка выбора типа расписания"""
    query = update.callback_query
    await query.answer()

    schedule_type = query.data
    temp_mailing = context.user_data["temp_mailing"]
    now = datetime.now()

    if schedule_type == "schedule_now":
        # Отправить сейчас
        temp_mailing["next_run_time"] = now
        temp_mailing["is_recurring"] = False
        temp_mailing["recurrence_interval"] = None

        # Переходим к выбору получателей
        return await show_recipients_types_selector(update, context)

    elif schedule_type == "schedule_once":
        # Запланировать отправку - показываем календарь
        # Создаем клавиатуру с календарем для выбора даты
        await show_date_picker(query, context)
        return ENTER_SCHEDULE

    elif schedule_type == "schedule_daily":
        # Отправлять ежедневно - выбор времени
        temp_mailing["is_recurring"] = True
        temp_mailing["recurrence_interval"] = "daily"

        # Показываем выбор времени
        await show_time_picker(query, context)
        return ENTER_SCHEDULE

    elif schedule_type == "schedule_weekly":
        # Отправлять в выбранные дни - выбор дней недели
        temp_mailing["is_recurring"] = True
        temp_mailing["recurrence_interval"] = "weekly"

        # Показываем выбор дней недели
        await show_weekday_picker(query, context)
        return ENTER_SCHEDULE

    else:
        # Неизвестный тип расписания
        await query.edit_message_text(
            "Неизвестный тип расписания. Пожалуйста, выберите снова.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "❌ Отменить создание", callback_data="cancel_create"
                        )
                    ]
                ]
            ),
        )
        return ENTER_SCHEDULE


async def show_date_picker(query, context):
    """Показать календарь для выбора даты"""
    # Текущий месяц и год
    now = datetime.now()
    year = now.year
    month = now.month

    # Сохраняем текущий выбранный месяц и год
    context.user_data["calendar"] = {"year": year, "month": month}

    # Генерируем календарь
    calendar_keyboard = generate_calendar_keyboard(year, month)

    await query.edit_message_text(
        f"Выберите дату отправки (текущий месяц: {month}/{year}):",
        reply_markup=InlineKeyboardMarkup(calendar_keyboard),
    )


def generate_calendar_keyboard(year, month):
    """Генерирует клавиатуру календаря"""
    import calendar

    # Создаем календарь
    cal = calendar.monthcalendar(year, month)

    # Создаем клавиатуру
    keyboard = []

    # Добавляем заголовок с навигацией
    keyboard.append(
        [
            InlineKeyboardButton("◀️", callback_data=f"cal_prev:{month}:{year}"),
            InlineKeyboardButton(f"{month}/{year}", callback_data="ignore"),
            InlineKeyboardButton("▶️", callback_data=f"cal_next:{month}:{year}"),
        ]
    )

    # Добавляем дни недели
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    keyboard.append([InlineKeyboardButton(day, callback_data="ignore") for day in days])

    # Добавляем дни месяца
    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="ignore"))
            else:
                row.append(
                    InlineKeyboardButton(
                        str(day), callback_data=f"cal_day:{day}:{month}:{year}"
                    )
                )
        keyboard.append(row)

    # Добавляем кнопку отмены
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")])

    return keyboard


async def show_time_picker(query, context):
    """Показать выбор времени"""
    # Генерируем клавиатуру для выбора часов
    keyboard = []
    for hour in range(0, 24, 3):
        row = []
        for h in range(hour, min(hour + 3, 24)):
            row.append(
                InlineKeyboardButton(f"{h:02d}:00", callback_data=f"time:{h:02d}:00")
            )
        keyboard.append(row)

    # Добавляем другие популярные варианты времени
    keyboard.append(
        [
            InlineKeyboardButton("09:30", callback_data="time:09:30"),
            InlineKeyboardButton("12:30", callback_data="time:12:30"),
            InlineKeyboardButton("18:30", callback_data="time:18:30"),
        ]
    )

    # Добавляем кнопку для ручного ввода
    keyboard.append(
        [InlineKeyboardButton("⌨️ Ввести вручную", callback_data="time_manual")]
    )

    # Добавляем кнопку отмены
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")])

    await query.edit_message_text(
        "Выберите время отправки:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_weekday_picker(query, context):
    """Показать выбор дней недели"""
    # Инициализируем выбранные дни, если еще не выбраны
    if "selected_days" not in context.user_data:
        context.user_data["selected_days"] = []

    # Дни недели на русском
    weekdays = [
        "Понедельник",
        "Вторник",
        "Среда",
        "Четверг",
        "Пятница",
        "Суббота",
        "Воскресенье",
    ]

    # Создаем клавиатуру с чекбоксами
    keyboard = []
    for i, day in enumerate(weekdays):
        # Определяем, выбран ли день
        is_selected = i in context.user_data["selected_days"]
        checkbox = "✅" if is_selected else "☐"

        keyboard.append(
            [InlineKeyboardButton(f"{checkbox} {day}", callback_data=f"toggle_day:{i}")]
        )

    # Добавляем кнопки подтверждения и отмены
    keyboard.append(
        [
            InlineKeyboardButton("✅ Подтвердить", callback_data="days_confirmed"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_create"),
        ]
    )

    await query.edit_message_text(
        "Выберите дни недели для отправки:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_weekday_toggle(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Обработка выбора/отмены выбора дня недели"""
    query = update.callback_query
    await query.answer()

    # Получаем индекс дня недели
    day_index = int(query.data.split(":")[1])

    # Переключаем состояние дня
    if "selected_days" not in context.user_data:
        context.user_data["selected_days"] = []

    if day_index in context.user_data["selected_days"]:
        context.user_data["selected_days"].remove(day_index)
    else:
        context.user_data["selected_days"].append(day_index)

    # Обновляем интерфейс
    await show_weekday_picker(query, context)
    return ENTER_SCHEDULE


def get_active_chats(session, send_to_users=True, send_to_groups=True):
    """Получить список всех активных чатов с фильтрацией по типу"""
    query = session.query(Chat).filter(Chat.status == "active")

    if send_to_users and not send_to_groups:
        # Только пользователи
        query = query.filter(Chat.type == "private")
    elif send_to_groups and not send_to_users:
        # Только группы и каналы
        query = query.filter(Chat.type.in_(["group", "supergroup", "channel"]))
    # Если оба True - получаем все чаты
    # Если оба False - пустой список
    elif not send_to_users and not send_to_groups:
        return []

    return query.all()


async def perform_mailing(bot, mailing_id, status_msg=None):
    """Выполнение рассылки"""
    sent = 0
    failed = 0

    with db_session() as session:
        mailing = session.query(Mailing).filter_by(mailing_id=mailing_id).first()

        if not mailing:
            logger.error(f"Рассылка с ID {mailing_id} не найдена.")
            return

        message_text = mailing.message_text

        # Фильтруем получателей в зависимости от настроек рассылки
        send_to_users = getattr(mailing, "send_to_users", True)
        send_to_groups = getattr(mailing, "send_to_groups", True)

        # Получаем только активные чаты нужных типов
        all_active_chats = get_active_chats(session, send_to_users, send_to_groups)

        # Фильтруем только те чаты, которые выбраны для этой рассылки
        recipients = []
        for chat in all_active_chats:
            if chat in mailing.recipients:
                recipients.append((chat.chat_id, chat.title or str(chat.chat_id)))

        total = len(recipients)


# РЕДАКТИРОВАНИЕ РАССЫЛКИ
async def edit_message_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Начать редактирование текста сообщения"""
    query = update.callback_query
    await query.answer()

    try:
        mailing_id = int(query.data.split(":")[1])

        # Сохраняем ID рассылки для дальнейшего обновления
        context.user_data["edit_mailing_id"] = mailing_id

        with db_session() as session:
            mailing = session.query(Mailing).filter_by(mailing_id=mailing_id).first()
            current_text = (
                mailing.message_text if mailing and mailing.message_text else ""
            )

        await query.edit_message_text(
            f"Текущий текст сообщения:\n\n{current_text}\n\n"
            f"Отправьте новый текст сообщения для рассылки ID {mailing_id}:",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "❌ Отмена", callback_data=f"mailing:{mailing_id}"
                        )
                    ]
                ]
            ),
        )

        # Устанавливаем ожидание ввода текста
        context.user_data["awaiting_input"] = "message_text"

    except Exception as e:
        logger.error(f"Ошибка при начале редактирования сообщения: {e}")
        await query.edit_message_text(
            f"Произошла ошибка: {str(e)}",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Назад к меню", callback_data=f"mailing:{mailing_id}"
                        )
                    ]
                ]
            ),
        )


async def edit_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Начать редактирование расписания"""
    query = update.callback_query
    await query.answer()

    try:
        mailing_id = int(query.data.split(":")[1])

        # Сохраняем ID рассылки для дальнейшего обновления
        context.user_data["edit_mailing_id"] = mailing_id

        # Показываем интерфейс выбора расписания
        await query.edit_message_text(
            f"Выберите новое расписание для рассылки ID {mailing_id}:\n\n"
            f"1. Отправить сейчас\n"
            f"2. Отправить в определенное время (формат: ГГГГ-ММ-ДД ЧЧ:ММ)\n"
            f"3. Отправлять ежедневно (формат: ЧЧ:ММ)\n"
            f"4. Отправлять еженедельно (формат: ЧЧ:ММ)\n\n"
            f"Введите тип и время (например, '2 2025-05-15 14:30' или '3 10:00'):",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "❌ Отмена", callback_data=f"mailing:{mailing_id}"
                        )
                    ]
                ]
            ),
        )

        # Устанавливаем ожидание ввода расписания
        context.user_data["awaiting_input"] = "schedule"

    except Exception as e:
        logger.error(f"Ошибка при начале редактирования расписания: {e}")
        await query.edit_message_text(
            f"Произошла ошибка: {str(e)}",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Назад к меню", callback_data=f"mailing:{mailing_id}"
                        )
                    ]
                ]
            ),
        )


async def handle_awaiting_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Обработка ожидаемого ввода для редактирования"""
    input_type = context.user_data.get("awaiting_input")
    mailing_id = context.user_data.get("edit_mailing_id")

    if not input_type or not mailing_id:
        return

    # Удаляем флаг ожидания после обработки
    del context.user_data["awaiting_input"]
    del context.user_data["edit_mailing_id"]

    # Обработка в зависимости от типа ввода
    if input_type == "message_text":
        # Обрабатываем новый текст сообщения
        new_text = update.message.text

        with db_session() as session:
            mailing = session.query(Mailing).filter_by(mailing_id=mailing_id).first()

            if mailing:
                mailing.message_text = new_text
                session.commit()

        await update.message.reply_text(
            f"Текст сообщения для рассылки ID {mailing_id} обновлен."
        )

        # Открываем меню рассылки
        await show_mailing_menu(update, context, mailing_id)

    elif input_type == "schedule":
        # Обрабатываем новое расписание
        schedule_input = update.message.text

        try:
            parts = schedule_input.split(maxsplit=1)
            schedule_type = int(parts[0])

            with db_session() as session:
                mailing = (
                    session.query(Mailing).filter_by(mailing_id=mailing_id).first()
                )

                if not mailing:
                    await update.message.reply_text("Ошибка: рассылка не найдена.")
                    return

                if schedule_type == 1:  # Отправить сейчас
                    mailing.next_run_time = datetime.now()
                    mailing.is_recurring = False

                elif schedule_type == 2:  # Конкретное время
                    try:
                        time_str = parts[1]
                        next_run = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
                        mailing.next_run_time = next_run
                        mailing.is_recurring = False
                    except ValueError:
                        await update.message.reply_text(
                            "Неверный формат времени. Используйте ГГГГ-ММ-ДД ЧЧ:ММ."
                        )
                        return

                elif schedule_type == 3:  # Ежедневно
                    try:
                        time_str = parts[1]
                        hours, minutes = map(int, time_str.split(":"))
                        now = datetime.now()
                        next_run = datetime(
                            now.year, now.month, now.day, hours, minutes
                        )

                        if next_run < now:
                            next_run = next_run + timedelta(days=1)

                        mailing.next_run_time = next_run
                        mailing.is_recurring = True
                        mailing.recurrence_interval = "daily"
                    except ValueError:
                        await update.message.reply_text(
                            "Неверный формат времени. Используйте ЧЧ:ММ."
                        )
                        return

                elif schedule_type == 4:  # Еженедельно
                    try:
                        time_str = parts[1]
                        hours, minutes = map(int, time_str.split(":"))
                        now = datetime.now()
                        next_run = datetime(
                            now.year, now.month, now.day, hours, minutes
                        )

                        if next_run < now:
                            next_run = next_run + timedelta(days=1)

                        mailing.next_run_time = next_run
                        mailing.is_recurring = True
                        mailing.recurrence_interval = "weekly"
                    except ValueError:
                        await update.message.reply_text(
                            "Неверный формат времени. Используйте ЧЧ:ММ."
                        )
                        return
                else:
                    await update.message.reply_text(
                        "Неверный тип расписания. Пожалуйста, выберите 1, 2, 3 или 4."
                    )
                    return

                session.commit()

            await update.message.reply_text(
                f"Расписание для рассылки ID {mailing_id} обновлено."
            )

            # Открываем меню рассылки
            await show_mailing_menu(update, context, mailing_id)

        except Exception as e:
            logger.error(f"Ошибка при обновлении расписания: {e}")
            await update.message.reply_text(f"Произошла ошибка: {str(e)}")


# ОБРАБОТЧИКИ КНОПОК ОСНОВНОГО МЕНЮ
async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать главное меню"""
    query = update.callback_query
    await query.answer()

    # Создаем клавиатуру с кнопками основных команд
    keyboard = [
        [InlineKeyboardButton("📝 Создать рассылку", callback_data="start_create")],
        [InlineKeyboardButton("📋 Список рассылок", callback_data="open_list")],
        [InlineKeyboardButton("📊 Статистика", callback_data="show_stats")],
    ]

    markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "Выберите действие из меню ниже:", reply_markup=markup
    )


async def show_stats_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Показать статистику через кнопку в меню"""
    query = update.callback_query
    await query.answer()

    # Удаляем данные предыдущего состояния
    context.user_data.clear()

    try:
        with db_session() as session:
            # Общее количество рассылок
            total_mailings = session.query(Mailing).count()

            # Количество отправленных сообщений
            sent_messages = session.query(SendLog).count()

            # Количество успешных отправок
            try:
                successful = session.query(SendLog).filter_by(status="success").count()
                failed = session.query(SendLog).filter_by(status="failed").count()
            except Exception as e:
                logger.error(f"Ошибка при подсчете логов: {e}")
                successful = 0
                failed = 0

            # Получаем статистику по типам чатов из новой функции
            from database import get_statistics_by_chat_type

            chat_stats = get_statistics_by_chat_type()

        stats_text = "📊 Общая статистика рассылок:\n\n"
        stats_text += f"📨 Всего рассылок: {total_mailings}\n"
        stats_text += f"📤 Отправлено сообщений: {sent_messages}\n"

        if sent_messages > 0:
            success_rate = successful / sent_messages * 100
            stats_text += f"✅ Успешно доставлено: {successful} ({success_rate:.1f}%)\n"
            stats_text += f"❌ Ошибок доставки: {failed}\n\n"

        stats_text += "👥 Статистика по чатам:\n"
        stats_text += f"• Всего чатов: {chat_stats['total']['all']}\n"
        stats_text += f"  ✓ Активных: {chat_stats['total']['active']}\n"
        stats_text += f"  ✗ Заблокированных: {chat_stats['total']['blocked']}\n\n"

        stats_text += "👤 Пользователи:\n"
        stats_text += f"• Всего: {chat_stats['users']['all']}\n"
        stats_text += f"  ✓ Активных: {chat_stats['users']['active']}\n"
        stats_text += f"  ✗ Заблокированных: {chat_stats['users']['blocked']}\n\n"

        stats_text += "👥 Группы и каналы:\n"
        stats_text += f"• Всего: {chat_stats['groups']['all']}\n"
        stats_text += f"  ✓ Активных: {chat_stats['groups']['active']}\n"
        stats_text += f"  ✗ Заблокированных: {chat_stats['groups']['blocked']}\n"

        # Кнопка возврата в главное меню
        keyboard = [
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(stats_text, reply_markup=markup)

    except Exception as e:
        logger.error(f"Ошибка при получении статистики: {e}")

        # В случае ошибки все равно показываем кнопку возврата
        keyboard = [
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"Произошла ошибка при получении статистики: {str(e)}", reply_markup=markup
        )


async def show_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Открыть список рассылок через кнопку в меню"""
    # Просто переадресуем на обработчик списка
    await list_mailings(update, context)


# ОБРАБОТКА ДАННЫХ ИЗ MINI APP
async def handle_webapp_data(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Обработка данных, отправленных из Mini App"""
    if not await is_admin(update.effective_user.id):
        return

    try:
        data = json.loads(update.effective_message.web_app_data.data)
        mailing_id = data.get("mailing_id")
        selected_chats = data.get("selected_chats", [])

        if not isinstance(selected_chats, list):
            await update.message.reply_text("Получены некорректные данные от Mini App.")
            return

        # Проверяем, идет ли создание новой рассылки или редактирование существующей
        if mailing_id == "temp":
            # Это создание новой рассылки - сохраняем выбранных получателей во временные данные
            if "temp_mailing" in context.user_data:
                context.user_data["temp_mailing"]["selected_chats"] = selected_chats

                await update.message.reply_text(
                    f"Получатели для новой рассылки выбраны.\n"
                    f"Выбрано {len(selected_chats)} получателей.\n\n"
                    f"Нажмите на кнопку ниже, чтобы завершить создание рассылки:"
                )

                # Создаем кнопку для завершения создания
                keyboard = [
                    [
                        InlineKeyboardButton(
                            "✅ Завершить создание", callback_data="finish_create"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "❌ Отменить создание", callback_data="cancel_create"
                        )
                    ],
                ]

                await update.message.reply_text(
                    "Выберите действие:", reply_markup=InlineKeyboardMarkup(keyboard)
                )

                # Здесь не вызываем finish_create, ждем нажатия на кнопку

            else:
                await update.message.reply_text(
                    "Ошибка: данные рассылки не найдены. Возможно, сессия создания истекла."
                )

        else:
            # Это редактирование существующей рассылки
            try:
                mailing_id = int(mailing_id)

                with db_session() as session:
                    # Находим рассылку
                    mailing = (
                        session.query(Mailing).filter_by(mailing_id=mailing_id).first()
                    )

                    if not mailing:
                        await update.message.reply_text(
                            f"Рассылка с ID {mailing_id} не найдена."
                        )
                        return

                    # Очищаем текущий список получателей
                    mailing.recipients = []

                    # Добавляем новых получателей
                    for chat_id in selected_chats:
                        chat = session.query(Chat).filter_by(chat_id=chat_id).first()
                        if chat:
                            mailing.recipients.append(chat)

                    session.commit()
                    recipient_count = len(mailing.recipients)

                await update.message.reply_text(
                    f"Получатели для рассылки ID {mailing_id} обновлены.\n"
                    f"Выбрано {recipient_count} получателей."
                )

                # После обновления получателей показываем меню рассылки
                await show_mailing_menu(update, context, mailing_id)

            except ValueError:
                await update.message.reply_text("Неверный ID рассылки.")
                return

    except json.JSONDecodeError:
        await update.message.reply_text("Ошибка при обработке данных от Mini App.")
    except Exception as e:
        logger.error(f"Ошибка при обработке данных от Mini App: {e}")
        await update.message.reply_text(f"Произошла ошибка: {str(e)}")


# ОБСЛУЖИВАНИЕ И ПРОВЕРКА РАССЫЛОК
async def post_init(application: Application) -> None:
    """Действия после инициализации бота"""

    # Вместо JobQueue используем asyncio для периодических задач
    async def periodic_check():
        while True:
            try:
                await check_mailings(application)
            except Exception as e:
                logger.error(f"Ошибка проверки рассылок: {e}")
            await asyncio.sleep(60)  # проверка каждые 60 секунд

    # Запускаем задачу асинхронно
    asyncio.create_task(periodic_check())

    logger.info("Бот запущен и готов к работе.")


async def check_mailings(application: Application) -> None:
    """Проверка и запуск запланированных рассылок"""
    now = datetime.now()

    with db_session() as session:
        # Находим рассылки, которые должны быть отправлены
        mailings = (
            session.query(Mailing)
            .filter(Mailing.next_run_time <= now, Mailing.next_run_time != None)
            .all()
        )

        for mailing in mailings:
            logger.info(f"Запуск запланированной рассылки ID {mailing.mailing_id}")
            # Запускаем отправку рассылки
            await perform_mailing(application.bot, mailing.mailing_id)


async def chat_join_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка добавления бота в чат"""
    chat = update.effective_chat

    if not chat:
        return

    # Проверяем, что добавленный участник - это наш бот
    if context.bot.id in [member.user.id for member in update.message.new_chat_members]:
        with db_session() as session:
            # Проверяем, существует ли уже запись о чате
            existing_chat = session.query(Chat).filter_by(chat_id=chat.id).first()

            if existing_chat:
                # Обновляем статус и время последней активности
                existing_chat.status = "active"
                existing_chat.last_active = datetime.now()
            else:
                # Создаем новую запись о чате
                new_chat = Chat(
                    chat_id=chat.id,
                    type=chat.type,
                    title=chat.title or str(chat.id),
                    status="active",
                )
                session.add(new_chat)

            session.commit()

        logger.info(f"Бот добавлен в чат: {chat.id} ({chat.title})")


async def chat_leave_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Обработка удаления бота из чата"""
    chat = update.effective_chat

    if not chat:
        return

    # Проверяем, что удаленный участник - это наш бот
    if (
        update.message.left_chat_member
        and update.message.left_chat_member.id == context.bot.id
    ):
        with db_session() as session:
            # Находим запись о чате
            chat_record = session.query(Chat).filter_by(chat_id=chat.id).first()

            if chat_record:
                # Помечаем чат как удаленный
                chat_record.status = "left"
                chat_record.last_error = "Бот был удален из чата"
                session.commit()

        logger.info(f"Бот удален из чата: {chat.id} ({chat.title})")


def main() -> None:
    """Основная функция для запуска бота"""
    # Получаем токен бота из переменных окружения
    token = os.environ.get("TELEGRAM_BOT_TOKEN")

    if not token:
        logger.error(
            "Токен бота не найден. Установите переменную окружения TELEGRAM_BOT_TOKEN."
        )
        return

    # Создаем таблицы в базе данных (если они еще не созданы)
    from database import create_tables

    create_tables()

    # Устанавливаем параметры по умолчанию для форматирования сообщений
    defaults = Defaults(
        parse_mode=None
    )  # Устанавливаем по умолчанию форматирование None

    # Создаем объект Application с параметрами по умолчанию
    application = (
        Application.builder()
        .token(token)
        .defaults(defaults)
        .post_init(post_init)
        .build()
    )

    # Регистрируем обработчик диалога создания рассылки
    create_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("create", create),
            CallbackQueryHandler(start_create_handler, pattern="^start_create$"),
        ],
        states={
            ENTER_MESSAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_message),
                CallbackQueryHandler(cancel_create_handler, pattern="^cancel_create$"),
            ],
            ENTER_SCHEDULE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_schedule),
                CallbackQueryHandler(cancel_create_handler, pattern="^cancel_create$"),
            ],
            SELECT_RECIPIENTS: [
                CallbackQueryHandler(finish_create_handler, pattern="^finish_create$"),
                CallbackQueryHandler(cancel_create_handler, pattern="^cancel_create$"),
                MessageHandler(
                    filters.ALL & ~filters.COMMAND, lambda u, c: SELECT_RECIPIENTS
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        per_user=True,
        name="create_mailing_conversation",
    )
    application.add_handler(create_conv_handler)

    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("list", list_mailings))

    # Регистрируем обработчики взаимодействия с интерфейсом
    application.add_handler(
        CallbackQueryHandler(main_menu_handler, pattern="^main_menu$")
    )
    application.add_handler(
        CallbackQueryHandler(show_list_handler, pattern="^open_list$")
    )
    application.add_handler(
        CallbackQueryHandler(show_stats_handler, pattern="^show_stats$")
    )
    application.add_handler(CallbackQueryHandler(handle_pagination, pattern="^page:"))
    application.add_handler(
        CallbackQueryHandler(show_mailing_menu, pattern="^mailing:")
    )
    application.add_handler(CallbackQueryHandler(send_mailing_now, pattern="^send:"))
    application.add_handler(
        CallbackQueryHandler(refresh_status, pattern="^refresh_status:")
    )
    application.add_handler(
        CallbackQueryHandler(edit_message_text, pattern="^edit_message:")
    )
    application.add_handler(
        CallbackQueryHandler(edit_schedule, pattern="^edit_schedule:")
    )
    application.add_handler(
        CallbackQueryHandler(list_mailings, pattern="^back_to_list$")
    )

    # Регистрируем обработчик для данных от Mini App
    application.add_handler(
        MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp_data)
    )

    # Регистрируем обработчик текстовых сообщений для ожидаемого ввода
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.UpdateType.MESSAGE,
            handle_awaiting_input,
        )
    )

    # Регистрируем обработчик команд для прерывания ожидания ввода
    # Важно: этот обработчик должен быть после ConversationHandler и перед обычными CommandHandler
    command_interrupt_handler = MessageHandler(
        filters.COMMAND, handle_command_during_conversation
    )
    application.add_handler(command_interrupt_handler, group=1)

    # Регистрируем обработчики для добавления/удаления из чатов
    application.add_handler(
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, chat_join_handler)
    )
    application.add_handler(
        MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, chat_leave_handler)
    )

    # Запускаем бота
    application.run_polling()


if __name__ == "__main__":
    main()

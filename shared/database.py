from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    BigInteger,
    String,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    Table,
)

# Заменяем устаревший импорт на новый
from sqlalchemy.orm import relationship, sessionmaker, declarative_base
from sqlalchemy.sql import func, text
import os
from contextlib import contextmanager
from datetime import datetime

# Создаем базовый класс моделей
Base = declarative_base()

# Таблица связи многие-ко-многим между рассылками и получателями
mailing_recipients = Table(
    "mailing_recipients",
    Base.metadata,
    Column("mailing_id", Integer, ForeignKey("mailings.mailing_id"), primary_key=True),
    Column("chat_id", BigInteger, ForeignKey("chats.chat_id"), primary_key=True),
)


class Chat(Base):
    __tablename__ = "chats"

    chat_id = Column(BigInteger, primary_key=True)
    type = Column(String(20))  # 'user', 'group', 'supergroup', 'channel'
    title = Column(String(255))
    last_active = Column(DateTime, default=datetime.now)
    status = Column(String(20), default="active")  # 'active', 'blocked', 'left'
    last_error = Column(Text, nullable=True)

    # Отношение к рассылкам через таблицу связи
    mailings = relationship(
        "Mailing", secondary=mailing_recipients, back_populates="recipients"
    )
    # Отношение к логам отправки
    send_logs = relationship("SendLog", back_populates="chat")


class Mailing(Base):
    __tablename__ = "mailings"

    mailing_id = Column(Integer, primary_key=True)
    message_text = Column(Text, nullable=True)
    next_run_time = Column(DateTime, nullable=True)
    is_recurring = Column(Boolean, default=False)
    recurrence_interval = Column(String(100), nullable=True)
    recurrence_days = Column(String(100), nullable=True)  # Новое поле для дней недели
    created_at = Column(DateTime, default=datetime.now)
    created_by = Column(BigInteger)
    send_to_users = Column(Boolean, default=True)  # Отправлять пользователям
    send_to_groups = Column(Boolean, default=True)  # Отправлять в группы

    # Отношение к получателям через таблицу связи
    recipients = relationship(
        "Chat", secondary=mailing_recipients, back_populates="mailings"
    )
    # Отношение к логам отправки
    send_logs = relationship("SendLog", back_populates="mailing")


class SendLog(Base):
    __tablename__ = "send_logs"

    log_id = Column(Integer, primary_key=True)
    mailing_id = Column(Integer, ForeignKey("mailings.mailing_id"))
    chat_id = Column(BigInteger, ForeignKey("chats.chat_id"))
    send_time = Column(DateTime, default=datetime.now)
    status = Column(String(20))  # 'success', 'failed'
    error_message = Column(Text, nullable=True)

    # Отношения
    mailing = relationship("Mailing", back_populates="send_logs")
    chat = relationship("Chat", back_populates="send_logs")


# Создание подключения к базе данных
def get_database_url():
    """Получение URL базы данных из переменных окружения"""
    user = os.environ.get("DB_USER")
    password = os.environ.get("DB_PASSWORD")
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    db_name = os.environ.get("DB_NAME", "telegram_broadcast")

    return f"postgresql://{user}:{password}@{host}:{port}/{db_name}"


def get_statistics_by_chat_type():
    """Получение статистики по типам чатов (пользователи/группы)"""
    with db_session() as session:
        # Статистика по всем чатам
        total_chats = session.query(Chat).count()
        active_chats = session.query(Chat).filter_by(status="active").count()
        blocked_chats = session.query(Chat).filter_by(status="blocked").count()

        # Статистика по пользователям
        users = session.query(Chat).filter(Chat.type == "private").count()
        active_users = (
            session.query(Chat)
            .filter(Chat.type == "private", Chat.status == "active")
            .count()
        )
        blocked_users = (
            session.query(Chat)
            .filter(Chat.type == "private", Chat.status == "blocked")
            .count()
        )

        # Статистика по группам (включая супергруппы)
        groups = (
            session.query(Chat)
            .filter(Chat.type.in_(["group", "supergroup", "channel"]))
            .count()
        )
        active_groups = (
            session.query(Chat)
            .filter(
                Chat.type.in_(["group", "supergroup", "channel"]),
                Chat.status == "active",
            )
            .count()
        )
        blocked_groups = (
            session.query(Chat)
            .filter(
                Chat.type.in_(["group", "supergroup", "channel"]),
                Chat.status == "blocked",
            )
            .count()
        )

        return {
            "total": {
                "all": total_chats,
                "active": active_chats,
                "blocked": blocked_chats,
            },
            "users": {"all": users, "active": active_users, "blocked": blocked_users},
            "groups": {
                "all": groups,
                "active": active_groups,
                "blocked": blocked_groups,
            },
        }


# Создание движка и сессии
engine = create_engine(get_database_url())
SessionLocal = sessionmaker(bind=engine)


@contextmanager
def db_session():
    """Контекстный менеджер для работы с сессией базы данных"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


# Функция для создания всех таблиц
def create_tables():
    Base.metadata.create_all(engine)
    # Вызываем проверку структуры БД после создания таблиц
    verify_database_structure()


def verify_database_structure():
    """Проверяет и обновляет структуру базы данных при необходимости"""
    from sqlalchemy import inspect
    from sqlalchemy.exc import SQLAlchemyError

    inspector = inspect(engine)

    # Проверяем таблицу send_logs
    if "send_logs" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("send_logs")]

        # Проверяем наличие колонки mailing_id
        if "mailing_id" not in columns:
            print(
                "Обнаружена проблема: отсутствует колонка mailing_id в таблице send_logs"
            )

            try:
                # Создаем временную таблицу с правильной структурой
                print("Создание временной таблицы...")
                with engine.connect() as conn:
                    # Создаем временную таблицу
                    conn.execute(
                        text(
                            """
                        CREATE TABLE send_logs_temp (
                            log_id SERIAL PRIMARY KEY,
                            mailing_id INTEGER REFERENCES mailings(mailing_id),
                            chat_id BIGINT REFERENCES chats(chat_id),
                            send_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                            status VARCHAR(20),
                            error_message TEXT
                        )
                    """
                        )
                    )

                    # Переносим существующие данные
                    print("Перенос данных...")
                    conn.execute(
                        text(
                            """
                        INSERT INTO send_logs_temp (log_id, chat_id, send_time, status, error_message)
                        SELECT log_id, chat_id, send_time, status, error_message FROM send_logs
                    """
                        )
                    )

                    # Удаляем старую таблицу и переименовываем новую
                    print("Обновление структуры таблицы...")
                    conn.execute(text("DROP TABLE send_logs"))
                    conn.execute(text("ALTER TABLE send_logs_temp RENAME TO send_logs"))

                    # Фиксируем изменения
                    conn.commit()

                print("Структура таблицы send_logs успешно обновлена!")

            except SQLAlchemyError as e:
                print(f"Ошибка при обновлении структуры таблицы: {e}")
                print(
                    "Рекомендуется выполнить миграцию вручную или пересоздать базу данных."
                )


if __name__ == "__main__":
    create_tables()

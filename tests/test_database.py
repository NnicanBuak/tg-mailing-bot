import os
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import sys

# Add parent directory to path for shared imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.database import Base, Chat, Mailing, SendLog, get_statistics_by_chat_type


@pytest.fixture
def db_session():
    """Фикстура для тестовой базы данных"""
    # Используем SQLite в памяти для тестов
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    yield session

    session.close()


def test_chat_model(db_session):
    """Проверка создания и сохранения Chat"""
    # Создаем тестовый чат
    chat = Chat(chat_id=123456789, type="private", title="Test User", status="active")

    db_session.add(chat)
    db_session.commit()

    # Получаем чат из базы
    saved_chat = db_session.query(Chat).filter_by(chat_id=123456789).first()

    assert saved_chat is not None
    assert saved_chat.chat_id == 123456789
    assert saved_chat.type == "private"
    assert saved_chat.title == "Test User"
    assert saved_chat.status == "active"


def test_mailing_model(db_session):
    """Проверка создания и сохранения Mailing"""
    # Создаем тестовую рассылку
    mailing = Mailing(
        message_text="Test message", created_by=123456789, is_recurring=False
    )

    db_session.add(mailing)
    db_session.commit()

    # Получаем рассылку из базы
    saved_mailing = db_session.query(Mailing).first()

    assert saved_mailing is not None
    assert saved_mailing.message_text == "Test message"
    assert saved_mailing.created_by == 123456789
    assert saved_mailing.is_recurring == False


def test_mailing_recipients_relationship(db_session):
    """Проверка связи многие-ко-многим между рассылками и чатами"""
    # Создаем тестовый чат
    chat = Chat(chat_id=123456789, type="private", title="Test User", status="active")

    # Создаем тестовую рассылку
    mailing = Mailing(
        message_text="Test message", created_by=123456789, is_recurring=False
    )

    # Связываем их
    mailing.recipients.append(chat)

    db_session.add(chat)
    db_session.add(mailing)
    db_session.commit()

    # Проверяем связь
    saved_mailing = db_session.query(Mailing).first()
    assert len(saved_mailing.recipients) == 1
    assert saved_mailing.recipients[0].chat_id == 123456789

    saved_chat = db_session.query(Chat).first()
    assert len(saved_chat.mailings) == 1
    assert saved_chat.mailings[0].message_text == "Test message"


@patch("shared.database.db_session")
def test_get_statistics_by_chat_type(mock_db_session):
    """Проверка функции получения статистики"""
    # Мокаем сессию и запросы
    mock_session = MagicMock()
    mock_db_session.return_value.__enter__.return_value = mock_session

    # Настраиваем возвращаемые значения для запросов
    mock_session.query().count.return_value = 10
    mock_session.query().filter_by().count.return_value = 8
    mock_session.query().filter().count.return_value = 5
    mock_session.query().filter().filter_by().count.return_value = 4

    # Вызываем тестируемую функцию
    stats = get_statistics_by_chat_type()

    # Проверяем результат
    assert isinstance(stats, dict)
    assert "total" in stats
    assert "users" in stats
    assert "groups" in stats

    assert stats["total"]["all"] == 10
    assert stats["users"]["active"] == 4
    assert stats["groups"]["blocked"] == 4


def test_send_log_model(db_session):
    """Проверка создания и сохранения SendLog"""
    # Создаем тестовый чат и рассылку
    chat = Chat(chat_id=123456789, type="private", title="Test User", status="active")
    mailing = Mailing(
        message_text="Test message", created_by=123456789, is_recurring=False
    )

    db_session.add(chat)
    db_session.add(mailing)
    db_session.commit()

    # Создаем запись в логах отправки
    send_log = SendLog(
        mailing_id=mailing.mailing_id,
        chat_id=chat.chat_id,
        status="success",
        error_message=None,
    )

    db_session.add(send_log)
    db_session.commit()

    # Проверяем сохранение
    saved_log = db_session.query(SendLog).first()
    assert saved_log is not None
    assert saved_log.mailing_id == mailing.mailing_id
    assert saved_log.chat_id == chat.chat_id
    assert saved_log.status == "success"
    assert saved_log.error_message is None

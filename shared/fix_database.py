import os
import sys
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError


def get_database_url():
    """Получение URL базы данных из переменных окружения"""
    user = os.environ.get("DB_USER", "postgres")
    password = os.environ.get("DB_PASSWORD", "1")
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    db_name = os.environ.get("DB_NAME", "telegram_broadcast")

    return f"postgresql://{user}:{password}@{host}:{port}/{db_name}"


def fix_database_structure():
    """Исправляет структуру базы данных, добавляя недостающие колонки"""
    engine = create_engine(get_database_url())
    inspector = inspect(engine)

    try:
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
                        conn.execute(
                            text("ALTER TABLE send_logs_temp RENAME TO send_logs")
                        )

                        # Фиксируем изменения
                        conn.commit()

                    print("Структура таблицы send_logs успешно обновлена!")
                    return True

                except SQLAlchemyError as e:
                    print(f"Ошибка при обновлении структуры таблицы: {e}")
                    print("Попробуем более простой подход - добавление колонки...")

                    try:
                        # Альтернативный подход - просто добавить колонку
                        with engine.connect() as conn:
                            conn.execute(
                                text(
                                    """
                                ALTER TABLE send_logs 
                                ADD COLUMN mailing_id INTEGER REFERENCES mailings(mailing_id)
                            """
                                )
                            )
                            # Фиксируем изменения
                            conn.commit()

                        print("Колонка mailing_id успешно добавлена!")
                        return True
                    except SQLAlchemyError as e2:
                        print(f"Не удалось добавить колонку: {e2}")
                        return False
            else:
                print("Структура таблицы send_logs корректна.")
                return True
        else:
            print(
                "Таблица send_logs не найдена. Возможно, база данных пуста или не инициализирована."
            )
            return False

    except Exception as e:
        print(f"Произошла ошибка при проверке структуры базы данных: {e}")
        return False
    finally:
        engine.dispose()


if __name__ == "__main__":
    print("Запуск исправления структуры базы данных...")
    success = fix_database_structure()

    if success:
        print("База данных успешно обновлена!")
        sys.exit(0)
    else:
        print(
            "Не удалось обновить базу данных. Возможно, потребуется ручное вмешательство."
        )
        sys.exit(1)

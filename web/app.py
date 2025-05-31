from fastapi import FastAPI, Query, HTTPException, Depends, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict, Any, List
import os
import hashlib
import hmac
import json
import time
from pydantic import BaseModel
from dotenv import load_dotenv
from shared.database import Chat, db_session, Mailing, mailing_recipients

# Загрузка переменных окружения из .env
load_dotenv()

# Создаем экземпляр FastAPI
app = FastAPI(title="Telegram Broadcast Bot API")

# Настраиваем CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем статические файлы
app.mount("/static", StaticFiles(directory="static"), name="static")

# Настраиваем шаблоны
templates = Jinja2Templates(directory="templates")

# Список ID администраторов
ADMIN_IDS = [int(id) for id in os.environ.get("ADMIN_IDS", "").split(",") if id]

# Токен бота для проверки данных от Telegram
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")


# Модели данных Pydantic
class ChatsResponse(BaseModel):
    active_chats: List[Dict[str, Any]]
    unavailable_count: int


class RecipientsResponse(BaseModel):
    recipients: List[int]


class ErrorResponse(BaseModel):
    error: str


# Функция проверки данных от Telegram
def verify_telegram_data(init_data: str) -> tuple[bool, Optional[int]]:
    """Проверка данных от Telegram"""
    if not init_data:
        return False, None

    # Разбираем данные
    data_dict = {}
    for item in init_data.split("&"):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        data_dict[key] = value

    # Получаем хеш
    received_hash = data_dict.get("hash")
    if not received_hash:
        return False, None

    # Удаляем хеш из данных
    data_dict.pop("hash", None)

    # Сортируем по ключам
    data_check_arr = []
    for key in sorted(data_dict.keys()):
        data_check_arr.append(f"{key}={data_dict[key]}")

    data_check_string = "\n".join(data_check_arr)

    # Создаем хеш с секретным ключом
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    # Проверяем хеш
    if calculated_hash != received_hash:
        return False, None

    # Проверяем время
    auth_date = int(data_dict.get("auth_date", "0"))
    if time.time() - auth_date > 86400:  # 24 часа
        return False, None

    # Получаем user_id из данных
    try:
        user_data = json.loads(data_dict.get("user", "{}"))
        user_id = user_data.get("id")
        return True, user_id
    except:
        return False, None


# Dependency для проверки авторизации
async def verify_admin(initData: str = Query(...)):
    is_valid, user_id = verify_telegram_data(initData)
    if not is_valid or user_id not in ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Unauthorized")
    return user_id


# Маршруты
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Главная страница"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/mini_app", response_class=HTMLResponse)
async def mini_app(request: Request, mailing_id: int = Query(...)):
    """Страница Mini App для выбора получателей"""
    if not mailing_id:
        raise HTTPException(status_code=400, detail="Не указан ID рассылки")

    return templates.TemplateResponse(
        "mini_app.html", {"request": request, "mailing_id": mailing_id}
    )


@app.get("/api/chats", response_model=ChatsResponse)
async def get_chats(
    user_id: int = Depends(verify_admin), show_only_active: bool = Query(True)
):
    """API-эндпоинт для получения списка чатов"""
    with db_session() as session:
        if show_only_active:
            # Получаем только активные чаты
            chats = session.query(Chat).filter_by(status="active").all()
            # Подсчитываем количество недоступных чатов
            unavailable_count = (
                session.query(Chat).filter(Chat.status != "active").count()
            )
        else:
            # Получаем все чаты
            chats = session.query(Chat).all()
            unavailable_count = 0

        # Формируем список чатов
        chat_list = []
        for chat in chats:
            chat_list.append(
                {
                    "chat_id": chat.chat_id,
                    "title": chat.title or str(chat.chat_id),
                    "type": chat.type,
                    "status": chat.status,
                }
            )

    return ChatsResponse(active_chats=chat_list, unavailable_count=unavailable_count)


@app.get("/api/mailing/{mailing_id}/recipients", response_model=RecipientsResponse)
async def get_mailing_recipients(mailing_id: int, user_id: int = Depends(verify_admin)):
    """API-эндпоинт для получения получателей рассылки"""
    with db_session() as session:
        from sqlalchemy.orm import joinedload

        # Получаем рассылку с получателями
        mailing = (
            session.query(Mailing)
            .options(joinedload(Mailing.recipients))
            .filter_by(mailing_id=mailing_id)
            .first()
        )

        if not mailing:
            raise HTTPException(status_code=404, detail="Рассылка не найдена")

        # Формируем список получателей
        recipients = [chat.chat_id for chat in mailing.recipients]

    return RecipientsResponse(recipients=recipients)


# Запуск приложения
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)

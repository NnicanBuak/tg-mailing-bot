import aiohttp
import json
import logging

logger = logging.getLogger(__name__)


class TelegramAPI:
    def __init__(self, token: str):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.session.close()

    async def _make_request(self, method: str, params: dict = None):
        url = f"{self.base_url}/{method}"
        try:
            async with self.session.post(url, json=params) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    logger.error(f"Telegram API error: {data}")
                    raise Exception(f"Telegram API error: {data.get('description')}")
                return data["result"]
        except Exception as e:
            logger.error(f"Error making request to Telegram API: {e}")
            raise

    async def send_message(
        self, chat_id: int, text: str, parse_mode: str = None, reply_markup: dict = None
    ):
        params = {"chat_id": chat_id, "text": text}
        if parse_mode:
            params["parse_mode"] = parse_mode
        if reply_markup:
            params["reply_markup"] = json.dumps(reply_markup)
        return await self._make_request("sendMessage", params)

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: str = None,
        reply_markup: dict = None,
    ):
        params = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if parse_mode:
            params["parse_mode"] = parse_mode
        if reply_markup:
            params["reply_markup"] = json.dumps(reply_markup)
        return await self._make_request("editMessageText", params)

    async def answer_callback_query(
        self, callback_query_id: str, text: str = None, show_alert: bool = False
    ):
        params = {"callback_query_id": callback_query_id, "show_alert": show_alert}
        if text:
            params["text"] = text
        return await self._make_request("answerCallbackQuery", params)

    async def get_updates(self, offset: int = None, timeout: int = 30):
        params = {"timeout": timeout}
        if offset:
            params["offset"] = offset
        return await self._make_request("getUpdates", params)

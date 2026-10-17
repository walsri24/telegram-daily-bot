
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dotenv import load_dotenv
import logging

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

def send_message(token: str, chat_id: str, message: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
    }).encode()

    request = urllib.request.Request(url, data=payload)

    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.loads(response.read().decode())

    if not result.get("ok"):
        raise RuntimeError(f"Telegram rejected message for chat {chat_id}")


def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    message = os.environ["TELEGRAM_MESSAGE"]

    chat_ids = [
        os.environ["TELEGRAM_CHAT_ID_SELF"],
        os.environ["TELEGRAM_CHAT_ID_FRIEND"],
    ]

    for chat_id in dict.fromkeys(chat_ids):
        send_message(token, chat_id, message)
        print("Message sent successfully.")


if __name__ == "__main__":
    main()

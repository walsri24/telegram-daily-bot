import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from dotenv import load_dotenv

load_dotenv()

# Configure logging for both local execution and GitHub Actions.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)

logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)


def send_message(token: str, chat_id: str, message: str) -> None:
    """Send a Telegram message and log the result."""

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
    }).encode()

    request = urllib.request.Request(url, data=payload)

    start_time = time.monotonic()
    log.info("Sending Telegram message to chat_id=%s", chat_id)

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status_code = response.status
            result = json.loads(response.read().decode())

        elapsed = time.monotonic() - start_time

        if not result.get("ok"):
            log.error(
                "Telegram rejected message | chat_id=%s | "
                "http_status=%s | elapsed=%.2fs",
                chat_id,
                status_code,
                elapsed,
            )
            raise RuntimeError(
                f"Telegram rejected message for chat_id={chat_id}"
            )

        message_id = result.get("result", {}).get("message_id")

        log.info(
            "Telegram message sent successfully | chat_id=%s | "
            "message_id=%s | http_status=%s | elapsed=%.2fs",
            chat_id,
            message_id,
            status_code,
            elapsed,
        )

    except urllib.error.HTTPError as exc:
        elapsed = time.monotonic() - start_time

        # Read the API error without logging the request URL,
        # which contains the bot token.
        try:
            error_body = exc.read().decode("utf-8", errors="replace")
            error_data = json.loads(error_body)
            error_description = error_data.get(
                "description", "No error description provided"
            )
        except (ValueError, OSError):
            error_description = "Could not parse Telegram error response"

        log.error(
            "Telegram HTTP error | chat_id=%s | status=%s | "
            "description=%s | elapsed=%.2fs",
            chat_id,
            exc.code,
            error_description,
            elapsed,
        )
        raise

    except urllib.error.URLError as exc:
        elapsed = time.monotonic() - start_time

        log.error(
            "Telegram connection error | chat_id=%s | "
            "reason=%s | elapsed=%.2fs",
            chat_id,
            exc.reason,
            elapsed,
        )
        raise

    except (TimeoutError, json.JSONDecodeError) as exc:
        elapsed = time.monotonic() - start_time

        log.exception(
            "Telegram request failed | chat_id=%s | "
            "error_type=%s | elapsed=%.2fs",
            chat_id,
            type(exc).__name__,
            elapsed,
        )
        raise


def main() -> None:
    start_time = time.monotonic()

    log.info("=" * 60)
    log.info("Telegram Scheduled Messages workflow started")
    log.info("Execution time (UTC): %s", time.strftime(
        "%Y-%m-%d %H:%M:%S", time.gmtime()
    ))
    log.info("Execution time (local runner time): %s", time.strftime(
        "%Y-%m-%d %H:%M:%S", time.localtime()
    ))

    try:
        token = os.environ["TELEGRAM_BOT_TOKEN"]
        message = os.environ["TELEGRAM_MESSAGE"]

        chat_ids = [
            os.environ["TELEGRAM_CHAT_ID_SELF"],
            os.environ["TELEGRAM_CHAT_ID_FRIEND"],
        ]

        # Remove duplicates while preserving order.
        chat_ids = list(dict.fromkeys(chat_ids))

        if not token.strip():
            raise ValueError("TELEGRAM_BOT_TOKEN is empty")

        if not message.strip():
            raise ValueError("TELEGRAM_MESSAGE is empty")

        log.info("Configuration validated successfully")
        log.info("Number of unique recipients: %d", len(chat_ids))

        successful = 0
        failed = 0

        for index, chat_id in enumerate(chat_ids, start=1):
            log.info("Processing recipient %d/%d", index, len(chat_ids))

            try:
                send_message(token, chat_id, message)
                successful += 1

            except Exception:
                failed += 1
                log.exception(
                    "Failed to send message to recipient %d/%d",
                    index,
                    len(chat_ids),
                )

        elapsed = time.monotonic() - start_time

        log.info(
            "Workflow summary | total=%d | successful=%d | failed=%d | "
            "elapsed=%.2fs",
            len(chat_ids),
            successful,
            failed,
            elapsed,
        )

        if failed:
            raise RuntimeError(
                f"Failed to send Telegram messages to {failed} recipient(s)"
            )

        log.info("Telegram Scheduled Messages workflow completed successfully")
        log.info("=" * 60)

    except Exception:
        log.exception("Telegram Scheduled Messages workflow failed")
        raise


if __name__ == "__main__":
    main()
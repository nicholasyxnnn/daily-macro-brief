"""
Telegram delivery — sectioned, one message per module.
Style: Bloomberg terminal aesthetic. HTML parse mode. Monospace blocks. No emoji.
"""
import time
import requests
import config as cfg

TELEGRAM_API = f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT_TOKEN}"
SEND_DELAY = 0.5  # seconds between messages


def _send_message(text: str, chat_id: str = None) -> None:
    target = chat_id or cfg.TELEGRAM_CHAT_ID
    payload = {
        "chat_id": target,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    resp = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=15)
    if not resp.ok:
        raise RuntimeError(
            f"Telegram sendMessage failed {resp.status_code}: {resp.text[:300]}"
        )


def _send_photo(image_bytes: bytes, caption: str, chat_id: str = None) -> None:
    target = chat_id or cfg.TELEGRAM_CHAT_ID
    resp = requests.post(
        f"{TELEGRAM_API}/sendPhoto",
        data={"chat_id": target, "caption": caption, "parse_mode": "HTML"},
        files={"photo": ("chart.png", image_bytes, "image/png")},
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(
            f"Telegram sendPhoto failed {resp.status_code}: {resp.text[:300]}"
        )


def send_module(title: str, content: str, chat_id: str = None) -> None:
    """Send a single module section. Raises RuntimeError on Telegram failure."""
    msg = f"<b>── {title} ──</b>\n\n{content}"
    _send_message(msg, chat_id)
    time.sleep(SEND_DELAY)


def send_chart(image_bytes: bytes, caption: str, chat_id: str = None) -> None:
    _send_photo(image_bytes, caption, chat_id)
    time.sleep(SEND_DELAY)


def format_module_2(items: list[dict]) -> str:
    """Format Module 2 synthesis output for Telegram."""
    parts = []
    for i, item in enumerate(items, 1):
        parts.append(
            f"<b>{i}. {item['headline']}</b>\n"
            f"{item['body']}\n"
            f"<i>→ {item['so_what']}</i>"
        )
    return "\n\n".join(parts)


def format_module_5(items: list[dict]) -> str:
    """Format Module 5 theme radar for Telegram."""
    parts = []
    for item in items:
        parts.append(
            f"<b>{item['title']}</b>\n"
            f"<i>{item['source']}</i> — <a href=\"{item['link']}\">link</a>\n\n"
            f"{item['summary']}\n\n"
            f"<i>Book: {item['book_implication']}</i>"
        )
    return "\n\n─────\n\n".join(parts)


def format_module_6(text: str) -> str:
    return f"<pre>{text}</pre>"


def send_incomplete_notice(missing_modules: list[int], chat_id: str = None) -> None:
    msg = (
        f"<b>[Brief incomplete — modules {missing_modules} delayed. Admin notified.]</b>"
    )
    _send_message(msg, chat_id)

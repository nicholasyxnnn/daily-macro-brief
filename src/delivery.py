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


def _trim_to_word_limit(headline: str, body: str, so_what: str, limit: int = 80) -> str:
    """Trim body so headline + body + so_what stay within limit words."""
    headline_words = len(headline.split())
    so_what_words = len(so_what.split())
    budget = limit - headline_words - so_what_words
    if budget <= 0:
        return ""
    words = body.split()
    if len(words) <= budget:
        return body
    # Trim to budget, ending on a complete sentence where possible
    trimmed = " ".join(words[:budget])
    last_stop = max(trimmed.rfind("."), trimmed.rfind("!"), trimmed.rfind("?"))
    return trimmed[:last_stop + 1] if last_stop > len(trimmed) // 2 else trimmed + "…"


def format_module_2(items: list[dict]) -> str:
    parts = []
    for i, item in enumerate(items, 1):
        if not item.get("headline") or not item.get("body"):
            continue
        headline = item["headline"]
        body = _trim_to_word_limit(headline, item["body"], item.get("so_what", ""))
        so_what = item.get("so_what", "")
        parts.append(
            f"<b>{i}. {headline}</b>\n"
            f"{body}\n"
            f"<i>→ {so_what}</i>"
        )
    return "\n\n".join(parts) if parts else "[No items generated]"


def format_module_5(items: list[dict]) -> str:
    parts = []
    for item in items:
        if not item.get("title") or not item.get("summary"):
            continue
        link_part = f' — <a href="{item["link"]}">link</a>' if item.get("link") else ""
        parts.append(
            f"<b>{item['title']}</b>\n"
            f"<i>{item.get('source', '')}</i>{link_part}\n\n"
            f"{item['summary']}\n\n"
            f"<i>Book: {item['book_implication']}</i>"
        )
    return "\n\n─────\n\n".join(parts) if parts else "[No other theme items available today]"


def format_module_6(text: str) -> str:
    return f"<pre>{text}</pre>"


def send_incomplete_notice(missing_modules: list[int], chat_id: str = None) -> None:
    msg = (
        f"<b>[Brief incomplete — modules {missing_modules} delayed. Admin notified.]</b>"
    )
    _send_message(msg, chat_id)

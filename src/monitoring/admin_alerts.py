"""
Silent failure alerts to admin Telegram channel.
Never raises — monitoring must not cascade into additional failures.
"""
import traceback
import requests
import config as cfg

TELEGRAM_API = f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT_TOKEN}"


def admin_alert(module: str, error: Exception) -> None:
    """Send a silent failure alert to the admin channel."""
    tb = traceback.format_exc()[-800:]  # trim long tracebacks
    msg = (
        f"<b>[BRIEF ALERT] Module failure: {module}</b>\n\n"
        f"<code>{type(error).__name__}: {str(error)[:200]}</code>\n\n"
        f"<pre>{tb}</pre>"
    )
    try:
        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": cfg.TELEGRAM_ADMIN_CHAT_ID,
                "text": msg,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
    except Exception:
        pass  # alert failure must never propagate

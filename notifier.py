import os
import httpx
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("orbit")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"


async def send_telegram(message: str) -> bool:
    """Send a message via Telegram bot. Returns True on success."""
    # Debug: Check if credentials are loaded
    token_set = bool(TELEGRAM_BOT_TOKEN)
    chat_id_set = bool(TELEGRAM_CHAT_ID)
    logger.debug(f"[Orbit] Telegram credentials check — Token set: {token_set}, Chat ID set: {chat_id_set}")
    
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("[Orbit] Telegram credentials not set — skipping notification.")
        logger.warning(f"[Orbit] TELEGRAM_BOT_TOKEN: {TELEGRAM_BOT_TOKEN if TELEGRAM_BOT_TOKEN else 'NOT SET'}")
        logger.warning(f"[Orbit] TELEGRAM_CHAT_ID: {TELEGRAM_CHAT_ID if TELEGRAM_CHAT_ID else 'NOT SET'}")
        return False

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(TELEGRAM_API, json=payload)
            resp.raise_for_status()
            logger.info(f"[Orbit] Telegram notification sent successfully (status: {resp.status_code})")
            return True
    except httpx.HTTPStatusError as e:
        logger.error(f"[Orbit] Telegram notification failed with HTTP error: {e.response.status_code}")
        logger.error(f"[Orbit] Response body: {e.response.text}")
        logger.error(f"[Orbit] Full error details: {e}")
        return False
    except Exception as e:
        logger.error(f"[Orbit] Telegram notification failed: {type(e).__name__}: {e}")
        logger.error(f"[Orbit] Full traceback: {e.__class__.__module__}.{e.__class__.__name__}")
        return False


async def notify_match(match: dict) -> bool:
    """Format and send a job match notification."""
    score = match.get("score", 0)
    title = match.get("title", "Unknown Position")
    company = match.get("company", "Unknown Company")
    reason = match.get("reason", "Good match for your profile")
    url = match.get("url", "")

    message = (
        f"🎯 <b>New Match — Score: {score}/10</b>\n\n"
        f"<b>{title}</b>\n"
        f"{company}\n\n"
        f"<i>Why:</i> {reason}\n\n"
        f"🔗 {url}"
    )

    return await send_telegram(message)

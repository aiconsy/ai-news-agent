"""Telegram delivery — send text and audio briefings.

v5.2: Silent rule — if briefing is empty, no delivery. noteworthy_count
parameter to track how many HIGH/MEDIUM articles were included.
"""

import json
import logging
from pathlib import Path

import requests

from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

log = logging.getLogger("ai_news_agent")

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def send_text(text: str, chat_id: str | None = None, token: str | None = None) -> bool:
    """Send a text message to Telegram. Handles long messages by splitting.

    Returns True on success.
    """
    token = token or TELEGRAM_BOT_TOKEN
    chat_id = chat_id or TELEGRAM_CHAT_ID
    if not token or not chat_id:
        log.warning("Telegram credentials not configured — skipping text delivery")
        return False

    # Split into chunks (Telegram limit is 4096 chars per message)
    chunks = _split_message(text, max_length=4096)
    success = True

    for i, chunk in enumerate(chunks):
        try:
            url = TELEGRAM_API.format(token=token, method="sendMessage")
            payload = {
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
            }
            resp = requests.post(url, json=payload, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            log.error(f"Failed to send text chunk {i+1}/{len(chunks)}: {e}")
            success = False

    return success


def send_audio(audio_path: str, chat_id: str | None = None, token: str | None = None, caption: str = "") -> bool:
    """Send an OGG audio file as a Telegram voice message.

    Returns True on success.
    """
    token = token or TELEGRAM_BOT_TOKEN
    chat_id = chat_id or TELEGRAM_CHAT_ID
    if not token or not chat_id:
        log.warning("Telegram credentials not configured — skipping audio delivery")
        return False

    if not Path(audio_path).exists():
        log.error(f"Audio file not found: {audio_path}")
        return False

    try:
        url = TELEGRAM_API.format(token=token, method="sendVoice")
        with open(audio_path, "rb") as audio_file:
            files = {"voice": audio_file}
            data = {
                "chat_id": chat_id,
                "caption": caption[:1024] if caption else "",
            }
            resp = requests.post(url, files=files, data=data, timeout=120)
            resp.raise_for_status()
        log.info(f"Audio sent to Telegram: {audio_path}")
        return True
    except Exception as e:
        log.error(f"Failed to send audio: {e}")
        return False


def deliver_briefing(
    text: str,
    audio_path: str | None = None,
    caption: str = "📰 Hourly News Briefing",
    noteworthy_count: int = 0,
) -> bool:
    """Deliver a complete briefing — text and optional audio — to Telegram.

    v5.2 Silent rule: if briefing is empty (no noteworthy articles),
    skip delivery entirely — no spam.

    Args:
        text: The briefing text.
        audio_path: Optional path to OGG audio file.
        caption: Caption for the audio message.
        noteworthy_count: Number of HIGH/MEDIUM articles in the briefing.
            If 0, delivery is skipped (silent rule).

    Returns True if at least the text was sent successfully.
    """
    # Silent rule: empty briefing → no delivery
    if not text or not text.strip():
        log.info("Briefing is empty — skipping delivery (silent rule)")
        return False

    if noteworthy_count == 0:
        log.info("No noteworthy articles (HIGH/MEDIUM) — skipping delivery (silent rule)")
        return False

    log.info(f"Delivering briefing: {noteworthy_count} noteworthy articles")

    text_ok = send_text(text)
    audio_ok = False

    if audio_path:
        audio_ok = send_audio(audio_path, caption=caption)

    return text_ok or audio_ok


def _split_message(text: str, max_length: int = 4096) -> list[str]:
    """Split a long message into chunks that fit Telegram's length limit."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    # Split on paragraph breaks
    paragraphs = text.split("\n\n")
    current_chunk = ""

    for paragraph in paragraphs:
        if len(current_chunk) + len(paragraph) + 2 > max_length:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = paragraph
        else:
            current_chunk = current_chunk + "\n\n" + paragraph if current_chunk else paragraph

    if current_chunk:
        chunks.append(current_chunk)

    return chunks
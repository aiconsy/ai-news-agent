"""Telegram delivery — send text and audio briefings.

v5.2: Silent rule — if briefing is empty, no delivery. noteworthy_count
parameter to track how many HIGH/MEDIUM articles were included.
"""

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
    url = TELEGRAM_API.format(token=token, method="sendMessage")

    for i, chunk in enumerate(chunks):
        # Markdown first so **bold** survives. A stray character in a title
        # makes Telegram return 400; retry that chunk as plain text. Other
        # failures are not retried, so a timeout cannot deliver the chunk twice.
        # The exception text is not logged: requests includes the bot token URL.
        ok, status = _post_text(url, chat_id, chunk, "Markdown")
        if ok:
            continue
        if status == 400 and _post_text(url, chat_id, chunk, None)[0]:
            continue
        log.error("Failed to send text chunk %d/%d", i + 1, len(chunks))
        success = False

    return success


def _http_failure(exc: Exception) -> str:
    """Status and body only. Request exceptions embed the bot token in the URL."""
    response = getattr(exc, "response", None)
    if response is not None:
        body = (getattr(response, "text", "") or "")[:180]
        return f"HTTP {response.status_code}: {body}"
    return exc.__class__.__name__


def _post_text(url: str, chat_id: str, text: str, parse_mode: str | None) -> tuple[bool, int | None]:
    payload: dict = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        return True, resp.status_code
    except Exception as exc:
        response = getattr(exc, "response", None)
        status = response.status_code if response is not None else None
        log.warning("Telegram sendMessage failed (%s): %s", parse_mode or "plain", _http_failure(exc))
        return False, status


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
    except Exception as exc:
        log.error("Failed to send audio: %s", _http_failure(exc))
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
        # A single paragraph can itself exceed the limit; splitting only on
        # paragraph breaks would emit it unchanged and Telegram would reject the
        # whole chunk, silently losing that part of the briefing.
        while len(paragraph) > max_length:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""
            chunks.append(paragraph[:max_length])
            paragraph = paragraph[max_length:]

        if len(current_chunk) + len(paragraph) + 2 > max_length:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = paragraph
        else:
            current_chunk = current_chunk + "\n\n" + paragraph if current_chunk else paragraph

    if current_chunk:
        chunks.append(current_chunk)

    return chunks

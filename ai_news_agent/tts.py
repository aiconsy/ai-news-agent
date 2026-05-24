"""Text-to-speech — generate OGG audio via Edge-TTS."""

import logging
import os
import subprocess
import tempfile
from pathlib import Path

from .config import TTS_VOICE, EDGE_TTS_BIN, OUTPUT_DIR

log = logging.getLogger("ai_news_agent")


def text_to_speech(text: str, output_path: str | None = None, voice: str | None = None) -> str | None:
    """Convert text briefing to OGG audio using Edge-TTS.
    
    Steps:
    1. Generate MP3 with edge-tts
    2. Convert to OGG/Opus with ffmpeg for Telegram
    
    Returns path to OGG file or None on failure.
    """
    voice = voice or TTS_VOICE
    if output_path is None:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        output_path = str(OUTPUT_DIR / f"briefing_{timestamp}.ogg")

    # Clean text for TTS
    clean_text = _clean_text_for_tts(text)
    if not clean_text:
        log.error("No text to synthesize after cleaning")
        return None

    # Step 1: Generate MP3 with Edge-TTS
    mp3_path = output_path.replace(".ogg", ".mp3")
    try:
        result = subprocess.run(
            [EDGE_TTS_BIN, "--voice", voice, "--text", clean_text, "--write-media", mp3_path],
            capture_output=True,
            text=True,
            timeout=300,  # 5 min timeout for long briefings
        )
        if result.returncode != 0:
            log.error(f"edge-tts failed: {result.stderr[:500]}")
            return None

        if not os.path.exists(mp3_path) or os.path.getsize(mp3_path) < 1000:
            log.error(f"edge-tts produced empty/small file: {mp3_path}")
            return None

    except subprocess.TimeoutExpired:
        log.error("edge-tts timed out after 300s")
        return None
    except FileNotFoundError:
        log.error(f"edge-tts not found at: {EDGE_TTS_BIN}")
        return None

    # Step 2: Convert MP3 to OGG/Opus for Telegram
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", mp3_path,
                "-c:a", "libopus", "-b:a", "48k",
                "-vn", output_path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            log.error(f"ffmpeg conversion failed: {result.stderr[:500]}")
            return None

    except subprocess.TimeoutExpired:
        log.error("ffmpeg timed out")
        return None
    except FileNotFoundError:
        log.error("ffmpeg not found")
        return None
    finally:
        # Clean up MP3
        if os.path.exists(mp3_path):
            os.remove(mp3_path)

    # Verify output
    if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        log.info(f"TTS audio generated: {output_path} ({size_mb:.1f} MB)")
        return output_path
    else:
        log.error(f"OGG output missing or too small: {output_path}")
        return None


def _clean_text_for_tts(text: str) -> str:
    """Clean markdown and special characters for TTS readability."""
    import re

    # Remove markdown headers
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Remove bold/italic markers
    text = re.sub(r'\*{1,2}(.*?)\*{1,2}', r'\1', text)
    # Remove links, keep text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Remove horizontal rules
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
    # Remove inline code
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # Fix abbreviations (U.S. → US, etc.)
    text = re.sub(r'\b([A-Z])\.\s*', r'\1', text)
    # Collapse whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    # Truncate if too long for TTS (Edge-TTS has limits)
    max_chars = 50000  # Conservative limit
    if len(text) > max_chars:
        log.warning(f"TTS text truncated from {len(text)} to {max_chars} chars")
        text = text[:max_chars]

    return text
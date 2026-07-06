"""Text-to-speech — Piper TTS CLI primary, Edge-TTS fallback.

v5.2: Piper TTS support via CLI. Falls back to edge-tts if Piper
binary or model not available.
"""

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import TTS_VOICE, EDGE_TTS_BIN, OUTPUT_DIR

log = logging.getLogger("ai_news_agent")

# Piper TTS configuration from environment
PIPER_BIN = os.getenv("PIPER_BIN", "")
PIPER_MODEL = os.getenv("PIPER_MODEL", "")


def _piper_available() -> bool:
    """Check if Piper TTS binary and model are available."""
    if not PIPER_BIN:
        return False
    if not os.path.isfile(PIPER_BIN) and not shutil.which(PIPER_BIN):
        log.debug(f"Piper binary not found: {PIPER_BIN}")
        return False
    if not PIPER_MODEL or not os.path.isfile(PIPER_MODEL):
        log.debug(f"Piper model not found: {PIPER_MODEL}")
        return False
    return True


def _tts_piper(text: str, output_path: str) -> str | None:
    """Generate audio using Piper TTS CLI.

    Piper generates WAV, then we convert to OGG/Opus via ffmpeg.
    """
    wav_path = output_path.replace(".ogg", ".wav")
    try:
        # Piper CLI: echo "text" | piper --model model.onnx --output_file out.wav
        cmd = [PIPER_BIN, "--model", PIPER_MODEL, "--output_file", wav_path]
        result = subprocess.run(
            cmd,
            input=text,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            log.error(f"Piper TTS failed: {result.stderr[:500]}")
            return None

        if not os.path.exists(wav_path) or os.path.getsize(wav_path) < 1000:
            log.error(f"Piper produced empty/small file: {wav_path}")
            return None

    except subprocess.TimeoutExpired:
        log.error("Piper TTS timed out after 300s")
        return None
    except FileNotFoundError:
        log.error(f"Piper binary not found at: {PIPER_BIN}")
        return None
    except Exception as e:
        log.error(f"Piper TTS error: {e}")
        return None

    # Convert WAV to OGG/Opus
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", wav_path,
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
        # Clean up WAV
        if os.path.exists(wav_path):
            os.remove(wav_path)

    if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        log.info(f"Piper TTS audio generated: {output_path} ({size_mb:.1f} MB)")
        return output_path

    log.error(f"OGG output missing or too small: {output_path}")
    return None


def _tts_edge(text: str, output_path: str, voice: str) -> str | None:
    """Generate audio using Edge-TTS (fallback)."""
    mp3_path = output_path.replace(".ogg", ".mp3")
    try:
        result = subprocess.run(
            [EDGE_TTS_BIN, "--voice", voice, "--text", text, "--write-media", mp3_path],
            capture_output=True,
            text=True,
            timeout=300,
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

    # Convert MP3 to OGG/Opus
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
        if os.path.exists(mp3_path):
            os.remove(mp3_path)

    if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        log.info(f"Edge-TTS audio generated: {output_path} ({size_mb:.1f} MB)")
        return output_path

    log.error(f"OGG output missing or too small: {output_path}")
    return None


def text_to_speech(text: str, output_path: str | None = None, voice: str | None = None) -> str | None:
    """Convert text briefing to OGG audio.

    Tries Piper TTS first (if configured), falls back to Edge-TTS.

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

    # Try Piper first
    if _piper_available():
        log.info("Using Piper TTS")
        result = _tts_piper(clean_text, output_path)
        if result:
            return result
        log.warning("Piper TTS failed — falling back to edge-tts")

    # Fallback to Edge-TTS
    log.info("Using Edge-TTS")
    return _tts_edge(clean_text, output_path, voice)


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

    # Truncate if too long for TTS
    max_chars = 50000  # Conservative limit
    if len(text) > max_chars:
        log.warning(f"TTS text truncated from {len(text)} to {max_chars} chars")
        text = text[:max_chars]

    return text
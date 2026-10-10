"""Configuration loader — reads from .env file and environment variables.

Process environment wins over the .env file. Paths are resolved after the
file is loaded, so BASE_DIR set in .env is honored.
"""

import os
from pathlib import Path

from dotenv import load_dotenv


def _load_env() -> None:
    """Load the project .env, then a BASE_DIR .env if it is a different file."""
    project_root = Path(__file__).resolve().parent.parent
    project_env = project_root / ".env"
    if project_env.exists():
        load_dotenv(project_env, override=False)

    base = Path(os.path.expanduser(os.getenv("BASE_DIR", str(Path.home() / ".ai-news-agent"))))
    base_env = base / ".env"
    if base_env.exists() and base_env.resolve() != project_env.resolve():
        load_dotenv(base_env, override=False)


_load_env()

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(os.path.expanduser(os.getenv("BASE_DIR", str(Path.home() / ".ai-news-agent"))))
CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
DB_DIR = BASE_DIR / "db"
OUTPUT_DIR = BASE_DIR / "output"
LOG_DIR = BASE_DIR / "logs"
DB_PATH = DB_DIR / "news_intel.db"
FEEDS_PATH = CONFIG_DIR / "feeds.json"

for d in (DB_DIR, OUTPUT_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ── LLM Configuration ────────────────────────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
# Default: local Ollama native chat API. OpenAI-compatible endpoints
# (Ollama Cloud /v1/chat/completions, OpenRouter) are detected from the URL.
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/api/chat")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")

FALLBACK_PROVIDER = os.getenv("FALLBACK_PROVIDER", "openrouter")
FALLBACK_BASE_URL = os.getenv("FALLBACK_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")
FALLBACK_API_KEY = os.getenv("FALLBACK_API_KEY", "")

OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "60"))
OLLAMA_CONNECT_TIMEOUT = int(os.getenv("OLLAMA_CONNECT_TIMEOUT", "10"))
SYNTHESIS_TIMEOUT = int(os.getenv("SYNTHESIS_TIMEOUT", "120"))

# ── Model Selection ───────────────────────────────────────────────────────────
MODEL_CLASSIFY = os.getenv("MODEL_CLASSIFY", "minimax-m2.7:cloud")
MODEL_SUMMARIZE = os.getenv("MODEL_SUMMARIZE", "minimax-m2.7:cloud")
MODEL_SYNTHESIS = os.getenv("MODEL_SYNTHESIS", "glm-5.1:cloud")

# ── Fallback Models ───────────────────────────────────────────────────────────
_fallback = os.getenv("FALLBACK_MODELS", "deepseek/deepseek-chat,qwen/qwen3-32b")
FALLBACK_MODELS = [model.strip() for model in _fallback.split(",") if model.strip()]

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── TTS ───────────────────────────────────────────────────────────────────────
TTS_VOICE = os.getenv("TTS_VOICE", "en-GB-RyanNeural")
EDGE_TTS_BIN = os.getenv("EDGE_TTS_BIN", "edge-tts")

# ── Pipeline Settings ─────────────────────────────────────────────────────────
MAX_DEEP_READ = int(os.getenv("MAX_DEEP_READ", "10"))
MAX_NOTEWORTHY = int(os.getenv("MAX_NOTEWORTHY", "20"))
HIGH_CAP = int(os.getenv("HIGH_CAP", "12"))
DEDUP_HOURS = int(os.getenv("DEDUP_HOURS", "12"))
DEVELOPING_WINDOW_HOURS = int(os.getenv("DEVELOPING_WINDOW_HOURS", "2"))
# Token-set overlap. Higher means fewer headlines are treated as the same story.
DEDUP_THRESHOLD = float(os.getenv("DEDUP_THRESHOLD", "0.72"))
QUIET_HOUR_START = int(os.getenv("QUIET_HOUR_START", "22"))
QUIET_HOUR_END = int(os.getenv("QUIET_HOUR_END", "6"))
MAX_ARTICLE_AGE_HOURS = int(os.getenv("MAX_ARTICLE_AGE_HOURS", "36"))
MAX_ITEMS_PER_FEED = int(os.getenv("MAX_ITEMS_PER_FEED", "8"))
# Ambiguous headlines sent to the classifier. The rest are ranked without a model.
MAX_LLM_CLASSIFY = int(os.getenv("MAX_LLM_CLASSIFY", "24"))
CLASSIFY_BATCH_SIZE = int(os.getenv("CLASSIFY_BATCH_SIZE", "12"))
SYNTHESIS_STORY_CHARS = int(os.getenv("SYNTHESIS_STORY_CHARS", "320"))
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "12000"))
DEEP_READ_WORKERS = int(os.getenv("DEEP_READ_WORKERS", "4"))

# ── Source Quality Tiers ─────────────────────────────────────────────────────
SOURCE_TIERS = {
    # Tier 1: Wire services, world-class outlets
    1: [
        "reuters", "ap news", "bbc", "associated press", "propublica",
        "the guardian", "new york times", "nyt", "washington post",
        "npr", "al jazeera", "the intercept", "pbs", "democracy now",
        "der spiegel", "france 24", "deutsche welle", "nature",
        "science", "scientist", "the economist", "financial times",
        "wall street journal", "wsj",
    ],
    # Tier 2: Established outlets
    2: [
        "cnn", "nbc", "abc news", "cbs", "sky news", "channel 4",
        "the atlantic", "vox", "five thirty eight", "mother jones",
        "arstechnica", "the verge", "wired", "techcrunch",
        "venturebeat", "the register", "mit technology review",
        "scientific american", "new scientist", "ieee spectrum",
        "hacker news", "cnbc", "bloomberg", "forbes", "fortune",
        "time", "newsweek", "politico", "the hill", "independent",
        "the times of israel", "south china morning post",
        "engadget", "the next web",
    ],
    # Everything else is Tier 3
}

# ── Topic Keywords (Geopolitics-first) ────────────────────────────────────────
GEOPOLITICS_KEYWORDS = [
    "war", "conflict", "military", "nato", "eu", "european union", "sanctions", "treaty",
    "diplomacy", "summit", "election", "regime", "border", "annexation",
    "occupation", "sovereignty", "alliance", "nuclear", "missile",
    "cyberattack", "espionage", "intelligence", "geopolitics", "geopolitical",
    "foreign policy", "defense", "invasion", "retaliation", "strike", "escalation",
    "ceasefire", "peace talks", "un security", "ambassador", "diplomat",
    "territorial", "dispute", "humanitarian", "refugee", "crisis",
    "ukraine", "gaza", "taiwan strait", "south china sea",
]

TECH_KEYWORDS = [
    "ai", "artificial intelligence", "llm", "machine learning", "deep learning",
    "neural", "transformer", "gpt", "chatgpt", "openai", "google deepmind", "anthropic",
    "chip", "semiconductor", "nvidia", "amd", "intel", "tsmc", "fab",
    "quantum", "fusion", "rocket", "spacex", "starship", "mars",
    "cybersecurity", "ransomware", "zero-day", "vulnerability",
    "blockchain", "defi", "regulation tech", "data privacy", "gdpr",
]

FINANCE_KEYWORDS = [
    "fed", "interest rate", "inflation", "gdp", "recession", "tariff",
    "trade war", "imf", "world bank", "fiscal", "monetary", "treasury",
    "bond", "yield", "equity", "market crash", "bull market", "bear market",
    "ipo", "valuation", "venture capital", "private equity",
]

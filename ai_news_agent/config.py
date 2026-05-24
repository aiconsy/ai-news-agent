"""Configuration loader — reads from .env file and environment variables."""

import os
from pathlib import Path
from dotenv import load_dotenv

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(os.getenv("BASE_DIR", str(Path.home() / ".ai-news-agent")))
CONFIG_DIR = Path(__file__).parent.parent / "config"
DB_DIR = Path(BASE_DIR) / "db"
OUTPUT_DIR = Path(BASE_DIR) / "output"
LOG_DIR = Path(BASE_DIR) / "logs"
DB_PATH = DB_DIR / "news_intel.db"
FEEDS_PATH = CONFIG_DIR / "feeds.json"

# Ensure directories exist
for d in [DB_DIR, OUTPUT_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)


def _load_env():
    """Load .env from project root or BASE_DIR."""
    # Try project root first, then BASE_DIR
    project_root = Path(__file__).parent.parent
    env_candidates = [
        project_root / ".env",
        Path(BASE_DIR) / ".env",
        Path.home() / ".ai-news-agent" / ".env",
    ]
    for env_path in env_candidates:
        if env_path.exists():
            load_dotenv(env_path, override=True)
            break


_load_env()

# ── LLM Configuration ────────────────────────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
# Default: local Ollama. For Ollama Cloud, use https://ollama.com/v1/chat/completions
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/api/chat")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")

FALLBACK_PROVIDER = os.getenv("FALLBACK_PROVIDER", "openrouter")
FALLBACK_BASE_URL = os.getenv("FALLBACK_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")
FALLBACK_API_KEY = os.getenv("FALLBACK_API_KEY", "")

OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "60"))
OLLAMA_CONNECT_TIMEOUT = int(os.getenv("OLLAMA_CONNECT_TIMEOUT", "10"))

# ── Model Selection ───────────────────────────────────────────────────────────
MODEL_CLASSIFY = os.getenv("MODEL_CLASSIFY", "minimax-m2.7:cloud")
MODEL_SUMMARIZE = os.getenv("MODEL_SUMMARIZE", "minimax-m2.7:cloud")
MODEL_SYNTHESIS = os.getenv("MODEL_SYNTHESIS", "glm-5.1:cloud")

# ── Fallback Models ───────────────────────────────────────────────────────────
FALLBACK_MODELS = os.getenv("FALLBACK_MODELS", "deepseek/deepseek-chat,qwen/qwen3-32b").split(",")

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── TTS ───────────────────────────────────────────────────────────────────────
TTS_VOICE = os.getenv("TTS_VOICE", "en-GB-RyanNeural")
EDGE_TTS_BIN = os.getenv("EDGE_TTS_BIN", "edge-tts")

# ── Pipeline Settings ─────────────────────────────────────────────────────────
MAX_DEEP_READ = int(os.getenv("MAX_DEEP_READ", "30"))
MAX_NOTEWORTHY = int(os.getenv("MAX_NOTEWORTHY", "50"))
HIGH_CAP = int(os.getenv("HIGH_CAP", "20"))
DEDUP_HOURS = int(os.getenv("DEDUP_HOURS", "12"))
DEDUP_THRESHOLD = float(os.getenv("DEDUP_THRESHOLD", "0.6"))
QUIET_HOUR_START = int(os.getenv("QUIET_HOUR_START", "22"))
QUIET_HOUR_END = int(os.getenv("QUIET_HOUR_END", "6"))

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
        "techcrunch", "engadget", "the next web",
    ],
    # Everything else is Tier 3
}

# ── Topic Keywords (Geopolitics-first) ────────────────────────────────────────
GEOPOLITICS_KEYWORDS = [
    "war", "conflict", "military", "nato", "eu", "sanctions", "treaty",
    "diplomacy", "summit", "election", "regime", "border", "annexation",
    "occupation", "sovereignty", "alliance", "treaty", "nuclear", "missile",
    "cyberattack", "espionage", "intelligence", "geopolitics", "geopolitical",
    "foreign policy", "defense", "invasion", "retaliation", "strike", "escalation",
    "ceasefire", "peace talks", "un security", "ambassador", "diplomat",
    "territorial", "dispute", "humanitarian", "refugee", "crisis",
]

TECH_KEYWORDS = [
    "ai", "artificial intelligence", "llm", "machine learning", "deep learning",
    "neural", "transformer", "gpt", "openai", "google deepmind", "anthropic",
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
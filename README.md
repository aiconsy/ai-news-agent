<div align="center">

# 🎙️ AI News Agent

**Autonomous hourly news intelligence pipeline**

*Turn 275+ RSS feeds into a concise, podcast-style audio briefing — every hour, fully hands-free.*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://python.org)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

</div>

---

## What It Does

```
📰 285+ RSS Feeds         🎧 Audio Briefing
       │                       │
       ▼                       ▼
  ┌─────────┐   ┌──────────┐   ┌──────┐   ┌───────────┐   ┌─────┐
  │  Fetch   │──▶│  Dedup   │──▶│ Deep │──▶│  LLM      │──▶│ TTS │──▶ 📱 Telegram
  │ + Classify│   │ (12h +   │   │ Read │   │ Synthesize│   │Audio│
  │          │   │  fuzzy)  │   │      │   │           │   │     │
  └─────────┘   └──────────┘   └──────┘   └───────────┘   └─────┘
```

**Pass 1** — Fetch headlines from 275+ RSS feeds, deduplicate (12h rolling window + fuzzy matching), classify by topic and priority.

**Pass 2** — Deep-read the top articles (requests → trafilatura → readability fallback), summarize each with context.

**Synthesis** — LLM generates a natural, podcast-length geopolitical briefing (1,500–3,000 words).

**Delivery** — Edge-TTS converts to audio (OGG/Opus), sends both text and voice message to Telegram.

## ✨ Features

- **🆓 Zero-cost operation** — Uses Ollama Cloud subscription models, no per-token charges
- **🎧 Podcast-style audio** — Natural-sounding TTS briefings delivered as Telegram voice messages
- **📰 275+ global feeds** — Geopolitics, tech, AI, finance, cybersecurity, science (fully customizable)
- **🔄 Hourly automation** — Run as a cron job or Hermes Agent skill
- **🧠 Smart dedup** — 12h rolling window + fuzzy matching (0.6 threshold) — no repeated stories
- **📊 Source tiers** — Reuters/BBC/NYT → Tier 1 (highest trust), everything else → Tier 2–3
- **🌙 Quiet hours** — Pauses during configurable hours (default 22:00–06:00)
- **🔒 Auto fallback** — If Ollama is down, falls back to OpenRouter automatically
- **🛡️ Robust HTTP** — SSL retry, browser UA, trafilatura + readability extraction

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com) (local or cloud subscription)
- `ffmpeg` (for audio conversion)
- A Telegram bot token ([@BotFather](https://t.me/BotFather))

### Install

```bash
git clone https://github.com/AI-Consy/ai-news-agent.git
cd ai-news-agent
pip install -e .
```

### Configure

```bash
cp .env.example .env
# Edit .env with your settings:
#   LLM_API_KEY=your_ollama_key
#   TELEGRAM_BOT_TOKEN=your_bot_token
#   TELEGRAM_CHAT_ID=your_chat_id
```

> 💡 **LLM Provider?** By default, it uses local Ollama. For Ollama Cloud, just change `LLM_BASE_URL`. For OpenRouter, set `FALLBACK_API_KEY`. The default feeds are just starting points — edit `config/feeds.json` to match your interests.

### Run

```bash
# One-shot run
ai-news run

# Text only (skip TTS)
ai-news run --text-only

# Force (ignore dedup/quiet hours)
ai-news run --force

# Skip Telegram delivery
ai-news run --no-deliver
```

### Automate (Hermes Agent)

```bash
hermes cron create \
  --name "Hourly News Briefing" \
  --schedule "0 * * * *" \
  --prompt "Run the news briefing: cd ~/ai-news-agent && python -m ai_news_agent.main" \
  --deliver telegram
```

Or add to crontab:
```
0 * * * * /path/to/ai-news-agent/scripts/run_hourly.sh
```

## 📡 Feed Categories

The included `config/feeds.json` gives you 275+ curated global feeds:

| Category | Count | Examples |
|----------|-------|---------|
| 🌍 World News | 78 | Reuters, BBC, Al Jazeera, NPR, FT, NYT |
| 💻 Tech & Science | 63 | Ars Technica, The Verge, Wired, MIT Tech Review |
| 💰 Business & Investment | 39 | Bloomberg, CNBC, The Economist |
| 🪙 Cryptocurrency | 26 | CoinDesk, The Block |
| 🤖 AI | 17 | AI News, MIT News, Hugging Face Blog |
| 🔒 Cybersecurity | 27 | Krebs on Security, The Record, Dark Reading |

> 🎯 **Your feeds, your rules** — These are defaults. Remove, add, or recategorize feeds in `config/feeds.json` to match your interests.

## ⚙️ Configuration

All settings live in `.env` (see `.env.example` for full docs):

| Variable | Default | What it does |
|----------|---------|-------------|
| `LLM_PROVIDER` | `ollama` | Primary LLM provider |
| `LLM_BASE_URL` | `http://localhost:11434/api/chat` | Primary endpoint (local Ollama) |
| `LLM_API_KEY` | — | Your Ollama / OpenAI key |
| `MODEL_CLASSIFY` | `minimax-m2.7:cloud` | Classification model |
| `MODEL_SYNTHESIS` | `glm-5.1:cloud` | Briefing synthesis model |
| `TTS_VOICE` | `en-GB-RyanNeural` | Edge-TTS voice |
| `TELEGRAM_BOT_TOKEN` | — | From @BotFather |
| `MAX_DEEP_READ` | `30` | Max articles to deep-read |
| `DEDUP_HOURS` | `12` | How long to remember headlines |
| `QUIET_HOUR_START` | `22` | Pause start (24h) |
| `QUIET_HOUR_END` | `6` | Pause end (24h) |

## 🏗️ Architecture

```
ai-news-agent/
├── ai_news_agent/          # Core pipeline package
│   ├── main.py              # Orchestrator + CLI
│   ├── config.py            # All settings from .env
│   ├── feeds.py             # RSS fetch & parse
│   ├── dedup.py             # Exact + fuzzy dedup
│   ├── deepread.py          # Article text extraction
│   ├── classify.py          # Topic & priority classification
│   ├── synthesize.py        # LLM briefing generation
│   ├── tts.py               # Edge-TTS → OGG audio
│   ├── deliver.py           # Telegram delivery
│   └── db.py                # SQLite persistence
├── config/
│   └── feeds.json           # 275+ RSS feeds (edit to customize!)
├── scripts/
│   └── run_hourly.sh        # Cron wrapper
├── tests/
│   └── test_pipeline.py     # Unit tests + redaction guards
├── docs/
│   └── architecture.md      # Detailed architecture docs
├── .env.example             # Configuration template
├── pyproject.toml           # Package definition
└── requirements.txt          # Python dependencies
```

## 🔌 Using as a Plugin

### Hermes Agent
```yaml
# In ~/.hermes/config.yaml
skills:
  - ai-news-agent
```

### OpenClaw
```json
{
  "plugins": [{
    "name": "ai-news-agent",
    "command": "python -m ai_news_agent.main"
  }]
}
```

### Standalone
```bash
# Just run it — no agent needed
python -m ai_news_agent.main
```

## 🎨 Adding Custom Feeds

Edit `config/feeds.json`:

```json
{
  "feeds": [
    {
      "name": "My Custom Feed",
      "url": "https://example.com/rss",
      "category": "Tech&Science",
      "tier": 2
    }
  ]
}
```

**Categories**: `World News`, `Tech&Science`, `Business and investment`, `Cryptocurrency`, `A.I.`, `Cybersecurity`

**Tier**: `1` (wire services), `2` (established outlets), `3` (everything else)

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes (`git commit -m 'Add my feature'`)
4. Push to the branch (`git push origin feature/my-feature`)
5. Open a Pull Request

## 📄 License

MIT License — Copyright © 2026 **AI Consy**

Free to use, modify, and distribute. The only requirement: **include the original copyright notice** (attribution to "AI Consy") in any copy or substantial portion of the Software.

See [LICENSE](LICENSE) for the full text.

---

<div align="center">

*Brought to you by [AI Consy](https://github.com/AI-Consy) — built with ❤️ and too many RSS feeds*

</div>
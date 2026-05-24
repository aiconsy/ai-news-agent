# Architecture

## Overview

AI News Agent is a two-pass news intelligence pipeline that transforms hundreds of RSS feeds into concise, podcast-length audio briefings delivered via Telegram.

## Data Flow

```
RSS Feeds (285+)
       │
       ▼
┌──────────────────┐
│   Pass 1: Fetch  │  feedparser → dedup (12h + fuzzy 0.6) → classify (keywords + LLM)
│   + Classify     │  Source quality tiers (1=Reuters/BBC, 2=CNN/TechCrunch, 3=everything)
└────────┬─────────┘
         │ top 50 stories
         ▼
┌──────────────────┐
│   Pass 2: Deep   │  requests+browser UA → trafilatura → readability fallback
│   Read + Summarize│  Up to 30 articles deep-read, each summarized by LLM
└────────┬─────────┘
         │ summarized articles
         ▼
┌──────────────────┐
│   LLM Synthesis  │  Geopolitics-first narrative briefing (1,500-3,000 words)
│                  │  Ollama Cloud primary → OpenRouter fallback
└────────┬─────────┘
         │ briefing text
         ▼
┌──────────────────┐
│   TTS + Deliver  │  Edge-TTS → MP3 → ffmpeg → OGG/Opus → Telegram
└──────────────────┘
```

## Module Structure

| Module | Responsibility |
|--------|---------------|
| `config.py` | Environment config, LLM routing, source tiers, keyword lists |
| `feeds.py` | RSS feed loading and fetching via feedparser |
| `dedup.py` | Headline deduplication (exact hash + fuzzy SequenceMatcher) |
| `deepread.py` | Article content extraction (requests → trafilatura → readability) |
| `classify.py` | Topic classification and priority assignment (keywords + LLM) |
| `synthesize.py` | LLM briefing synthesis with geopolitics-first prompt |
| `tts.py` | Edge-TTS audio generation with ffmpeg OGG/Opus conversion |
| `deliver.py` | Telegram delivery (text + voice messages) |
| `db.py` | SQLite storage for headlines, articles, and briefing history |
| `main.py` | Pipeline orchestration and CLI |

## LLM Routing

```
Primary: Ollama Cloud (localhost:11434 or ollama.com/v1)
  ├── Classification: minimax-m2.7:cloud (42 tok/s, function calling)
  ├── Summarization: minimax-m2.7:cloud (consistent quality)
  └── Synthesis: glm-5.1:cloud (114 tok/s, best for long-form)
      │
      ▼ (if Ollama fails)
Fallback: OpenRouter (openrouter.ai/api/v1)
  ├── deepseek/deepseek-chat
  ├── qwen/qwen3-32b
  └── qwen/qwen-plus
```

## Source Quality Tiers

| Tier | Examples | Weight |
|------|---------|--------|
| 1 (Wire) | Reuters, BBC, NYT, Al Jazeera, FT | Highest trust, deep-read priority |
| 2 (Established) | CNN, The Verge, Wired, TechCrunch | Solid, prioritized |
| 3 (Other) | Blogs, niche outlets | Included but lower priority |

## Deduplication

1. **Exact hash**: SHA-256 of normalized title → skip if seen within 12h
2. **Fuzzy match**: SequenceMatcher ratio ≥ 0.6 → skip as duplicate
3. **Cleanup**: Headlines older than 2× dedup window are purged

## Quiet Hours

Pipeline exits early during configurable quiet hours (default 22:00–06:00 local time) to save compute.

## Database Schema

SQLite with three tables:
- `headlines_seen` — dedup cache (url_hash, title, seen_at, category, priority)
- `articles` — deep-read results (url, title, summary, content, deep_read)
- `briefings` — delivery history (timestamp, word_count, runtime_seconds)

## Scheduling

Run hourly via:
- **Hermes cron**: `hermes cron create --name "News" --schedule "0 * * * *"`
- **systemd timer**: See `deploy/ai-news-agent.timer`
- **crontab**: `0 * * * * /path/to/scripts/run_hourly.sh`
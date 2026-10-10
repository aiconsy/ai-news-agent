# Architecture

## Overview

AI News Agent is a two-pass news intelligence pipeline that transforms a curated RSS list into a short audio briefing delivered via Telegram. Ranking and dedup happen in code. The model only sees stories that survived that filter.

## Data Flow

```
RSS Feeds
       │
       ▼
┌──────────────────┐
│   Pass 1: Fetch  │  age window → same-run clustering → 12h token dedup
│   + Classify     │  word-boundary keywords; LLM only for a capped ambiguous set
└────────┬─────────┘
         │ up to 20 HIGH/MEDIUM stories
         ▼
┌──────────────────┐
│   Pass 2: Deep   │  requests (redirects re-checked) → trafilatura → readability
│   Read           │  top stories only; a short lead is kept, not the full body
└────────┬─────────┘
         │ compact leads, hard character budget
         ▼
┌──────────────────┐
│   LLM Synthesis  │  one call, ~700-1,600 words. Skipped when nothing is new
│                  │  Ollama primary → OpenRouter fallback
└────────┬─────────┘
         │ briefing text
         ▼
┌──────────────────┐
│   TTS + Deliver  │  Piper or Edge-TTS → ffmpeg → OGG/Opus → Telegram
└──────────────────┘
```

## Module Structure

| Module | Responsibility |
|--------|---------------|
| `config.py` | Environment config, LLM routing, source tiers, keyword lists |
| `feeds.py` | RSS feed loading and fetching via feedparser |
| `dedup.py` | Same-run clustering plus exact hash and token-overlap dedup |
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

1. **Same-run clustering**: token overlap collapses copies of one story and keeps the better source
2. **Exact hash**: SHA-256 of the normalized title, skipped if seen inside the window
3. **Token overlap**: content-word Jaccard (default 0.72), not raw character similarity
4. **Developing stories**: a short window (default 2h) so a real update can land
5. **Refresh on sight**: seeing a headline again updates `seen_at`, so the window slides
6. **Cleanup**: headlines older than 2× the dedup window are purged

## Token budget

- RSS items older than `MAX_ARTICLE_AGE_HOURS` (default 36) never reach ranking
- Keyword rules use word boundaries, so ordinary words are not treated as topics
- At most `MAX_LLM_CLASSIFY` ambiguous headlines are classified, in batches of one-letter labels
- Synthesis receives HIGH and MEDIUM stories only, each clipped to a lead, under `MAX_CONTEXT_CHARS`
- An hour with nothing new makes no model call

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
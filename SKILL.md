---
name: ai-news-agent
description: >
  Produce an hourly news briefing from the bundled RSS feeds. Use when the
  user asks for a news briefing, news digest, audio briefing, or to install,
  schedule, or troubleshoot AI News Agent. Run the packaged CLI. Do not
  reimplement feed fetching, ranking, or Telegram delivery.
version: 1.3.0
author: AI Consy
license: MIT
metadata:
  hermes:
    tags: [News, Briefing, Telegram, RSS]
    related_skills: []
required_environment_variables:
  - name: LLM_API_KEY
    prompt: API key for the briefing model
    help: Leave empty when LLM_BASE_URL is a local Ollama server that does not need a key.
    required_for: cloud model calls
  - name: TELEGRAM_BOT_TOKEN
    prompt: Telegram bot token from BotFather
    help: https://t.me/BotFather
    required_for: Telegram delivery
  - name: TELEGRAM_CHAT_ID
    prompt: Telegram chat id that should receive the briefing
    help: The numeric chat id of the user or group.
    required_for: Telegram delivery
---

# AI News Agent

Turn the bundled RSS list into one short briefing. The Python package does the fetching, deduplication, ranking, and delivery. The agent only installs it, checks it, and runs it.

This is an addon for an agent host such as Hostinger Managed OpenClaw or Hermes. It is not a Node.js website and not a static site. Do not upload it through a Node.js or static website deploy.

## Install

From the skill directory (the checkout that contains this file):

```bash
python3 -m pip install -e .
sudo apt-get install -y ffmpeg
cp .env.example .env
```

On Hostinger the server clock is often UTC. Set `TZ` in `.env` or the cron environment to the user's timezone before relying on quiet hours. Example: `TZ=Europe/Zurich`.

Fill `LLM_BASE_URL` and, if that endpoint requires one, `LLM_API_KEY`. Fill `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` only when the user wants Telegram. Never print those values, never commit `.env`, and never paste secrets into the chat.

## Check, then run

```bash
ai-news doctor
ai-news run --text-only --no-deliver
```

`doctor` must print `status: ready`. The text-only run writes a briefing under the output directory and does not call Telegram. Read that file and show the user a short summary.

When the user wants delivery:

```bash
ai-news run --text-only
```

Add audio only after `doctor` reports `ffmpeg` and `edge-tts` as present:

```bash
ai-news run
```

## Schedule

Use one scheduler, not two. After a successful delivered run, install cron:

```bash
0 * * * * /path/to/ai-news-agent/scripts/run_hourly.sh
```

Quiet hours default to 22:00–06:00 in the process timezone. The script skips the model during those hours.

## Rules

- Run `ai-news`. Do not write a new RSS client, prompt, or Telegram caller.
- If `doctor` prints `status: not_ready`, fix the listed problem before a live run.
- A missing Telegram token is fine for a local briefing. Say so, and pass `--no-deliver`.
- If audio tools are missing, pass `--text-only` instead of installing unrelated packages beyond `ffmpeg` and the Python dependencies.
- Feed edits belong in `ai_news_agent/data/feeds.json`, or in a file pointed to by `FEEDS_PATH`. An existing `config/feeds.json` overrides the packaged list.
- Do not deploy this repository as a Hostinger Node.js app or static website.

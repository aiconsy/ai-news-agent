"""LLM classification and summarization — Ollama primary, OpenRouter fallback.

v5.2: Keyword pre-classification BEFORE batch LLM. Junk keywords auto-LOW,
important keywords auto-HIGH/MEDIUM. Only ambiguous articles go to LLM.
Batch LLM in groups of 15.
"""

import json
import logging
import re
import time

import requests

from .config import (
    LLM_BASE_URL, LLM_API_KEY, MODEL_CLASSIFY, MODEL_SUMMARIZE,
    FALLBACK_BASE_URL, FALLBACK_API_KEY, FALLBACK_MODELS,
    OLLAMA_TIMEOUT, OLLAMA_CONNECT_TIMEOUT,
    GEOPOLITICS_KEYWORDS, TECH_KEYWORDS, FINANCE_KEYWORDS,
    HIGH_CAP,
)

log = logging.getLogger("ai_news_agent")

# ── Keyword Pre-Classification ────────────────────────────────────────────────
# Junk keywords: sports, gossip, entertainment → always LOW
JUNK_KEYWORDS = [
    # Sports
    "sports", "football", "basketball", "baseball", "soccer", "tennis",
    "golf", "hockey", "nfl", "nba", "mlb", "nhl", "olympic", "athlete",
    "tournament", "championship", "playoff", "super bowl", "world cup",
    "nascar", "f1", "formula 1", "boxing", "mma", "ufc", "wrestling",
    "cricket", "rugby", "premier league", "la liga", "champions league",
    # Celebrity gossip
    "celebrity", "gossip", "kardashian", "hollywood", "red carpet",
    "celebrity news", "paparazzi", "divorce", "breakup", "dating",
    "engagement", "wedding", "baby bump", "pregnancy rumor",
    # Entertainment
    "entertainment", "movie review", "tv show", "streaming", "netflix",
    "hulu", "disney+", "box office", "concert", "tour dates",
    "album release", "music video", "reality tv", "soap opera",
    "awards ceremony", "grammy", "oscar", "emmy", "golden globe",
    "celebrity chef", "cooking show", "game show", "talk show",
    # Lifestyle
    "lifestyle", "fashion", "beauty", "skincare", "workout routine",
    "diet tips", "travel destination", "recipe", "restaurant review",
    "home decor", "interior design", "gardening", "parenting tips",
    "relationship advice", "self-help", "wellness trend",
    # Product launches (minor)
    "product launch", "unboxing", "review roundup", "best of",
    "gift guide", "black friday", "cyber monday", "deal of the day",
]

# Important keywords → HIGH priority
IMPORTANT_KEYWORDS = {
    "high": [
        # War & conflict
        "war", "invasion", "military strike", "airstrike", "missile attack",
        "nuclear", "ceasefire", "peace talks", "humanitarian crisis",
        "genocide", "ethnic cleansing", "war crime", "refugee crisis",
        "escalation", "retaliation", "troop deployment", "mobilization",
        # Geopolitics
        "nato", "un security council", "summit", "sanctions", "embargo",
        "trade war", "tariff", "diplomatic crisis", "expel ambassador",
        "annexation", "sovereignty", "territorial claim", "border dispute",
        "regime change", "coup", "political crisis", "no-confidence",
        # Economy & markets
        "market crash", "recession", "bank failure", "interest rate",
        "fed decision", "inflation crisis", "currency collapse",
        "sovereign debt", "default", "bailout", "stimulus",
        # Technology & science
        "breakthrough", "landmark", "first-ever", "major discovery",
        "ai model", "quantum computing", "fusion energy", "semiconductor",
        "cyberattack", "ransomware", "zero-day", "data breach",
        # Health
        "pandemic", "epidemic", "outbreak", "vaccine", "fda approval",
        "drug recall", "public health emergency",
    ],
    "medium": [
        # Geopolitics
        "diplomacy", "foreign policy", "treaty", "alliance", "election",
        "parliament", "congress", "senate", "bill", "legislation",
        "regulation", "policy", "minister", "secretary",
        # Economy
        "gdp", "trade", "investment", "merger", "acquisition",
        "earnings", "quarterly", "market", "bond", "yield",
        "inflation", "deflation", "imf", "world bank",
        # Technology
        "ai", "artificial intelligence", "machine learning", "llm",
        "chip", "semiconductor", "platform", "startup", "funding",
        "privacy", "regulation tech", "blockchain",
        # Science
        "research", "study", "climate", "emissions", "satellite",
        "space", "rocket", "biotech", "genome", "clinical trial",
    ],
}


def _keyword_classify(title: str, summary: str = "") -> str | None:
    """Pre-classify an article using keywords.

    Returns 'LOW', 'HIGH', 'MEDIUM', or None (needs LLM).
    Checks junk first (→LOW), then high (→HIGH), then medium (→MEDIUM).
    """
    text = (title + " " + summary).lower()

    # Check junk first — always LOW
    for kw in JUNK_KEYWORDS:
        if kw in text:
            return "LOW"

    # Check high-priority keywords
    for kw in IMPORTANT_KEYWORDS["high"]:
        if kw in text:
            return "HIGH"

    # Check medium-priority keywords
    for kw in IMPORTANT_KEYWORDS["medium"]:
        if kw in text:
            return "MEDIUM"

    # No keyword match — needs LLM
    return None


def _detect_category(title: str, summary: str = "") -> str:
    """Detect article category from keywords."""
    text = (title + " " + summary).lower()
    cats = []
    if any(kw in text for kw in GEOPOLITICS_KEYWORDS):
        cats.append("Geopolitics")
    if any(kw in text for kw in TECH_KEYWORDS):
        cats.append("Tech & AI")
    if any(kw in text for kw in FINANCE_KEYWORDS):
        cats.append("Finance")
    if not cats:
        cats.append("General")
    return ", ".join(cats)


def _call_llm(prompt: str, model: str, max_tokens: int = 2048, temperature: float = 0.3, use_fallback: bool = False) -> str:
    """Call LLM API — Ollama primary, OpenRouter fallback.

    Returns the response text or empty string on failure.
    """
    # Try primary (Ollama)
    if not use_fallback:
        try:
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            headers = {"Content-Type": "application/json"}
            if LLM_API_KEY:
                headers["Authorization"] = f"Bearer {LLM_API_KEY}"

            resp = requests.post(
                LLM_BASE_URL,
                json=payload,
                headers=headers,
                timeout=OLLAMA_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()

            # Ollama format
            if "message" in data:
                return data["message"].get("content", "")
            # OpenAI-compatible format
            if "choices" in data:
                return data["choices"][0].get("message", {}).get("content", "")
            return str(data)

        except Exception as e:
            log.warning(f"Primary LLM failed ({model}): {e}")
            if not use_fallback:
                log.info("Trying fallback provider...")

    # Try fallback (OpenRouter)
    try:
        for fb_model in FALLBACK_MODELS:
            try:
                payload = {
                    "model": fb_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {FALLBACK_API_KEY}",
                }
                resp = requests.post(
                    FALLBACK_BASE_URL,
                    json=payload,
                    headers=headers,
                    timeout=OLLAMA_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if content:
                    return content
            except Exception as e:
                log.warning(f"Fallback model {fb_model} failed: {e}")
                continue
    except Exception as e:
        log.error(f"All fallback models failed: {e}")

    return ""


def _parse_batch_response(response: str, count: int) -> list[str]:
    """Parse batch LLM response into list of priorities.

    Expected format: one priority per line (HIGH/MEDIUM/LOW).
    """
    priorities = []
    lines = response.strip().split("\n")
    for line in lines:
        line = line.strip().upper()
        # Extract just the priority word
        for p in ["HIGH", "MEDIUM", "LOW"]:
            if p in line:
                priorities.append(p)
                break
        if len(priorities) >= count:
            break

    # Pad if we didn't get enough
    while len(priorities) < count:
        priorities.append("MEDIUM")

    return priorities[:count]


def _batch_llm_classify(articles: list[dict], batch_size: int = 15) -> list[str]:
    """Classify a list of articles using batch LLM calls.

    Sends articles in batches of 15 to the LLM, which returns
    HIGH/MEDIUM/LOW for each.
    """
    all_priorities = []

    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]
        lines = []
        for j, article in enumerate(batch):
            title = article.get("title", "")[:200]
            summary = article.get("summary", "")[:300]
            lines.append(f"{j+1}. {title} | {summary}")
        numbered = "\n".join(lines)

        prompt = f"""You are a news priority classifier. Classify each article as HIGH, MEDIUM, or LOW.

Rules:
- HIGH: Major world events, wars, geopolitical crises, market crashes, significant tech breakthroughs, public health emergencies
- MEDIUM: Important but not urgent — policy changes, routine diplomacy, earnings reports, tech updates
- LOW: Minor news, local interest, routine updates
- Sports, celebrity gossip, entertainment, lifestyle, and product launch stories are ALWAYS low.

Articles:
{numbered}

Respond with one word per line (HIGH, MEDIUM, or LOW). {len(batch)} lines:"""

        result = _call_llm(prompt, model=MODEL_CLASSIFY, max_tokens=512, temperature=0.2)
        if result:
            priorities = _parse_batch_response(result, len(batch))
            all_priorities.extend(priorities)
        else:
            # LLM failed — default all to MEDIUM
            all_priorities.extend(["MEDIUM"] * len(batch))

    return all_priorities


def classify_article(title: str, summary: str = "") -> dict:
    """Classify an article by topic and priority (keyword-only, no LLM).

    Returns dict with 'category', 'priority', 'keywords'.
    """
    text = (title + " " + summary).lower()

    matched_cats = []
    if any(kw in text for kw in GEOPOLITICS_KEYWORDS):
        matched_cats.append("Geopolitics")
    if any(kw in text for kw in TECH_KEYWORDS):
        matched_cats.append("Tech & AI")
    if any(kw in text for kw in FINANCE_KEYWORDS):
        matched_cats.append("Finance")

    if not matched_cats:
        matched_cats.append("General")

    # Determine priority based on keywords and matches
    priority = "MEDIUM"
    if "Geopolitics" in matched_cats and any(w in text for w in ["war", "conflict", "nuclear", "invasion", "sanctions"]):
        priority = "HIGH"
    elif "Tech & AI" in matched_cats and any(w in text for w in ["breakthrough", "landmark", "major", "first-ever"]):
        priority = "HIGH"
    elif len(matched_cats) >= 2:
        priority = "HIGH"

    return {
        "category": ", ".join(matched_cats),
        "priority": priority,
        "keywords": matched_cats,
    }


def classify_articles(articles: list[dict]) -> list[dict]:
    """Classify all articles by topic and priority.

    v5.2: Keyword pre-classification FIRST, then batch LLM only for
    articles that keywords couldn't classify.
    """
    # Phase 1: Keyword pre-classification
    needs_llm = []
    kw_high = 0
    kw_medium = 0
    kw_low = 0

    for article in articles:
        title = article.get("title", "")
        summary = article.get("summary", "")
        category = _detect_category(title, summary)
        article["category"] = category

        priority = _keyword_classify(title, summary)
        if priority is not None:
            article["priority"] = priority
            if priority == "HIGH":
                kw_high += 1
            elif priority == "MEDIUM":
                kw_medium += 1
            else:
                kw_low += 1
        else:
            # Needs LLM
            needs_llm.append(article)

    log.info(f"Keyword pre-classify: {kw_high} HIGH, {kw_medium} MEDIUM, {kw_low} LOW, {len(needs_llm)} need LLM")

    # Phase 2: Batch LLM classification for ambiguous articles
    if needs_llm:
        llm_priorities = _batch_llm_classify(needs_llm)
        for article, priority in zip(needs_llm, llm_priorities):
            article["priority"] = priority
        log.info(f"LLM classified {len(needs_llm)} articles")

    # Cap HIGH articles
    high_count = sum(1 for a in articles if a.get("priority") == "HIGH")
    if high_count > HIGH_CAP:
        log.info(f"Capping HIGH articles: {high_count} → {HIGH_CAP}")
        capped = 0
        for article in reversed(articles):
            if article.get("priority") == "HIGH" and capped < (high_count - HIGH_CAP):
                article["priority"] = "MEDIUM"
                capped += 1

    # Sort: HIGH first, then MEDIUM, then LOW; within same priority, lower tier first
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    articles.sort(key=lambda a: (priority_order.get(a.get("priority", "MEDIUM"), 1), a.get("tier", 3)))

    return articles


def summarize_article(title: str, content: str, source: str = "") -> str:
    """Summarize a deep-read article using LLM."""
    prompt = f"""Summarize this article in 2-3 concise sentences focusing on key facts and implications.

Title: {title}
Source: {source}

{content[:3000]}

Summary:"""

    result = _call_llm(prompt, model=MODEL_SUMMARIZE, max_tokens=256, temperature=0.2)
    return result.strip() if result else title
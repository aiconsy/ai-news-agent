"""Topic and priority ranking.

Obvious stories are ranked with word-boundary keywords. Only a capped set of
ambiguous headlines is sent to a model, in short batches, so a busy hour
cannot turn into hundreds of classification calls.
"""

import logging
import re

import requests

from .config import (
    CLASSIFY_BATCH_SIZE,
    FALLBACK_API_KEY,
    FALLBACK_BASE_URL,
    FALLBACK_MODELS,
    FINANCE_KEYWORDS,
    GEOPOLITICS_KEYWORDS,
    HIGH_CAP,
    LLM_API_KEY,
    LLM_BASE_URL,
    MAX_LLM_CLASSIFY,
    MODEL_CLASSIFY,
    MODEL_SUMMARIZE,
    OLLAMA_CONNECT_TIMEOUT,
    OLLAMA_TIMEOUT,
    TECH_KEYWORDS,
)

log = logging.getLogger("ai_news_agent")

# Sports, gossip, and lifestyle. Matched with word boundaries so "war" does
# not fire inside "warning" and "ai" does not fire inside "said".
JUNK_KEYWORDS = [
    "sports", "football", "basketball", "baseball", "soccer", "tennis",
    "golf", "hockey", "nfl", "nba", "mlb", "nhl", "olympic", "olympics", "athlete",
    "tournament", "championship", "playoff", "super bowl", "world cup",
    "nascar", "f1", "formula 1", "boxing", "mma", "ufc", "wrestling",
    "cricket", "rugby", "premier league", "la liga", "champions league",
    "celebrity", "gossip", "kardashian", "hollywood", "red carpet",
    "paparazzi", "breakup", "baby bump",
    "movie review", "tv show", "box office", "concert", "tour dates",
    "entertainment", "album release", "music video", "reality tv", "soap opera",
    "awards ceremony", "grammy", "oscar", "emmy", "golden globe",
    "lifestyle", "fashion", "skincare", "workout routine",
    "diet tips", "recipe", "restaurant review",
    "home decor", "interior design", "gardening", "parenting tips",
    "relationship advice", "self-help",
    "unboxing", "gift guide", "black friday", "cyber monday", "deal of the day",
]

IMPORTANT_KEYWORDS = {
    "high": [
        "war", "invasion", "military strike", "airstrike", "missile attack",
        "nuclear", "ceasefire", "peace talks", "humanitarian crisis",
        "genocide", "ethnic cleansing", "war crime", "refugee crisis",
        "escalation", "retaliation", "troop deployment", "mobilization",
        "nato", "un security council", "summit", "sanctions", "embargo",
        "trade war", "tariff", "diplomatic crisis", "expel ambassador",
        "annexation", "sovereignty", "territorial claim", "border dispute",
        "regime change", "coup", "political crisis", "no-confidence",
        "market crash", "recession", "bank failure", "interest rate",
        "fed decision", "inflation crisis", "currency collapse",
        "sovereign debt", "default", "bailout", "stimulus",
        "breakthrough", "landmark", "first-ever", "major discovery",
        "ai model", "quantum computing", "fusion energy", "semiconductor",
        "cyberattack", "ransomware", "zero-day", "data breach",
        "pandemic", "epidemic", "outbreak", "vaccine", "fda approval",
        "drug recall", "public health emergency",
    ],
    "medium": [
        "diplomacy", "foreign policy", "treaty", "alliance", "election",
        "parliament", "congress", "senate", "legislation",
        "regulation", "minister", "secretary",
        "gdp", "merger", "acquisition", "earnings", "quarterly",
        "inflation", "deflation", "imf", "world bank",
        "artificial intelligence", "machine learning", "llm", "openai", "chatgpt",
        "chip", "semiconductor", "startup", "funding round",
        "data privacy", "blockchain",
        "climate", "emissions", "satellite", "rocket", "biotech", "genome",
        "clinical trial", "ukraine", "gaza", "taiwan",
    ],
}

_PRIORITY_RE = re.compile(r"\b(HIGH|MEDIUM|LOW|H|M|L)\b", re.I)
_PRIORITY_MAP = {
    "HIGH": "HIGH",
    "H": "HIGH",
    "MEDIUM": "MEDIUM",
    "M": "MEDIUM",
    "LOW": "LOW",
    "L": "LOW",
}
_THINK_RE = re.compile(r"<think>.*?</think>", re.I | re.S)


def _compile_keywords(keywords: list[str]) -> list[re.Pattern[str]]:
    patterns = []
    for keyword in keywords:
        parts = [re.escape(part) for part in keyword.lower().split()]
        patterns.append(re.compile(r"(?<!\w)" + r"\s+".join(parts) + r"(?!\w)"))
    return patterns


_JUNK_PATTERNS = _compile_keywords(JUNK_KEYWORDS)
_HIGH_PATTERNS = _compile_keywords(IMPORTANT_KEYWORDS["high"])
_MEDIUM_PATTERNS = _compile_keywords(IMPORTANT_KEYWORDS["medium"])
_GEO_PATTERNS = _compile_keywords(GEOPOLITICS_KEYWORDS)
_TECH_PATTERNS = _compile_keywords(TECH_KEYWORDS)
_FINANCE_PATTERNS = _compile_keywords(FINANCE_KEYWORDS)


def _matches_any(text: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _keyword_classify(title: str, summary: str = "") -> str | None:
    """Return LOW, HIGH, MEDIUM, or None when a model should decide."""
    text = f"{title} {summary}".lower()
    if _matches_any(text, _JUNK_PATTERNS):
        return "LOW"
    if _matches_any(text, _HIGH_PATTERNS):
        return "HIGH"
    if _matches_any(text, _MEDIUM_PATTERNS):
        return "MEDIUM"
    return None


def _detect_category(title: str, summary: str = "") -> str:
    """Label a story from its headline and deck. Feed labels are hints only."""
    text = f"{title} {summary}".lower()
    cats = []
    if _matches_any(text, _GEO_PATTERNS):
        cats.append("Geopolitics")
    if _matches_any(text, _TECH_PATTERNS):
        cats.append("Tech & AI")
    if _matches_any(text, _FINANCE_PATTERNS):
        cats.append("Finance")
    if not cats:
        cats.append("General")
    return ", ".join(cats)


def _uses_openai_payload(url: str) -> bool:
    """Native Ollama /api/chat ignores max_tokens. /v1 and OpenRouter do not."""
    lowered = url.lower()
    return lowered.rstrip("/").endswith("chat/completions") or "openrouter.ai" in lowered or "/v1/" in lowered


def build_llm_payload(url: str, model: str, prompt: str, max_tokens: int, temperature: float) -> dict:
    """Build a request body for either native Ollama or an OpenAI-compatible API."""
    messages = [{"role": "user", "content": prompt}]
    if _uses_openai_payload(url):
        return {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
    return {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }


def _strip_thinking(text: str) -> str:
    """Drop chain-of-thought blocks so they are not spoken or classified."""
    return _THINK_RE.sub("", text).strip()


def _response_text(data: dict) -> str:
    if "message" in data and isinstance(data["message"], dict):
        return str(data["message"].get("content") or "")
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") or {}
        return str(message.get("content") or "")
    return ""


def _call_llm(
    prompt: str,
    model: str,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    timeout: int | None = None,
    use_fallback: bool = False,
) -> str:
    """Call the primary model, then each configured fallback. Empty string on failure."""
    read_timeout = timeout or OLLAMA_TIMEOUT
    request_timeout = (OLLAMA_CONNECT_TIMEOUT, read_timeout)

    if not use_fallback:
        try:
            headers = {"Content-Type": "application/json"}
            if LLM_API_KEY:
                headers["Authorization"] = f"Bearer {LLM_API_KEY}"
            resp = requests.post(
                LLM_BASE_URL,
                json=build_llm_payload(LLM_BASE_URL, model, prompt, max_tokens, temperature),
                headers=headers,
                timeout=request_timeout,
            )
            resp.raise_for_status()
            content = _strip_thinking(_response_text(resp.json()))
            if content:
                return content
            log.warning("Primary LLM returned an empty response (%s)", model)
        except Exception as exc:
            log.warning("Primary LLM failed (%s): %s", model, exc.__class__.__name__)

    if not FALLBACK_API_KEY or not FALLBACK_MODELS:
        log.info("No fallback provider configured")
        return ""

    for fb_model in FALLBACK_MODELS:
        try:
            resp = requests.post(
                FALLBACK_BASE_URL,
                json=build_llm_payload(FALLBACK_BASE_URL, fb_model, prompt, max_tokens, temperature),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {FALLBACK_API_KEY}",
                },
                timeout=request_timeout,
            )
            resp.raise_for_status()
            content = _strip_thinking(_response_text(resp.json()))
            if content:
                return content
        except Exception as exc:
            log.warning("Fallback model %s failed: %s", fb_model, exc.__class__.__name__)
    return ""


def _parse_batch_response(response: str, count: int) -> list[str]:
    """Parse H/M/L (or HIGH/MEDIUM/LOW) lines into exactly `count` priorities."""
    response = _strip_thinking(response)
    lines = [line.strip() for line in response.splitlines() if line.strip()]
    if len(lines) <= 2:
        found = _PRIORITY_RE.findall(response)
    else:
        found = []
        for line in lines:
            hits = _PRIORITY_RE.findall(line)
            if hits:
                found.append(hits[0])
    priorities = [_PRIORITY_MAP[token.upper()] for token in found]
    if len(priorities) < count:
        priorities.extend(["MEDIUM"] * (count - len(priorities)))
    return priorities[:count]


def _batch_llm_classify(articles: list[dict], batch_size: int = CLASSIFY_BATCH_SIZE) -> list[str]:
    """Classify a capped list. One letter per story keeps the output tiny."""
    all_priorities: list[str] = []
    for start in range(0, len(articles), batch_size):
        batch = articles[start:start + batch_size]
        lines = []
        for index, article in enumerate(batch, 1):
            title = (article.get("title") or "").replace("\n", " ")[:140]
            summary = (article.get("summary") or "").replace("\n", " ")[:160]
            lines.append(f"{index}. {title} | {summary}")
        prompt = (
            "Rank each item H (must know), M (notable), or L "
            "(skip: sports, gossip, entertainment, lifestyle, local, routine).\n"
            "H only for war, crises, major markets, security, or real science/tech breakthroughs.\n"
            f"Reply with exactly {len(batch)} lines, one of H/M/L, and no other text.\n\n"
            + "\n".join(lines)
        )
        result = _call_llm(
            prompt,
            model=MODEL_CLASSIFY,
            max_tokens=max(32, 6 * len(batch)),
            temperature=0.0,
            timeout=min(OLLAMA_TIMEOUT, 45),
        )
        if result:
            all_priorities.extend(_parse_batch_response(result, len(batch)))
        else:
            all_priorities.extend("MEDIUM" if article.get("tier", 3) <= 2 else "LOW" for article in batch)
    return all_priorities


def classify_article(title: str, summary: str = "") -> dict:
    """Keyword-only classification, used by tests and offline callers."""
    priority = _keyword_classify(title, summary) or "MEDIUM"
    category = _detect_category(title, summary)
    return {"category": category, "priority": priority, "keywords": category.split(", ")}


def classify_articles(articles: list[dict], stats: dict | None = None) -> list[dict]:
    """Rank every article. The model sees only a bounded ambiguous slice."""
    needs_llm: list[dict] = []
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}

    for article in articles:
        title = article.get("title", "")
        summary = article.get("summary", "")
        article["category"] = _detect_category(title, summary)
        priority = _keyword_classify(title, summary)
        if priority is None and article.get("tier", 3) == 1:
            # Wire copy that missed the keyword lists is still worth reading,
            # and it does not need a model call to say so.
            priority = "MEDIUM"
        if priority is not None:
            article["priority"] = priority
            counts[priority] += 1
        else:
            needs_llm.append(article)

    needs_llm.sort(key=lambda article: (article.get("tier", 3), -(article.get("published_ts") or 0)))
    budget = needs_llm[:MAX_LLM_CLASSIFY]
    overflow = needs_llm[MAX_LLM_CLASSIFY:]
    for article in overflow:
        article["priority"] = "LOW"
        counts["LOW"] += 1

    log.info(
        "Keyword pre-classify: %d HIGH, %d MEDIUM, %d LOW, %d go to LLM, %d dropped without LLM",
        counts["HIGH"],
        counts["MEDIUM"],
        counts["LOW"],
        len(budget),
        len(overflow),
    )

    if budget:
        for article, priority in zip(budget, _batch_llm_classify(budget)):
            article["priority"] = priority
        log.info("LLM classified %d articles", len(budget))

    high_articles = [article for article in articles if article.get("priority") == "HIGH"]
    if len(high_articles) > HIGH_CAP:
        high_articles.sort(key=lambda article: (article.get("tier", 3), -(len(article.get("summary") or ""))))
        demoted = 0
        for article in reversed(high_articles):
            if demoted >= len(high_articles) - HIGH_CAP:
                break
            article["priority"] = "MEDIUM"
            demoted += 1
        log.info("Capped HIGH articles: %d → %d", len(high_articles), HIGH_CAP)

    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    articles.sort(
        key=lambda article: (
            priority_order.get(article.get("priority", "LOW"), 2),
            article.get("tier", 3),
            -(article.get("published_ts") or 0),
        )
    )
    if stats is not None:
        stats["llm_classify_articles"] = len(budget)
        stats["llm_classify_batches"] = (len(budget) + CLASSIFY_BATCH_SIZE - 1) // CLASSIFY_BATCH_SIZE if budget else 0
        stats["ranked_without_llm"] = len(articles) - len(budget)
    return articles


def summarize_article(title: str, content: str, source: str = "") -> str:
    """Summarize one article. The pipeline uses extractive leads instead."""
    prompt = (
        "Summarize in 2 sentences. Facts and why it matters. No preamble.\n\n"
        f"Title: {title}\nSource: {source}\n\n{content[:2000]}"
    )
    result = _call_llm(prompt, model=MODEL_SUMMARIZE, max_tokens=180, temperature=0.2)
    return result.strip() if result else title

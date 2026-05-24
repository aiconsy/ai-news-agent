"""LLM classification and summarization — Ollama primary, OpenRouter fallback."""

import json
import logging
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


def classify_article(title: str, summary: str = "") -> dict:
    """Classify an article by topic and priority.
    
    Returns dict with 'category', 'priority', 'keywords'.
    """
    # First try keyword matching (fast, no LLM needed)
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
    
    Uses fast keyword matching first, falls back to LLM for ambiguous cases.
    """
    high_count = 0
    for article in articles:
        classification = classify_article(
            article.get("title", ""),
            article.get("summary", ""),
        )
        article["category"] = classification["category"]
        article["priority"] = classification["priority"]

        # Cap HIGH articles
        if article["priority"] == "HIGH":
            high_count += 1
            if high_count > HIGH_CAP:
                article["priority"] = "MEDIUM"

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
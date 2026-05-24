"""RSS feed fetching and parsing."""

import json
import logging
import ssl
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

import feedparser

from .config import FEEDS_PATH, SOURCE_TIERS

log = logging.getLogger("ai_news_agent")


def load_feeds(feeds_path: Path | None = None) -> list[dict]:
    """Load RSS feeds from JSON config file."""
    path = feeds_path or FEEDS_PATH
    if not path.exists():
        log.error(f"Feeds file not found: {path}")
        return []
    with open(path) as f:
        data = json.load(f)
    feeds = data.get("feeds", data) if isinstance(data, dict) else data
    log.info(f"Loaded {len(feeds)} feeds from {path}")
    return feeds


def classify_source_tier(source_name: str) -> int:
    """Determine the quality tier of a news source (1=best, 3=default)."""
    name_lower = source_name.lower()
    for tier, keywords in SOURCE_TIERS.items():
        for keyword in keywords:
            if keyword in name_lower:
                return tier
    return 3


def fetch_feed(url: str, timeout: int = 30) -> list[dict]:
    """Fetch and parse a single RSS feed. Returns list of article dicts."""
    articles = []
    try:
        # Use feedparser with SSL fallback
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        d = feedparser.parse(url, request_headers={
            "User-Agent": "Mozilla/5.0 (AI-News-Bot/1.0; +https://github.com/ai-news-agent)"
        })

        if d.bozo and not d.entries:
            log.warning(f"Feed error {url}: {d.bozo_exception}")
            return []

        for entry in d.entries[:10]:  # Cap at 10 per feed
            title = entry.get("title", "").strip()
            link = entry.get("link", "")
            summary = entry.get("summary", entry.get("description", ""))

            if not title or not link:
                continue

            # Strip HTML from summary
            import re
            summary = re.sub(r"<[^>]+>", "", summary)[:500]

            articles.append({
                "title": title,
                "url": link,
                "summary": summary,
                "source": d.feed.get("title", url),
                "published": entry.get("published", entry.get("updated", "")),
            })

    except Exception as e:
        log.warning(f"Feed fetch failed {url}: {e}")

    return articles


def fetch_all_feeds(feeds: list[dict], delay: float = 0.3) -> list[dict]:
    """Fetch all RSS feeds with rate limiting. Returns deduplicated article list."""
    all_articles = []
    seen_urls = set()

    for i, feed_config in enumerate(feeds):
        url = feed_config.get("url", "")
        category = feed_config.get("category", "World News")
        tier = feed_config.get("tier", classify_source_tier(feed_config.get("name", "")))

        if not url:
            continue

        articles = fetch_feed(url)
        for article in articles:
            if article["url"] in seen_urls:
                continue
            seen_urls.add(article["url"])
            article["category"] = category
            article["tier"] = tier
            all_articles.append(article)

        if (i + 1) % 50 == 0:
            log.info(f"Fetched {i + 1}/{len(feeds)} feeds, {len(all_articles)} articles so far")

        time.sleep(delay)  # Rate limit

    log.info(f"Fetched {len(feeds)} feeds, {len(all_articles)} unique articles")
    return all_articles
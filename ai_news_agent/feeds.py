"""RSS feed fetching and parsing."""

import json
import logging
import re
import ssl
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import feedparser

from .config import FEEDS_PATH, SOURCE_TIERS

log = logging.getLogger("ai_news_agent")

USER_AGENT = "Mozilla/5.0 (AI-News-Bot/1.0; +https://github.com/ai-news-agent)"


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


def _fetch_raw(url: str, timeout: int = 15) -> bytes | None:
    """Fetch raw bytes from a URL using urllib with User-Agent header.

    Never let feedparser fetch directly — always pre-fetch with urllib
    so we control timeouts, headers, and SSL behavior.
    """
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        })
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        log.warning(f"HTTP {e.code} fetching {url}: {e.reason}")
    except urllib.error.URLError as e:
        log.warning(f"URL error fetching {url}: {e.reason}")
    except Exception as e:
        log.warning(f"Fetch error {url}: {e}")
    return None


def fetch_feed(url: str, timeout: int = 15) -> list[dict]:
    """Fetch and parse a single RSS feed. Returns list of article dicts.

    Pre-fetches raw bytes with urllib.request, then passes bytes to
    feedparser.parse(). Never calls feedparser.parse(url) directly.
    """
    articles = []
    raw = _fetch_raw(url, timeout=timeout)
    if raw is None:
        return []

    try:
        d = feedparser.parse(raw)
    except Exception as e:
        log.warning(f"feedparser parse failed for {url}: {e}")
        return []

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
        summary = re.sub(r"<[^>]+>", "", summary)[:500]

        articles.append({
            "title": title,
            "url": link,
            "summary": summary,
            "source": d.feed.get("title", url),
            "published": entry.get("published", entry.get("updated", "")),
        })

    return articles


def _fetch_one(feed_config: dict) -> list[dict]:
    """Fetch a single feed config, returning articles with category/tier set."""
    url = feed_config.get("url", "")
    category = feed_config.get("category", "World News")
    tier = feed_config.get("tier", classify_source_tier(feed_config.get("name", "")))

    if not url:
        return []

    articles = fetch_feed(url)
    for article in articles:
        article["category"] = category
        article["tier"] = tier
    return articles


def fetch_all_feeds(feeds: list[dict], delay: float = 0.0) -> list[dict]:
    """Fetch all RSS feeds in parallel using ThreadPoolExecutor.

    Returns deduplicated article list (by URL).
    """
    all_articles = []
    seen_urls = set()

    # Fetch in parallel — ThreadPoolExecutor with up to 20 workers
    max_workers = min(20, len(feeds)) if feeds else 1
    completed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_config = {
            executor.submit(_fetch_one, fc): fc for fc in feeds if fc.get("url")
        }

        for future in as_completed(future_to_config):
            completed += 1
            feed_config = future_to_config[future]
            try:
                articles = future.result()
            except Exception as e:
                log.warning(f"Feed fetch failed {feed_config.get('url', '?')}: {e}")
                continue

            for article in articles:
                if article["url"] in seen_urls:
                    continue
                seen_urls.add(article["url"])
                all_articles.append(article)

            if completed % 50 == 0:
                log.info(f"Fetched {completed}/{len(feeds)} feeds, {len(all_articles)} articles so far")

    log.info(f"Fetched {len(feeds)} feeds, {len(all_articles)} unique articles")
    return all_articles
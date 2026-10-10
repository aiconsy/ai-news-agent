"""RSS feed fetching and parsing."""

import calendar
import json
import logging
import re
import ssl
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import feedparser

from .config import FEEDS_PATH, MAX_ARTICLE_AGE_HOURS, MAX_ITEMS_PER_FEED, SOURCE_TIERS

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
    unique = []
    seen_urls: set[str] = set()
    for feed in feeds:
        url = (feed.get("url") or "").strip()
        key = url.rstrip("/")
        if not key or key in seen_urls:
            continue
        seen_urls.add(key)
        unique.append(feed)
    dropped = len(feeds) - len(unique)
    if dropped:
        log.info(f"Dropped {dropped} duplicate feed URLs")
    log.info(f"Loaded {len(unique)} feeds from {path}")
    return unique


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
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        log.warning(f"Skipping non-http feed URL: {url}")
        return None
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        })
        context = ssl.create_default_context()
        context.check_hostname = False
        # Certificate verification stays ON. Disabling it let anyone on the path
        # tamper with feed responses and inject content into the briefing.
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
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

    for entry in d.entries[:MAX_ITEMS_PER_FEED]:
        title = entry.get("title", "").strip()
        link = entry.get("link", "")
        summary = entry.get("summary", entry.get("description", ""))

        if not title or not link:
            continue

        # Strip HTML from summary
        summary = re.sub(r"<[^>]+>", "", summary)[:500]
        published_struct = entry.get("published_parsed") or entry.get("updated_parsed")
        published_ts = calendar.timegm(published_struct) if published_struct else None

        articles.append({
            "title": title,
            "url": link,
            "summary": summary,
            "source": d.feed.get("title", url),
            "published": entry.get("published", entry.get("updated", "")),
            "published_ts": published_ts,
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


def filter_fresh(
    articles: list[dict],
    max_age_hours: int | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """Drop items older than the age window. Undated items are kept.

    A zero or negative window disables the filter. Dated items more than an
    hour in the future are dropped as clock-skew junk.
    """
    if max_age_hours is None:
        max_age_hours = MAX_ARTICLE_AGE_HOURS
    if max_age_hours <= 0:
        return list(articles)

    now_ts = (now or datetime.now(timezone.utc)).timestamp()
    max_age = max_age_hours * 3600
    kept = []
    dropped = 0
    for article in articles:
        published_ts = article.get("published_ts")
        if published_ts and (now_ts - published_ts > max_age or published_ts - now_ts > 3600):
            dropped += 1
            continue
        kept.append(article)
    if dropped:
        log.info(f"Age filter: dropped {dropped} articles older than {max_age_hours}h")
    return kept


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

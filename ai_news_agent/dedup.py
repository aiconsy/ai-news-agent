"""Article deduplication — smart windowed dedup.

v5.2: Smart dedup with different windows:
- 12h window for static stories (skip repeats)
- 2h window for developing stories (allow updates)
- DEVELOPING_KEYWORDS list to identify developing stories
- Detailed logging with new/developing/skipped counts
"""

import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher

from .config import DEDUP_THRESHOLD, DEDUP_HOURS
from .db import is_duplicate, mark_seen, _get_conn, _title_hash

log = logging.getLogger("ai_news_agent")

# Keywords that indicate a developing/breaking story — allow more frequent updates
DEVELOPING_KEYWORDS = [
    "breaking", "developing", "update", "live", "latest",
    "ongoing", "unfolding", "just in", "urgent",
    "breaking news", "news alert", "bulletin",
    "situation", "evolving", "in progress",
    "attack", "invasion", "crisis", "emergency",
    "ceasefire", "negotiation", "summit", "summit talks",
    "protest", "coup", "uprising", "martial law",
    "market crash", "crash", "meltdown",
    "outbreak", "pandemic", "evacuation",
]

# Dedup windows
STATIC_WINDOW_HOURS = 12
DEVELOPING_WINDOW_HOURS = 2


def _is_developing(title: str, summary: str = "") -> bool:
    """Check if an article is a developing/breaking story."""
    text = (title + " " + summary).lower()
    for kw in DEVELOPING_KEYWORDS:
        if kw in text:
            return True
    return False


def _is_duplicate_within(
    title: str,
    conn: sqlite3.Connection,
    window_hours: int,
) -> bool:
    """Check if a headline was seen within the given window (hours)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    url_hash = _title_hash(title)

    # Exact hash match
    row = conn.execute(
        "SELECT 1 FROM headlines_seen WHERE url_hash = ? AND seen_at > ?",
        (url_hash, cutoff),
    ).fetchone()
    if row:
        return True

    # Fuzzy match against recent headlines in the window
    recent = conn.execute(
        "SELECT title FROM headlines_seen WHERE seen_at > ?", (cutoff,)
    ).fetchall()
    for (existing,) in recent:
        if SequenceMatcher(None, title.lower(), existing.lower()).ratio() >= DEDUP_THRESHOLD:
            return True

    return False


def deduplicate_articles(articles: list[dict], conn: sqlite3.Connection | None = None) -> list[dict]:
    """Remove duplicate articles using smart windowed dedup.

    Static stories: 12h window (skip repeats)
    Developing stories: 2h window (allow updates)

    Returns deduplicated list with detailed logging.
    """
    close = False
    if conn is None:
        conn = _get_conn()
        close = True

    unique = []
    new_count = 0
    developing_count = 0
    skipped_static = 0
    skipped_developing = 0

    try:
        for article in articles:
            title = article.get("title", "").strip()
            summary = article.get("summary", "")
            if not title:
                continue

            is_dev = _is_developing(title, summary)
            window = DEVELOPING_WINDOW_HOURS if is_dev else STATIC_WINDOW_HOURS

            if _is_duplicate_within(title, conn, window):
                if is_dev:
                    skipped_developing += 1
                    log.debug(f"Dedup skip (developing, {window}h): {title[:60]}")
                else:
                    skipped_static += 1
                    log.debug(f"Dedup skip (static, {window}h): {title[:60]}")
                continue

            unique.append(article)
            if is_dev:
                developing_count += 1
            else:
                new_count += 1

            mark_seen(
                title=title,
                url=article.get("url", ""),
                category=article.get("category", ""),
                priority=article.get("priority", "MEDIUM"),
                conn=conn,
            )

        log.info(
            f"Dedup: {len(articles)} → {len(unique)} articles "
            f"(new: {new_count}, developing: {developing_count}, "
            f"skipped static: {skipped_static}, skipped developing: {skipped_developing})"
        )
        return unique
    finally:
        if close:
            conn.close()
"""Article deduplication — exact hash + fuzzy matching."""

import logging
import sqlite3
from difflib import SequenceMatcher

from .config import DEDUP_THRESHOLD, DEDUP_HOURS
from .db import is_duplicate, mark_seen

log = logging.getLogger("ai_news_agent")


def deduplicate_articles(articles: list[dict], conn: sqlite3.Connection | None = None) -> list[dict]:
    """Remove duplicate articles using hash + fuzzy matching.
    
    Returns deduplicated list of articles not seen within DEDUP_HOURS.
    """
    unique = []
    for article in articles:
        title = article.get("title", "").strip()
        if not title:
            continue
        if is_duplicate(title, conn):
            log.debug(f"Dedup skip: {title[:60]}")
            continue
        unique.append(article)
        mark_seen(
            title=title,
            url=article.get("url", ""),
            category=article.get("category", ""),
            priority=article.get("priority", "MEDIUM"),
            conn=conn,
        )

    log.info(f"Dedup: {len(articles)} → {len(unique)} articles (removed {len(articles) - len(unique)})")
    return unique
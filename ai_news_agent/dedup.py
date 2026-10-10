"""Article deduplication — same-run clustering plus a time window.

Static stories are suppressed for DEDUP_HOURS. Developing stories use a
shorter window so a genuine update can land. Matching is on content tokens,
not raw character overlap, so shared words like "the" and "says" do not
glue unrelated headlines together.
"""

import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone

from .config import DEDUP_HOURS, DEDUP_THRESHOLD, DEVELOPING_WINDOW_HOURS
from .db import _get_conn, _title_hash, mark_seen

log = logging.getLogger("ai_news_agent")

# Phrases that mark a story still moving. Bare words like "update", "live",
# and "latest" match almost every homepage and used to reopen the window.
DEVELOPING_KEYWORDS = [
    "breaking", "developing", "just in", "unfolding",
    "breaking news", "news alert",
]

_STOPWORDS = frozenset(
    """
    a an the of to in on for and or with from by at as is are was were be been
    being this that it its their his her over into after before about amid than
    then also will would can could may might more most other per via not no nor
    but if so just up out off its
    """.split()
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_DEVELOPING_PATTERNS = [
    re.compile(r"(?<!\w)" + r"\s+".join(re.escape(part) for part in phrase.split()) + r"(?!\w)")
    for phrase in DEVELOPING_KEYWORDS
]


def _tokens(title: str) -> frozenset[str]:
    """Content words used for near-duplicate checks."""
    words = _TOKEN_RE.findall(title.lower())
    return frozenset(word for word in words if len(word) > 1 and word not in _STOPWORDS)


def _similar(left: frozenset[str], right: frozenset[str], threshold: float | None = None) -> bool:
    """True when two headlines are the same story.

    Jaccard catches reworded copies. Containment catches a short wire headline
    that is repeated with a longer tail ("...after summit").
    """
    if threshold is None:
        threshold = DEDUP_THRESHOLD
    if not left or not right:
        return False
    overlap = len(left & right)
    if overlap == 0:
        return False
    if overlap / len(left | right) >= threshold:
        return True
    shorter = min(len(left), len(right))
    return shorter >= 5 and overlap / shorter >= 0.9


def _is_developing(title: str, summary: str = "") -> bool:
    """True when the copy says the story is still breaking."""
    text = f"{title} {summary}".lower()
    return any(pattern.search(text) for pattern in _DEVELOPING_PATTERNS)


def cluster_articles(articles: list[dict]) -> tuple[list[dict], list[dict]]:
    """Collapse same-run copies of one story. Keep the best source.

    Returns (kept, suppressed). Suppressed items should still be marked seen
    so a later run does not revive the copy that was thrown away.
    """
    ranked = sorted(
        articles,
        key=lambda article: (article.get("tier", 3), -len(article.get("summary") or "")),
    )
    kept: list[dict] = []
    kept_tokens: list[frozenset[str]] = []
    suppressed: list[dict] = []
    for article in ranked:
        title = (article.get("title") or "").strip()
        if not title:
            continue
        tokens = _tokens(title)
        if any(_similar(tokens, previous) for previous in kept_tokens):
            suppressed.append(article)
            continue
        kept.append(article)
        kept_tokens.append(tokens)
    return kept, suppressed


def deduplicate_articles(articles: list[dict], conn: sqlite3.Connection | None = None) -> list[dict]:
    """Drop stories already briefed, and collapse copies inside this run."""
    close = False
    if conn is None:
        conn = _get_conn()
        close = True

    try:
        kept, suppressed = cluster_articles(articles)
        for article in suppressed:
            mark_seen(
                title=article.get("title", ""),
                url=article.get("url", ""),
                category=article.get("category", ""),
                priority=article.get("priority", "MEDIUM"),
                conn=conn,
            )

        now = datetime.now(timezone.utc)
        static_cutoff = now - timedelta(hours=DEDUP_HOURS)
        developing_cutoff = now - timedelta(hours=DEVELOPING_WINDOW_HOURS)
        min_cutoff = min(static_cutoff, developing_cutoff).isoformat()

        rows = conn.execute(
            "SELECT url_hash, title, seen_at FROM headlines_seen WHERE seen_at > ?",
            (min_cutoff,),
        ).fetchall()
        recent_hashes: dict[str, str] = {}
        recent_tokens: list[tuple[frozenset[str], str]] = []
        for url_hash, title, seen_at in rows:
            recent_hashes[url_hash] = seen_at
            recent_tokens.append((_tokens(title), seen_at))

        unique: list[dict] = []
        skipped_static = 0
        skipped_developing = 0
        developing_kept = 0

        for article in kept:
            title = (article.get("title") or "").strip()
            if not title:
                continue
            summary = article.get("summary", "")
            developing = _is_developing(title, summary)
            cutoff = (developing_cutoff if developing else static_cutoff).isoformat()
            tokens = _tokens(title)
            url_hash = _title_hash(title)
            seen_at = recent_hashes.get(url_hash)
            is_dup = bool(seen_at and seen_at > cutoff)
            if not is_dup:
                is_dup = any(stamp > cutoff and _similar(tokens, previous) for previous, stamp in recent_tokens)

            if is_dup:
                if developing:
                    skipped_developing += 1
                else:
                    skipped_static += 1
                continue

            unique.append(article)
            if developing:
                developing_kept += 1
            seen_stamp = now.isoformat()
            recent_hashes[url_hash] = seen_stamp
            recent_tokens.append((tokens, seen_stamp))
            mark_seen(
                title=title,
                url=article.get("url", ""),
                category=article.get("category", ""),
                priority=article.get("priority", "MEDIUM"),
                conn=conn,
            )

        log.info(
            "Dedup: %d → %d articles (clustered out: %d, new: %d, developing: %d, "
            "skipped static: %d, skipped developing: %d)",
            len(articles),
            len(unique),
            len(suppressed),
            len(unique) - developing_kept,
            developing_kept,
            skipped_static,
            skipped_developing,
        )
        return unique
    finally:
        if close:
            conn.close()

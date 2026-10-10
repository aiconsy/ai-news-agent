"""SQLite storage for headline dedup, articles, and briefing history."""

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone

from .config import DB_PATH, DEDUP_HOURS


def _get_conn() -> sqlite3.Connection:
    """Get a connection to the news database, creating tables if needed."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS headlines_seen (
            url_hash TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            url TEXT,
            seen_at TEXT NOT NULL,
            category TEXT,
            priority TEXT DEFAULT 'MEDIUM'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            url TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            source TEXT,
            category TEXT,
            priority TEXT DEFAULT 'MEDIUM',
            tier INTEGER DEFAULT 3,
            summary TEXT,
            content TEXT,
            fetched_at TEXT NOT NULL,
            deep_read INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS briefings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            text_path TEXT,
            audio_path TEXT,
            word_count INTEGER,
            runtime_seconds REAL,
            articles_count INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_headlines_seen_at ON headlines_seen(seen_at)")
    conn.commit()
    return conn


def _title_hash(title: str) -> str:
    """Normalize and hash a headline for dedup."""
    normalized = title.lower().strip()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def is_duplicate(title: str, conn: sqlite3.Connection | None = None) -> bool:
    """Check if a headline was already seen within DEDUP_HOURS."""
    close = False
    if conn is None:
        conn = _get_conn()
        close = True
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=DEDUP_HOURS)).isoformat()
        url_hash = _title_hash(title)
        row = conn.execute(
            "SELECT 1 FROM headlines_seen WHERE url_hash = ? AND seen_at > ?",
            (url_hash, cutoff),
        ).fetchone()
        if row:
            return True
        # Local import: dedup imports this module at load, so a top-level import cycles.
        from .dedup import _similar, _tokens

        recent = conn.execute(
            "SELECT title FROM headlines_seen WHERE seen_at > ?", (cutoff,)
        ).fetchall()
        tokens = _tokens(title)
        for (existing,) in recent:
            if _similar(tokens, _tokens(existing)):
                return True
        return False
    finally:
        if close:
            conn.close()


def mark_seen(
    title: str,
    url: str = "",
    category: str = "",
    priority: str = "MEDIUM",
    conn: sqlite3.Connection | None = None,
) -> None:
    """Record a headline as seen, refreshing the timestamp if it was seen before.

    INSERT OR IGNORE left the original seen_at in place, so after the dedup
    window expired the row still existed, the insert was ignored, and the same
    headline was treated as new on every later run.
    """
    close = False
    if conn is None:
        conn = _get_conn()
        close = True
    try:
        url_hash = _title_hash(title)
        conn.execute(
            """INSERT INTO headlines_seen (url_hash, title, url, seen_at, category, priority)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(url_hash) DO UPDATE SET
                   title = excluded.title,
                   url = excluded.url,
                   seen_at = excluded.seen_at,
                   category = excluded.category,
                   priority = excluded.priority""",
            (url_hash, title, url, datetime.now(timezone.utc).isoformat(), category, priority),
        )
        conn.commit()
    finally:
        if close:
            conn.close()


def save_article(article: dict, conn: sqlite3.Connection | None = None) -> None:
    """Save or update an article record."""
    close = False
    if conn is None:
        conn = _get_conn()
        close = True
    try:
        conn.execute(
            """INSERT OR IGNORE INTO articles
               (url, title, source, category, priority, tier, summary, content, fetched_at, deep_read)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                article.get("url", ""),
                article.get("title", ""),
                article.get("source", ""),
                article.get("category", ""),
                article.get("priority", "MEDIUM"),
                article.get("tier", 3),
                article.get("summary", ""),
                article.get("content", ""),
                datetime.now(timezone.utc).isoformat(),
                article.get("deep_read", 0),
            ),
        )
        conn.commit()
    finally:
        if close:
            conn.close()


def save_briefing(
    text_path: str,
    audio_path: str,
    word_count: int,
    runtime_seconds: float,
    articles_count: int,
) -> None:
    """Record a completed briefing."""
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO briefings (timestamp, text_path, audio_path, word_count, runtime_seconds, articles_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                text_path,
                audio_path,
                word_count,
                runtime_seconds,
                articles_count,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def cleanup_old(hours: int | None = None) -> int:
    """Remove headlines older than the given hours. Returns count deleted.

    Defaults to 2x the dedup window. It must never default to 0: a zero-hour
    cutoff means "everything seen before right now", so every successful run
    wiped the whole seen-headlines table and cross-run deduplication stopped
    working (the same headlines were re-announced every run).
    """
    if hours is None:
        hours = DEDUP_HOURS * 2
    conn = _get_conn()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        result = conn.execute("DELETE FROM headlines_seen WHERE seen_at < ?", (cutoff,))
        conn.commit()
        return result.rowcount
    finally:
        conn.close()

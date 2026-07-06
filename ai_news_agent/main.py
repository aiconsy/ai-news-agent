"""Main pipeline — orchestrates the full news intelligence briefing.

v5.2: --deliver-at HH:MM flag for scheduled delivery. _wait_until() sleeps
until target time.
"""

import argparse
import logging
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .config import (
    QUIET_HOUR_START, QUIET_HOUR_END, OUTPUT_DIR, LOG_DIR,
    MODEL_SYNTHESIS,
)
from .feeds import load_feeds, fetch_all_feeds
from .dedup import deduplicate_articles
from .deepread import deep_read_articles
from .classify import classify_articles
from .synthesize import synthesize_briefing
from .tts import text_to_speech
from .deliver import deliver_briefing
from .db import save_briefing, cleanup_old, _get_conn

log = logging.getLogger("ai_news_agent")


def _is_quiet_hours() -> bool:
    """Check if current time is within quiet hours."""
    now = datetime.now().astimezone()
    hour = now.hour
    if QUIET_HOUR_START > QUIET_HOUR_END:  # overnight (e.g. 22-06)
        return hour >= QUIET_HOUR_START or hour < QUIET_HOUR_END
    else:  # same-day (e.g. 12-14)
        return QUIET_HOUR_START <= hour < QUIET_HOUR_END


def _wait_until(target_hhmm: str) -> None:
    """Sleep until the target time (HH:MM format, local time).

    If the target time has already passed today, wait until tomorrow.
    """
    try:
        target_hour, target_minute = map(int, target_hhmm.split(":"))
    except (ValueError, AttributeError):
        log.error(f"Invalid --deliver-at format: {target_hhmm} (expected HH:MM)")
        return

    now = datetime.now().astimezone()
    target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)

    if target <= now:
        target += timedelta(days=1)

    wait_seconds = (target - now).total_seconds()
    log.info(f"Waiting {wait_seconds:.0f}s ({wait_seconds/3600:.1f}h) until {target.strftime('%H:%M')} local time...")

    # Sleep in chunks so we can log progress and remain responsive
    while True:
        remaining = (target - datetime.now().astimezone()).total_seconds()
        if remaining <= 0:
            break
        sleep_chunk = min(remaining, 60)  # Check every minute max
        time.sleep(sleep_chunk)

    log.info(f"Reached target time {target.strftime('%H:%M')} — proceeding with pipeline")


def run_pipeline(force: bool = False, text_only: bool = False, no_deliver: bool = False, deliver_at: str | None = None) -> dict:
    """Run the full news intelligence pipeline.

    Args:
        force: Skip dedup (re-process all articles)
        text_only: Skip TTS and audio generation
        no_deliver: Skip Telegram delivery (save locally only)
        deliver_at: Wait until HH:MM before running (e.g. "07:30")

    Returns:
        Dict with pipeline results (articles, word_count, runtime, etc.)
    """
    # Wait until target time if specified
    if deliver_at:
        _wait_until(deliver_at)

    start_time = time.time()
    log.info("=" * 60)
    log.info("AI News Agent — Pipeline Starting")
    log.info("=" * 60)

    # Check quiet hours
    if not force and _is_quiet_hours():
        log.info(f"Quiet hours ({QUIET_HOUR_START}:00-{QUIET_HOUR_END}:00) — skipping pipeline")
        return {"status": "quiet_hours", "runtime_seconds": 0}

    conn = _get_conn()

    try:
        # Step 1: Load and fetch feeds
        log.info("Step 1/6: Loading RSS feeds...")
        feeds = load_feeds()
        if not feeds:
            log.error("No feeds loaded — aborting")
            return {"status": "error", "error": "no_feeds"}

        articles = fetch_all_feeds(feeds)
        log.info(f"Step 1/6: Fetched {len(articles)} articles from {len(feeds)} feeds")

        if not articles:
            log.warning("No articles fetched — producing minimal briefing")
            return {"status": "no_articles", "runtime_seconds": time.time() - start_time}

        # Step 2: Deduplicate
        log.info("Step 2/6: Deduplicating articles...")
        if not force:
            articles = deduplicate_articles(articles, conn)
        log.info(f"Step 2/6: {len(articles)} unique articles after dedup")

        # Step 3: Classify
        log.info("Step 3/6: Classifying articles...")
        articles = classify_articles(articles)
        high_count = sum(1 for a in articles if a.get("priority") == "HIGH")
        med_count = sum(1 for a in articles if a.get("priority") == "MEDIUM")
        low_count = sum(1 for a in articles if a.get("priority") == "LOW")
        log.info(f"Step 3/6: {high_count} HIGH, {med_count} MEDIUM, {low_count} LOW")

        # Step 4: Deep read
        log.info("Step 4/6: Deep-reading top articles...")
        articles = deep_read_articles(articles)
        deep_read_ok = sum(1 for a in articles if a.get("deep_read") == 1)
        log.info(f"Step 4/6: {deep_read_ok} articles deep-read successfully")

        # Step 5: Synthesize briefing
        log.info(f"Step 5/6: Synthesizing briefing with {MODEL_SYNTHESIS}...")
        briefing_text = synthesize_briefing(articles)
        word_count = len(briefing_text.split())
        log.info(f"Step 5/6: Briefing generated — {word_count} words")

        # Save text briefing
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        text_path = str(OUTPUT_DIR / f"briefing_{timestamp}.md")
        Path(text_path).write_text(briefing_text)
        log.info(f"Text briefing saved: {text_path}")

        # Step 6: TTS and delivery
        audio_path = None
        if not text_only:
            log.info("Step 6/6: Generating audio...")
            audio_path = text_to_speech(briefing_text)
            if audio_path:
                log.info(f"Audio briefing saved: {audio_path}")
            else:
                log.warning("TTS generation failed — delivering text only")

        # Deliver
        if not no_deliver:
            log.info("Delivering briefing to Telegram...")
            noteworthy_count = sum(1 for a in articles if a.get("priority") in ("HIGH", "MEDIUM"))
            success = deliver_briefing(
                text=briefing_text,
                audio_path=audio_path,
                caption=f"📰 News Briefing — {datetime.now().strftime('%H:%M')} UTC",
                noteworthy_count=noteworthy_count,
            )
            log.info(f"Delivery {'succeeded' if success else 'failed'}")
        else:
            log.info("Delivery skipped (--no-deliver)")

        # Save to database
        runtime = time.time() - start_time
        save_briefing(
            text_path=text_path,
            audio_path=audio_path or "",
            word_count=word_count,
            runtime_seconds=runtime,
            articles_count=len(articles),
        )

        # Cleanup old headlines
        deleted = cleanup_old()
        if deleted:
            log.info(f"Cleaned up {deleted} old headlines")

        log.info(f"Pipeline complete in {runtime:.1f}s — {word_count} words, {len(articles)} articles")
        return {
            "status": "success",
            "articles": len(articles),
            "word_count": word_count,
            "audio": audio_path is not None,
            "text_path": text_path,
            "audio_path": audio_path,
            "runtime_seconds": runtime,
        }

    except Exception as e:
        log.error(f"Pipeline error: {e}", exc_info=True)
        return {"status": "error", "error": str(e), "runtime_seconds": time.time() - start_time}
    finally:
        conn.close()


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="AI News Agent — Hourly news intelligence pipeline")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "fetch", "version"],
                        help="Command to run (default: run)")
    parser.add_argument("--force", action="store_true", help="Skip dedup — re-process all articles")
    parser.add_argument("--text-only", action="store_true", help="Generate text only, skip TTS")
    parser.add_argument("--no-deliver", action="store_true", help="Skip Telegram delivery")
    parser.add_argument("--deliver-at", metavar="HH:MM", default=None,
                        help="Wait until target time (e.g. 07:30) before running pipeline")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / "ai_news_agent.log", mode="a"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    if args.command == "version":
        from . import __version__
        print(f"ai-news-agent v{__version__}")
        return

    if args.command == "fetch":
        feeds = load_feeds()
        articles = fetch_all_feeds(feeds)
        print(f"Fetched {len(articles)} articles from {len(feeds)} feeds")
        return

    # Run the pipeline
    result = run_pipeline(
        force=args.force,
        text_only=args.text_only,
        no_deliver=args.no_deliver,
        deliver_at=args.deliver_at,
    )
    print(f"\nPipeline result: {result.get('status', 'unknown')}")
    if result.get("word_count"):
        print(f"  Words: {result['word_count']}")
        print(f"  Articles: {result.get('articles', 0)}")
        print(f"  Audio: {'✓' if result.get('audio') else '✗'}")
        print(f"  Runtime: {result.get('runtime_seconds', 0):.1f}s")


if __name__ == "__main__":
    main()
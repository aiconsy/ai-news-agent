"""Main pipeline — orchestrates the full news intelligence briefing.

v5.2: --deliver-at HH:MM flag for scheduled delivery. _wait_until() sleeps
until target time.
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__
from .classify import classify_articles
from .config import (
    LOG_DIR,
    MODEL_SYNTHESIS,
    OUTPUT_DIR,
    QUIET_HOUR_END,
    QUIET_HOUR_START,
)
from .db import _get_conn, cleanup_old, save_briefing
from .dedup import cluster_articles, deduplicate_articles
from .deepread import deep_read_articles
from .deliver import deliver_briefing
from .feeds import fetch_all_feeds, filter_fresh, load_feeds
from .synthesize import select_articles_for_briefing, synthesize_briefing
from .tts import text_to_speech

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


def run_pipeline(
    force: bool = False,
    text_only: bool = False,
    no_deliver: bool = False,
    deliver_at: str | None = None,
) -> dict:
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

        if not force:
            articles = filter_fresh(articles)
        log.info(f"Step 1/6: {len(articles)} articles inside the age window")

        # Step 2: Deduplicate. --force still collapses same-run copies so the
        # model is not handed twenty versions of one headline.
        log.info("Step 2/6: Deduplicating articles...")
        if force:
            articles, _suppressed = cluster_articles(articles)
        else:
            articles = deduplicate_articles(articles, conn)
        log.info(f"Step 2/6: {len(articles)} unique articles after dedup")

        if not articles:
            deleted = cleanup_old()
            log.info("No new articles after dedup — skipping LLM (%d old headlines cleaned)", deleted)
            return {"status": "no_new_articles", "runtime_seconds": time.time() - start_time}

        # Step 3: Classify
        log.info("Step 3/6: Classifying articles...")
        stats: dict = {}
        articles = classify_articles(articles, stats=stats)
        high_count = sum(1 for a in articles if a.get("priority") == "HIGH")
        med_count = sum(1 for a in articles if a.get("priority") == "MEDIUM")
        low_count = sum(1 for a in articles if a.get("priority") == "LOW")
        log.info(f"Step 3/6: {high_count} HIGH, {med_count} MEDIUM, {low_count} LOW")

        selected = select_articles_for_briefing(articles)
        if not selected:
            deleted = cleanup_old()
            log.info("No noteworthy stories — skipping synthesis (%d old headlines cleaned)", deleted)
            return {
                "status": "nothing_noteworthy",
                "articles": len(articles),
                "runtime_seconds": time.time() - start_time,
                "llm_classify_articles": stats.get("llm_classify_articles", 0),
            }

        # Step 4: Deep read only the stories that can make the briefing.
        log.info("Step 4/6: Deep-reading top articles...")
        deep_read_articles(selected)
        deep_read_ok = sum(1 for a in selected if a.get("deep_read") == 1)
        log.info(f"Step 4/6: {deep_read_ok} articles deep-read successfully")

        # Step 5: Synthesize briefing
        log.info(f"Step 5/6: Synthesizing briefing with {MODEL_SYNTHESIS}...")
        briefing_text = synthesize_briefing(selected, stats=stats)
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
            noteworthy_count = len(selected)
            success = deliver_briefing(
                text=briefing_text,
                audio_path=audio_path,
                caption=f"📰 News Briefing — {datetime.now(timezone.utc).strftime('%H:%M')} UTC",
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
            articles_count=len(selected),
        )

        # Cleanup old headlines
        deleted = cleanup_old()
        if deleted:
            log.info(f"Cleaned up {deleted} old headlines")

        log.info(
            "Pipeline complete in %.1fs — %d words, %d stories, ~%d prompt tokens",
            runtime,
            word_count,
            len(selected),
            stats.get("prompt_tokens_est", 0),
        )
        return {
            "status": "success",
            "articles": len(selected),
            "word_count": word_count,
            "audio": audio_path is not None,
            "text_path": text_path,
            "audio_path": audio_path,
            "runtime_seconds": runtime,
            "llm_classify_articles": stats.get("llm_classify_articles", 0),
            "prompt_tokens_est": stats.get("prompt_tokens_est", 0),
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
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore quiet hours, the age window, and cross-run dedup",
    )
    parser.add_argument("--text-only", action="store_true", help="Generate text only, skip TTS")
    parser.add_argument("--no-deliver", action="store_true", help="Skip Telegram delivery")
    parser.add_argument("--deliver-at", metavar="HH:MM", default=None,
                        help="Wait until target time (e.g. 07:30) before running pipeline")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        LOG_DIR / "ai_news_agent.log",
        mode="a",
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            file_handler,
            logging.StreamHandler(sys.stdout),
        ],
    )

    if args.command == "version":
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

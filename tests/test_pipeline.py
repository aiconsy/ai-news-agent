"""Tests for AI News Agent."""

import json
import tempfile
from pathlib import Path

from ai_news_agent.feeds import load_feeds, classify_source_tier
from ai_news_agent.dedup import _title_hash
from ai_news_agent.config import SOURCE_TIERS


def test_load_feeds():
    """Feeds file loads and contains expected categories."""
    feeds_path = Path(__file__).parent.parent / "config" / "feeds.json"
    feeds = load_feeds(feeds_path)
    assert len(feeds) > 200, f"Expected 200+ feeds, got {len(feeds)}"
    categories = {f["category"] for f in feeds}
    assert "World News" in categories
    assert "Tech&Science" in categories
    assert "A.I." in categories


def test_classify_source_tier():
    """Source tier classification works correctly."""
    assert classify_source_tier("Reuters") == 1
    assert classify_source_tier("BBC News") == 1
    assert classify_source_tier("CNN") == 2
    assert classify_source_tier("The Verge") == 2
    assert classify_source_tier("Some Random Blog") == 3


def test_title_hash():
    """Title hashing produces consistent results."""
    assert _title_hash("Hello World") == _title_hash("Hello World")
    assert _title_hash("Hello World") != _title_hash("Different Title")
    # Case-insensitive normalization
    assert _title_hash("hello world") == _title_hash("HELLO WORLD")


def test_source_tiers_no_personal_info():
    """Source tiers list contains no personal/regional references."""
    all_keywords = []
    for tier_keywords in SOURCE_TIERS.values():
        all_keywords.extend(tier_keywords)
    combined = " ".join(all_keywords).lower()
    # No Hungarian, Romanian, or Swiss-specific references
    assert "hungar" not in combined
    assert "roman" not in combined
    assert "bucharest" not in combined


def test_feeds_no_regional():
    """Feeds list contains no Hungarian/Romanian/Swiss regional feeds."""
    feeds_path = Path(__file__).parent.parent / "config" / "feeds.json"
    feeds = load_feeds(feeds_path)
    regional_cats = {"Hun. News", "Ro. News", "Swiss"}
    for feed in feeds:
        assert feed.get("category", "") not in regional_cats, \
            f"Regional feed found: {feed['name']} [{feed['category']}]"


if __name__ == "__main__":
    test_load_feeds()
    test_classify_source_tier()
    test_title_hash()
    test_source_tiers_no_personal_info()
    test_feeds_no_regional()
    print("All tests passed! ✅")
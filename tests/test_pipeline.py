"""Tests for AI News Agent."""

import time
from pathlib import Path

import requests

from ai_news_agent.classify import (
    _detect_category,
    _keyword_classify,
    _parse_batch_response,
    build_llm_payload,
    classify_articles,
)
from ai_news_agent.config import SOURCE_TIERS
from ai_news_agent.db import _get_conn, cleanup_old, mark_seen
from ai_news_agent.dedup import _title_hash, cluster_articles, deduplicate_articles
from ai_news_agent.deepread import deep_read_article, is_safe_fetch_url
from ai_news_agent.deliver import _split_message
from ai_news_agent.feeds import classify_source_tier, filter_fresh, load_feeds
from ai_news_agent.synthesize import build_synthesis_prompt


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


def test_feed_urls_are_unique():
    feeds = load_feeds(Path(__file__).parent.parent / "config" / "feeds.json")
    keys = [(feed.get("url") or "").strip().rstrip("/") for feed in feeds]
    assert len(keys) == len(set(keys))
    assert len(feeds) > 200


def test_keyword_boundaries_do_not_match_inside_words():
    assert _keyword_classify("Officials said the campaign remains available") is None
    assert _keyword_classify("Residents got a storm warning overnight") is None
    assert _keyword_classify("The valuation is several billion dollars") is None
    assert _keyword_classify("Super Bowl halftime show lineup") == "LOW"
    assert _keyword_classify("NATO summit ends with new sanctions") == "HIGH"
    assert "Tech" in _detect_category("OpenAI releases a new model")
    assert "Geopolitics" not in _detect_category("OpenAI releases a new model")


def test_keyword_path_does_not_call_the_model(monkeypatch):
    monkeypatch.setattr("ai_news_agent.classify.MAX_LLM_CLASSIFY", 0)

    def boom(*_args, **_kwargs):
        raise AssertionError("classifier model should not be called")

    monkeypatch.setattr("ai_news_agent.classify._call_llm", boom)
    articles = [
        {"title": "Super Bowl halftime setlist", "summary": "championship night", "tier": 2},
        {"title": "NATO summit ends with new sanctions", "summary": "leaders agreed", "tier": 1},
        {"title": "Officials said the campaign remains on track", "summary": "no policy change", "tier": 3},
    ]
    ranked = classify_articles(articles)
    by_title = {article["title"]: article["priority"] for article in ranked}
    assert by_title["Super Bowl halftime setlist"] == "LOW"
    assert by_title["NATO summit ends with new sanctions"] == "HIGH"
    assert by_title["Officials said the campaign remains on track"] == "LOW"


def test_high_cap_keeps_better_source(monkeypatch):
    monkeypatch.setattr("ai_news_agent.classify.HIGH_CAP", 1)
    monkeypatch.setattr("ai_news_agent.classify._call_llm", lambda *_a, **_k: "")
    articles = [
        {"title": "Military strike reported in the north", "summary": "invasion fears", "tier": 3},
        {
            "title": "Military strike hits a second city",
            "summary": "invasion continues and the wire copy is much longer than the blog",
            "tier": 1,
        },
    ]
    classify_articles(articles)
    highs = [article for article in articles if article["priority"] == "HIGH"]
    assert len(highs) == 1
    assert highs[0]["tier"] == 1


def test_cluster_keeps_distinct_stories_and_best_source():
    articles = [
        {
            "title": "NATO leaders agree new sanctions on Moscow",
            "url": "http://a.example/1",
            "tier": 2,
            "summary": "short",
        },
        {
            "title": "NATO leaders agree new sanctions on Moscow after the summit",
            "url": "http://b.example/2",
            "tier": 1,
            "summary": "wire copy with more detail about the package",
        },
        {
            "title": "NATO leaders reject sanctions on Moscow",
            "url": "http://c.example/3",
            "tier": 1,
            "summary": "different outcome",
        },
        {
            "title": "Local bakery opens on Main Street",
            "url": "http://d.example/4",
            "tier": 3,
            "summary": "unrelated",
        },
    ]
    kept, suppressed = cluster_articles(articles)
    titles = {article["title"] for article in kept}
    assert len(suppressed) == 1
    assert "NATO leaders agree new sanctions on Moscow after the summit" in titles
    assert "NATO leaders agree new sanctions on Moscow" not in titles
    assert "NATO leaders reject sanctions on Moscow" in titles
    assert "Local bakery opens on Main Street" in titles


def test_mark_seen_refreshes_the_window(tmp_path, monkeypatch):
    monkeypatch.setattr("ai_news_agent.db.DB_PATH", tmp_path / "news.db")
    mark_seen("NATO leaders agree new sanctions on Moscow", url="https://example.com/a")
    conn = _get_conn()
    conn.execute("UPDATE headlines_seen SET seen_at = ?", ("2000-01-01T00:00:00+00:00",))
    conn.commit()
    mark_seen("NATO leaders agree new sanctions on Moscow", url="https://example.com/a")
    seen_at = conn.execute("SELECT seen_at FROM headlines_seen").fetchone()[0]
    assert not seen_at.startswith("2000")

    again = deduplicate_articles(
        [{
            "title": "NATO leaders agree new sanctions on Moscow",
            "url": "https://example.com/a",
            "tier": 1,
            "summary": "x",
        }],
        conn,
    )
    assert again == []
    assert cleanup_old() == 0
    conn.close()


def test_filter_fresh_drops_old_items():
    now_ts = time.time()
    articles = [
        {"title": "old", "published_ts": now_ts - 10 * 24 * 3600},
        {"title": "new", "published_ts": now_ts - 3600},
        {"title": "undated"},
    ]
    kept = filter_fresh(articles, max_age_hours=36)
    assert [article["title"] for article in kept] == ["new", "undated"]


def test_synthesis_prompt_skips_low_and_stays_small():
    articles = []
    for index in range(30):
        articles.append(
            {
                "priority": "LOW" if index >= 25 else "HIGH",
                "title": f"Distinct sanctions story {index}",
                "summary": "s" * 4000,
                "content": "FULLCONTENT " + ("y" * 8000),
                "deep_read": 1,
                "source": "BBC",
                "tier": 1,
                "category": "Geopolitics",
            }
        )
    articles.append(
        {
            "priority": "LOW",
            "title": "LOWSTORY_UNIQUE bakery opens",
            "summary": "not noteworthy",
            "source": "Blog",
            "tier": 3,
            "category": "General",
        }
    )
    prompt = build_synthesis_prompt(articles)
    assert "LOWSTORY_UNIQUE" not in prompt
    assert "y" * 400 not in prompt
    assert len(prompt) < 13000
    assert "Distinct sanctions story 0" in prompt


def test_llm_payload_matches_the_endpoint():
    native = build_llm_payload("http://localhost:11434/api/chat", "m", "hi", 80, 0.2)
    assert native["options"]["num_predict"] == 80
    assert "max_tokens" not in native

    remote = build_llm_payload("https://ollama.com/v1/chat/completions", "m", "hi", 80, 0.2)
    assert remote["max_tokens"] == 80
    assert "options" not in remote

    assert _parse_batch_response("<think>HIGH HIGH HIGH</think>\nL\nM", 2) == ["LOW", "MEDIUM"]


def test_safe_fetch_urls():
    assert is_safe_fetch_url("https://example.com/a")
    assert is_safe_fetch_url("http://8.8.8.8/dns")
    assert not is_safe_fetch_url("http://localhost/admin")
    assert not is_safe_fetch_url("http://127.0.0.1/")
    assert not is_safe_fetch_url("http://169.254.169.254/latest/meta-data")
    assert not is_safe_fetch_url("http://10.1.2.3/")
    assert not is_safe_fetch_url("http://192.168.1.9/")
    assert not is_safe_fetch_url("http://172.16.0.5/")
    assert not is_safe_fetch_url("http://metadata.google.internal/")
    assert not is_safe_fetch_url("file:///etc/passwd")
    assert not is_safe_fetch_url("ftp://example.com/feed")
    assert not is_safe_fetch_url("http://intranet/secret")
    assert not is_safe_fetch_url("http://[::1]/")
    assert not is_safe_fetch_url("http://2130706433/")


def test_deep_read_does_not_follow_private_redirects(monkeypatch):
    calls = []

    class Resp:
        def __init__(self, status, headers, text=""):
            self.status_code = status
            self.headers = headers
            self.text = text

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(response=self)

    def fake_get(url, **_kwargs):
        calls.append(url)
        if url.startswith("https://news.example"):
            return Resp(302, {"Location": "http://169.254.169.254/latest/meta-data"})
        raise AssertionError(url)

    monkeypatch.setattr("ai_news_agent.deepread.requests.get", fake_get)
    assert deep_read_article("https://news.example/story") is None
    assert calls == ["https://news.example/story"]


def test_split_message_hard_cuts_a_long_paragraph():
    chunks = _split_message("x" * 9000, max_length=4096)
    assert chunks
    assert all(len(chunk) <= 4096 for chunk in chunks)
    assert "".join(chunks) == "x" * 9000


if __name__ == "__main__":
    test_load_feeds()
    test_classify_source_tier()
    test_title_hash()
    test_source_tiers_no_personal_info()
    test_feeds_no_regional()
    print("All tests passed! ✅")

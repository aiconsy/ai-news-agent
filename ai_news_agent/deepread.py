"""Deep-read articles — extract full text via requests, trafilatura, readability."""

import ipaddress
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import requests
import trafilatura
from readability import Document

from .config import DEEP_READ_WORKERS, MAX_DEEP_READ

log = logging.getLogger("ai_news_agent")

# Hosts that must never be fetched on behalf of feed content. Feed URLs are
# attacker-influenced, so an unrestricted fetch is an SSRF primitive against
# loopback, private ranges, and cloud metadata endpoints.
_BLOCKED_HOSTS = re.compile(
    r"^(localhost|127\.|0\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|169\.254\.|\[?::1\]?$|metadata\.)",
    re.I,
)

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def _literal_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    if host.isdigit():
        try:
            return ipaddress.ip_address(int(host))
        except ValueError:
            return None
    if host.lower().startswith("0x"):
        try:
            return ipaddress.ip_address(int(host, 16))
        except ValueError:
            return None
    return None


def is_safe_fetch_url(url: str) -> bool:
    """True when `url` is a plain http(s) URL to a public host."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").strip().rstrip(".").lower()
    if not host:
        return False
    ip = _literal_ip(host)
    if ip is not None:
        return bool(ip.is_global)
    if "." not in host:
        return False
    if host.endswith((".local", ".localhost", ".internal")):
        return False
    if _BLOCKED_HOSTS.match(host):
        return False
    return True


def _fetch_html(url: str, timeout: int) -> str | None:
    """GET a public page. Each redirect hop is checked again before it is followed."""
    current = url
    headers = {"User-Agent": BROWSER_UA}
    for _hop in range(4):
        if not is_safe_fetch_url(current):
            log.debug("refusing unsafe url: %s", current)
            return None
        try:
            resp = requests.get(
                current,
                headers=headers,
                timeout=timeout,
                verify=True,
                allow_redirects=False,
            )
        except Exception as exc:
            log.debug("requests failed for %s: %s", current, exc)
            return None
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location")
            if not location:
                return None
            current = urljoin(current, location)
            continue
        try:
            resp.raise_for_status()
        except Exception as exc:
            log.debug("status failed for %s: %s", current, exc)
            return None
        return resp.text
    log.debug("too many redirects for %s", url)
    return None


def deep_read_article(url: str, timeout: int = 20) -> dict | None:
    """Extract full article text from a URL.

    Returns dict with 'text', 'method', 'word_count' or None on failure.
    """
    if not is_safe_fetch_url(url):
        log.debug("refusing to deep-read unsafe url: %s", url)
        return None

    html = _fetch_html(url, timeout)
    if not html:
        return None

    try:
        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        if text and len(text.split()) >= 30:
            return {"text": text, "method": "trafilatura", "word_count": len(text.split())}
    except Exception as exc:
        log.debug("trafilatura failed for %s: %s", url, exc)

    try:
        summary = Document(html).summary()
        text = re.sub(r"<[^>]+>", "", summary)
        text = re.sub(r"\s+", " ", text).strip()
        if text and len(text.split()) >= 30:
            return {"text": text, "method": "readability", "word_count": len(text.split())}
    except Exception as exc:
        log.debug("readability failed for %s: %s", url, exc)

    return None


def _read_one(article: dict) -> tuple[dict, dict | None]:
    return article, deep_read_article(article.get("url", ""))


def deep_read_articles(articles: list[dict], max_articles: int = 0) -> list[dict]:
    """Deep-read the highest-ranked HIGH/MEDIUM stories. Incoming order is kept.

    LOW stories are not fetched. Workers are capped so a slow origin cannot
    multiply into dozens of hung connections.
    """
    max_articles = max_articles or MAX_DEEP_READ
    targets = [
        article
        for article in articles
        if article.get("url") and article.get("priority") in ("HIGH", "MEDIUM")
    ][:max_articles]
    if not targets:
        return articles

    workers = max(1, min(DEEP_READ_WORKERS, len(targets)))
    started = time.time()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for article, result in executor.map(_read_one, targets):
            if result:
                article["content"] = result["text"]
                article["deep_read"] = 1
                article["extract_method"] = result["method"]
            else:
                article["deep_read"] = 0
                article["extract_method"] = "failed"

    ok = sum(1 for article in targets if article.get("deep_read") == 1)
    log.info("Deep-read %d/%d articles in %.1fs", ok, len(targets), time.time() - started)
    return articles

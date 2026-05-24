"""Deep-read articles — extract full text via requests+trafilatura+readability."""

import logging
import re
import ssl
import time
import urllib.request
import urllib.error

import requests

from .config import MAX_DEEP_READ

log = logging.getLogger("ai_news_agent")

# Browser-like user agent to avoid blocks
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def deep_read_article(url: str, timeout: int = 20) -> dict | None:
    """Extract full article text from a URL.
    
    Strategy:
    1. requests.get() with browser UA
    2. trafilatura extraction
    3. readability fallback
    
    Returns dict with 'text', 'method', 'word_count' or None on failure.
    """
    # Strategy 1: requests with browser UA
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": BROWSER_UA},
            timeout=timeout,
            verify=False,  # SSL fallback
        )
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        log.debug(f"requests failed for {url}: {e}")
        html = None

    if html:
        # Strategy 2: trafilatura
        try:
            import trafilatura
            text = trafilatura.extract(html, include_comments=False, include_tables=False)
            if text and len(text.split()) >= 30:
                return {
                    "text": text,
                    "method": "trafilatura",
                    "word_count": len(text.split()),
                }
        except ImportError:
            log.warning("trafilatura not installed, falling back to readability")
        except Exception as e:
            log.debug(f"trafilatura failed for {url}: {e}")

        # Strategy 3: readability fallback
        try:
            from readability import Document
            doc = Document(html)
            summary = doc.summary()
            # Strip HTML tags
            text = re.sub(r"<[^>]+>", "", summary)
            if text and len(text.split()) >= 30:
                return {
                    "text": text,
                    "method": "readability",
                    "word_count": len(text.split()),
                }
        except ImportError:
            pass
        except Exception as e:
            log.debug(f"readability failed for {url}: {e}")

    # Strategy 4: urllib fallback (no SSL verification)
    if not html:
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
            resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
            html = resp.read().decode("utf-8", errors="replace")

            import trafilatura
            text = trafilatura.extract(html, include_comments=False, include_tables=False)
            if text and len(text.split()) >= 30:
                return {
                    "text": text,
                    "method": "trafilatura_urllib",
                    "word_count": len(text.split()),
                }
        except Exception as e:
            log.debug(f"urllib fallback failed for {url}: {e}")

    return None


def deep_read_articles(articles: list[dict], max_articles: int = 0) -> list[dict]:
    """Deep-read the top articles by priority and tier.
    
    Returns articles with 'content' field populated.
    """
    max_articles = max_articles or MAX_DEEP_READ
    deep_read_count = 0

    # Sort by tier (1=best) then by priority
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    sorted_articles = sorted(
        articles,
        key=lambda a: (a.get("tier", 3), priority_order.get(a.get("priority", "MEDIUM"), 1)),
    )

    for article in sorted_articles:
        if deep_read_count >= max_articles:
            break

        url = article.get("url", "")
        if not url:
            continue

        log.info(f"Deep-reading ({deep_read_count + 1}/{max_articles}): {article.get('title', '?')[:60]}")
        result = deep_read_article(url)

        if result:
            article["content"] = result["text"]
            article["deep_read"] = 1
            article["extract_method"] = result["method"]
            deep_read_count += 1
        else:
            article["deep_read"] = 0
            article["extract_method"] = "failed"

        time.sleep(0.5)  # Rate limit

    log.info(f"Deep-read {deep_read_count}/{min(len(articles), max_articles)} articles")
    return articles
"""Briefing synthesis.

The model sees a short list of HIGH and MEDIUM stories, each clipped to a
lead. LOW stories and full article bodies never enter the prompt.
"""

import logging
import re

from .classify import _call_llm
from .config import (
    MAX_CONTEXT_CHARS,
    MAX_NOTEWORTHY,
    MODEL_SYNTHESIS,
    SYNTHESIS_STORY_CHARS,
    SYNTHESIS_TIMEOUT,
)

log = logging.getLogger("ai_news_agent")

INTELLIGENCE_BRIEFING_PROMPT = """You are a world news editor writing an intelligence briefing.
Include only news a head of government, investor, or strategist still needs next week.

Rules:
- Skip sports, celebrity gossip, entertainment, lifestyle, and opinion.
- Skip a story that will not matter in a week.
- Skip a section when you have no story for it.
- 2-3 sentences per story: what happened, then why it matters.
- Precise names, numbers, and places. No filler and no "now turning to".
- 700-1,600 words.

Sections, in this order:
## World & Geopolitics
## Economy & Markets
## Technology & Science
## Cybersecurity
## Regional
Regional means developments in the UK, Switzerland, Hungary, Romania, and other local news with wider consequences.

Stories are ranked. Prefer earlier items and higher tiers when you must cut."""

_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")


def extractive_lead(text: str, max_chars: int = SYNTHESIS_STORY_CHARS) -> str:
    """First sentence or two, clipped, with whitespace collapsed."""
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    window = cleaned[:max_chars]
    match = None
    for candidate in _SENTENCE_END.finditer(window):
        if candidate.end() >= max_chars // 2:
            match = candidate
            break
    if match:
        return window[: match.end()].strip()
    trimmed = window.rsplit(" ", 1)[0]
    return f"{trimmed}…" if trimmed else window


def story_blurb(article: dict, limit: int = SYNTHESIS_STORY_CHARS) -> str:
    """Best short text we already have. Deep-read leads beat RSS decks."""
    if article.get("deep_read") and article.get("content"):
        source = article.get("content") or ""
    elif len((article.get("summary") or "").strip()) >= 80:
        source = article.get("summary") or ""
    else:
        source = article.get("content") or article.get("summary") or ""
    return extractive_lead(source, limit)


def _rank(article: dict) -> tuple:
    priority = {"HIGH": 0, "MEDIUM": 1}.get(article.get("priority", ""), 9)
    category = article.get("category") or ""
    if "Geopolitics" in category:
        topic = 0
    elif "Tech" in category or "Cyber" in category:
        topic = 1
    elif "Finance" in category:
        topic = 2
    else:
        topic = 3
    return (priority, topic, article.get("tier", 3), -(article.get("published_ts") or 0))


def select_articles_for_briefing(articles: list[dict]) -> list[dict]:
    """HIGH and MEDIUM only, geopolitics before routine markets, then the cap."""
    pool = [article for article in articles if article.get("priority") in ("HIGH", "MEDIUM")]
    pool.sort(key=_rank)
    return pool[:MAX_NOTEWORTHY]


def build_synthesis_prompt(articles: list[dict]) -> str:
    """Compact prompt. Stops adding stories once the character budget is spent."""
    blocks: list[str] = []
    used = len(INTELLIGENCE_BRIEFING_PROMPT) + 40
    for index, article in enumerate(select_articles_for_briefing(articles), 1):
        blurb = story_blurb(article)
        title = (article.get("title") or "Untitled").replace("\n", " ")
        block = (
            f"{index}. [{article.get('priority', 'MEDIUM')}|{article.get('category', 'General')}] "
            f"{title} ({article.get('source', '?')}, tier {article.get('tier', 3)})\n"
            f"{blurb}"
        )
        if blocks and used + len(block) + 2 > MAX_CONTEXT_CHARS:
            log.info("Context budget reached at %d stories (%d chars)", len(blocks), used)
            break
        blocks.append(block)
        used += len(block) + 2
    context = "\n\n".join(blocks)
    return f"{INTELLIGENCE_BRIEFING_PROMPT}\n\n{context}\n\nProduce the briefing now:"


def synthesize_briefing(articles: list[dict], stats: dict | None = None) -> str:
    """Write the briefing. Callers should skip this when the selection is empty."""
    selected = select_articles_for_briefing(articles)
    prompt = build_synthesis_prompt(articles)
    if stats is not None:
        stats["prompt_chars"] = len(prompt)
        stats["prompt_tokens_est"] = max(1, len(prompt) // 4)
        stats["briefing_stories"] = len(selected)
    log.info(
        "Synthesizing from %d stories (~%d tokens, %d chars)",
        len(selected),
        max(1, len(prompt) // 4),
        len(prompt),
    )

    result = _call_llm(
        prompt,
        model=MODEL_SYNTHESIS,
        max_tokens=2200,
        temperature=0.4,
        timeout=SYNTHESIS_TIMEOUT,
    )
    result = result.strip()
    if result:
        return result

    log.error("Synthesis LLM call failed — building a local fallback")
    lines = ["# News Briefing (Fallback)", ""]
    for index, article in enumerate(selected, 1):
        lines.append(f"{index}. **{article.get('title', 'Untitled')}** ({article.get('source', '?')})")
        blurb = story_blurb(article, 200)
        if blurb:
            lines.append(f"   {blurb}")
    return "\n".join(lines)

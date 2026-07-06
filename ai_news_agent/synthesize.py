"""Briefing synthesis — generate podcast-length news briefing from classified articles.

v5.2: Intelligence briefing prompt — world news editor for intelligence briefing service.
Structured sections: World & Geopolitics, Economy & Markets, Technology & Science,
Cybersecurity, Regional. Strict no-junk rules.
"""

import json
import logging

from .config import MODEL_SYNTHESIS, MAX_NOTEWORTHY
from .classify import _call_llm

log = logging.getLogger("ai_news_agent")


INTELLIGENCE_BRIEFING_PROMPT = """You are a world news editor for an intelligence briefing service. Your audience is a professional who wants HIGH-IMPACT news with LONG-TERM global significance — not hype, drama, sports, gossip, or entertainment.

Your job is to produce a concise, professional intelligence briefing from the articles provided below.

STRICT RULES:
- NO sports
- NO celebrity gossip
- NO entertainment
- NO lifestyle
- NO opinion pieces
- If a story won't matter in a week — SKIP IT
- Only include stories that a world leader, investor, or strategist would need to know

FORMAT:
Structure the briefing with these sections (skip a section if no relevant articles):

## World & Geopolitics
(Wars, diplomacy, sanctions, treaties, political crises, elections with global impact)

## Economy & Markets
(Market movements, central bank decisions, trade, inflation, recession signals)

## Technology & Science
(AI breakthroughs, semiconductors, quantum, space, major research, cyber policy)

## Cybersecurity
(Cyberattacks, data breaches, zero-days, state-sponsored operations, cyber policy)

## Regional
(Important regional developments — Switzerland, UK, Hungary, Romania, and other regional news)

WRITING STYLE:
- Be concise and factual — 2-4 sentences per story
- Lead with the most important developments
- Provide context on WHY it matters, not just WHAT happened
- Use bullet points within sections for readability
- Write 800-2,000 words total
- No filler, no fluff, no transitions like "Now turning to..." — just the news
- Be precise with numbers, names, and locations

Produce the briefing from these articles:"""


def synthesize_briefing(articles: list[dict]) -> str:
    """Generate a podcast-length briefing from classified articles.

    Takes the top MAX_NOTEWORTHY articles, formats them as context,
    and calls the synthesis LLM to generate a natural briefing.
    """
    # Select top articles
    top_articles = articles[:MAX_NOTEWORTHY]

    # Format articles for LLM context
    context_parts = []
    for i, article in enumerate(top_articles, 1):
        priority = article.get("priority", "MEDIUM")
        category = article.get("category", "General")
        source = article.get("source", "Unknown")
        title = article.get("title", "Untitled")
        summary = article.get("summary", "")
        content = article.get("content", summary)

        # Truncate content to keep within context window
        if len(content) > 800:
            content = content[:800] + "..."

        context_parts.append(
            f"[{i}] [{priority}] [{category}] {title}\n"
            f"    Source: {source}\n"
            f"    {content}"
        )

    context = "\n\n".join(context_parts)
    prompt = f"{INTELLIGENCE_BRIEFING_PROMPT}\n\n{context}\n\nProduce the briefing now:"

    log.info(f"Synthesizing briefing from {len(top_articles)} articles (context: {len(prompt)} chars)")

    result = _call_llm(prompt, model=MODEL_SYNTHESIS, max_tokens=4096, temperature=0.4)

    if not result:
        log.error("Synthesis LLM call failed — no output")
        # Fallback: generate a simple text summary
        result = "# News Briefing (Fallback)\n\n"
        for i, article in enumerate(top_articles, 1):
            result += f"{i}. **{article.get('title', 'Untitled')}** ({article.get('source', '?')})\n"
            if article.get("summary"):
                result += f"   {article['summary'][:200]}\n"

    return result
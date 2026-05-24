"""Briefing synthesis — generate podcast-length news briefing from classified articles."""

import json
import logging

from .config import MODEL_SYNTHESIS, MAX_NOTEWORTHY
from .classify import _call_llm

log = logging.getLogger("ai_news_agent")


GEOPOLITICS_PROMPT = """You are a seasoned geopolitical analyst and news anchor producing a podcast-length briefing. 

风格要求：
- Write in a natural, conversational podcast style — as if you're speaking to an intelligent listener
- Lead with the most urgent geopolitical developments
- Provide context and implications, not just reporting
- Use transitions between stories ("Now turning to...", "In other developments...", "Meanwhile...")
- End with a brief outlook on what to watch next
- Be precise with numbers, names, and locations
- Avoid editorializing — present facts and analysis
- Write 1,500-3,000 words for a comprehensive briefing

Structure:
1. **Opening** — Top 2-3 stories of the hour
2. **Geopolitics** — Wars, diplomacy, sanctions, treaties
3. **Technology** — AI, cybersecurity, semiconductors, space
4. **Finance** — Markets, central banks, trade, economy
5. **Closing** — What to watch next

Do NOT include any of the following:
- Personal opinions or subjective commentary beyond analysis
- References to specific individuals' personal lives
- Unverified rumors
- Local/regional news of limited global interest

Produce a complete briefing from these articles:"""


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
    prompt = f"{GEOPOLITICS_PROMPT}\n\n{context}\n\nProduce the briefing now:"

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
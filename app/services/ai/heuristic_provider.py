"""Deterministic fallback provider.

Used when no ANTHROPIC_API_KEY is configured or as a degradation path.
It is intentionally conservative (PRD 21.2): extractive summaries only,
keyword classification, and NO generated "why it matters" - we never show
text that was not grounded in the article.
"""

import re

from app.services.ai.base import AIProvider, ArticleAnalysis, StorySynthesis

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Technology": [
        "ai", "artificial intelligence", "software", "app", "chip", "semiconductor",
        "startup", "google", "apple", "microsoft", "meta", "openai", "anthropic",
        "cyber", "robot", "smartphone", "internet", "data center", "cloud",
    ],
    "Economy": [
        "economy", "inflation", "interest rate", "stocks", "market", "gdp", "trade",
        "tariff", "bank", "currency", "unemployment", "oil price", "investment",
        "earnings", "budget deficit",
    ],
    "Science": [
        "research", "study finds", "scientists", "space", "nasa", "telescope",
        "quantum", "physics", "climate", "species", "fossil", "experiment", "spacex",
    ],
    "Health": [
        "health", "vaccine", "virus", "disease", "hospital", "cancer", "drug",
        "fda", "who ", "outbreak", "mental health", "treatment",
    ],
    "Sports": [
        "match", "league", "cup", "tournament", "championship", "olympic", "goal",
        "football", "soccer", "basketball", "tennis", "fifa", "coach", "season",
    ],
    "Culture": [
        "film", "movie", "music", "album", "festival", "museum", "art ", "novel",
        "celebrity", "box office", "netflix", "fashion",
    ],
    "Politics": [
        "election", "parliament", "minister", "president", "senate", "congress",
        "vote", "policy", "legislation", "campaign", "coalition", "prime minister",
    ],
    "Middle East": [
        "israel", "palestine", "gaza", "west bank", "lebanon", "syria", "iran",
        "iraq", "saudi", "uae", "qatar", "egypt", "jordan", "yemen", "turkey",
    ],
}

_REGION_KEYWORDS: dict[str, list[str]] = {
    "Israel / Palestine": ["israel", "palestin", "gaza", "west bank", "jerusalem", "tel aviv"],
    "Middle East": [
        "middle east", "lebanon", "syria", "iran", "iraq", "saudi", "uae", "qatar",
        "egypt", "jordan", "yemen", "gulf",
    ],
    "United States": [
        "united states", "u.s.", "washington", "white house", "congress", "american",
        "california", "new york",
    ],
    "Europe": [
        "europe", "european union", " eu ", "germany", "france", "uk ", "britain",
        "london", "paris", "berlin", "brussels", "spain", "italy",
    ],
    "Technology Global": ["silicon valley", "big tech"],
}

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
# Capitalized multi-or-single word phrases, used as a crude named-entity signal.
_ENTITY_PATTERN = re.compile(r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,3})\b")
_ENTITY_STOPWORDS = {
    "The", "This", "That", "These", "Those", "It", "He", "She", "They", "We",
    "But", "And", "After", "Before", "When", "While", "However", "Monday",
    "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "In",
    "On", "At", "For", "From", "With", "As", "By", "An", "A", "If", "New",
}

_OPINION_MARKERS = ["opinion", "analysis", "editorial", "comment:", "viewpoint", "op-ed"]


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text or "") if s.strip()]


def extract_entities(text: str, limit: int = 10) -> list[str]:
    counts: dict[str, int] = {}
    for match in _ENTITY_PATTERN.finditer(text or ""):
        words = match.group(1).split()
        # Drop leading articles/pronouns: "The European Commission" -> "European Commission"
        while words and words[0] in _ENTITY_STOPWORDS:
            words = words[1:]
        if not words:
            continue
        candidate = " ".join(words)
        if candidate in _ENTITY_STOPWORDS or len(candidate) < 3:
            continue
        # Single capitalized words at a sentence start are usually just
        # sentence case ("Several", "Regulators"), not entities.
        before = (text[: match.start()]).rstrip()
        at_sentence_start = not before or before[-1] in ".!?\n"
        if at_sentence_start and len(words) == 1:
            continue
        counts[candidate] = counts.get(candidate, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [name for name, _ in ranked[:limit]]


def classify_category(text: str) -> str:
    lowered = f" {text.lower()} "
    best, best_score = "World", 0
    for category, keywords in _CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in lowered)
        if score > best_score:
            best, best_score = category, score
    return best


def classify_region(text: str) -> str:
    lowered = f" {text.lower()} "
    best, best_score = "World", 0
    for region, keywords in _REGION_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in lowered)
        if score > best_score:
            best, best_score = region, score
    return best


class HeuristicProvider(AIProvider):
    name = "heuristic"
    model_name = "heuristic-extractive-v1"

    def analyze_article(self, title: str, text: str, source_name: str) -> ArticleAnalysis:
        combined = f"{title}. {text or ''}"
        sentences = split_sentences(text or "")
        summary = " ".join(sentences[:2])[:500]
        # Sentences containing digits tend to carry concrete facts.
        fact_sentences = [s for s in sentences[:12] if re.search(r"\d", s)][:3]
        entities = extract_entities(combined)
        is_opinion = any(marker in combined.lower() for marker in _OPINION_MARKERS)
        # Importance: longer coverage and more named entities -> likely bigger story.
        importance = min(1.0, 0.3 + 0.05 * len(entities) + 0.02 * min(len(sentences), 15))
        return ArticleAnalysis(
            category=classify_category(combined),
            region=classify_region(combined),
            language="en",
            topic_tags=entities[:4],
            entities=entities,
            importance_score=round(importance, 2),
            short_summary=summary,
            key_facts=fact_sentences,
            why_it_matters="",  # never generated heuristically - must stay grounded
            unclear_points=[],
            is_opinion=is_opinion,
        )

    def synthesize_story(self, articles: list[dict]) -> StorySynthesis:
        primary = articles[0]
        all_facts: list[str] = []
        for a in articles:
            for fact in a.get("key_facts") or []:
                if fact not in all_facts:
                    all_facts.append(fact)
        comparison = [
            {"source": a["source"], "framing": f"Headline: {a['title']}"} for a in articles
        ]
        return StorySynthesis(
            headline=primary["title"],
            summary=primary.get("summary") or "",
            what_happened=primary.get("summary") or "",
            why_it_matters="",
            key_facts=all_facts[:8],
            unclear_points=[],
            source_comparison=comparison if len(articles) > 1 else [],
        )

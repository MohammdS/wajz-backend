"""Story clustering (PRD 12.5).

Groups articles about the same event into one story using:
same category + time window + (TF-IDF cosine similarity of title+summary,
boosted by named-entity overlap).
"""

import math
import re
from collections import Counter
from datetime import timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Article, Story, StoryArticle, utcnow

_TOKEN_PATTERN = re.compile(r"[a-zA-Z֐-׿؀-ۿ]{2,}")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "as", "is", "are", "was", "were", "be", "been", "has",
    "have", "had", "it", "its", "this", "that", "these", "those", "he", "she",
    "they", "we", "you", "his", "her", "their", "will", "would", "could", "after",
    "before", "over", "under", "into", "about", "than", "then", "new", "says",
    "said", "say",
}


def tokenize(text: str) -> list[str]:
    return [
        t.lower()
        for t in _TOKEN_PATTERN.findall(text or "")
        if t.lower() not in _STOPWORDS
    ]


def cosine_similarity(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[t] * b[t] for t in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def entity_overlap(a: list[str], b: list[str]) -> float:
    set_a = {e.lower() for e in a or []}
    set_b = {e.lower() for e in b or []}
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / min(len(set_a), len(set_b))


def article_vector(title: str, summary: str | None) -> Counter:
    return Counter(tokenize(f"{title} {summary or ''}"))


def story_similarity(article: Article, story: Story, story_vector: Counter) -> float:
    text_sim = cosine_similarity(article_vector(article.title, article.summary), story_vector)
    ent_sim = entity_overlap(article.entities or [], story.entities or [])
    return 0.7 * text_sim + 0.3 * ent_sim


def find_matching_story(db: Session, article: Article) -> Story | None:
    """Find a recent story similar enough to attach this article to.

    Deliberately not filtered by category: different sources (and the
    classifier) can file the same event under different categories.
    """
    settings = get_settings()
    window_start = utcnow() - timedelta(hours=settings.cluster_window_hours)
    candidates = (
        db.query(Story)
        .filter(
            Story.status == "published",
            Story.last_updated_at >= window_start,
        )
        .order_by(Story.last_updated_at.desc())
        .limit(300)
        .all()
    )
    best_story, best_score = None, 0.0
    for story in candidates:
        vector = article_vector(story.headline, story.summary)
        score = story_similarity(article, story, vector)
        if score > best_score:
            best_story, best_score = story, score
    if best_story is not None and best_score >= settings.cluster_similarity_threshold:
        return best_story
    return None


def attach_article_to_story(db: Session, article: Article, story: Story) -> None:
    exists = (
        db.query(StoryArticle)
        .filter(StoryArticle.story_id == story.id, StoryArticle.article_id == article.id)
        .first()
    )
    if not exists:
        db.add(StoryArticle(story_id=story.id, article_id=article.id))
    story.last_updated_at = utcnow()
    merged = {e.lower(): e for e in (story.entities or [])}
    for entity in article.entities or []:
        merged.setdefault(entity.lower(), entity)
    story.entities = list(merged.values())[:16]
    story.importance_score = max(story.importance_score, article.importance_score)


def create_story_from_article(db: Session, article: Article) -> Story:
    story = Story(
        headline=article.title,
        summary=article.summary,
        what_happened=article.summary,
        why_it_matters=article.why_it_matters,
        key_facts=article.key_facts or [],
        unclear_points=article.unclear_points or [],
        category=article.category,
        region=article.region,
        importance_score=article.importance_score,
        language=article.language or "en",
        entities=article.entities or [],
        confidence_label="opinion_analysis" if article.is_opinion else "single_source",
        status="published",
        published_at=utcnow(),
    )
    db.add(story)
    db.flush()
    db.add(StoryArticle(story_id=story.id, article_id=article.id))
    return story

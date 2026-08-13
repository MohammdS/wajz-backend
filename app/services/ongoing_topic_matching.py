"""Conservative automatic story matching for published ongoing-topic hubs."""

from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import (
    Article,
    OngoingTopic,
    OngoingTopicStory,
    Story,
    StoryArticle,
    utcnow,
)
from app.services.clustering import tokenize

AUTO_ATTACH_THRESHOLD = 0.8
_GENERIC = {
    "breaking",
    "event",
    "follow",
    "hub",
    "latest",
    "news",
    "ongoing",
    "stories",
    "story",
    "update",
    "updates",
    "wajz",
}


@dataclass(frozen=True)
class TopicMatch:
    score: float
    shared_terms: tuple[str, ...]
    matched_signals: tuple[str, ...]


def _normalized_tokens(text: str) -> set[str]:
    return set(tokenize(text)) - _GENERIC


def _story_signals(db: Session, story: Story) -> tuple[set[str], set[str]]:
    text_tokens = _normalized_tokens(
        " ".join(
            [
                story.headline or "",
                story.summary or "",
                story.what_happened or "",
                story.why_it_matters or "",
            ]
        )
    )
    named_signals = {str(value).strip().lower() for value in story.entities or [] if value}
    articles = (
        db.query(Article)
        .join(StoryArticle, StoryArticle.article_id == Article.id)
        .filter(StoryArticle.story_id == story.id)
        .all()
    )
    for article in articles:
        for value in [*(article.entities or []), *(article.topic_tags or [])]:
            normalized = str(value).strip().lower()
            if normalized:
                named_signals.add(normalized)
                text_tokens.update(_normalized_tokens(normalized))
    return text_tokens, named_signals


def score_story_for_topic(db: Session, story: Story, topic: OngoingTopic) -> TopicMatch:
    if not story.category or not topic.category:
        return TopicMatch(0.0, (), ())
    if story.category.casefold() != topic.category.casefold():
        return TopicMatch(0.0, (), ())

    topic_text = " ".join(
        f"{translation.title} {translation.description}" for translation in topic.translations
    )
    category_tokens = _normalized_tokens(topic.category)
    topic_tokens = _normalized_tokens(topic_text) - category_tokens
    story_tokens, signals = _story_signals(db, story)
    shared = sorted((topic_tokens & story_tokens) - category_tokens)
    matched_signals = sorted(
        signal
        for signal in signals
        if len(_normalized_tokens(signal)) >= 1
        and _normalized_tokens(signal).issubset(topic_tokens)
    )

    score = 0.4
    if matched_signals:
        score += 0.4
    else:
        score += min(0.4, len(shared) * 0.2)
    return TopicMatch(round(score, 3), tuple(shared[:8]), tuple(matched_signals[:8]))


def auto_attach_story_to_topics(db: Session, story: Story) -> list[OngoingTopicStory]:
    """Attach only high-confidence matches to active published hubs."""
    if story.status != "published":
        return []
    now = utcnow()
    topics = (
        db.query(OngoingTopic)
        .filter(
            OngoingTopic.status == "published",
            or_(OngoingTopic.expires_at.is_(None), OngoingTopic.expires_at > now),
        )
        .all()
    )
    attached: list[OngoingTopicStory] = []
    for topic in topics:
        if db.get(OngoingTopicStory, (topic.id, story.id)) is not None:
            continue
        match = score_story_for_topic(db, story, topic)
        if match.score < AUTO_ATTACH_THRESHOLD:
            continue
        link = OngoingTopicStory(
            topic_id=topic.id,
            story_id=story.id,
            added_by="automatic",
            match_score=match.score,
            match_reason={
                "shared_terms": list(match.shared_terms),
                "matched_signals": list(match.matched_signals),
                "threshold": AUTO_ATTACH_THRESHOLD,
            },
        )
        db.add(link)
        attached.append(link)
    if attached:
        db.commit()
    return attached

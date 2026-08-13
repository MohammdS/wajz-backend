from datetime import timedelta

from app.models import (
    Article,
    OngoingTopic,
    OngoingTopicStory,
    OngoingTopicTranslation,
    Source,
    Story,
    StoryArticle,
    utcnow,
)
from app.services.ongoing_topic_matching import auto_attach_story_to_topics


def _add_topic(
    db,
    *,
    title: str,
    priority: int,
    story_ids: list[str],
    status: str = "published",
    expires_at=None,
) -> OngoingTopic:
    topic = OngoingTopic(
        category="Sports",
        priority=priority,
        status=status,
        published_at=utcnow() if status == "published" else None,
        expires_at=expires_at,
    )
    db.add(topic)
    db.flush()
    db.add_all(
        [
            OngoingTopicTranslation(
                topic_id=topic.id,
                language="en",
                title=title,
                description="All verified stories from the ongoing event.",
            ),
            OngoingTopicTranslation(
                topic_id=topic.id,
                language="ar",
                title="البطولة العالمية",
                description="كل الأخبار الموثوقة من الحدث الجاري.",
            ),
            *[OngoingTopicStory(topic_id=topic.id, story_id=story_id) for story_id in story_ids],
        ]
    )
    db.commit()
    return topic


def test_seeded_topic_is_public_localized_and_tracks_saved_state(client, auth_headers, demo_data):
    english = client.get("/ongoing-topics").json()
    assert english["total"] == 1
    topic = english["items"][0]
    assert topic["title"] == "Technology in transition"
    assert topic["story_count"] >= 1
    assert topic["content_language"] == "en"

    arabic = client.get("/ongoing-topics", params={"language": "ar"}).json()
    assert arabic["items"][0]["title"] == "تحولات قطاع التكنولوجيا"
    assert arabic["items"][0]["content_language"] == "ar"

    detail = client.get(f"/ongoing-topics/{topic['id']}", params={"limit": 1}).json()
    story_id = detail["stories"]["items"][0]["id"]
    client.post(f"/me/saved-stories/{story_id}", headers=auth_headers)
    saved_detail = client.get(
        f"/ongoing-topics/{topic['id']}",
        headers=auth_headers,
        params={"limit": 1},
    ).json()
    assert saved_detail["stories"]["items"][0]["saved"] is True


def test_priority_expiry_and_unpublished_story_filtering(client, demo_data, db):
    published_story = db.query(Story).filter(Story.status == "published").first()
    assert published_story is not None
    draft_story = Story(headline="Unpublished update", status="draft")
    db.add(draft_story)
    db.commit()

    low = _add_topic(
        db,
        title="Lower priority",
        priority=1,
        story_ids=[published_story.id],
    )
    high = _add_topic(
        db,
        title="Higher priority",
        priority=50,
        story_ids=[published_story.id, draft_story.id],
    )

    listed = client.get("/ongoing-topics").json()["items"]
    custom = [item for item in listed if item["id"] in {low.id, high.id}]
    assert [item["id"] for item in custom] == [high.id, low.id]

    detail = client.get(f"/ongoing-topics/{high.id}").json()
    assert detail["stories"]["total"] == 1
    assert all(item["id"] != draft_story.id for item in detail["stories"]["items"])

    high.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    ids = {item["id"] for item in client.get("/ongoing-topics").json()["items"]}
    assert high.id not in ids
    assert client.get(f"/ongoing-topics/{high.id}").status_code == 404


def test_draft_empty_topics_and_legacy_admin_routes_are_hidden(client, demo_data, db):
    published_story = db.query(Story).filter(Story.status == "published").first()
    assert published_story is not None
    draft = _add_topic(
        db,
        title="Draft topic",
        priority=500,
        story_ids=[published_story.id],
        status="draft",
    )
    empty = _add_topic(
        db,
        title="Empty topic",
        priority=500,
        story_ids=[],
    )

    ids = {item["id"] for item in client.get("/ongoing-topics").json()["items"]}
    assert draft.id not in ids
    assert empty.id not in ids
    assert client.get("/admin/overview").status_code == 404
    paths = client.get("/openapi.json").json()["paths"]
    assert "/admin/overview" not in paths
    assert "/admin/v1/session" in paths


def test_only_high_confidence_stories_are_automatically_attached(demo_data, db):
    topic = db.query(OngoingTopic).filter(OngoingTopic.status == "published").first()
    source = db.query(Source).first()
    assert topic is not None and source is not None

    high = Story(
        headline="New artificial intelligence policy transparency rules",
        summary="Regulators publish artificial intelligence policy requirements.",
        category="Technology",
        entities=["Artificial intelligence"],
        status="published",
        published_at=utcnow(),
    )
    weak = Story(
        headline="Smartphone maker reveals three new case colors",
        summary="The accessories arrive next month.",
        category="Technology",
        entities=["Smartphone"],
        status="published",
        published_at=utcnow(),
    )
    db.add_all([high, weak])
    db.flush()
    high_article = Article(
        source_id=source.id,
        title=high.headline,
        url="https://example.com/high-confidence-hub-match",
        processing_status="processed",
        topic_tags=["artificial intelligence", "technology policy"],
        entities=["Artificial intelligence"],
    )
    weak_article = Article(
        source_id=source.id,
        title=weak.headline,
        url="https://example.com/weak-hub-match",
        processing_status="processed",
        topic_tags=["smartphones", "accessories"],
        entities=["Smartphone"],
    )
    db.add_all([high_article, weak_article])
    db.flush()
    db.add_all(
        [
            StoryArticle(story_id=high.id, article_id=high_article.id),
            StoryArticle(story_id=weak.id, article_id=weak_article.id),
        ]
    )
    db.commit()

    attached = auto_attach_story_to_topics(db, high)
    assert len(attached) == 1
    assert attached[0].topic_id == topic.id
    assert attached[0].added_by == "automatic"
    assert attached[0].match_score >= 0.8
    assert "artificial intelligence" in attached[0].match_reason["matched_signals"]

    assert auto_attach_story_to_topics(db, weak) == []
    assert db.get(OngoingTopicStory, (topic.id, weak.id)) is None

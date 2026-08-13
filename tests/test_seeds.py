from app.models import Article, Source, Story, StoryArticle
from app.seeds import seed_demo, seed_sources


def test_demo_seed_does_not_process_or_publish_unrelated_content(db):
    seed_sources(db)
    source = db.query(Source).first()
    unrelated_article = Article(
        source_id=source.id,
        title="Unrelated live article",
        url="https://example.com/live-article",
        raw_text="A live article that is not part of the reviewed demo fixtures.",
        cleaned_text="A live article that is not part of the reviewed demo fixtures.",
        processing_status="pending",
    )
    unrelated_story = Story(
        headline="Existing editorial review",
        status="pending_review",
    )
    db.add_all([unrelated_article, unrelated_story])
    db.commit()

    seed_demo(db)

    db.refresh(unrelated_article)
    db.refresh(unrelated_story)
    assert unrelated_article.processing_status == "pending"
    assert unrelated_story.status == "pending_review"

    demo_story_ids = {
        row.story_id
        for row in db.query(StoryArticle)
        .join(Article, Article.id == StoryArticle.article_id)
        .filter(Article.url.like("https://demo.wajz.app/%"))
        .all()
    }
    assert demo_story_ids
    assert (
        db.query(Story).filter(Story.id.in_(demo_story_ids), Story.status != "published").count()
        == 0
    )

from app.models import Article, Source, Story, StoryArticle
from app.services.clustering import create_story_from_article


def test_pipeline_clusters_same_event(demo_data):
    """The three EU AI rules articles must merge into a single story."""
    db = demo_data
    eu_articles = (
        db.query(Article).filter(Article.url.like("%eu-ai-rules%")).all()
    )
    assert len(eu_articles) == 3
    story_ids = set()
    for article in eu_articles:
        links = db.query(StoryArticle).filter(StoryArticle.article_id == article.id).all()
        assert len(links) == 1
        story_ids.add(links[0].story_id)
    assert len(story_ids) == 1, "same-event articles were not clustered together"

    story = db.get(Story, story_ids.pop())
    # BBC (high) + Guardian (high) + The Verge (medium) = 3 reliable sources
    assert story.confidence_label == "confirmed_by_multiple_sources"
    assert len(story.source_comparison) == 3


def test_pipeline_keeps_distinct_events_separate(demo_data):
    db = demo_data
    stories = db.query(Story).all()
    # 7 demo articles: 3 cluster into 1 story + 4 standalone = 5 stories
    assert len(stories) == 5


def test_articles_marked_processed(demo_data):
    db = demo_data
    pending = db.query(Article).filter(Article.processing_status == "pending").count()
    assert pending == 0
    processed = db.query(Article).filter(Article.processing_status == "processed").count()
    assert processed == 7


def test_single_source_story_label(demo_data):
    db = demo_data
    exoplanet = db.query(Article).filter(Article.url.like("%exoplanet%")).one()
    link = db.query(StoryArticle).filter(StoryArticle.article_id == exoplanet.id).one()
    story = db.get(Story, link.story_id)
    assert story.confidence_label == "single_source"


def test_ingested_story_is_published_immediately(db):
    source = Source(
        name="Automatic RSS",
        website_url="https://automatic.example",
        rss_url="https://automatic.example/feed.xml",
    )
    db.add(source)
    db.flush()
    article = Article(
        source_id=source.id,
        title="Automatically published story",
        url="https://automatic.example/story",
        summary="A source-grounded summary.",
        why_it_matters="It verifies direct publication.",
        language="en",
    )
    db.add(article)
    db.flush()

    story = create_story_from_article(db, article)

    assert story.status == "published"
    assert story.published_at is not None

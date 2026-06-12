"""Seed data.

Usage:
    python -m app.seeds sources   # seed trusted RSS sources
    python -m app.seeds demo      # seed offline demo articles + run the pipeline
    python -m app.seeds all
"""

import sys
from datetime import timedelta

from app.database import Base, SessionLocal, engine
from app.models import Article, Source, utcnow
from app.services.cleaning import clean_text
from app.services.pipeline import process_pending_articles

TRUSTED_SOURCES = [
    {
        "name": "BBC News",
        "website_url": "https://www.bbc.com/news",
        "rss_url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "country": "United Kingdom",
        "language": "en",
        "reliability_level": "high",
    },
    {
        "name": "NPR",
        "website_url": "https://www.npr.org",
        "rss_url": "https://feeds.npr.org/1001/rss.xml",
        "country": "United States",
        "language": "en",
        "reliability_level": "high",
    },
    {
        "name": "The Guardian",
        "website_url": "https://www.theguardian.com",
        "rss_url": "https://www.theguardian.com/world/rss",
        "country": "United Kingdom",
        "language": "en",
        "reliability_level": "high",
    },
    {
        "name": "Al Jazeera English",
        "website_url": "https://www.aljazeera.com",
        "rss_url": "https://www.aljazeera.com/xml/rss/all.xml",
        "country": "Qatar",
        "language": "en",
        "reliability_level": "medium",
    },
    {
        "name": "The Verge",
        "website_url": "https://www.theverge.com",
        "rss_url": "https://www.theverge.com/rss/index.xml",
        "country": "United States",
        "language": "en",
        "reliability_level": "medium",
    },
    {
        "name": "Ars Technica",
        "website_url": "https://arstechnica.com",
        "rss_url": "https://feeds.arstechnica.com/arstechnica/index",
        "country": "United States",
        "language": "en",
        "reliability_level": "medium",
    },
    {
        "name": "The Times of Israel",
        "website_url": "https://www.timesofisrael.com",
        "rss_url": "https://www.timesofisrael.com/feed/",
        "country": "Israel",
        "language": "en",
        "reliability_level": "medium",
    },
]

# Fictional demo articles so the full flow works offline. Three of them cover
# the same event from different sources to exercise clustering.
_NOW = utcnow()
DEMO_ARTICLES = [
    {
        "source": "BBC News",
        "title": "EU proposes stricter AI model rules",
        "url": "https://demo.wajz.app/bbc/eu-ai-rules",
        "published_at": _NOW - timedelta(hours=3),
        "text": (
            "The European Commission proposed new rules on Tuesday that would require large "
            "AI companies to disclose more details about model safety and training data. "
            "The proposal covers models above a defined compute threshold and would take "
            "effect in 2027. Regulators said the measure is needed for accountability. "
            "Several technology companies warned the rules could slow innovation in Europe. "
            "The proposal now moves to the European Parliament for debate."
        ),
    },
    {
        "source": "The Verge",
        "title": "Europe wants AI giants to open up about training data",
        "url": "https://demo.wajz.app/verge/eu-ai-rules",
        "published_at": _NOW - timedelta(hours=2),
        "text": (
            "The European Commission unveiled a proposal requiring major AI developers to "
            "publish summaries of training data and safety testing results. The draft rules "
            "target models above a compute threshold and include fines of up to 4 percent of "
            "global revenue. Industry groups criticized the timeline as unrealistic, while "
            "consumer organizations welcomed the transparency requirements."
        ),
    },
    {
        "source": "The Guardian",
        "title": "EU unveils transparency rules for powerful AI systems",
        "url": "https://demo.wajz.app/guardian/eu-ai-rules",
        "published_at": _NOW - timedelta(hours=1),
        "text": (
            "European Union officials presented draft legislation that would force developers "
            "of the most powerful AI systems to disclose safety evaluations and training data "
            "sources. The European Commission said the rules build on the AI Act and respond "
            "to rapid advances in general-purpose models. A vote in the European Parliament "
            "is expected next year. Civil society groups called the proposal a step toward "
            "accountability, while several companies said compliance costs would be significant."
        ),
    },
    {
        "source": "NPR",
        "title": "Global markets steady as central banks hold interest rates",
        "url": "https://demo.wajz.app/npr/markets-rates",
        "published_at": _NOW - timedelta(hours=5),
        "text": (
            "Stock markets were broadly stable on Wednesday after central banks in the United "
            "States and Europe kept interest rates unchanged. The Federal Reserve said inflation "
            "continues to ease toward its 2 percent target. Analysts expect one rate cut later "
            "this year. Bond yields fell slightly following the announcements."
        ),
    },
    {
        "source": "Ars Technica",
        "title": "Astronomers detect water vapor on distant exoplanet",
        "url": "https://demo.wajz.app/ars/exoplanet-water",
        "published_at": _NOW - timedelta(hours=8),
        "text": (
            "Scientists using the James Webb Space Telescope reported detecting water vapor in "
            "the atmosphere of an exoplanet 120 light-years away. The planet, located in its "
            "star's habitable zone, is roughly twice the size of Earth. Researchers cautioned "
            "that water vapor alone does not indicate life. The findings were published in the "
            "journal Nature Astronomy."
        ),
    },
    {
        "source": "Al Jazeera English",
        "title": "Regional leaders meet for economic cooperation summit",
        "url": "https://demo.wajz.app/aljazeera/regional-summit",
        "published_at": _NOW - timedelta(hours=6),
        "text": (
            "Leaders from across the Middle East gathered in Amman on Thursday for a two-day "
            "summit focused on regional trade and water security. Delegates discussed a proposed "
            "rail corridor linking Gulf ports to the Mediterranean. Officials said agreements on "
            "cross-border energy projects are expected to be signed on Friday. Jordan's prime "
            "minister called the talks constructive."
        ),
    },
    {
        "source": "The Times of Israel",
        "title": "Tech sector hiring rebounds in first quarter, report finds",
        "url": "https://demo.wajz.app/toi/tech-hiring",
        "published_at": _NOW - timedelta(hours=10),
        "text": (
            "Hiring in the technology sector grew 8 percent in the first quarter compared with "
            "the previous year, according to a report released Sunday by the Innovation "
            "Authority. The report counted 12,400 new positions, concentrated in cybersecurity "
            "and AI companies. Startup funding rose to 2.1 billion dollars in the quarter. "
            "Economists said the rebound signals renewed investor confidence."
        ),
    },
]


def seed_sources(db) -> None:
    for spec in TRUSTED_SOURCES:
        if not db.query(Source).filter(Source.name == spec["name"]).first():
            db.add(Source(**spec))
    db.commit()
    print(f"Sources seeded ({db.query(Source).count()} total).")


def seed_demo(db) -> None:
    seed_sources(db)
    sources = {s.name: s for s in db.query(Source).all()}
    added = 0
    for spec in DEMO_ARTICLES:
        if db.query(Article).filter(Article.url == spec["url"]).first():
            continue
        db.add(
            Article(
                source_id=sources[spec["source"]].id,
                title=spec["title"],
                url=spec["url"],
                published_at=spec["published_at"],
                language="en",
                raw_text=spec["text"],
                cleaned_text=clean_text(spec["text"]),
                processing_status="pending",
            )
        )
        added += 1
    db.commit()
    print(f"Demo articles added: {added}")
    result = process_pending_articles(db)
    print(f"Pipeline: {result}")


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "all"
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        if command in ("sources", "all"):
            seed_sources(db)
        if command in ("demo", "all"):
            seed_demo(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()

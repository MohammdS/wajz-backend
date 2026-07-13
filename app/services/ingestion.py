"""RSS ingestion: fetch feeds from active sources and store new articles."""

import logging
from datetime import datetime

import feedparser
import httpx
from sqlalchemy.orm import Session

from app.models import Article, IngestionRun, Source, utcnow
from app.observability import dispatch_alert, record_ingestion_run
from app.services.cleaning import clean_text

logger = logging.getLogger(__name__)

FETCH_TIMEOUT_SECONDS = 20
MAX_ENTRIES_PER_FEED = 40


def _entry_published(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime(*parsed[:6])
            except (TypeError, ValueError):
                continue
    return None


def _entry_text(entry) -> str:
    if getattr(entry, "content", None):
        return " ".join(c.get("value", "") for c in entry.content)
    return getattr(entry, "summary", "") or ""


def _entry_image(entry) -> str | None:
    for media in getattr(entry, "media_content", []) or []:
        if media.get("url"):
            return media["url"]
    for media in getattr(entry, "media_thumbnail", []) or []:
        if media.get("url"):
            return media["url"]
    for link in getattr(entry, "links", []) or []:
        if link.get("rel") == "enclosure" and str(link.get("type", "")).startswith("image"):
            return link.get("href")
    return None


def ingest_source(db: Session, source: Source, run_id: str | None = None) -> int:
    """Fetch a single source's feed. Returns the number of new articles stored."""
    response = httpx.get(
        source.rss_url,
        timeout=FETCH_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": "WajzBot/0.1 (+news briefing aggregator)"},
    )
    response.raise_for_status()
    feed = feedparser.parse(response.content)

    new_count = 0
    for entry in feed.entries[:MAX_ENTRIES_PER_FEED]:
        url = getattr(entry, "link", None)
        title = getattr(entry, "title", None)
        if not url or not title:
            continue
        if db.query(Article.id).filter(Article.url == url).first():
            continue
        raw = _entry_text(entry)
        article = Article(
            source_id=source.id,
            title=title.strip(),
            url=url,
            author=getattr(entry, "author", None),
            published_at=_entry_published(entry),
            language=source.language,
            raw_text=raw,
            cleaned_text=clean_text(raw),
            image_url=_entry_image(entry),
            processing_status="pending",
            status="collected",
            ingestion_run_id=run_id,
        )
        db.add(article)
        new_count += 1
    db.commit()
    source.last_successful_fetch = utcnow()
    source.failure_count = 0
    source.last_error = None
    db.commit()
    return new_count


def run_ingestion(db: Session) -> IngestionRun:
    """Fetch all active sources, recording an observability row for the run."""
    run = IngestionRun()
    db.add(run)
    db.commit()

    sources = db.query(Source).filter(Source.active.is_(True)).all()
    run.sources_total = len(sources)
    errors: list[str] = []

    for source in sources:
        try:
            fetched = ingest_source(db, source, run.id)
            run.articles_fetched += fetched
            logger.info("Ingested %s new articles from %s", fetched, source.name)
        except Exception as exc:  # noqa: BLE001 - one bad feed must not kill the run
            db.rollback()
            run.sources_failed += 1
            source.failure_count += 1
            source.last_error = str(exc)[:2000]
            errors.append(f"{source.name}: {exc}")
            logger.warning("Failed to ingest %s: %s", source.name, exc)

    run.completed_at = utcnow()
    if run.sources_failed == 0:
        run.status = "succeeded"
    elif run.sources_failed < run.sources_total:
        run.status = "partial"
    else:
        run.status = "failed"
    run.error_message = "; ".join(errors)[:2000] or None
    db.commit()
    record_ingestion_run(run.status, run.articles_fetched, run.sources_failed)
    if run.sources_failed:
        dispatch_alert(
            "ingestion.source_failures",
            "critical" if run.status == "failed" else "warning",
            {
                "run_id": run.id,
                "status": run.status,
                "failed_sources": run.sources_failed,
                "sources_total": run.sources_total,
            },
        )
    return run

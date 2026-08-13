import logging
from datetime import timedelta
from urllib.parse import urlparse

import feedparser
from bs4 import BeautifulSoup
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    AdminJob,
    AnalyticsDailyAggregate,
    AnalyticsEvent,
    Article,
    IngestionRun,
    Source,
    utcnow,
)
from app.observability import dispatch_alert, record_ingestion_run
from app.services.ingestion import ingest_source
from app.services.cleaning import clean_text
from app.services.operational_settings import get_runtime_controls
from app.services.pipeline import process_pending_articles
from app.services.safe_urls import fetch_public_url
from app.services.translations import generate_missing_translations

logger = logging.getLogger(__name__)


def claim_next_job(db: Session) -> AdminJob | None:
    now = utcnow()
    query = (
        db.query(AdminJob)
        .filter(
            AdminJob.status == "queued",
            or_(AdminJob.next_attempt_at.is_(None), AdminJob.next_attempt_at <= now),
        )
        .order_by(AdminJob.next_attempt_at, AdminJob.created_at)
    )
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    job = query.first()
    if job is None:
        return None
    job.status = "running"
    job.started_at = utcnow()
    job.next_attempt_at = None
    job.attempts += 1
    job.error_message = None
    db.commit()
    return job


def _cancelled(db: Session, job: AdminJob) -> bool:
    db.refresh(job)
    if not job.cancel_requested:
        return False
    job.status = "cancelled"
    job.completed_at = utcnow()
    db.commit()
    return True


def _run_ingestion_job(db: Session, job: AdminJob) -> dict:
    controls = get_runtime_controls(db)
    if not controls.ingestion_enabled:
        raise RuntimeError("Ingestion is disabled by operational settings")
    args = job.arguments or {}
    query = db.query(Source).filter(Source.active.is_(True))
    if args.get("source_ids"):
        query = query.filter(Source.id.in_(args["source_ids"]))
    if args.get("category"):
        query = query.filter(Source.category == args["category"])
    if args.get("region"):
        query = query.filter(Source.region == args["region"])
    sources = query.order_by(Source.name).all()
    run = IngestionRun(sources_total=len(sources))
    db.add(run)
    db.commit()
    job.progress_total = len(sources)
    db.commit()
    errors = []
    for source in sources:
        if _cancelled(db, job):
            run.status = "cancelled"
            run.completed_at = utcnow()
            db.commit()
            return {"ingestion_run_id": run.id, "cancelled": True}
        try:
            run.articles_fetched += ingest_source(db, source, run.id)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            source = db.get(Source, source.id)
            run = db.get(IngestionRun, run.id)
            run.sources_failed += 1
            source.failure_count += 1
            source.last_error = str(exc)[:2000]
            errors.append(f"{source.name}: {type(exc).__name__}")
        job = db.get(AdminJob, job.id)
        job.progress_current += 1
        db.commit()
    run.completed_at = utcnow()
    run.status = (
        "succeeded"
        if run.sources_failed == 0
        else "partial"
        if run.sources_failed < run.sources_total
        else "failed"
    )
    run.error_message = "; ".join(errors)[:2000] or None
    db.commit()
    record_ingestion_run(run.status, run.articles_fetched, run.sources_failed)
    return {
        "ingestion_run_id": run.id,
        "status": run.status,
        "sources_total": run.sources_total,
        "sources_failed": run.sources_failed,
        "articles_fetched": run.articles_fetched,
    }


def _run_processing_job(db: Session, job: AdminJob) -> dict:
    if not get_runtime_controls(db).ai_processing_enabled:
        raise RuntimeError("AI processing is disabled by operational settings")
    article_ids = list((job.arguments or {}).get("article_ids") or [])
    if article_ids:
        job.progress_total = len(article_ids)
        db.commit()
        total = {"processed": 0, "failed": 0, "stories_touched": 0}
        for start in range(0, len(article_ids), 10):
            if _cancelled(db, job):
                return {**total, "cancelled": True}
            chunk = article_ids[start : start + 10]
            result = process_pending_articles(db, limit=len(chunk), article_ids=chunk)
            for key in total:
                total[key] += result[key]
            job = db.get(AdminJob, job.id)
            job.progress_current += len(chunk)
            db.commit()
        return total
    return process_pending_articles(db)


def _run_test_source(db: Session, job: AdminJob) -> dict:
    source = db.get(Source, (job.arguments or {}).get("source_id", ""))
    if source is None:
        raise RuntimeError("Source no longer exists")
    response = fetch_public_url(source.rss_url)
    feed = feedparser.parse(response.content)
    if getattr(feed, "bozo", False) and not feed.entries:
        raise RuntimeError("Feed could not be parsed")
    return {"source_id": source.id, "entries_found": len(feed.entries), "healthy": True}


def _run_url_import(db: Session, job: AdminJob) -> dict:
    urls = list((job.arguments or {}).get("urls") or [])
    job.progress_total = len(urls)
    db.commit()
    created_ids = []
    for url in urls:
        if _cancelled(db, job):
            return {"article_ids": created_ids, "cancelled": True}
        if db.query(Article.id).filter(Article.url == url).first():
            job.progress_current += 1
            db.commit()
            continue
        response = fetch_public_url(url)
        soup = BeautifulSoup(response.text, "html.parser")
        title = (
            (soup.title.string.strip() if soup.title and soup.title.string else None)
            or urlparse(url).hostname
            or "Imported article"
        )
        for node in soup(["script", "style", "noscript"]):
            node.decompose()
        text = clean_text(soup.get_text(" ", strip=True))[:100_000]
        hostname = urlparse(url).hostname or "manual"
        source = db.query(Source).filter(Source.name == hostname).first()
        if source is None:
            source = Source(
                name=hostname,
                rss_url=f"https://{hostname}/",
                website_url=f"https://{hostname}/",
                language="en",
                source_type="manual",
                active=False,
            )
            db.add(source)
            db.flush()
        article = Article(
            source_id=source.id,
            title=title[:1000],
            url=url,
            raw_text=None,
            cleaned_text=text,
            processing_status="pending",
            status="collected",
        )
        db.add(article)
        db.flush()
        created_ids.append(article.id)
        job.progress_current += 1
        db.commit()
    if created_ids and get_runtime_controls(db).ai_processing_enabled:
        process_pending_articles(db, limit=len(created_ids), article_ids=created_ids)
    return {"article_ids": created_ids, "imported": len(created_ids)}


def aggregate_analytics(db: Session) -> dict:
    now = utcnow()
    raw_cutoff = now - timedelta(days=get_settings().analytics_raw_retention_days)
    aggregate_cutoff = (
        (now - timedelta(days=get_settings().analytics_aggregate_retention_days)).date().isoformat()
    )
    rows = (
        db.query(
            func.date(AnalyticsEvent.occurred_at),
            AnalyticsEvent.name,
            func.count(AnalyticsEvent.id),
        )
        .group_by(func.date(AnalyticsEvent.occurred_at), AnalyticsEvent.name)
        .all()
    )
    days = {str(day) for day, _, _ in rows}
    if days:
        db.query(AnalyticsDailyAggregate).filter(AnalyticsDailyAggregate.day.in_(days)).delete(
            synchronize_session=False
        )
    for day, name, count in rows:
        db.add(
            AnalyticsDailyAggregate(day=str(day), metric=name, dimensions={}, value=float(count))
        )
    deleted_raw = (
        db.query(AnalyticsEvent)
        .filter(AnalyticsEvent.received_at < raw_cutoff)
        .delete(synchronize_session=False)
    )
    deleted_aggregates = (
        db.query(AnalyticsDailyAggregate)
        .filter(AnalyticsDailyAggregate.day < aggregate_cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    return {
        "days_aggregated": len(days),
        "raw_events_deleted": deleted_raw,
        "aggregates_deleted": deleted_aggregates,
    }


def execute_job(db: Session, job: AdminJob) -> None:
    handlers = {
        "ingest_sources": _run_ingestion_job,
        "process_articles": _run_processing_job,
        "test_source": _run_test_source,
        "translate_stories": lambda session, _: generate_missing_translations(session),
        "aggregate_analytics": lambda session, _: aggregate_analytics(session),
        "import_urls": _run_url_import,
    }
    try:
        handler = handlers.get(job.job_type)
        if handler is None:
            raise RuntimeError("Unsupported admin job type")
        result = handler(db, job)
        job = db.get(AdminJob, job.id)
        if job.status != "cancelled":
            job.status = "succeeded"
            job.result = result
            job.completed_at = utcnow()
            db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job = db.get(AdminJob, job.id)
        job.error_message = str(exc)[:2000]
        if job.attempts < job.max_attempts and not job.cancel_requested:
            job.status = "queued"
            job.started_at = None
            job.next_attempt_at = utcnow() + timedelta(seconds=2**job.attempts)
        else:
            job.status = "failed"
            job.completed_at = utcnow()
            dispatch_alert(
                "admin_job.failed",
                "warning",
                {"job_id": job.id, "job_type": job.job_type},
            )
        db.commit()
        logger.warning("Admin job %s failed: %s", job.id, type(exc).__name__)

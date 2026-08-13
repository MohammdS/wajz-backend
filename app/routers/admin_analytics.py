import csv
import io
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from app.auth import require_owner
from app.database import get_db
from app.models import (
    AIRun,
    AdminJob,
    AnalyticsDailyAggregate,
    AnalyticsEvent,
    Article,
    Source,
    Story,
    User,
    utcnow,
)
from app.rate_limit import rate_limit

router = APIRouter(
    prefix="/admin/v1/analytics",
    tags=["admin analytics"],
    dependencies=[Depends(rate_limit("admin", "rate_limit_admin"))],
)


def _range(from_date: datetime | None, to_date: datetime | None) -> tuple[datetime, datetime]:
    end = (to_date or utcnow()).replace(tzinfo=None)
    start = (from_date or end - timedelta(days=30)).replace(tzinfo=None)
    if end < start or end - start > timedelta(days=366):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Analytics range must be between 0 and 366 days",
        )
    return start, end


def _distinct_installations(db: Session, start: datetime, end: datetime) -> int:
    return (
        db.query(func.count(distinct(AnalyticsEvent.installation_id)))
        .filter(AnalyticsEvent.occurred_at >= start, AnalyticsEvent.occurred_at <= end)
        .scalar()
        or 0
    )


def _timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid timezone") from exc
    return value


def _time_bucket(db: Session, interval: str, timezone: str):
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        localized = func.timezone(timezone, AnalyticsEvent.occurred_at)
        return func.date_trunc(interval, localized)
    if timezone != "UTC":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Non-UTC analytics buckets require PostgreSQL",
        )
    if interval == "week":
        return func.strftime("%Y-W%W", AnalyticsEvent.occurred_at)
    return func.date(AnalyticsEvent.occurred_at)


@router.get("/overview")
def overview(
    from_date: datetime | None = Query(default=None, alias="from"),
    to_date: datetime | None = Query(default=None, alias="to"),
    timezone: str = "UTC",
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    _timezone(timezone)
    start, end = _range(from_date, to_date)
    now = utcnow()
    event_query = db.query(AnalyticsEvent).filter(
        AnalyticsEvent.occurred_at >= start,
        AnalyticsEvent.occurred_at <= end,
    )

    def event_count(name: str) -> int:
        return event_query.filter(AnalyticsEvent.name == name).count()

    return {
        "range": {"from": start, "to": end},
        "active_installations": _distinct_installations(db, start, end),
        "dau": _distinct_installations(db, now - timedelta(days=1), now),
        "wau": _distinct_installations(db, now - timedelta(days=7), now),
        "mau": _distinct_installations(db, now - timedelta(days=30), now),
        "signed_in_users": (
            event_query.with_entities(func.count(distinct(AnalyticsEvent.user_id)))
            .filter(AnalyticsEvent.user_id.is_not(None))
            .scalar()
            or 0
        ),
        "sessions": event_query.with_entities(
            func.count(distinct(AnalyticsEvent.session_id))
        ).scalar()
        or 0,
        "story_opens": event_count("story_opened"),
        "story_saves": event_count("story_saved"),
        "source_clicks": event_count("source_link_clicked"),
        "briefing_completions": event_count("briefing_completed"),
        "content": {
            "published_stories": db.query(Story).filter(Story.status == "published").count(),
            "pending_stories": db.query(Story).filter(Story.status == "pending_review").count(),
            "failed_articles": db.query(Article)
            .filter(Article.processing_status == "failed")
            .count(),
        },
        "operations": {
            "unhealthy_sources": db.query(Source)
            .filter(Source.active.is_(True), Source.failure_count >= 3)
            .count(),
            "failed_jobs": db.query(AdminJob).filter(AdminJob.status == "failed").count(),
            "running_jobs": db.query(AdminJob)
            .filter(AdminJob.status.in_(["queued", "running"]))
            .count(),
            "ai_failures": db.query(AIRun).filter(AIRun.status == "error").count(),
        },
    }


@router.get("/timeseries")
def timeseries(
    metric: str = Query(default="session_started", max_length=48),
    interval: str = Query(default="day", pattern="^(day|week)$"),
    from_date: datetime | None = Query(default=None, alias="from"),
    to_date: datetime | None = Query(default=None, alias="to"),
    timezone: str = "UTC",
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    timezone = _timezone(timezone)
    start, end = _range(from_date, to_date)
    bucket = _time_bucket(db, interval, timezone)
    rows = (
        db.query(bucket.label("bucket"), func.count(AnalyticsEvent.id))
        .filter(
            AnalyticsEvent.name == metric,
            AnalyticsEvent.occurred_at >= start,
            AnalyticsEvent.occurred_at <= end,
        )
        .group_by(bucket)
        .order_by(bucket)
        .all()
    )
    return {
        "metric": metric,
        "interval": interval,
        "items": [{"bucket": str(day), "value": value} for day, value in rows],
    }


@router.get("/funnel")
def funnel(
    from_date: datetime | None = Query(default=None, alias="from"),
    to_date: datetime | None = Query(default=None, alias="to"),
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    start, end = _range(from_date, to_date)
    steps = [
        ("session_started", "Session"),
        ("story_opened", "Read a story"),
        ("authentication_completed", "Signed in"),
        ("onboarding_completed", "Completed onboarding"),
        ("briefing_viewed", "Viewed briefing"),
        ("briefing_completed", "Completed briefing"),
    ]
    items = []
    first = None
    previous = None
    for name, label in steps:
        count = (
            db.query(func.count(distinct(AnalyticsEvent.installation_id)))
            .filter(
                AnalyticsEvent.name == name,
                AnalyticsEvent.occurred_at >= start,
                AnalyticsEvent.occurred_at <= end,
            )
            .scalar()
            or 0
        )
        first = count if first is None else first
        items.append(
            {
                "event": name,
                "label": label,
                "count": count,
                "from_start_rate": count / first if first else 0,
                "from_previous_rate": count / previous if previous else (1 if count else 0),
            }
        )
        previous = count
    return {"items": items}


@router.get("/retention")
def retention(
    from_date: datetime | None = Query(default=None, alias="from"),
    to_date: datetime | None = Query(default=None, alias="to"),
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    start, end = _range(from_date, to_date)
    rows = (
        db.query(AnalyticsEvent.installation_id, AnalyticsEvent.occurred_at)
        .filter(
            AnalyticsEvent.name == "session_started",
            AnalyticsEvent.occurred_at >= start,
            AnalyticsEvent.occurred_at <= end,
        )
        .order_by(AnalyticsEvent.installation_id, AnalyticsEvent.occurred_at)
        .all()
    )
    by_installation: dict[str, set] = {}
    for installation_id, occurred_at in rows:
        by_installation.setdefault(installation_id, set()).add(occurred_at.date())
    cohorts: dict[str, dict[str, int]] = {}
    for dates in by_installation.values():
        first = min(dates)
        cohort = cohorts.setdefault(first.isoformat(), {"size": 0, "d1": 0, "d7": 0, "d30": 0})
        cohort["size"] += 1
        for days in (1, 7, 30):
            if first + timedelta(days=days) in dates:
                cohort[f"d{days}"] += 1
    items = []
    for cohort_day, values in sorted(cohorts.items()):
        size = values["size"]
        items.append(
            {
                "cohort": cohort_day,
                "size": size,
                "d1": values["d1"] / size,
                "d7": values["d7"] / size,
                "d30": values["d30"] / size,
            }
        )
    return {"items": items}


@router.get("/content")
def content_performance(
    from_date: datetime | None = Query(default=None, alias="from"),
    to_date: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=50, ge=1, le=200),
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    start, end = _range(from_date, to_date)
    rows = (
        db.query(
            AnalyticsEvent.entity_id,
            AnalyticsEvent.name,
            func.count(AnalyticsEvent.id),
            func.count(distinct(AnalyticsEvent.installation_id)),
        )
        .filter(
            AnalyticsEvent.entity_type == "story",
            AnalyticsEvent.entity_id.is_not(None),
            AnalyticsEvent.occurred_at >= start,
            AnalyticsEvent.occurred_at <= end,
        )
        .group_by(AnalyticsEvent.entity_id, AnalyticsEvent.name)
        .all()
    )
    grouped: dict[str, dict] = {}
    for story_id, name, count, unique_count in rows:
        item = grouped.setdefault(
            story_id,
            {"story_id": story_id, "opens": 0, "saves": 0, "source_clicks": 0, "unique_readers": 0},
        )
        if name == "story_opened":
            item["opens"] = count
            item["unique_readers"] = unique_count
        elif name == "story_saved":
            item["saves"] = count
        elif name == "source_link_clicked":
            item["source_clicks"] = count
    items = []
    for item in grouped.values():
        story = db.get(Story, item["story_id"])
        if story is None:
            continue
        item.update(
            {
                "headline": story.headline,
                "category": story.category,
                "region": story.region,
                "language": story.language,
                "save_rate": item["saves"] / item["opens"] if item["opens"] else 0,
            }
        )
        items.append(item)
    items.sort(key=lambda item: item["opens"], reverse=True)
    return {"items": items[:limit], "total": len(items), "limit": limit, "offset": 0}


@router.get("/export.csv")
def export_aggregates(
    from_date: datetime | None = Query(default=None, alias="from"),
    to_date: datetime | None = Query(default=None, alias="to"),
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    start, end = _range(from_date, to_date)
    rows = (
        db.query(AnalyticsDailyAggregate)
        .filter(
            AnalyticsDailyAggregate.day >= start.date().isoformat(),
            AnalyticsDailyAggregate.day <= end.date().isoformat(),
        )
        .order_by(AnalyticsDailyAggregate.day, AnalyticsDailyAggregate.metric)
        .all()
    )
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["day", "metric", "value"])
    for row in rows:
        writer.writerow([row.day, row.metric, row.value])
    return StreamingResponse(
        iter([stream.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=wajz-analytics.csv"},
    )

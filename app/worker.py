"""Background worker: periodically ingest feeds and run the AI pipeline.

Run with:  python -m app.worker
Not exposed publicly (PRD 20.6) - it only talks to the database.
"""

import logging
import time
from datetime import timedelta

from app.config import get_settings
from app.database import SessionLocal
from app.observability import dispatch_alert
from app.services.admin_jobs import aggregate_analytics, claim_next_job, execute_job
from app.services.ingestion import run_ingestion
from app.services.operational_settings import get_runtime_controls
from app.services.pipeline import process_pending_articles

logger = logging.getLogger("wajz.worker")


def run_once() -> None:
    db = SessionLocal()
    try:
        run = run_ingestion(db)
        logger.info(
            "Ingestion %s: %s articles from %s sources (%s failed)",
            run.status,
            run.articles_fetched,
            run.sources_total,
            run.sources_failed,
        )
        result = process_pending_articles(db)
        logger.info("Processing: %s", result)
    finally:
        db.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    next_ingestion = 0.0
    next_analytics = 0.0
    logger.info(
        "Wajz worker started (ingestion: %s minutes, jobs: %s seconds)",
        settings.ingestion_interval_minutes,
        settings.admin_job_poll_seconds,
    )
    while True:
        try:
            db = SessionLocal()
            try:
                job = claim_next_job(db)
                if job is not None:
                    execute_job(db, job)
                controls = get_runtime_controls(db)
                now = time.monotonic()
                if now >= next_ingestion:
                    if controls.ingestion_enabled:
                        run = run_ingestion(db)
                        logger.info("Scheduled ingestion completed status=%s", run.status)
                        if controls.ai_processing_enabled:
                            process_pending_articles(db)
                    next_ingestion = now + controls.ingestion_interval_minutes * 60
                if now >= next_analytics:
                    aggregate_analytics(db)
                    next_analytics = now + timedelta(hours=1).total_seconds()
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001 - the worker loop must survive any cycle failure
            logger.exception("Worker cycle failed")
            dispatch_alert(
                "worker.cycle_failed",
                "critical",
                {"exception_type": type(exc).__name__},
            )
        time.sleep(max(1, settings.admin_job_poll_seconds))


if __name__ == "__main__":
    main()

"""Background worker: periodically ingest feeds and run the AI pipeline.

Run with:  python -m app.worker
Not exposed publicly (PRD 20.6) - it only talks to the database.
"""

import logging
import time

from app.config import get_settings
from app.database import SessionLocal
from app.observability import dispatch_alert
from app.services.ingestion import run_ingestion
from app.services.pipeline import process_pending_articles

logger = logging.getLogger("wajz.worker")


def run_once() -> None:
    db = SessionLocal()
    try:
        run = run_ingestion(db)
        logger.info(
            "Ingestion %s: %s articles from %s sources (%s failed)",
            run.status, run.articles_fetched, run.sources_total, run.sources_failed,
        )
        result = process_pending_articles(db)
        logger.info("Processing: %s", result)
    finally:
        db.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    interval = settings.ingestion_interval_minutes * 60
    logger.info("Wajz worker started (interval: %s minutes)", settings.ingestion_interval_minutes)
    while True:
        try:
            run_once()
        except Exception as exc:  # noqa: BLE001 - the worker loop must survive any cycle failure
            logger.exception("Worker cycle failed")
            dispatch_alert(
                "worker.cycle_failed",
                "critical",
                {"exception_type": type(exc).__name__},
            )
        time.sleep(interval)


if __name__ == "__main__":
    main()

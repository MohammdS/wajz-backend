from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import SessionLocal, get_db
from app.models import AIRun, Article, IngestionRun, Source
from app.rate_limit import rate_limit
from app.schemas import SourceCreate, SourceOut, SourceUpdate
from app.services.ingestion import run_ingestion
from app.services.pipeline import process_pending_articles

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin), Depends(rate_limit("admin", "rate_limit_auth"))],
)


@router.post("/sources", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
def create_source(body: SourceCreate, db: Session = Depends(get_db)) -> Source:
    if db.query(Source).filter(Source.name == body.name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Source with this name already exists")
    source = Source(**body.model_dump())
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.put("/sources/{source_id}", response_model=SourceOut)
def update_source(source_id: str, body: SourceUpdate, db: Session = Depends(get_db)) -> Source:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(source, field, value)
    db.commit()
    db.refresh(source)
    return source


def _run_ingestion_and_processing() -> None:
    db = SessionLocal()
    try:
        run_ingestion(db)
        process_pending_articles(db)
    finally:
        db.close()


@router.post("/ingestion/run", status_code=status.HTTP_202_ACCEPTED)
def trigger_ingestion(background: BackgroundTasks) -> dict:
    background.add_task(_run_ingestion_and_processing)
    return {"status": "scheduled"}


@router.post("/articles/{article_id}/reprocess")
def reprocess_article(article_id: str, db: Session = Depends(get_db)) -> dict:
    article = db.get(Article, article_id)
    if article is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Article not found")
    article.processing_status = "pending"
    db.commit()
    result = process_pending_articles(db, limit=10)
    return {"status": "done", **result}


@router.post("/processing/run")
def trigger_processing(db: Session = Depends(get_db)) -> dict:
    return process_pending_articles(db)


@router.get("/ingestion-runs")
def list_ingestion_runs(limit: int = 20, db: Session = Depends(get_db)) -> list[dict]:
    runs = db.query(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "started_at": r.started_at,
            "completed_at": r.completed_at,
            "status": r.status,
            "sources_total": r.sources_total,
            "sources_failed": r.sources_failed,
            "articles_fetched": r.articles_fetched,
            "error_message": r.error_message,
        }
        for r in runs
    ]


@router.get("/ai-runs")
def list_ai_runs(limit: int = 50, db: Session = Depends(get_db)) -> list[dict]:
    runs = db.query(AIRun).order_by(AIRun.created_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "task_type": r.task_type,
            "input_reference_type": r.input_reference_type,
            "input_reference_id": r.input_reference_id,
            "model_name": r.model_name,
            "status": r.status,
            "error_message": r.error_message,
            "created_at": r.created_at,
            "completed_at": r.completed_at,
        }
        for r in runs
    ]

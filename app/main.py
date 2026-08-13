import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import engine
from app.observability import configure_observability
from app.routers import (
    admin_analytics,
    admin_content,
    admin_operations,
    auth,
    health,
    me,
    privacy,
    public,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

settings = get_settings()
settings.validate_runtime()

app = FastAPI(
    title=settings.app_name,
    description="Calm, source-grounded daily news briefings. No noise. Sources included.",
    version=settings.release,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

configure_observability(app, engine)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(public.router)
app.include_router(me.router)
app.include_router(privacy.router)
app.include_router(admin_analytics.router)
app.include_router(admin_content.router)
app.include_router(admin_operations.router)

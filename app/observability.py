"""Production observability primitives with opt-in external exporters."""

import logging
import re
import threading
import time
import uuid
from contextvars import ContextVar
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from sqlalchemy.engine import Engine

from app.config import get_settings

logger = logging.getLogger(__name__)
request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)

HTTP_REQUESTS = Counter(
    "wajz_http_requests_total",
    "HTTP requests handled by the API.",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "wajz_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method", "route"),
)
HTTP_IN_PROGRESS = Gauge(
    "wajz_http_requests_in_progress",
    "HTTP requests currently being handled.",
    ("method",),
)
AI_RUNS = Counter(
    "wajz_ai_runs_total",
    "AI pipeline runs by task and outcome.",
    ("task_type", "status"),
)
INGESTION_RUNS = Counter(
    "wajz_ingestion_runs_total",
    "Ingestion runs by outcome.",
    ("status",),
)
INGESTION_ARTICLES = Counter(
    "wajz_ingestion_articles_total",
    "Articles collected by ingestion runs.",
)
INGESTION_SOURCE_FAILURES = Counter(
    "wajz_ingestion_source_failures_total",
    "Source failures observed during ingestion.",
)

_safe_request_id = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def configure_observability(app: FastAPI, engine: Engine) -> None:
    """Install local metrics/request tracing and optional external exporters."""
    settings = get_settings()
    _configure_sentry()
    _configure_open_telemetry(app, engine)

    @app.middleware("http")
    async def request_observability(request: Request, call_next):
        incoming_id = request.headers.get("x-request-id", "")
        request_id = incoming_id if _safe_request_id.fullmatch(incoming_id) else uuid.uuid4().hex
        token = request_id_context.set(request_id)
        started = time.perf_counter()
        method = request.method
        response_status = status.HTTP_500_INTERNAL_SERVER_ERROR
        HTTP_IN_PROGRESS.labels(method=method).inc()
        try:
            response = await call_next(request)
            response_status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            route = request.scope.get("route")
            route_path = getattr(route, "path", "unmatched")
            duration = time.perf_counter() - started
            HTTP_IN_PROGRESS.labels(method=method).dec()
            HTTP_REQUESTS.labels(
                method=method,
                route=route_path,
                status=str(response_status),
            ).inc()
            HTTP_DURATION.labels(method=method, route=route_path).observe(duration)
            logger.info(
                "request.complete method=%s route=%s status=%s duration_ms=%.1f request_id=%s",
                method,
                route_path,
                response_status,
                duration * 1000,
                request_id,
            )
            request_id_context.reset(token)

    @app.get("/metrics", include_in_schema=False)
    def metrics(request: Request) -> Response:
        expected = settings.metrics_token
        if expected and request.headers.get("x-metrics-token") != expected:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid metrics token")
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _configure_sentry() -> None:
    settings = get_settings()
    if not settings.sentry_dsn:
        return
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=settings.release,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
    )
    logger.info("Sentry crash reporting enabled")


def _configure_open_telemetry(app: FastAPI, engine: Engine) -> None:
    settings = get_settings()
    if not settings.otel_exporter_otlp_endpoint:
        return
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/")
    if not endpoint.endswith("/v1/traces"):
        endpoint = f"{endpoint}/v1/traces"
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "wajz-api",
                "service.version": settings.release,
                "deployment.environment": settings.environment,
            }
        )
    )
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    SQLAlchemyInstrumentor().instrument(engine=engine)
    logger.info("OpenTelemetry export enabled endpoint=%s", endpoint)


def record_ai_run(task_type: str, run_status: str) -> None:
    AI_RUNS.labels(task_type=task_type, status=run_status).inc()


def record_ingestion_run(run_status: str, articles: int, failed_sources: int) -> None:
    INGESTION_RUNS.labels(status=run_status).inc()
    if articles:
        INGESTION_ARTICLES.inc(articles)
    if failed_sources:
        INGESTION_SOURCE_FAILURES.inc(failed_sources)


def dispatch_alert(event: str, severity: str, details: dict[str, Any] | None = None) -> None:
    """Send an alert without blocking ingestion or request handling."""
    settings = get_settings()
    if not settings.alert_webhook_url:
        return
    payload = {
        "event": event,
        "severity": severity,
        "environment": settings.environment,
        "release": settings.release,
        "details": details or {},
    }
    threading.Thread(
        target=_send_alert,
        args=(settings.alert_webhook_url, settings.alert_webhook_token, payload),
        daemon=True,
        name="wajz-alert-webhook",
    ).start()


def _send_alert(url: str, token: str, payload: dict[str, Any]) -> None:
    headers = {"Authorization": f"Bearer {token}"} if token else None
    try:
        httpx.post(url, json=payload, headers=headers, timeout=5.0).raise_for_status()
    except Exception as exc:  # noqa: BLE001 - alert delivery must not crash the app
        logger.warning("Alert webhook delivery failed: %s", type(exc).__name__)

# wajz-backend

Backend for **Wajz (واجِز)** — a calm, trust-first, source-grounded daily news briefing app.

> Stay informed in minutes. No noise. Sources included.

## Architecture

```
Flutter app ── HTTPS ──> FastAPI API ──> PostgreSQL / SQLite
                              │
              ┌───────────────┴───────────────┐
        Ingestion worker                AI pipeline
        (RSS feeds)                     (Anthropic / Z.AI or
                                         heuristic fallback)
```

- **Ingestion** fetches RSS feeds from vetted sources, cleans article text.
- **AI pipeline** classifies (category/region/entities/importance) and
  summarizes (summary, key facts, why it matters, unclear points) each article,
  then clusters same-event articles into **stories** and synthesizes a
  multi-source summary with a confidence label.
- **Story translations** are stored once per supported language in
  `story_translations`. APIs select the requested or user's preferred language
  and fall back to the source language when a translation is unavailable.
- **Briefings** are finite, per-user, per-day story selections sized by the
  user's briefing-length preference. Stories must match at least one selected
  topic or region and are ranked by normalized topic match, region match, and
  recency within a 36-hour window. The endpoint ends with "You are caught up."
- AI runs only in the backend (PRD key architecture decision). If no Anthropic
  or Z.AI API key is configured, a deterministic extractive fallback keeps
  the product working — it never invents interpretation.

## Quick start (local, zero setup)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1          # or: source .venv/bin/activate
pip install -e .[dev]
copy .env.example .env               # defaults: SQLite + dev auth

alembic upgrade head                 # create schema
python -m app.seeds all              # seed sources + offline demo stories
uvicorn app.main:app --reload        # http://127.0.0.1:8000/docs
```

Fetch real news (network required):

```powershell
python -m app.worker                 # ingest + process on an interval
# or one-off via the API:
curl -X POST http://127.0.0.1:8000/admin/ingestion/run -H "X-Admin-Token: <ADMIN_TOKEN>"
```

## Quick start (Docker)

```bash
docker compose up --build            # API on :8000 + PostgreSQL + worker
```

## API overview

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` | — | liveness |
| `GET /health/live`, `GET /health/ready` | — | external liveness + database readiness probes |
| `GET /metrics` | optional `X-Metrics-Token` | Prometheus metrics |
| `GET /categories`, `GET /sources` | — | reference data |
| `GET /stories`, `GET /stories/{id}` | optional | story feed + detail (sources always included) |
| `POST /auth/dev-login` | — | local-dev JWT (AUTH_MODE=dev only) |
| `GET /me`, `GET/PUT /me/preferences` | bearer | profile + preferences |
| `GET /me/briefing/today` | bearer | finite daily briefing |
| `POST /me/stories/{id}/opened` | bearer | record per-user story progress |
| `GET/POST/DELETE /me/saved-stories[/{id}]` | bearer | read-later |
| `POST /admin/sources`, `PUT /admin/sources/{id}` | X-Admin-Token | source management |
| `POST /admin/ingestion/run`, `POST /admin/processing/run` | X-Admin-Token | manual triggers |
| `POST /admin/translations/run` | X-Admin-Token | backfill missing story translations |
| `GET /admin/ingestion-runs`, `GET /admin/ai-runs` | X-Admin-Token | observability |

Interactive docs: `http://127.0.0.1:8000/docs`.

## Auth modes

- `AUTH_MODE=dev` — `POST /auth/dev-login {email}` issues an HS256 JWT signed
  with `SECRET_KEY`. For local development only.
- `AUTH_MODE=supabase` — bearer tokens are verified against
  `SUPABASE_JWT_SECRET`; users are auto-provisioned from token claims.

Secrets (LLM keys, JWT secrets, admin token) live only in backend env vars —
never in the mobile app.

## Admin dashboard

Admin access uses the normal bearer token plus a backend-stored role:
`viewer`, `editor`, or `super_admin`. Configure the initial super-admin email
with `ADMIN_EMAILS`; subsequent role changes are restricted to `super_admin`.
Every admin write is recorded in `audit_logs`.

Build the separate Flutter Web entry point from `wajz-mobile`:

```powershell
flutter build web -t lib/main_admin.dart
```

The consumer app continues to use `lib/main.dart`. AI/RSS stories enter
`pending_review`; only an explicit admin publish action exposes them publicly.

## Observability

- Every response includes `X-Request-ID`; an incoming safe request ID is preserved.
- `/metrics` exports bounded-cardinality HTTP, AI, and ingestion Prometheus metrics.
- `SENTRY_DSN` enables FastAPI/worker crash reporting without sending user PII.
- `OTEL_EXPORTER_OTLP_ENDPOINT` enables FastAPI and SQLAlchemy trace export over OTLP/HTTP.
- `ALERT_WEBHOOK_URL` sends non-blocking ingestion and worker failure alerts. Set
  `ALERT_WEBHOOK_TOKEN` when the receiver requires a bearer token.
- External monitors should probe `/health/live` for process health and
  `/health/ready` for database readiness.

All external exporters are disabled by default for local development.

## Tests

```powershell
pytest
```

Covers: API contract, auth/ownership, preference validation, briefing
generation, saved stories, clustering of same-event articles, confidence
labels, rate limiting, cleaning, and the heuristic provider's grounding rules.

## Configuration

See [.env.example](.env.example). Notable:

- `DATABASE_URL` — SQLite by default; PostgreSQL in docker-compose.
- `AI_PROVIDER` — `auto`, `anthropic`, `zai`, or `heuristic`. In `auto`,
  Anthropic is preferred when both provider keys are present.
- `ANTHROPIC_API_KEY` / `AI_MODEL` — Anthropic credentials and model.
- `ZAI_API_KEY` / `ZAI_MODEL` — Z.AI credentials and GLM model
  (`glm-4.5-air` by default).
- `ZAI_BASE_URL` — defaults to Z.AI's OpenAI-compatible API endpoint.
- `CONTENT_LANGUAGES` — comma-separated stored story languages (`en,ar` by default).
- `RATE_LIMIT_*` — in-memory fixed-window limiter (single-process MVP; move to
  Redis when scaling out).

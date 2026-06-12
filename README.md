# wajz-backend

Backend for **Wajz (وجز)** — a calm, trust-first, source-grounded daily news briefing app.

> Stay informed in minutes. No noise. Sources included.

## Architecture

```
Flutter app ── HTTPS ──> FastAPI API ──> PostgreSQL / SQLite
                              │
              ┌───────────────┴───────────────┐
        Ingestion worker                AI pipeline
        (RSS feeds)                     (Anthropic API or
                                         heuristic fallback)
```

- **Ingestion** fetches RSS feeds from vetted sources, cleans article text.
- **AI pipeline** classifies (category/region/entities/importance) and
  summarizes (summary, key facts, why it matters, unclear points) each article,
  then clusters same-event articles into **stories** and synthesizes a
  multi-source summary with a confidence label.
- **Briefings** are finite, per-user, per-day story selections sized by the
  user's briefing-length preference. The endpoint ends with "You are caught up."
- AI runs only in the backend (PRD key architecture decision). If no
  `ANTHROPIC_API_KEY` is configured, a deterministic extractive fallback keeps
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
| `GET /categories`, `GET /sources` | — | reference data |
| `GET /stories`, `GET /stories/{id}` | optional | story feed + detail (sources always included) |
| `POST /auth/dev-login` | — | local-dev JWT (AUTH_MODE=dev only) |
| `GET /me`, `GET/PUT /me/preferences` | bearer | profile + preferences |
| `GET /me/briefing/today` | bearer | finite daily briefing |
| `GET/POST/DELETE /me/saved-stories[/{id}]` | bearer | read-later |
| `POST /admin/sources`, `PUT /admin/sources/{id}` | X-Admin-Token | source management |
| `POST /admin/ingestion/run`, `POST /admin/processing/run` | X-Admin-Token | manual triggers |
| `GET /admin/ingestion-runs`, `GET /admin/ai-runs` | X-Admin-Token | observability |

Interactive docs: `http://127.0.0.1:8000/docs`.

## Auth modes

- `AUTH_MODE=dev` — `POST /auth/dev-login {email}` issues an HS256 JWT signed
  with `SECRET_KEY`. For local development only.
- `AUTH_MODE=supabase` — bearer tokens are verified against
  `SUPABASE_JWT_SECRET`; users are auto-provisioned from token claims.

Secrets (LLM keys, JWT secrets, admin token) live only in backend env vars —
never in the mobile app.

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
- `AI_MODEL` — defaults to `claude-opus-4-8`.
- `RATE_LIMIT_*` — in-memory fixed-window limiter (single-process MVP; move to
  Redis when scaling out).

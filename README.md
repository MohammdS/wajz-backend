# Wajz backend

FastAPI backend for Wajz (واجِز), an Arabic-first, source-grounded news app.

## Architecture

```text
Flutter clients -> HTTPS/Caddy -> FastAPI -> PostgreSQL
                                      |
                                      +-> Periodic worker
                                             +-> RSS ingestion
                                             +-> Anthropic/Gemini/Z.AI
                                             +-> Arabic translation
```

The periodic worker runs RSS ingestion, article analysis, story synthesis, and
translation directly. Admin-triggered processing and News Studio operations
run synchronously.

Only `published` stories are public, eligible for saved-story reads, or added
to briefings. Seed data is isolated to the demo records created by the seeder.

## Local development

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
alembic upgrade head
python -m app.seeds all
docker compose up --build
```

Docker Compose starts PostgreSQL, the API, and the periodic worker. API docs
are at `http://127.0.0.1:8000/docs`.

For a host-run API, start these separately:

```powershell
uvicorn app.main:app --reload
python -m app.worker
```

## Authentication

- `AUTH_MODE=dev` exposes `/auth/dev-login` for explicit local development.
- `AUTH_MODE=supabase` verifies asymmetric JWTs through Supabase JWKS and
  confirms every token with Supabase Auth. This makes deleted or banned users
  fail immediately instead of remaining active until token expiry.
- Wajz users are keyed by the stable Supabase subject, not a mutable email.
- Locally disabled Wajz accounts are rejected after identity verification.
- Admin APIs require a bearer token and a database-backed `viewer`, `editor`,
  or `super_admin` role. UI visibility never substitutes for API authorization.

The consumer client supports guests; authentication is required only for
account-scoped features such as preferences, saved stories, and briefings.

## AI and Arabic operations

Set `AI_PROVIDER` to `anthropic`, `gemini`, `zai`, `heuristic`, or `auto`.
Provider keys stay on the backend.

Gemini configuration:

```dotenv
AI_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-3.6-flash
```

Gemini analysis, synthesis, and translation use structured JSON responses.
`CONTENT_LANGUAGES=en,ar` and `TRANSLATION_LANGUAGES=ar` make Arabic an
explicit operational target. Translation jobs are bounded by
`TRANSLATION_BATCH_SIZE` and exclude archived or rejected stories.

## Production

Copy `.env.production.example` outside version control, replace every
placeholder, then:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml config
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
```

The production stack includes PostgreSQL, the API, periodic worker, and Caddy.
Caddy provisions and renews HTTPS automatically.
Production startup fails closed when auth, database, secrets, HTTPS CORS,
metrics protection, Arabic operations, or the selected AI provider are
misconfigured.

Never commit `.env.production`, provider keys, Supabase secrets, or database
credentials. The mobile/web clients receive only the Supabase publishable key.

## Validation

```powershell
ruff check app tests
pytest -q
alembic upgrade head
alembic check
docker compose config --quiet
docker build -t wajz-backend:local .
```

CI runs this matrix on pull requests and `main`. Version tags publish a
provenance- and SBOM-enabled image to GHCR.

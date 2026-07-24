# SyncUp

An AI "chief of staff" for university student organizations, driven from Discord.
Describe an event in plain English and SyncUp schedules it, reserves resources, and
drafts a budget — in one atomic transaction. See [.claude/CLAUDE.md](.claude/CLAUDE.md)
for architecture and [docs/](docs/) for the flow diagrams.

```
api/   FastAPI backend + Discord bot (one process)  → Render
web/   Vite + React + TypeScript dashboard          → Vercel
```

**Status:** scaffold. Core infra, DB schema, migration `0001`, and the Foundry client
are wired; `/health` works. The three feature modules (`scheduling`, `resources`,
`finance`) and the Discord bot are still stubs — their `/api/*` routes raise
`NotImplementedError` until each owner implements them.

## Prerequisites

- Python 3.12 · Node 18+ · a PostgreSQL 16 database (Supabase free tier)
- The steps below use stock `python3 -m venv` + `pip`. `uv` is optional (faster) —
  install with `brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`.

## Database setup (once)

In the Supabase SQL editor, enable the required extensions **before** migrating:

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS btree_gist;
```

Use the **Shared Pooler (Supavisor)** connection string, not the direct one
(direct is IPv6-only on free tier and times out from Render).

## Backend — `api/`

```bash
cd api
cp .env.example .env          # fill in DATABASE_URL (required to start), then the rest
az login                      # Foundry auth is Entra ID, not an API key (skip if not using the LLM)

python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
# have uv? faster:  uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"
# Python 3.14+ locally but project targets 3.12? use  python3.12 -m venv .venv  (brew install python@3.12)

alembic upgrade head          # applies schema.sql (all tables, indexes, constraints)
python scripts/seed.py        # optional: load demo data (DEV database only)

uvicorn app.main:app --reload --port 8000
```

API docs at http://localhost:8000/docs · health check at `/health`.

## Frontend — `web/`

```bash
cd web
cp .env.example .env.local    # VITE_API_URL defaults to http://localhost:8000
npm install
npm run dev                   # http://localhost:5173
```

## Quality checks

```bash
# backend (from api/)
ruff format . && ruff check . && mypy app

# frontend (from web/)
npm run typecheck && npm run build
```

## Environment variables

Backend (`api/.env`) — see `api/.env.example`:

| Var | Required | Notes |
|---|---|---|
| `DATABASE_URL` | yes | Supabase Shared Pooler URL; rewritten for asyncpg at load |
| `ORG_ID` | no | The single org this deployment serves; seed creates the org with this id. Defaults to a fixed UUID |
| `FOUNDRY_PROJECT_ENDPOINT` / `FOUNDRY_AGENT_NAME` / `FOUNDRY_AGENT_VERSION` | for LLM features | Foundry project endpoint + hosted agent reference. Auth is Entra ID, **not** an API key |
| `AZURE_TENANT_ID` / `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` | Foundry on Render only | Service-principal login for `DefaultAzureCredential`. Local dev uses `az login` instead |
| `DISCORD_BOT_TOKEN` / `DISCORD_TEST_GUILD_ID` | for the bot | |
| `API_KEY` | for dashboard auth | sent as the `X-API-Key` header |
| `CORS_ORIGINS` | no | defaults to `http://localhost:5173` |

Frontend (`web/.env.local`): `VITE_API_URL`, `VITE_API_KEY`.

## Deploy

- **Backend** → Render, via [`api/render.yaml`](api/render.yaml). Set the env vars in the
  dashboard (they are `sync: false`, never committed).
- **Frontend** → Vercel, root directory `web/`. Auto-detected as a Vite project.

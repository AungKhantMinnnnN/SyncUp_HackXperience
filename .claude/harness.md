# harness.md

The day-to-day **dev / build harness** for SyncUp — how to get the repo running, work in it, and keep it running during the 24 hours. For design see `Architecture.md`; for coding rules see `CLAUDE.md`.

---

## 0. TL;DR — from zero to running

```bash
git clone git@github.com:<org>/syncup.git && cd syncup

# --- backend ---
cd api
uv venv && source .venv/bin/activate         # Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"
cp .env.example .env                          # fill in — see §3
alembic upgrade head
python scripts/seed.py
uvicorn app.main:app --reload --port 8000     # → http://localhost:8000/docs

# --- frontend (new terminal) ---
cd ../web
npm install
cp .env.example .env.local                    # VITE_API_BASE_URL=http://localhost:8000
npm run dev                                    # → http://localhost:5173
```

If `/health` returns `{"status":"ok"}` and the dashboard loads, you're in.

---

## 1. Prerequisites

| Tool | Version | Check |
|---|---|---|
| Python | 3.12+ | `python --version` |
| uv | latest | `uv --version` (or use `pip`) |
| Node | 20+ | `node --version` |
| Git | any | `git --version` |
| psql | 16 (optional) | `psql --version` |

Accounts (create **before** the hackathon): GitHub, Supabase (×2 projects: dev + prod), Render, Vercel, Discord (+ a test server you own + a registered bot app), Microsoft Foundry (with a model deployed and the endpoint smoke-tested).

---

## 2. Databases: dev vs prod

Create **two** Supabase projects: `syncup-dev` and `syncup-prod`. Everyone develops against **dev**; only `main` deploys point at prod. This prevents someone's test run from clobbering the demo DB at hour 22.

In each project's **SQL editor**, before the first migration:

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS btree_gist;
SELECT extname FROM pg_extension WHERE extname IN ('pgcrypto','btree_gist');  -- expect 2 rows
```

Grab the connection string from **Settings → Database → Connection string → Session pooler** (Supavisor). **Not** the direct connection — it is IPv6-only on the free plan and unreachable from Render.

---

## 3. Environment variables

### api/.env
```bash
# Supabase SESSION POOLER (Supavisor), not the direct connection
DATABASE_URL=postgresql+asyncpg://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres

FOUNDRY_ENDPOINT=https://<your-project>.services.ai.azure.com/...
FOUNDRY_API_KEY=<key>
FOUNDRY_MODEL=gpt-4o-mini

DISCORD_BOT_TOKEN=<token>
DISCORD_GUILD_ID=<test server id>
DISCORD_ANNOUNCE_CHANNEL_ID=<#events id>

ENVIRONMENT=development
CORS_ORIGINS=http://localhost:5173,https://<your>.vercel.app
API_KEY=<shared dashboard secret>
SQL_ECHO=false
LLM_CACHE=true          # cache LLM calls by prompt hash in dev — saves quota
```

### web/.env.local
```bash
VITE_API_BASE_URL=http://localhost:8000
```

`config.py` rewrites `postgresql://`→`postgresql+asyncpg://` and strips any `?sslmode=` param automatically, so paste Supabase's string as-is if you prefer. `.env` is gitignored; keep `.env.example` current with every key (blank values) so teammates can diff.

---

## 4. Database workflow (Alembic)

**One linear chain. Migrations are strictly sequential across the team.**

```bash
# Create a migration for YOUR module (only after the previous one is merged)
alembic revision --autogenerate -m "0002_resources"

# Apply
alembic upgrade head

# Roll back one step
alembic downgrade -1

# Where am I?
alembic current
alembic history
```

### The rules that prevent the #1 database disaster

1. **Sequence, don't parallelize:** A merges `0001_core` → then B autogenerates `0002` → then C autogenerates `0003`. Generating two revisions from the same parent creates **multiple heads** and `alembic upgrade` refuses to run.
2. If you already have two heads: edit one file's `down_revision` to point at the other. Do **not** reach for `alembic merge` under time pressure.
3. Every model file **must** be imported in `app/models/__init__.py` before `Base.metadata` is read, or autogenerate will propose dropping tables it can't see.
4. Never edit a migration that's already merged. Add a new one.

### Reseed to a known state
```bash
python scripts/seed.py        # idempotent: truncates then inserts. Run against DEV.
```
`seed.py` must always produce the demo fixture: 2 orgs, 12 members, ~150 busy_blocks, the pre-seeded **Chess Club projector clash**, a semester budget tuned so a demo event lands in `TIGHT`, and 4 past events for burn-down history.

---

## 5. The local dev loop

Two terminals, both hot-reloading:

```bash
# terminal 1 — backend (reloads on .py change)
uvicorn app.main:app --reload --port 8000

# terminal 2 — frontend (reloads on save)
npm run dev
```

- **API docs / manual testing:** http://localhost:8000/docs (Swagger UI — hit every endpoint without the bot).
- **The Discord bot starts with the backend** (via `lifespan`). To iterate on the bot you must restart uvicorn; `--reload` handles it on file save.
- **Bot not needed for most work:** test scheduling/resources/finance logic straight through `/docs` or `pytest`. Only wire the bot when the service layer is solid.
- **DB inspection:** Supabase dashboard → Table editor, or `psql "$DATABASE_URL"`.

### Working on just your module
You rarely need the whole system up. Because it's a monolith with pure-function cores, you can unit-test `scoring.py` / `availability.py` / `headroom.py` with **no DB and no LLM** (see §7). That's where most of your logic lives — build it there first.

---

## 6. Code quality

```bash
ruff format .          # autoformat — run on save, no style debates
ruff check . --fix     # lint
mypy app               # types (best-effort under time pressure)
```

Conventions (full list in `CLAUDE.md`): `feat/<module>-<thing>` branches, `feat(scheduling): …` commits, merge to `main` at least every 3 hours, no PR reviews.

---

## 7. Testing

Fast, deterministic tests over the pure functions are your safety net; they catch regressions without spinning up Postgres or calling the model.

```bash
pytest                         # everything
pytest tests/test_scoring.py   # one module
pytest -k headroom -q          # by keyword
pytest --lf                    # only last-failed (fast during a crunch)
```

### What to test, in priority order
1. **Pure functions** (`scoring`, `availability`, `headroom`) — no I/O, table-driven. These are the defensible logic; cover the boundaries (exact-fit slot, exam elimination, partial availability, OK/TIGHT/OVER edges).
2. **The confirm transaction rolls back** — assert that a forced resource conflict leaves **no** event row behind. This proves the monolith's core promise.
3. **LLM output validation** — feed a captured bad JSON blob, assert the retry/reject path (don't call the live model in tests).

### Testing without burning LLM quota
- Unit tests **never** hit Foundry. Inject a fake `complete_json` that returns a canned Pydantic object.
- In dev, `LLM_CACHE=true` memoizes real calls by prompt hash — first call hits the model, repeats are instant and free.

### Minimal fixtures
```python
# tests/conftest.py — an in-memory-ish session against the DEV db or a schema-per-test.
# Under 24h pressure it's fine to point tests at a throwaway Supabase schema and
# TRUNCATE between tests. Keep the pure-function tests DB-free so they always run fast.
```

---

## 8. Deploying (first hours, not last)

Do all of this in the **first two hours** while it's trivial to debug. Order:

1. Supabase dev + prod created, extensions enabled.
2. Repo scaffolded, `/health` returns 200 locally.
3. **Render** service live (`api/` root), `/health` returns 200 in prod.
4. **Vercel** deployed (`web/` root), dashboard loads and calls prod `/health`.
5. **Uptime pinger** (UptimeRobot / cron-job.org / scheduled GitHub Action) hitting `/health` every 10 min.

### Render (backend)
| Setting | Value |
|---|---|
| Root directory | `api` |
| Build | `pip install -e . && alembic upgrade head` |
| Start | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Health check | `/health` |
| Instance | Free |

Bind to `$PORT` (Render injects it). Migrations run in the build so schema and code deploy together. Set all secrets in the dashboard (`sync: false` in `render.yaml`).

### Vercel (frontend)
| Setting | Value |
|---|---|
| Root directory | `web` |
| Framework | Vite |
| Build | `npm run build` · Output `dist` |
| Env | `VITE_API_BASE_URL` = Render URL |

Add `web/vercel.json` so client routes survive refresh:
```json
{ "rewrites": [{ "source": "/(.*)", "destination": "/index.html" }] }
```
After the first Vercel deploy, put its URL in `CORS_ORIGINS` on Render and redeploy the backend. Remember `VITE_*` is baked at build time — changing it needs a redeploy, not a restart.

---

## 9. Discord bot setup

1. Developer Portal → New Application → Bot → Reset Token (copy). Enable **Message Content Intent** if you want `@mention` in addition to slash commands.
2. OAuth2 URL Generator → scopes `bot` + `applications.commands`; perms: Send Messages, Embed Links, Use Slash Commands, Read History. Open the URL, add the bot to your test server.
3. **Sync commands to the test guild, never globally** (global propagation ≈ up to an hour).
4. Command handlers must `defer(thinking=True)` first, then `followup.send(...)` — Discord's 3s ack limit is shorter than an LLM round trip.

---

## 10. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Connection timeout to Supabase from Render | Direct connection (IPv6-only on free) | Use the Supavisor pooler host |
| `InvalidCatalogName` / auth fail | Pooler user must be `postgres.<ref>` | Copy the URI verbatim from the dashboard |
| `sslmode is not a valid keyword` | asyncpg rejects libpq params | Strip `?sslmode=`; SSL via `connect_args` (handled in `config.py`) |
| First request hangs ~1 min | Render free cold start | Expected. Uptime pinger; warm it before the demo |
| Slash commands don't appear | Synced globally | Guild-scoped `tree.sync(guild=...)` |
| "The application did not respond" | Agent slower than Discord's 3s | `defer()` then `followup.send()` |
| CORS error in dashboard | Vercel URL missing / trailing slash in `CORS_ORIGINS` | Exact origin, no trailing slash, redeploy backend |
| Frontend still calls localhost in prod | `VITE_*` baked at build | Set on Vercel, redeploy |
| Budget totals off by a cent | `float` somewhere | `Decimal` end-to-end; `NUMERIC(12,2)` in DB |
| `IntegrityError` on reservation insert | Working as designed — a real double-book blocked | Catch it, return a friendly conflict message |
| LLM returns unparseable JSON | Temp too high / schema not in prompt | Lower to 0.2, restate schema, keep retry loop |
| Alembic "target database is not up to date" / multiple heads | Two migrations off one parent | Fix a `down_revision` by hand (§4) |
| `ImportError` circular | A leaf module imported `scheduling` | Move shared types to `core/types.py`; scheduling imports leaves, never the reverse |

---

## 11. Pre-demo checklist (10 minutes before)

- [ ] Hit prod `/health` — confirm fast response (service awake)
- [ ] `python scripts/seed.py` against prod — reset to known state
- [ ] Confirm the Chess Club projector booking exists (makes the conflict fire)
- [ ] Confirm the semester budget lands the demo event near `TIGHT`
- [ ] Bot shows **online** in the server member list
- [ ] Dashboard open in a second tab, already loaded
- [ ] Phone hotspot ready in case venue wifi dies
- [ ] **90-second screen recording of the working flow (captured ~hour 20)** ready as fallback

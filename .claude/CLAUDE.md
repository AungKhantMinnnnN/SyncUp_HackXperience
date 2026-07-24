# CLAUDE.md

Guidance for AI coding agents (and humans) working in the **SyncUp** repository.
Read this before writing code. It encodes decisions the team has already made — do not relitigate them mid-build.

---

## What SyncUp is

An AI "chief of staff" for university student organizations, driven from **Discord**. An organizer describes an event in plain English (`/plan a 100-person orientation night next Thursday, budget $300`) and SyncUp, in one conversation:

1. **Schedules** it — finds conflict-free, priority-weighted meeting times.
2. **Resources** it — infers a packing list, reserves equipment and a room, flags conflicts.
3. **Budgets** it — drafts an itemized budget and checks it against the semester allocation.

Hackathon context: **Track 2 (Friction to Flow), Subtrack 2A (Task & Time Management)**. Team of 3, 24-hour build, all-free stack.

## The one idea that ties it together

Time conflicts, resource conflicts, and budget overruns are **the same problem**: an unmanaged claim on a limited resource across an interval, detected before a human commits. **One conflict-detection primitive, three domains.** Keep this framing in code and comments — it is the pitch and the architecture.

---

## Golden rules (do not violate)

1. **This is a monolith.** One FastAPI process, one database, one deploy. `scheduling`, `resources`, and `finance` are Python packages, **not** services. Cross-module calls are direct in-process function calls sharing one `AsyncSession` — never HTTP, never a queue.
2. **The LLM proposes; Python decides.** The model parses language and explains results. It **never** computes a score, an availability number, or a money total. Every number comes from deterministic Python.
3. **One writer per table.** Each module owns its tables (see map below). Other modules read. Never write to another module's tables or edit their model file.
4. **Import direction is one-way.** `scheduling` may import `resources` and `finance`. They must **never** import `scheduling` (circular import = startup crash). Shared types go in `app/core/types.py`.
5. **Never `commit()` inside a module service that scheduling calls.** Scheduling owns the transaction. `plan_for_event()` and `draft_for_event()` receive a session and use it; they never manage its lifecycle.
6. **Money is `Decimal` / `NUMERIC(12,2)` everywhere.** Never `float`, never a JSON float on the wire (serialize money as strings like `"287.50"`).
7. **All timestamps are `TIMESTAMPTZ`, stored UTC.** Localize only in the UI.
8. **Secrets never enter git.** `.env` is gitignored from commit one. Commit `.env.example` with blank values.

---

## Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Backend | **Python 3.12 + FastAPI** (async) | Single process; hosts the REST API *and* the Discord bot |
| Bot | **discord.py** | Runs as an asyncio task in the app's `lifespan` |
| ORM / migrations | **SQLAlchemy 2.0 async + Alembic** | One linear migration chain |
| DB | **PostgreSQL 16 on Supabase** | `pgcrypto` + `btree_gist` extensions required |
| LLM | **Microsoft Foundry** via the **OpenAI SDK** | Point `base_url` at the Foundry endpoint. (Not the deprecated `azure-ai-inference` SDK) |
| Frontend | **React + Vite + TypeScript on Vercel** | Dashboard: calendar heatmap, resource timeline, budget burn-down |
| Jobs | **APScheduler** | Hold expiry, reminders |
| Hosting | **Render** (backend) + **Vercel** (frontend) + **Supabase** (DB) | All free tier |

---

## Repository layout

```
syncup/
├── api/                       # → Render
│   ├── app/
│   │   ├── main.py            # FastAPI app, lifespan, CORS, router mounts
│   │   ├── config.py          # pydantic-settings; rewrites DB URL, strips sslmode
│   │   ├── db.py              # async engine, session dependency
│   │   ├── core/
│   │   │   ├── types.py       # shared dataclasses (Event view, ReservationPlan…)
│   │   │   ├── llm.py         # Foundry client + JSON-schema helper + ai_interactions log
│   │   │   ├── time.py        # UTC + interval overlap utilities
│   │   │   └── security.py    # API key / Discord signature
│   │   ├── models/            # SQLAlchemy — one file per domain; ALL imported in __init__
│   │   │   ├── base.py org.py scheduling.py resources.py finance.py
│   │   ├── features/
│   │   │   ├── scheduling/    # router schemas service scoring agent   (Member A)
│   │   │   ├── resources/     # router schemas service availability agent (Member B)
│   │   │   └── finance/       # router schemas service headroom agent   (Member C)
│   │   ├── bot/               # client.py embeds.py commands/{plan,resources,budget}.py
│   │   └── jobs/scheduler.py  # APScheduler tasks
│   ├── alembic/versions/      # 0001_core → 0002_resources → 0003_finance
│   ├── scripts/seed.py
│   ├── tests/
│   └── pyproject.toml render.yaml
├── web/                       # → Vercel (Vite React)
│   └── src/{api/client.ts, pages/{Calendar,Resources,Budget}.tsx}
└── docs/                      # handbook + flow diagrams + this file
```

### Per-module file conventions

| File | Contains | Rule |
|---|---|---|
| `router.py` | FastAPI routes only | No logic — parse, call service, return |
| `schemas.py` | Pydantic request/response + **LLM output schemas** | |
| `service.py` | Business logic + DB access | **Only** layer that writes to the DB |
| `scoring.py` / `availability.py` / `headroom.py` | **Pure functions** | No I/O, no LLM. Unit-tested. The defensible logic lives here |
| `agent.py` | LLM prompts + tool defs | Calls pure functions; never computes |

---

## Ownership map

| Owner | Code | Tables (writes) |
|---|---|---|
| **A — Scheduling** | `features/scheduling/`, core scaffold, bot? no | `busy_blocks`, `scheduling_requests`, `slot_proposals`, `events`, `event_attendees` + creates shared `organizations`, `members`, `venues` |
| **B — Resources** | `features/resources/`, bot skeleton + embeds | `resources`, `resource_reservations`, `packing_list_items` |
| **C — Finance** | `features/finance/`, React shell | `budgets`, `event_budgets`, `budget_line_items`, `expenses` |

Everyone reads everything; only the owner writes.

---

## The confirm transaction (the heart of the app)

`POST /api/scheduling/proposals/{id}/confirm` runs **one transaction across all three modules**:

```python
# app/features/scheduling/service.py
from app.features.resources import service as resources_service
from app.features.finance   import service as finance_service

async def confirm_proposal(db, proposal_id, actor_id) -> EventPlan:
    async with db.begin():                       # BEGIN
        event = await _create_event(db, proposal, actor_id)
        await _add_attendees(db, event, proposal)
        plan   = await resources_service.plan_for_event(db, event)   # same session
        budget = await finance_service.draft_for_event(db, event, plan)  # same session
    # COMMIT here. Any exception above rolls back EVERYTHING.
    return EventPlan(event=event, reservations=plan, budget=budget)
```

If the resource `btree_gist` exclusion constraint fires, the event insert rolls back with it. No orphaned events, no compensating transactions. **This atomicity is the reason we chose a monolith — protect it.**

---

## LLM usage rules

- Always request **JSON against a Pydantic schema**; validate and retry (2×) on malformed output. Never patch bad JSON.
- **Temperature 0.1–0.3.** We want the same answer twice on stage.
- **Ground with real context** — inject the org's inventory / historical prices into the prompt. Grounding beats prompt-engineering.
- **Match IDs server-side by name.** Never trust an ID the model emits (hallucinated resource/line IDs must be impossible to act on).
- **Log every call** to `ai_interactions` (prompt, tool calls, tokens, latency). This is our answer to "how do you know the AI is right?"
- **Cache by prompt hash in dev** to save free quota and make iteration instant.

---

## Discord bot rules

- **Defer immediately**: `await interaction.response.defer(thinking=True)` then `followup.send(...)`. Discord kills un-acked interactions after 3s; an LLM round trip is slower.
- **Sync commands to the test guild, never globally** during the hackathon (global propagation can take an hour).
- All embeds come from shared builders in `bot/embeds.py` so the three features look like one product.
- A bot command is a **thin adapter** over the same `service.py` function the REST route calls — never a second implementation.

---

## Database rules

- One linear Alembic chain: **A merges `0001`, then B generates `0002`, then C generates `0003`.** Two autogenerates from the same parent = multiple heads = broken upgrade. If it happens, fix a `down_revision` by hand; don't `alembic merge` under pressure.
- All model files must be imported in `app/models/__init__.py` before `Base.metadata` is read, or autogenerate proposes dropping unseen tables.
- Use `TEXT` + `CHECK` constraints, not PG `ENUM` (enum changes need a migration and can block).
- Enable `pgcrypto` + `btree_gist` in the Supabase SQL editor **before** the first migration.

### Supabase connection gotchas (these cost an hour each)

1. **Use the Shared Pooler (Supavisor) host, not the direct connection.** Direct is IPv6-only on the free plan; Render has no IPv6 egress → opaque timeout.
2. Supabase gives `postgresql://`; SQLAlchemy async needs `postgresql+asyncpg://`, and asyncpg **rejects `?sslmode=`**. Rewrite the prefix and strip the param in `config.py`.

---

## Commands

```bash
# Backend (from api/)
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
alembic upgrade head
python scripts/seed.py
uvicorn app.main:app --reload --port 8000   # http://localhost:8000/docs

# Frontend (from web/)
npm install && npm run dev                  # http://localhost:5173

# Quality
ruff format . && ruff check . && mypy app
pytest                                       # see harness.md
```

Full setup and the day-to-day dev loop live in **harness.md**. System design lives in **Architecture.md**.

---

## Conventions

- Branches: `feat/<module>-<thing>`. Merge to `main` small and often (≥ every 3h). No PR reviews — ownership boundaries are the safety net.
- Commits: `feat(scheduling): weighted slot scoring` — the prefix makes the README write itself.
- API: routes under `/api/<feature>/`, JSON, snake_case fields. One error shape everywhere: `{"detail": str, "code": str}`.
- Datetimes on the wire: ISO-8601 UTC with `Z`. Money on the wire: strings.
- `ruff format` on save. Zero time on style debates.

## When unsure

Prefer the **boring, atomic, in-process** option over the clever, distributed, or eventually-consistent one. This is a 24-hour build: every dependency you add is a failure mode you have to debug at 3am. If a change would break one of the golden rules above, stop and flag it instead.

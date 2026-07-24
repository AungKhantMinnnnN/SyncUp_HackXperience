-- SyncUp — complete database schema (single PostgreSQL / Supabase, one public schema)
--
-- This is the canonical DDL. Two ways to apply it:
--   1. Supabase SQL editor / psql:  psql "$DATABASE_URL" -f schema.sql
--   2. Alembic:                      alembic upgrade head   (migration 0001 runs this file)
--
-- Rules encoded here (see docs/04-Database-Schema.html):
--   UUID PKs via gen_random_uuid()   · money as NUMERIC(12,2)   · time as TIMESTAMPTZ (UTC)
--   TEXT + CHECK instead of PG ENUM  · JSONB for volatile LLM output
--   btree_gist exclusion constraint makes double-booking impossible at the data layer
--
-- Ownership (writer module per table):
--   SHARED     organizations, members, venues, ai_interactions
--   SCHEDULING busy_blocks, scheduling_requests, slot_proposals, events, event_attendees
--   RESOURCES  resources, resource_reservations, packing_list_items
--   FINANCE    budgets, event_budgets, budget_line_items, expenses

-- ---------------------------------------------------------------------------
-- Extensions  (must exist before anything below; enable in Supabase SQL editor)
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;    -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS btree_gist;  -- = plus && in one GiST index / exclusion


-- ===========================================================================
-- SHARED
-- ===========================================================================

CREATE TABLE IF NOT EXISTS organizations (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name              text NOT NULL,
    discord_guild_id  text UNIQUE,
    timezone          text NOT NULL DEFAULT 'UTC',
    quiet_hours_start time,
    quiet_hours_end   time,
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS members (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    full_name        text NOT NULL,
    email            text,
    discord_user_id  text,
    role             text NOT NULL DEFAULT 'member'
                     CHECK (role IN ('president', 'exec', 'treasurer', 'member')),
    priority_weight  int  NOT NULL DEFAULT 1,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS venues (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name             text NOT NULL,
    capacity         int,
    hourly_cost      numeric(12,2) NOT NULL DEFAULT 0,
    external_room_id text,
    created_at       timestamptz NOT NULL DEFAULT now()
);

-- "How do you know the AI is right?" — logged prompt, tool calls, tokens, latency.
CREATE TABLE IF NOT EXISTS ai_interactions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      uuid REFERENCES organizations(id) ON DELETE SET NULL,
    feature     text NOT NULL,          -- scheduling | resources | finance
    model       text,
    prompt      text,
    response    jsonb,
    tool_calls  jsonb,
    tokens      int,
    latency_ms  int,
    created_at  timestamptz NOT NULL DEFAULT now()
);


-- ===========================================================================
-- SCHEDULING  (Member A)
-- ===========================================================================

CREATE TABLE IF NOT EXISTS busy_blocks (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id  uuid NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    kind       text NOT NULL
               CHECK (kind IN ('class', 'exam', 'work', 'club', 'personal')),
    start_utc  timestamptz NOT NULL,
    end_utc    timestamptz NOT NULL,
    weight     int  NOT NULL DEFAULT 1,
    source     text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (end_utc > start_utc)
);

CREATE TABLE IF NOT EXISTS scheduling_requests (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id             uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_by         uuid REFERENCES members(id) ON DELETE SET NULL,
    raw_prompt         text NOT NULL,
    parsed_constraints jsonb,
    status             text NOT NULL DEFAULT 'parsing'
                       CHECK (status IN ('parsing', 'proposing', 'awaiting_choice',
                                         'confirmed', 'expired', 'failed')),
    created_at         timestamptz NOT NULL DEFAULT now()
);

-- events referenced by slot_proposals.event_id, so create events first.
CREATE TABLE IF NOT EXISTS events (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    venue_id            uuid REFERENCES venues(id) ON DELETE SET NULL,
    created_by          uuid REFERENCES members(id) ON DELETE SET NULL,
    title               text NOT NULL,
    description         text,
    start_utc           timestamptz NOT NULL,
    end_utc             timestamptz NOT NULL,
    expected_attendance int,
    status              text NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft', 'confirmed', 'rescheduled',
                                          'completed', 'cancelled')),
    created_at          timestamptz NOT NULL DEFAULT now(),
    CHECK (end_utc > start_utc)
);

CREATE TABLE IF NOT EXISTS slot_proposals (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id     uuid NOT NULL REFERENCES scheduling_requests(id) ON DELETE CASCADE,
    event_id       uuid REFERENCES events(id) ON DELETE SET NULL,
    start_utc      timestamptz NOT NULL,
    end_utc        timestamptz NOT NULL,
    score          numeric(6,2),
    attendance_pct numeric(5,2),
    conflicts      jsonb,
    rank           int,
    selected       boolean NOT NULL DEFAULT false,
    created_at     timestamptz NOT NULL DEFAULT now(),
    CHECK (end_utc > start_utc)
);

CREATE TABLE IF NOT EXISTS event_attendees (
    event_id    uuid NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    member_id   uuid NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    required    boolean NOT NULL DEFAULT false,
    rsvp_status text NOT NULL DEFAULT 'pending',
    PRIMARY KEY (event_id, member_id)
);


-- ===========================================================================
-- RESOURCES  (Member B)
-- ===========================================================================

CREATE TABLE IF NOT EXISTS resources (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name             text NOT NULL,
    category         text,
    quantity_total   int  NOT NULL DEFAULT 1,
    exclusive        boolean NOT NULL DEFAULT false,
    replacement_cost numeric(12,2),
    condition        text,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS resource_reservations (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    resource_id uuid NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
    event_id    uuid REFERENCES events(id) ON DELETE CASCADE,
    quantity    int  NOT NULL DEFAULT 1,
    start_utc   timestamptz NOT NULL,
    end_utc     timestamptz NOT NULL,
    exclusive   boolean NOT NULL DEFAULT false,
    status      text NOT NULL DEFAULT 'held'
                CHECK (status IN ('held', 'confirmed', 'checked_out',
                                  'returned', 'overdue', 'released')),
    expires_at  timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CHECK (end_utc > start_utc),

    -- The heart of the app: an exclusive resource cannot be double-booked over
    -- an overlapping interval while a live hold exists. Rolls back the whole
    -- confirm transaction (event insert included) if violated.
    EXCLUDE USING gist (
        resource_id WITH =,
        tstzrange(start_utc, end_utc) WITH &&
    ) WHERE (exclusive AND status IN ('held', 'confirmed', 'checked_out'))
);

CREATE TABLE IF NOT EXISTS packing_list_items (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id    uuid NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    resource_id uuid REFERENCES resources(id) ON DELETE SET NULL,
    item_name   text NOT NULL,
    quantity    int  NOT NULL DEFAULT 1,
    org_owned   boolean NOT NULL DEFAULT false,
    source      text NOT NULL DEFAULT 'ai' CHECK (source IN ('ai', 'manual')),
    est_cost    numeric(12,2),
    created_at  timestamptz NOT NULL DEFAULT now()
);


-- ===========================================================================
-- FINANCE  (Member C)
-- ===========================================================================

CREATE TABLE IF NOT EXISTS budgets (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    semester        text NOT NULL,
    total_allocated numeric(12,2) NOT NULL DEFAULT 0,
    currency        char(3) NOT NULL DEFAULT 'USD',
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS event_budgets (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id        uuid NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    budget_id       uuid NOT NULL REFERENCES budgets(id) ON DELETE CASCADE,
    estimated_total numeric(12,2) NOT NULL DEFAULT 0,
    actual_total    numeric(12,2) NOT NULL DEFAULT 0,
    stated_cap      numeric(12,2),
    status          text NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'approved', 'rejected',
                                      'reconciling', 'closed', 'cancelled')),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS budget_line_items (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_budget_id uuid NOT NULL REFERENCES event_budgets(id) ON DELETE CASCADE,
    category        text NOT NULL
                    CHECK (category IN ('food', 'venue', 'equipment_rental',
                                        'printing', 'materials', 'transport',
                                        'contingency')),
    description     text,
    unit_cost       numeric(12,2) NOT NULL DEFAULT 0,
    quantity        int NOT NULL DEFAULT 1,
    line_total      numeric(12,2) NOT NULL DEFAULT 0,
    source          text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS expenses (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_budget_id uuid NOT NULL REFERENCES event_budgets(id) ON DELETE CASCADE,
    line_item_id    uuid REFERENCES budget_line_items(id) ON DELETE SET NULL,
    paid_by         uuid REFERENCES members(id) ON DELETE SET NULL,
    amount          numeric(12,2) NOT NULL,
    description     text,
    status          text NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'disputed',
                                      'rejected', 'reimbursed')),
    spent_at        timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);


-- ===========================================================================
-- Indexes that matter (overlap hot paths, hot lookups, price priors, sweeps)
-- ===========================================================================

-- Overlap queries: scheduling availability + resource conflicts
CREATE INDEX IF NOT EXISTS idx_busy_blocks_range ON busy_blocks
    USING gist (member_id, tstzrange(start_utc, end_utc));

CREATE INDEX IF NOT EXISTS idx_reservations_range ON resource_reservations
    USING gist (resource_id, tstzrange(start_utc, end_utc));

CREATE INDEX IF NOT EXISTS idx_events_org_time ON events (org_id, start_utc)
    WHERE status IN ('draft', 'confirmed');

-- Hot lookups
CREATE INDEX IF NOT EXISTS idx_members_org       ON members (org_id);
CREATE INDEX IF NOT EXISTS idx_members_discord   ON members (discord_user_id);
CREATE INDEX IF NOT EXISTS idx_line_items_budget ON budget_line_items (event_budget_id);
CREATE INDEX IF NOT EXISTS idx_expenses_budget   ON expenses (event_budget_id);

-- Historical price priors for the budget builder
CREATE INDEX IF NOT EXISTS idx_line_items_category ON budget_line_items (category, created_at DESC);

-- Expiring-hold sweep, runs every 5 minutes
CREATE INDEX IF NOT EXISTS idx_reservations_expiry ON resource_reservations (expires_at)
    WHERE status = 'held';

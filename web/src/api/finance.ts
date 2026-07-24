import { api } from "./client";

// Money is strings on the wire; parse with Number() only for rendering, never math.
export type LineItem = { category: string; description: string | null; line_total: string };
export type EventBudget = {
  event_title: string;
  estimated_total: string;
  actual_total: string;
  stated_cap: string | null;
  status: string;
  over_cap: boolean;
  line_items: LineItem[];
};
export type FinanceSummary = {
  semester: string | null;
  total_allocated: string;
  currency: string;
  committed: string;
  spent: string;
  events: EventBudget[];
};

export const getFinanceSummary = () => api<FinanceSummary>("/api/finance/summary");

// ---------------------------------------------------------------------------
// Real finance API (doc §8) — headroom, budget drafting, burndown, variance.
// ---------------------------------------------------------------------------

// No login/session concept in this dashboard yet — every approval is attributed
// to a placeholder actor. Swap for a real member id once auth lands.
export const DASHBOARD_ACTOR_ID = "00000000-0000-0000-0000-000000000000";

export type Verdict = "OK" | "TIGHT" | "OVER";

export type LineItemOut = {
  id: string;
  category: string;
  description: string | null;
  unit_cost: string;
  quantity: number;
  line_total: string;
  source: string | null;
};

export type EventBudgetOut = {
  id: string;
  event_id: string;
  status: string;
  estimated_total: string;
  actual_total: string;
  stated_cap: string | null;
  lines: LineItemOut[];
};

export type BudgetDraftOut = {
  event_budget: EventBudgetOut;
  verdict: Verdict;
  remaining: string;
  suggested_cuts: string[] | null;
};

export type HeadroomOut = {
  org_id: string;
  semester: string;
  allocated: string;
  committed: string;
  actual: string;
  remaining: string;
  verdict: Verdict;
};

export type BurndownPoint = { date: string; cumulative_committed: string; cumulative_actual: string };
export type BurndownOut = { org_id: string; semester: string; allocated: string; points: BurndownPoint[] };

export type VarianceLine = {
  event_title: string;
  category: string;
  description: string | null;
  estimated: string;
  actual: string;
  variance: string;
};
export type VarianceOut = { org_id: string; lines: VarianceLine[] };

const BASE = "/api/finance";

export const getEventBudget = (eventId: string) =>
  api<EventBudgetOut>(`${BASE}/events/${eventId}/budget`);

export const regenerateBudget = (eventId: string) =>
  api<BudgetDraftOut>(`${BASE}/events/${eventId}/budget/regenerate`, { method: "POST" });

export const patchLine = (
  budgetId: string,
  lineId: string,
  patch: { unit_cost?: string; quantity?: number; description?: string },
) =>
  api<LineItemOut>(`${BASE}/budgets/${budgetId}/lines/${lineId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

export const approveBudget = (budgetId: string, actorId: string) =>
  api<EventBudgetOut>(`${BASE}/budgets/${budgetId}/approve`, {
    method: "POST",
    body: JSON.stringify({ actor_id: actorId }),
  });

export const logExpense = (budgetId: string, amount: string, description: string, memberId: string) =>
  api<{ id: string; amount: string; description: string | null; status: string; variance: string | null }>(
    `${BASE}/budgets/${budgetId}/expenses`,
    { method: "POST", body: JSON.stringify({ amount, description, member_id: memberId }) },
  );

export const getHeadroom = (orgId: string, semester: string) =>
  api<HeadroomOut>(`${BASE}/headroom?org_id=${orgId}&semester=${encodeURIComponent(semester)}`);

export const getBurndown = (orgId: string, semester: string) =>
  api<BurndownOut>(`${BASE}/burndown?org_id=${orgId}&semester=${encodeURIComponent(semester)}`);

export const getVariance = (orgId: string) => api<VarianceOut>(`${BASE}/variance?org_id=${orgId}`);
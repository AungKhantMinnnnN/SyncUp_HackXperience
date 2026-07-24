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

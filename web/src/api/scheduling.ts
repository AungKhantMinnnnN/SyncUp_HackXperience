// Scheduling endpoints. Times are UTC on the wire; format to org-local in the UI.
import { api } from "./client";

export type Proposal = {
  id: string;
  start_utc: string;
  end_utc: string;
  score: number | null;
  attendance_pct: number | null;
  rank: number | null;
  conflicts: string[];
  available_members: string[];
};

export type RequestStatus = {
  request_id: string;
  status: string;
  parsed_constraints: Record<string, unknown> | null;
  proposals: Proposal[];
};

export type EventPlan = {
  event: { id: string; title: string; start_utc: string; end_utc: string; status: string };
  reservations: { reservation_ids: string[]; unowned_items: unknown[]; venue_cost: string };
  budget: { estimated_total: string; stated_cap: string | null; verdict: string };
};

export type Org = { id: string; name: string; timezone: string };

const BASE = "/api/scheduling";

export const getOrg = () => api<Org>(`${BASE}/org`);

export const createRequest = (prompt: string) =>
  api<{ request_id: string; status: string }>(`${BASE}/requests`, {
    method: "POST",
    body: JSON.stringify({ prompt }),
  });

export const getRequest = (id: string) => api<RequestStatus>(`${BASE}/requests/${id}`);

export const confirmProposal = (proposalId: string) =>
  api<EventPlan>(`${BASE}/proposals/${proposalId}/confirm`, {
    method: "POST",
    body: JSON.stringify({}),
  });

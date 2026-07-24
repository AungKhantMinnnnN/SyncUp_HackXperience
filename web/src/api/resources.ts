import { api } from "./client";

// Single-org build: org_id is pinned (matches the backend's settings.org_id default).
export const ORG_ID = "11111111-1111-1111-1111-111111111111";

export type Resource = {
  id: string;
  name: string;
  category: string | null;
  quantity_total: number;
  exclusive: boolean;
  condition: string | null;
};

export type Reservation = {
  id: string;
  resource_id: string;
  event_id: string | null;
  quantity: number;
  start_utc: string;
  end_utc: string;
  exclusive: boolean;
  status: string;
};

export type Conflict = {
  resource_name: string;
  event_id: string | null;
  requested: number;
  available: number;
  shortfall: number;
  blocking_event_title: string | null;
  suggested_alternative: string | null;
};

const BASE = "/api/resources";

export const listResources = () => api<Resource[]>(`${BASE}/?org_id=${ORG_ID}`);
export const listReservations = (resourceId: string) =>
  api<Reservation[]>(`${BASE}/${resourceId}/reservations?org_id=${ORG_ID}`);
export const listConflicts = () => api<Conflict[]>(`${BASE}/conflicts?org_id=${ORG_ID}`);

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

export type AvailabilityCell = { day: string; hour: number; free_count: number };
export type Availability = { member_count: number; cells: AvailabilityCell[] };
export type EventAllocation = { item_name: string; quantity: number; org_owned: boolean };
export type EventItem = {
  id: string;
  title: string;
  start_utc: string;
  end_utc: string;
  status: string;
  venue_id: string | null;
  members: string[];
  items: EventAllocation[];
};

export const getAvailability = (from: string, to: string) =>
  api<Availability>(`${BASE}/availability?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`);

export const getEvents = (from: string, to: string) =>
  api<EventItem[]>(`${BASE}/events?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`);

export type MemberInfo = { id: string; full_name: string; role: string };
export type BusyBlock = { member_id: string; kind: string; start_utc: string; end_utc: string };
export type CalendarEvent = { member_id: string; title: string; start_utc: string; end_utc: string };
export type CalendarData = { members: MemberInfo[]; busy: BusyBlock[]; events: CalendarEvent[] };

export const getMembers = () => api<MemberInfo[]>(`${BASE}/members`);

export const getCalendar = (from: string, to: string) =>
  api<CalendarData>(`${BASE}/calendar?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`);

export type MemberConflict = {
  member: string;
  member_id: string;
  event_a: string;
  event_a_id: string;
  event_b: string;
  event_b_id: string;
};
export const getMemberConflicts = () => api<MemberConflict[]>(`${BASE}/member-conflicts`);

export const removeAttendees = (eventId: string, memberIds: string[]) =>
  api<{ removed: number }>(`${BASE}/events/${eventId}/remove-attendees`, {
    method: "POST",
    body: JSON.stringify({ member_ids: memberIds }),
  });

export const recommendMemberResolution = (event_a: string, event_b: string, members: string[]) =>
  api<{ recommendation: string }>(`${BASE}/member-conflicts/recommend`, {
    method: "POST",
    body: JSON.stringify({ event_a, event_b, members }),
  });

export const rescheduleEvent = (eventId: string) =>
  api<EventItem>(`${BASE}/events/${eventId}/reschedule`, { method: "POST" });

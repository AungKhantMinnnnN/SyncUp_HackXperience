// Thin fetch wrapper over the SyncUp REST API. One error shape everywhere:
// { detail, code }. Money arrives as strings ("287.50"); datetimes as ISO-8601 Z.
const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const KEY = import.meta.env.VITE_API_KEY ?? "";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", "X-API-Key": KEY, ...init?.headers },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText, code: "http_error" }));
    throw new Error(body.detail ?? "Request failed");
  }
  return res.json() as Promise<T>;
}

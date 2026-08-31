// Central backend client. The frontend never talks to external APIs or holds
// API keys (spec FR8); it only calls this backend base URL.

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface HealthResponse {
  status: string;
  service: string;
  env: string;
  database: string;
}

export async function getHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE_URL}/health`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Backend health check failed (HTTP ${res.status})`);
  }
  return res.json();
}

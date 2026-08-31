// Central backend client. The frontend never talks to external APIs or holds
// API keys (spec FR8); it only calls this backend base URL.

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type MediaType = "movie" | "series" | "book";
export type LibraryStatus = "want" | "in_progress" | "completed" | "dropped";
export type LengthBucket = "short" | "medium" | "long";

export const STATUS_LABELS: Record<LibraryStatus, string> = {
  want: "Want to watch/read",
  in_progress: "In progress",
  completed: "Completed",
  dropped: "Dropped",
};

export interface HealthResponse {
  status: string;
  service: string;
  env: string;
  database: string;
}

export interface NormalizedMedia {
  source: string;
  source_id: string;
  type: MediaType;
  title: string;
  description?: string | null;
  genres: string[];
  language?: string | null;
  year?: number | null;
  external_rating?: number | null;
  artwork_url?: string | null;
  runtime_minutes?: number | null;
  seasons?: number | null;
  episodes?: number | null;
  episode_runtime_minutes?: number | null;
  author?: string | null;
  page_count?: number | null;
  length_bucket?: LengthBucket | null;
  mood_tags: string[];
  raw_metadata?: Record<string, unknown>;
}

export interface MediaItemOut {
  id: string;
  source: string;
  source_id: string;
  type: MediaType;
  title: string;
  description?: string | null;
  genres: string[];
  language?: string | null;
  year?: number | null;
  external_rating?: number | null;
  artwork_url?: string | null;
  runtime_minutes?: number | null;
  seasons?: number | null;
  episodes?: number | null;
  episode_runtime_minutes?: number | null;
  author?: string | null;
  page_count?: number | null;
  mood_tags: string[];
  length_bucket?: LengthBucket | null;
}

export interface SeriesProgressOut {
  seasons_completed: number;
  current_season?: number | null;
  current_episode?: number | null;
  updated_at: string;
}

export interface LibraryEntryOut {
  id: string;
  status: LibraryStatus;
  favourite: boolean;
  rating?: number | null;
  review?: string | null;
  added_at: string;
  updated_at: string;
  media: MediaItemOut;
  progress?: SeriesProgressOut | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new Error("Could not reach the server.");
  }
  if (!res.ok) {
    let detail = `Request failed (HTTP ${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : detail;
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export function getHealth() {
  return request<HealthResponse>("/health");
}

export function searchMedia(query: string, type?: MediaType) {
  const params = new URLSearchParams({ q: query });
  if (type) params.set("type", type);
  return request<NormalizedMedia[]>(`/search?${params.toString()}`);
}

export function addToLibrary(item: NormalizedMedia, status: LibraryStatus = "want") {
  return request<LibraryEntryOut>("/library", {
    method: "POST",
    body: JSON.stringify({ item, status }),
  });
}

export function listLibrary(filters?: { status?: LibraryStatus; type?: MediaType }) {
  const params = new URLSearchParams();
  if (filters?.status) params.set("status", filters.status);
  if (filters?.type) params.set("type", filters.type);
  const qs = params.toString();
  return request<LibraryEntryOut[]>(`/library${qs ? `?${qs}` : ""}`);
}

export function getEntry(entryId: string) {
  return request<LibraryEntryOut>(`/library/${entryId}`);
}

export interface EntryPatch {
  status?: LibraryStatus;
  rating?: number | null;
  review?: string | null;
  favourite?: boolean;
}

export function updateEntry(entryId: string, patch: EntryPatch) {
  return request<LibraryEntryOut>(`/library/${entryId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export interface ProgressPatch {
  seasons_completed?: number;
  current_season?: number | null;
  current_episode?: number | null;
}

export function updateProgress(entryId: string, patch: ProgressPatch) {
  return request<LibraryEntryOut>(`/library/${entryId}/progress`, {
    method: "PUT",
    body: JSON.stringify(patch),
  });
}

// 백엔드 API 래퍼. 세션 쿠키는 자동(same-origin proxy 또는 동일 도메인 prod 배포).

export interface AuthStatus {
  authenticated: boolean;
  setup_required: boolean;
}

export interface PhotoSummary {
  id: number;
  sha256: string;
  taken_at: string | null;
  camera_make: string | null;
  camera_model: string | null;
  lens_model: string | null;
  iso: number | null;
  aperture: number | null;
  shutter: string | null;
  focal_mm: number | null;
  gps_lat: number | null;
  gps_lon: number | null;
  width: number | null;
  height: number | null;
  size_bytes: number;
  score: number | null;
  raw_score: number | null;
  eval_model_id: string | null;
  thumb_url: string;
}

export interface PhotoListResponse {
  items: PhotoSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface EvaluationDetail {
  id: number;
  model_id: string;
  model_version: string;
  ai_score: number | null;
  raw_score: number | null;
  confidence: number | null;
  caption: string | null;
  created_at: string;
}

export interface PhotoDetail extends PhotoSummary {
  phash: string | null;
  state: string;
  first_seen_at: string;
  last_seen_at: string;
  paths: { nas_id: string; path: string; last_seen_at: string }[];
  evaluations: EvaluationDetail[];
}

export interface QueueCounts {
  pending: number;
  in_progress: number;
  done: number;
  failed: number;
}

export interface ScanJob {
  id: number;
  state: string;
  started_at: string | null;
  finished_at: string | null;
  discovered: number;
  new_photos: number;
  changed: number;
  skipped: number;
  error: string | null;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = {
    method,
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  };
  const res = await fetch(path, init);
  if (!res.ok) {
    const detail = await res.text();
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(`API ${status}: ${detail}`);
  }
}

export const api = {
  auth: {
    status: () => request<AuthStatus>("GET", "/api/auth/status"),
    setup: (password: string) => request<void>("POST", "/api/auth/setup", { password }),
    login: (password: string) => request<{ ok: true }>("POST", "/api/auth/login", { password }),
    logout: () => request<{ ok: true }>("POST", "/api/auth/logout"),
  },
  photos: {
    list: (params: {
      limit?: number;
      offset?: number;
      min_score?: number | null;
      sort?: string;
      camera?: string;
    }) => {
      const q = new URLSearchParams();
      if (params.limit !== undefined) q.set("limit", String(params.limit));
      if (params.offset !== undefined) q.set("offset", String(params.offset));
      if (params.min_score !== undefined && params.min_score !== null)
        q.set("min_score", String(params.min_score));
      if (params.sort) q.set("sort", params.sort);
      if (params.camera) q.set("camera", params.camera);
      return request<PhotoListResponse>("GET", `/api/photos?${q.toString()}`);
    },
    detail: (id: number) => request<PhotoDetail>("GET", `/api/photos/${id}`),
  },
  scan: {
    local: (folder: string) =>
      request<{ folder: string; queued: boolean }>("POST", "/api/scan/local", { folder }),
    dsm: (folder: string) =>
      request<{ folder: string; queued: boolean; nas_id: string }>(
        "POST",
        "/api/scan/dsm",
        { folder },
      ),
    jobs: () => request<ScanJob[]>("GET", "/api/scan/jobs?limit=10"),
  },
  nas: {
    status: () =>
      request<{
        configured: boolean;
        base_url?: string;
        username?: string;
        use_otp?: boolean;
        password_in_keyring?: boolean;
      }>("GET", "/api/nas/status"),
    folders: (path: string = "") =>
      request<{
        path: string;
        items: { name: string; path: string; isdir: boolean; size?: number }[];
      }>("GET", `/api/nas/folders?path=${encodeURIComponent(path)}`),
  },
  eval: {
    queue: () => request<QueueCounts>("GET", "/api/eval/queue"),
    process: (max_jobs: number | null = null) =>
      request<{ queued: boolean }>("POST", "/api/eval/process", { max_jobs }),
  },
};

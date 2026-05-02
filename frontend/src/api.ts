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
  prompt_score: number | null;
  prompt_raw: number | null;
  user_score: number | null;
  final_score: number | null;
  thumb_url: string;
}

export interface AppSettings {
  eval_prompt: string;
  default_eval_prompt: string;
  library_min_score: number;
  default_library_min_score: number;
  scan_local_paths: string[];
  scan_dsm_paths: string[];
  eval_max_workers: number;
  default_eval_max_workers: number;
  max_allowed_workers: number;
  external_allow_send: boolean;
  external_strip_exif: boolean;
  external_default_model: string;
  default_external_model: string;
  default_advanced_prompt: string;
  configured_api_providers: string[];
}

export interface AdvancedReview {
  id: number;
  model_id: string;
  prompt: string;
  response: string;
  cost_usd: number | null;
  tokens_in: number | null;
  tokens_out: number | null;
  user_note: string | null;
  created_at: string;
}

export interface ExternalModel {
  id: string;
  input_price_per_million: number;
  output_price_per_million: number;
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

export interface PhotoPathEntry {
  id: number;
  nas_id: string;
  path: string;
  size_bytes: number;
  last_seen_at: string;
}

export interface PhotoDetail extends PhotoSummary {
  phash: string | null;
  state: string;
  first_seen_at: string;
  last_seen_at: string;
  paths: PhotoPathEntry[];
  evaluations: EvaluationDetail[];
  user_note: string | null;
}

export interface PortfolioSummary {
  id: number;
  name: string;
  description: string | null;
  count: number;
  preview_photo_id: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface PortfolioItem {
  photo_id: number;
  taken_at: string | null;
  camera_model: string | null;
  added_at: string | null;
  note: string | null;
  thumb_url: string;
}

export interface PortfolioDetail {
  id: number;
  name: string;
  description: string | null;
  created_at: string | null;
  updated_at: string | null;
  items: PortfolioItem[];
}

export interface BackupRecord {
  id: number;
  state: string;
  started_at: string | null;
  finished_at: string | null;
  nas_path: string | null;
  size_bytes: number | null;
  photo_count: number | null;
  error: string | null;
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
      q?: string;
    }) => {
      const qs = new URLSearchParams();
      if (params.limit !== undefined) qs.set("limit", String(params.limit));
      if (params.offset !== undefined) qs.set("offset", String(params.offset));
      if (params.min_score !== undefined && params.min_score !== null)
        qs.set("min_score", String(params.min_score));
      if (params.sort) qs.set("sort", params.sort);
      if (params.camera) qs.set("camera", params.camera);
      if (params.q) qs.set("q", params.q);
      return request<PhotoListResponse>("GET", `/api/photos?${qs.toString()}`);
    },
    detail: (id: number) => request<PhotoDetail>("GET", `/api/photos/${id}`),
    bulkDelete: (ids: number[], delete_local_files = false) =>
      request<{ deleted: number; files_deleted: number; files_failed: number }>(
        "DELETE",
        "/api/photos",
        { ids, delete_local_files },
      ),
    deletePaths: (photo_id: number, path_ids: number[], delete_local_files = false) =>
      request<{ deleted: number; files_deleted: number; remaining_paths: number }>(
        "DELETE",
        `/api/photos/${photo_id}/paths`,
        { path_ids, delete_local_files },
      ),
    setUserScore: (id: number, score: number, note?: string) =>
      request<void>("PUT", `/api/photos/${id}/score`, { score, note: note ?? null }),
    clearUserScore: (id: number) =>
      request<void>("DELETE", `/api/photos/${id}/score`),
    similar: (id: number, limit = 20) =>
      request<{
        items: { id: number; hamming: number; taken_at: string | null; camera_model: string | null; thumb_url: string }[];
        total: number;
      }>("GET", `/api/photos/${id}/similar?limit=${limit}`),
    search: (q: string, limit = 50) =>
      request<{
        items: {
          id: number;
          similarity: number;
          taken_at: string | null;
          camera_model: string | null;
          width: number | null;
          height: number | null;
          thumb_url: string;
        }[];
        total: number;
        query: string;
      }>(
        "GET",
        `/api/photos/search?q=${encodeURIComponent(q)}&limit=${limit}`,
      ),
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
    jobs: (params: { state?: string; limit?: number } = {}) => {
      const qs = new URLSearchParams();
      if (params.state) qs.set("state", params.state);
      qs.set("limit", String(params.limit ?? 30));
      return request<ScanJob[]>("GET", `/api/scan/jobs?${qs.toString()}`);
    },
    retryJob: (id: number) =>
      request<{ queued: boolean; started: number }>("POST", `/api/scan/jobs/${id}/retry`),
    deleteJob: (id: number) =>
      request<void>("DELETE", `/api/scan/jobs/${id}`),
    bulkDeleteJobs: (state?: string, ids?: number[]) =>
      request<{ deleted: number }>("DELETE", "/api/scan/jobs", {
        state: state ?? null,
        ids: ids ?? null,
      }),
    retryFailed: () =>
      request<{ queued: boolean; retried_jobs: number; started_scans: number }>(
        "POST",
        "/api/scan/retry-failed",
      ),
  },
  portfolios: {
    list: () => request<PortfolioSummary[]>("GET", "/api/portfolios"),
    create: (name: string, description?: string, photo_ids?: number[]) =>
      request<{ id: number }>("POST", "/api/portfolios", {
        name,
        description: description ?? null,
        photo_ids: photo_ids ?? [],
      }),
    detail: (id: number) =>
      request<PortfolioDetail>("GET", `/api/portfolios/${id}`),
    update: (id: number, patch: { name?: string; description?: string }) =>
      request<{ id: number }>("PUT", `/api/portfolios/${id}`, patch),
    remove: (id: number) =>
      request<void>("DELETE", `/api/portfolios/${id}`),
    addItems: (id: number, photo_ids: number[]) =>
      request<{ added: number }>("POST", `/api/portfolios/${id}/items`, { photo_ids }),
    removeItems: (id: number, photo_ids: number[]) =>
      request<{ removed: number }>("DELETE", `/api/portfolios/${id}/items`, { photo_ids }),
  },
  advanced: {
    review: (photo_id: number, prompt?: string, model?: string) =>
      request<AdvancedReview>(
        "POST",
        `/api/photos/${photo_id}/advanced-review`,
        {
          prompt: prompt ?? null,
          model: model ?? null,
        },
      ),
    listReviews: (photo_id: number) =>
      request<AdvancedReview[]>("GET", `/api/photos/${photo_id}/advanced-reviews`),
    deleteReview: (id: number) =>
      request<void>("DELETE", `/api/advanced-reviews/${id}`),
    costPreview: (photo_id: number, model?: string) => {
      const qs = new URLSearchParams();
      qs.set("photo_id", String(photo_id));
      if (model) qs.set("model", model);
      return request<{
        model: string;
        cost_usd_estimate: number;
        image_width: number;
        image_height: number;
      }>("GET", `/api/advanced/cost-preview?${qs.toString()}`);
    },
    models: () =>
      request<{ models: ExternalModel[] }>("GET", "/api/advanced/models"),
  },
  backup: {
    trigger: () =>
      request<{ queued: boolean; id: number }>("POST", "/api/backup"),
    list: () => request<BackupRecord[]>("GET", "/api/backup"),
  },
  settings: {
    get: () => request<AppSettings>("GET", "/api/settings"),
    put: (patch: Partial<{
      eval_prompt: string;
      library_min_score: number;
      scan_local_paths: string[];
      scan_dsm_paths: string[];
      eval_max_workers: number;
      external_allow_send: boolean;
      external_strip_exif: boolean;
      external_default_model: string;
    }>) =>
      request<{ ok: boolean; prompt_rescored: boolean }>(
        "PUT",
        "/api/settings",
        patch,
      ),
    putApiKey: (provider: string, api_key: string) =>
      request<void>("PUT", "/api/settings/api-keys", { provider, api_key }),
    deleteApiKey: (provider: string) =>
      request<void>("DELETE", `/api/settings/api-keys/${provider}`),
    scanSaved: () =>
      request<{ queued: boolean; started: { local: number; dsm: number } }>(
        "POST",
        "/api/settings/scan-saved",
      ),
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
    getPrompt: () =>
      request<{ prompt: string; default: string }>("GET", "/api/eval/prompt"),
    putPrompt: (prompt: string) =>
      request<{ prompt: string }>("PUT", "/api/eval/prompt", { prompt }),
    rescorePrompt: () =>
      request<{ queued: boolean }>("POST", "/api/eval/rescore-prompt"),
  },
};

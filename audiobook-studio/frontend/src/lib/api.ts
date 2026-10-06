import type {
  AppSettings,
  Book,
  ChapterDetail,
  Collection,
  EngineInfo,
  Facets,
  Job,
  JobDetail,
  KokoroModel,
  LexiconRule,
  Metadata,
  MetadataResult,
  PiperCatalogVoice,
  ProjectDetail,
  ProjectSummary,
  RenderSettings,
  Stats,
  SystemInfo,
  TemplateInfo,
  Voice,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler;
}

function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length) {
      return detail
        .map((d) => (typeof d === "object" && d && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)))
        .join("; ");
    }
  }
  return fallback;
}

async function request<T>(method: string, url: string, body?: unknown, raw = false): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin", headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  const response = await fetch(url, init);
  if (response.status === 401 && !url.startsWith("/api/auth/")) {
    onUnauthorized?.();
  }
  if (!response.ok) {
    let parsed: unknown = null;
    try {
      parsed = await response.json();
    } catch {
      /* not json */
    }
    throw new ApiError(response.status, errorMessage(parsed, `${response.status} ${response.statusText}`));
  }
  if (raw) return response as unknown as T;
  if (response.status === 204) return undefined as T;
  const type = response.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? response.json() : response.text()) as Promise<T>;
}

const get = <T>(url: string) => request<T>("GET", url);
const post = <T>(url: string, body?: unknown) => request<T>("POST", url, body ?? {});
const patch = <T>(url: string, body: unknown) => request<T>("PATCH", url, body);
const put = <T>(url: string, body: unknown) => request<T>("PUT", url, body);
const del = <T>(url: string) => request<T>("DELETE", url);

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

async function audioBlob(url: string, body: unknown): Promise<Blob> {
  const response = await request<Response>("POST", url, body, true);
  return response.blob();
}

export interface BookQuery {
  q?: string;
  author?: string;
  genre?: string;
  series?: string;
  narrator?: string;
  language?: string;
  year?: string;
  tag?: string;
  collection?: number;
  favorite?: boolean;
  status?: string;
  source?: string;
  sort?: string;
  order?: "asc" | "desc";
}

export const api = {
  // auth
  authStatus: () => get<{ enabled: boolean; authenticated: boolean; managed_by_env: boolean }>("/api/auth/status"),
  login: (password: string) => post<{ ok: boolean }>("/api/auth/login", { password }),
  logout: () => post<{ ok: boolean }>("/api/auth/logout"),

  // projects
  formats: () => get<{ extensions: string[]; labels: Record<string, string> }>("/api/projects/formats"),
  projects: () => get<ProjectSummary[]>("/api/projects"),
  project: (id: number) => get<ProjectDetail>(`/api/projects/${id}`),
  uploadProjects: (files: File[], options: { autoRender?: boolean; ocr?: string } = {}) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    form.append("auto_render", String(Boolean(options.autoRender)));
    form.append("ocr", options.ocr ?? "auto");
    return request<ProjectSummary[]>("POST", "/api/projects/upload", form);
  },
  createTextProject: (body: { title: string; author: string; text: string }) =>
    post<ProjectDetail>("/api/projects/text", body),
  updateProject: (id: number, body: Partial<Metadata> & { settings?: Partial<RenderSettings> }) =>
    patch<ProjectDetail>(`/api/projects/${id}`, body),
  deleteProject: (id: number, deleteBook = false) => del<{ ok: boolean }>(`/api/projects/${id}${qs({ delete_book: deleteBook })}`),
  renderProject: (id: number, chapterIds?: number[]) => post<Job>(`/api/projects/${id}/render`, { chapter_ids: chapterIds ?? null }),
  cancelProject: (id: number) => post<{ ok: boolean }>(`/api/projects/${id}/cancel`),
  reimportProject: (id: number, body: { ocr: string; language: string }) => post<Job>(`/api/projects/${id}/reimport`, body),
  cleanProject: (id: number) => post<{ removed: number }>(`/api/projects/${id}/clean`),
  uploadProjectCover: (id: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ProjectDetail>("POST", `/api/projects/${id}/cover`, form);
  },
  projectCoverFromUrl: (id: number, url: string) => post<ProjectDetail>(`/api/projects/${id}/cover/url`, { url }),
  removeProjectCover: (id: number) => del<ProjectDetail>(`/api/projects/${id}/cover`),
  previewProject: (id: number, text?: string) => audioBlob(`/api/projects/${id}/preview`, { text: text ?? null }),

  // chapters
  chapter: (projectId: number, chapterId: number) => get<ChapterDetail>(`/api/projects/${projectId}/chapters/${chapterId}`),
  updateChapter: (projectId: number, chapterId: number, body: { title?: string; text?: string; include?: boolean; voice?: string }) =>
    patch<ChapterDetail>(`/api/projects/${projectId}/chapters/${chapterId}`, body),
  addChapter: (projectId: number, body: { title: string; text: string }, position?: number) =>
    post<ProjectDetail>(`/api/projects/${projectId}/chapters${qs({ position })}`, body),
  deleteChapter: (projectId: number, chapterId: number) => del<ProjectDetail>(`/api/projects/${projectId}/chapters/${chapterId}`),
  bulkChapters: (projectId: number, body: { chapter_ids: number[]; include?: boolean; voice?: string }) =>
    post<ProjectDetail>(`/api/projects/${projectId}/chapters/bulk`, body),
  splitChapter: (projectId: number, chapterId: number, offset: number, title?: string) =>
    post<ProjectDetail>(`/api/projects/${projectId}/chapters/${chapterId}/split`, { offset, title }),
  mergeChapters: (projectId: number, chapterIds: number[]) =>
    post<ProjectDetail>(`/api/projects/${projectId}/chapters/merge`, { chapter_ids: chapterIds }),
  reorderChapters: (projectId: number, chapterIds: number[]) =>
    post<ProjectDetail>(`/api/projects/${projectId}/chapters/reorder`, { chapter_ids: chapterIds }),
  previewChapter: (projectId: number, chapterId: number, text?: string) =>
    audioBlob(`/api/projects/${projectId}/chapters/${chapterId}/preview`, { text: text ?? null }),

  // library
  books: (query: BookQuery = {}) => get<Book[]>(`/api/books${qs(query as Record<string, string>)}`),
  book: (id: number) => get<Book>(`/api/books/${id}`),
  facets: () => get<Facets>("/api/books/facets"),
  updateBook: (id: number, body: Partial<Metadata> & { rating?: number; favorite?: boolean; finished?: boolean; collection_ids?: number[] }) =>
    patch<Book>(`/api/books/${id}`, body),
  bulkBooks: (body: { book_ids: number[]; changes?: Record<string, unknown>; add_collection_id?: number; remove_collection_id?: number }) =>
    post<{ updated: number }>("/api/books/bulk", body),
  deleteBook: (id: number, deleteFiles: boolean) => del<{ ok: boolean }>(`/api/books/${id}${qs({ delete_files: deleteFiles })}`),
  saveProgress: (id: number, position: number, finished?: boolean) =>
    put<Book>(`/api/books/${id}/progress`, { position, finished: finished ?? null }),
  uploadBookCover: (id: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Book>("POST", `/api/books/${id}/cover`, form);
  },
  bookCoverFromUrl: (id: number, url: string) => post<Book>(`/api/books/${id}/cover/url`, { url }),
  retagBook: (id: number) => post<Job>(`/api/books/${id}/retag`),
  templates: () => get<TemplateInfo>("/api/library/templates"),
  templatePreview: (template: string) => post<{ template: string; examples: string[] }>("/api/library/template-preview", { template }),
  organizePreview: (template?: string) =>
    post<{ template: string; moves: { book_id: number; title: string; from: string; to: string }[] }>(
      "/api/library/organize/preview",
      { template: template ?? null },
    ),
  organize: (template?: string) => post<Job>("/api/library/organize", { template: template ?? null }),
  scanLibrary: (path?: string) => post<Job>("/api/library/scan", { path: path || null }),

  // collections
  collections: () => get<Collection[]>("/api/collections"),
  createCollection: (body: { name: string; description?: string; color?: string }) => post<Collection>("/api/collections", body),
  updateCollection: (id: number, body: { name: string; description?: string; color?: string }) =>
    patch<Collection>(`/api/collections/${id}`, body),
  deleteCollection: (id: number) => del<{ ok: boolean }>(`/api/collections/${id}`),
  addToCollection: (id: number, bookIds: number[]) => post<Collection>(`/api/collections/${id}/books`, { book_ids: bookIds }),
  removeFromCollection: (id: number, bookId: number) => del<Collection>(`/api/collections/${id}/books/${bookId}`),

  // jobs
  jobs: (status?: string) => get<Job[]>(`/api/jobs${qs({ status })}`),
  job: (id: number) => get<JobDetail>(`/api/jobs/${id}`),
  cancelJob: (id: number) => post<{ ok: boolean }>(`/api/jobs/${id}/cancel`),
  retryJob: (id: number) => post<Job>(`/api/jobs/${id}/retry`),
  deleteJob: (id: number) => del<{ ok: boolean }>(`/api/jobs/${id}`),
  clearJobs: () => post<{ removed: number }>("/api/jobs/clear"),

  // voices
  engines: () => get<EngineInfo[]>("/api/tts/engines"),
  voices: (engine?: string, includeUnavailable = false) =>
    get<Voice[]>(`/api/tts/voices${qs({ engine, include_unavailable: includeUnavailable || undefined })}`),
  previewVoice: (body: { engine: string; voice: string; text: string; speed?: number; language?: string | null }) =>
    audioBlob("/api/tts/preview", body),
  models: () => get<{ kokoro: KokoroModel[]; piper_installed: string[] }>("/api/tts/models"),
  piperCatalog: (refresh = false) => get<PiperCatalogVoice[]>(`/api/tts/models/piper${qs({ refresh: refresh || undefined })}`),
  downloadModel: (engine: string, model: string) => post<Job>("/api/tts/models/download", { engine, model }),
  deleteModel: (engine: string, model: string) => del<{ ok: boolean }>(`/api/tts/models/${engine}/${encodeURIComponent(model)}`),

  // lexicon
  lexicon: (projectId?: number) => get<LexiconRule[]>(`/api/lexicon${qs({ project_id: projectId })}`),
  createRule: (body: Partial<LexiconRule> & { pattern: string }) => post<LexiconRule>("/api/lexicon", body),
  updateRule: (id: number, body: Partial<LexiconRule>) => patch<LexiconRule>(`/api/lexicon/${id}`, body),
  deleteRule: (id: number) => del<{ ok: boolean }>(`/api/lexicon/${id}`),
  testLexicon: (text: string, projectId?: number) =>
    post<{ cleaned: string; result: string; chunks: string[] }>("/api/lexicon/test", { text, project_id: projectId ?? null }),
  exportLexicon: (projectId?: number) => get<{ rules: Partial<LexiconRule>[] }>(`/api/lexicon/export${qs({ project_id: projectId })}`),
  importLexicon: (rules: Partial<LexiconRule>[], replace: boolean, projectId?: number) =>
    post<{ added: number }>(`/api/lexicon/import${qs({ project_id: projectId })}`, { rules, replace }),

  // settings & system
  settings: () => get<AppSettings>("/api/settings"),
  updateSettings: (body: Record<string, unknown>) => patch<AppSettings>("/api/settings", body),
  changePassword: (current: string, next: string) =>
    post<{ ok: boolean; enabled: boolean }>("/api/settings/password", { current_password: current, new_password: next }),
  regenerateFeedToken: () => post<{ feed_token: string }>("/api/settings/feed-token"),
  feeds: () => get<{ library: string; book_template: string; token_required: boolean }>("/api/feeds"),
  system: () => get<SystemInfo>("/api/system"),
  stats: () => get<Stats>("/api/stats"),
  metadataSearch: (params: { title?: string; author?: string; isbn?: string }) =>
    get<{ results: MetadataResult[]; errors: string[] }>(`/api/metadata/search${qs(params)}`),
  metadataDescription: (source: string, sourceId: string) =>
    get<{ description: string }>(`/api/metadata/description${qs({ source, source_id: sourceId })}`),
};

export function fileUrl(bookId: number, index: number) {
  return `/api/books/${bookId}/files/${index}`;
}

export type ProjectStatus = "importing" | "ready" | "queued" | "rendering" | "done" | "error";
export type OutputFormat = "m4b" | "mp3" | "mp3_single" | "opus";

export interface CleanupOptions {
  remove_footnote_markers: boolean;
  remove_urls: boolean;
  expand_abbreviations: boolean;
  normalize_punctuation: boolean;
  remove_bracketed_text: boolean;
  skip_all_caps_headers: boolean;
}

export interface RenderSettings {
  engine: string;
  voice: string;
  speed: number;
  language: string | null;
  dialogue_enabled: boolean;
  dialogue_engine: string | null;
  dialogue_voice: string | null;
  announce_chapters: boolean;
  sentence_pause: number;
  paragraph_pause: number;
  section_pause: number;
  chapter_pause: number;
  output_format: OutputFormat;
  bitrate: string;
  normalize: boolean;
  cleanup: CleanupOptions;
}

export interface Metadata {
  title: string;
  subtitle: string;
  author: string;
  narrator: string;
  series: string;
  series_index: string;
  genre: string;
  tags: string[];
  language: string;
  publisher: string;
  year: string;
  description: string;
  isbn: string;
}

export interface Chapter {
  id: number;
  position: number;
  title: string;
  include: boolean;
  kind: "front" | "chapter" | "back";
  word_count: number;
  voice: string | null;
  status: "pending" | "rendering" | "done" | "error";
  error: string;
  duration: number;
  audio_state: "none" | "ready" | "stale";
  preview: string;
  estimated_seconds: number;
}

export interface ChapterDetail extends Chapter {
  text: string;
}

export interface ProjectSummary {
  id: number;
  title: string;
  author: string;
  status: ProjectStatus;
  error: string;
  source_format: string;
  source_filename: string;
  cover_url: string | null;
  chapter_count: number;
  included_chapters: number;
  word_count: number;
  estimated_seconds: number;
  rendered_seconds: number;
  book_id: number | null;
  job_id: number | null;
  job_progress: number | null;
  job_message: string | null;
  engine: string;
  voice: string;
  created_at: string;
  updated_at: string;
  rendered_at: string | null;
}

export interface ProjectDetail extends ProjectSummary, Omit<Metadata, "title" | "author"> {
  settings: RenderSettings;
  warnings: string[];
  import_options: Record<string, unknown>;
  chapters: Chapter[];
  workspace_bytes: number;
  stale_chapters: number;
}

export interface BookFile {
  path: string;
  duration: number;
  size: number;
  title: string;
}

export interface BookChapter {
  title: string;
  start: number;
  end: number;
}

export interface Book extends Metadata {
  id: number;
  path: string;
  files: BookFile[];
  chapters: BookChapter[];
  duration: number;
  size: number;
  format: string;
  source: "studio" | "import";
  project_id: number | null;
  rating: number;
  favorite: boolean;
  progress: number;
  finished: boolean;
  missing: boolean;
  last_played_at: string | null;
  added_at: string;
  updated_at: string;
  cover_url: string | null;
  thumb_url: string | null;
  collection_ids: number[];
}

export interface FacetValue {
  value: string;
  count: number;
}

export interface Facets {
  author: FacetValue[];
  genre: FacetValue[];
  series: FacetValue[];
  narrator: FacetValue[];
  language: FacetValue[];
  year: FacetValue[];
  tags: FacetValue[];
  format: FacetValue[];
  total: number;
}

export interface Collection {
  id: number;
  name: string;
  description: string;
  color: string;
  created_at: string;
  book_count: number;
  cover_book_ids: number[];
}

export type JobStatus = "queued" | "running" | "done" | "error" | "cancelled";

export interface Job {
  id: number;
  kind: "render" | "ingest" | "download_model" | "organize" | "scan" | "retag";
  status: JobStatus;
  title: string;
  project_id: number | null;
  book_id: number | null;
  progress: number;
  message: string;
  error: string;
  result: Record<string, unknown>;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  eta_seconds: number | null;
  elapsed_seconds: number | null;
}

export interface JobDetail extends Job {
  log: string;
  payload: Record<string, unknown>;
}

export interface EngineInfo {
  id: string;
  name: string;
  description: string;
  online: boolean;
  needs_download: boolean;
  available: boolean;
  ready: boolean;
  enabled: boolean;
  message: string;
  supports_blending: boolean;
}

export interface Voice {
  id: string;
  name: string;
  engine: string;
  language: string;
  language_name: string;
  gender: string;
  quality: string;
  description: string;
  installed: boolean;
  recommended: boolean;
  speakers: string[];
}

export interface KokoroModel {
  engine: "kokoro";
  id: string;
  label: string;
  size_mb: number;
  installed: boolean;
  job_id: number | null;
}

export interface PiperCatalogVoice {
  id: string;
  name: string;
  language: string;
  language_name: string;
  quality: string;
  speakers: number;
  size_mb: number;
  installed: boolean;
  recommended: boolean;
  job_id: number | null;
}

export interface LexiconRule {
  id: number;
  project_id: number | null;
  pattern: string;
  replacement: string;
  is_regex: boolean;
  case_sensitive: boolean;
  whole_word: boolean;
  enabled: boolean;
  note: string;
  created_at: string;
}

export interface AppSettings {
  render_defaults: RenderSettings;
  library_template: string;
  auto_organize: boolean;
  write_sidecars: boolean;
  keep_workspace_audio: boolean;
  inbox_enabled: boolean;
  inbox_auto_render: boolean;
  inbox_interval: number;
  online_metadata: boolean;
  kokoro_variant: string;
  openai_base_url: string;
  openai_model: string;
  openai_voices: string;
  edge_enabled: boolean;
  feed_token: string;
  first_run_done: boolean;
  password_set: boolean;
  password_managed_by_env: boolean;
  openai_api_key_set: boolean;
}

export interface SystemInfo {
  version: string;
  python: string;
  platform: string;
  cpu_count: number;
  ffmpeg: string;
  ocr_available: boolean;
  paths: { data: string; library: string; inbox: string; models: string };
  disk: Record<string, { path: string; total: number; free: number; used: number }>;
  inbox_last_scan: number | null;
  render_workers: number;
}

export interface Stats {
  books: number;
  total_duration: number;
  total_size: number;
  authors: number;
  series: number;
  finished: number;
  listened_seconds: number;
  added_this_week: number;
  projects: number;
  projects_by_status: Record<string, number>;
  rendered_words: number;
  jobs: Record<string, number>;
  top_genres: { name: string; count: number }[];
  top_authors: { name: string; count: number }[];
  languages: { name: string; count: number }[];
  continue_listening: Book[];
  recently_added: Book[];
  recent_projects: ProjectSummary[];
}

export interface MetadataResult {
  source: "openlibrary" | "google";
  source_id: string;
  title: string;
  subtitle: string;
  author: string;
  year: string;
  publisher: string;
  genre: string;
  tags: string[];
  isbn: string;
  language: string;
  description: string;
  cover_url: string;
}

export interface TemplateInfo {
  presets: { id: string; label: string; template: string }[];
  fields: string[];
  current: string;
  library_path: string;
}

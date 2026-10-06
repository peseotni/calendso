import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  BookOpen,
  ChevronDown,
  Download,
  FileText,
  Globe,
  Headphones,
  Info,
  ListOrdered,
  Loader2,
  Mic2,
  Play,
  RefreshCw,
  SpellCheck,
  Square,
  Trash2,
  Wrench,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Cover } from "../components/Cover";
import { CoverEditor } from "../components/CoverEditor";
import { useFeedback } from "../components/feedback";
import { MetadataForm, type MetadataValue } from "../components/MetadataForm";
import { MetadataLookup } from "../components/MetadataLookup";
import { RenderSettingsForm } from "../components/RenderSettingsForm";
import { RuleTester, RulesTable } from "../components/RulesTable";
import { SaveBar } from "../components/SaveBar";
import { ProjectStatusBadge } from "../components/StatusBadge";
import { Badge, Button, Card, Field, LoadingBlock, ProgressBar, Section, Select, Tabs } from "../components/ui";
import { api } from "../lib/api";
import { formatBytes, formatDate, formatDuration, formatNumber } from "../lib/format";
import { usePreviewPlayer } from "../lib/hooks";
import type { Metadata, ProjectDetail, RenderSettings } from "../lib/types";
import { ChaptersTab } from "./project/ChaptersTab";

type Tab = "chapters" | "voice" | "details" | "pronunciation" | "source";
const ACTIVE = new Set(["importing", "queued", "rendering"]);
const META_KEYS: (keyof Metadata)[] = [
  "title", "subtitle", "author", "narrator", "series", "series_index", "genre", "tags", "language", "publisher", "year", "description", "isbn",
];

function JobPanel({ project }: { project: ProjectDetail }) {
  const [showLog, setShowLog] = useState(false);
  const job = useQuery({
    queryKey: ["job", project.job_id],
    queryFn: () => api.job(project.job_id!),
    enabled: project.job_id !== null,
    refetchInterval: 1500,
  });
  if (!ACTIVE.has(project.status)) return null;
  const data = job.data;
  const progress = data?.progress ?? project.job_progress ?? 0;
  return (
    <Card className="mb-6 overflow-hidden border-brand-200 dark:border-brand-500/30">
      <div className="p-5">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 font-medium">
            <Loader2 className="size-4 animate-spin text-brand-600" />
            {project.status === "importing" ? "Importing document" : project.status === "queued" ? "Waiting in the queue" : "Narrating"}
          </div>
          <div className="text-sm text-zinc-500 tabular-nums">
            {Math.round(progress * 100)}%
            {data?.eta_seconds ? ` · about ${formatDuration(data.eta_seconds)} left` : ""}
            {data?.elapsed_seconds ? ` · ${formatDuration(data.elapsed_seconds)} elapsed` : ""}
          </div>
        </div>
        <ProgressBar value={progress} indeterminate={project.status === "queued"} />
        <div className="mt-2 flex items-center justify-between gap-3">
          <span className="truncate text-sm text-zinc-500">{data?.message || project.job_message || "Starting…"}</span>
          {data?.log && (
            <button onClick={() => setShowLog(!showLog)} className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-brand-600 dark:text-brand-400">
              Log <ChevronDown className={showLog ? "size-3.5 rotate-180" : "size-3.5"} />
            </button>
          )}
        </div>
      </div>
      {showLog && data?.log && (
        <pre className="scrollbar-thin max-h-60 overflow-auto border-t border-zinc-200 bg-zinc-50 p-4 font-mono text-xs whitespace-pre-wrap dark:border-zinc-800 dark:bg-zinc-950">
          {data.log}
        </pre>
      )}
    </Card>
  );
}

function VoiceTab({ project, onSaved }: { project: ProjectDetail; onSaved: (p: ProjectDetail) => void }) {
  const feedback = useFeedback();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<RenderSettings>(project.settings);
  const savedSettings = JSON.stringify(project.settings);
  // Re-sync only when the saved settings really changed (not on every refetch).
  useEffect(() => setDraft(JSON.parse(savedSettings) as RenderSettings), [savedSettings]);
  const dirty = JSON.stringify(draft) !== JSON.stringify(project.settings);
  const save = useMutation({
    mutationFn: () => api.updateProject(project.id, { settings: draft }),
    onSuccess: (updated) => {
      onSaved(updated);
      feedback.success("Voice settings saved");
    },
    onError: feedback.error,
  });
  const makeDefault = useMutation({
    mutationFn: () => api.updateSettings({ render_defaults: draft }),
    onSuccess: () => {
      feedback.success("Saved as default for new projects");
      void queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: feedback.error,
  });
  return (
    <div>
      {project.status === "rendering" && (
        <div className="mb-4 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:bg-amber-500/10 dark:text-amber-300">
          Settings cannot be changed while narrating. Cancel the render first.
        </div>
      )}
      <RenderSettingsForm value={draft} language={project.language} onChange={(patch) => setDraft({ ...draft, ...patch })} />
      <div className="mt-6 flex justify-end">
        <Button variant="ghost" onClick={() => makeDefault.mutate()} loading={makeDefault.isPending}>
          Use these settings for new projects
        </Button>
      </div>
      <SaveBar visible={dirty} saving={save.isPending} onSave={() => save.mutate()} onDiscard={() => setDraft(project.settings)} />
    </div>
  );
}

function DetailsTab({ project, onSaved }: { project: ProjectDetail; onSaved: (p?: ProjectDetail) => void }) {
  const feedback = useFeedback();
  const initial = Object.fromEntries(META_KEYS.map((k) => [k, (project as unknown as Metadata)[k]])) as MetadataValue;
  const [draft, setDraft] = useState<MetadataValue>(initial);
  const [lookup, setLookup] = useState(false);
  const savedMetadata = JSON.stringify(initial);
  useEffect(() => setDraft(JSON.parse(savedMetadata) as MetadataValue), [savedMetadata]);
  const dirty = JSON.stringify(draft) !== JSON.stringify(initial);
  const save = useMutation({
    mutationFn: () => api.updateProject(project.id, draft),
    onSuccess: (updated) => {
      onSaved(updated);
      feedback.success("Details saved");
    },
    onError: feedback.error,
  });
  return (
    <div className="grid gap-8 lg:grid-cols-[16rem_minmax(0,1fr)]">
      <div className="mx-auto w-full max-w-64">
        <CoverEditor
          src={project.cover_url}
          title={draft.title ?? project.title}
          author={draft.author ?? project.author}
          onUpload={async (file) => onSaved(await api.uploadProjectCover(project.id, file))}
          onUrl={async (url) => onSaved(await api.projectCoverFromUrl(project.id, url))}
          onRemove={async () => onSaved(await api.removeProjectCover(project.id))}
        />
        <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-400">The cover is embedded in the audio files and shown in your library.</p>
      </div>
      <div>
        <div className="mb-4 flex justify-end">
          <Button icon={<Globe className="size-4" />} onClick={() => setLookup(true)}>
            Find metadata online
          </Button>
        </div>
        <MetadataForm value={draft} onChange={(patch) => setDraft({ ...draft, ...patch })} />
        <SaveBar visible={dirty} saving={save.isPending} onSave={() => save.mutate()} onDiscard={() => setDraft(initial)} />
      </div>
      <MetadataLookup
        open={lookup}
        onClose={() => setLookup(false)}
        initial={{ title: project.title, author: project.author, isbn: project.isbn }}
        onApply={async (patch, coverUrl) => {
          setDraft({ ...draft, ...patch });
          if (coverUrl) onSaved(await api.projectCoverFromUrl(project.id, coverUrl));
          feedback.success("Applied – review and save the details.");
        }}
      />
    </div>
  );
}

function SourceTab({ project, onChanged }: { project: ProjectDetail; onChanged: () => void }) {
  const feedback = useFeedback();
  const [ocr, setOcr] = useState(String(project.import_options.ocr ?? "auto"));
  const reimport = async () => {
    const { confirmed } = await feedback.confirm({
      title: "Re-import the document?",
      message: "Chapters are detected again from the source file. Your chapter edits in this project are lost.",
      confirmLabel: "Re-import",
      danger: true,
    });
    if (!confirmed) return;
    try {
      await api.reimportProject(project.id, { ocr, language: project.language });
      onChanged();
    } catch (error) {
      feedback.error(error);
    }
  };
  const clean = async () => {
    try {
      const result = await api.cleanProject(project.id);
      feedback.success(`Removed ${result.removed} rendered chapter files`);
      onChanged();
    } catch (error) {
      feedback.error(error);
    }
  };
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Section title="Source document" description={project.source_filename || "Created from pasted text"}>
        <dl className="mb-4 grid grid-cols-2 gap-y-2 text-sm">
          <dt className="text-zinc-500">Format</dt>
          <dd>{project.source_format.toUpperCase()}</dd>
          <dt className="text-zinc-500">Imported</dt>
          <dd>{formatDate(project.created_at)}</dd>
          <dt className="text-zinc-500">Last rendered</dt>
          <dd>{project.rendered_at ? formatDate(project.rendered_at) : "never"}</dd>
        </dl>
        <div className="flex flex-wrap gap-2">
          {project.source_filename && (
            <a href={`/api/projects/${project.id}/source`}>
              <Button size="sm" icon={<Download className="size-4" />}>
                Download original
              </Button>
            </a>
          )}
          <a href={`/api/projects/${project.id}/export.txt`}>
            <Button size="sm" icon={<FileText className="size-4" />}>
              Export text
            </Button>
          </a>
          <a href={`/api/projects/${project.id}/export.txt?cleaned=true`}>
            <Button size="sm" icon={<FileText className="size-4" />}>
              Export spoken text
            </Button>
          </a>
        </div>
      </Section>
      {project.source_filename && (
        <Section title="Re-import" description="Run chapter detection again, e.g. with OCR for scanned PDFs.">
          <Field label="OCR for scanned pages">
            <Select
              value={ocr}
              onChange={setOcr}
              options={[
                { value: "auto", label: "Automatic" },
                { value: "force", label: "Force OCR on every page" },
                { value: "off", label: "Off" },
              ]}
            />
          </Field>
          <Button className="mt-4" icon={<RefreshCw className="size-4" />} onClick={() => void reimport()} disabled={ACTIVE.has(project.status)}>
            Re-import document
          </Button>
        </Section>
      )}
      <Section title="Workspace" description="Rendered chapters are kept so that only changed chapters are narrated again.">
        <div className="mb-4 text-sm">
          <span className="font-semibold">{formatBytes(project.workspace_bytes)}</span>{" "}
          <span className="text-zinc-500">used by this project (source, cover and chapter audio)</span>
        </div>
        <Button size="sm" variant="ghost" icon={<Trash2 className="size-4" />} onClick={() => void clean()} disabled={ACTIVE.has(project.status)}>
          Delete rendered chapter audio
        </Button>
      </Section>
      {project.warnings.length > 0 && (
        <Section title="Import notes">
          <ul className="list-inside list-disc space-y-1 text-sm text-zinc-600 dark:text-zinc-300">
            {project.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

export default function ProjectEditor() {
  const { id } = useParams();
  const projectId = Number(id);
  const navigate = useNavigate();
  const feedback = useFeedback();
  const queryClient = useQueryClient();
  const preview = usePreviewPlayer();
  const [tab, setTab] = useState<Tab>("chapters");

  const query = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.project(projectId),
    refetchInterval: (q) => (q.state.data && ACTIVE.has(q.state.data.status) ? 1500 : false),
  });
  const project = query.data;

  const setProject = (updated?: ProjectDetail) => {
    if (updated) queryClient.setQueryData(["project", projectId], updated);
    else void queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    void queryClient.invalidateQueries({ queryKey: ["projects"] });
  };

  const render = useMutation({
    mutationFn: () => api.renderProject(projectId),
    onSuccess: () => {
      setProject();
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      feedback.success("Narration started – you can keep editing other projects meanwhile.");
    },
    onError: feedback.error,
  });
  const cancel = useMutation({
    mutationFn: () => api.cancelProject(projectId),
    onSuccess: () => setProject(),
    onError: feedback.error,
  });

  if (query.isLoading) return <LoadingBlock />;
  if (!project) return <div className="py-20 text-center text-zinc-500">Project not found.</div>;

  const included = project.chapters.filter((c) => c.include);
  const words = included.reduce((s, c) => s + c.word_count, 0);
  const busy = ACTIVE.has(project.status);

  const remove = async () => {
    const { confirmed, checked } = await feedback.confirm({
      title: `Delete project “${project.title}”?`,
      message: "The source document, chapter edits and workspace audio are deleted.",
      checkbox: project.book_id ? "Also remove the finished audiobook from the library (and disk)" : undefined,
      confirmLabel: "Delete",
      danger: true,
    });
    if (!confirmed) return;
    try {
      await api.deleteProject(project.id, checked);
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      navigate("/studio");
    } catch (error) {
      feedback.error(error);
    }
  };

  return (
    <div className="animate-fade-in">
      <Link to="/studio" className="mb-5 inline-flex items-center gap-1.5 text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-white">
        <ArrowLeft className="size-4" /> Studio
      </Link>

      <div className="mb-6 flex flex-col gap-5 sm:flex-row sm:items-start">
        <Cover src={project.cover_url} title={project.title} author={project.author} className="w-28 shrink-0 shadow-md sm:w-32" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <ProjectStatusBadge status={project.status} />
            <Badge>{project.source_format.toUpperCase()}</Badge>
            {project.stale_chapters > 0 && project.status !== "rendering" && (
              <Badge color="amber">{project.stale_chapters} chapters changed since last render</Badge>
            )}
          </div>
          <h1 className="mt-2 truncate text-2xl font-semibold tracking-tight sm:text-3xl">{project.title}</h1>
          <p className="text-zinc-500 dark:text-zinc-400">{project.author || "Unknown author"}</p>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-zinc-600 dark:text-zinc-300">
            <span>
              {included.length}/{project.chapter_count} chapters
            </span>
            <span>{formatNumber(words)} words</span>
            <span>≈ {formatDuration(project.estimated_seconds)} of audio</span>
            <span className="inline-flex items-center gap-1">
              <Mic2 className="size-3.5" /> {project.narrator || project.settings.voice}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2 sm:justify-end">
          <Button
            icon={preview.loading ? <Loader2 className="size-4 animate-spin" /> : preview.playing ? <Square className="size-3.5" fill="currentColor" /> : <Play className="size-4" />}
            onClick={() => preview.play("project", () => api.previewProject(project.id)).catch(feedback.error)}
            disabled={project.status === "importing"}
          >
            {preview.playing ? "Stop" : "Sample"}
          </Button>
          {busy && project.status !== "importing" ? (
            <Button variant="danger" icon={<X className="size-4" />} onClick={() => cancel.mutate()} loading={cancel.isPending}>
              Cancel
            </Button>
          ) : (
            <Button
              variant="primary"
              icon={<Headphones className="size-4" />}
              onClick={() => render.mutate()}
              loading={render.isPending}
              disabled={busy || !included.length}
            >
              {project.status === "done" ? (project.stale_chapters ? "Update audiobook" : "Render again") : "Create audiobook"}
            </Button>
          )}
          {project.book_id && (
            <Link to={`/library/${project.book_id}`}>
              <Button icon={<BookOpen className="size-4" />}>Open in library</Button>
            </Link>
          )}
          <Button variant="ghost" icon={<Trash2 className="size-4" />} onClick={() => void remove()} aria-label="Delete project" />
        </div>
      </div>

      {project.status === "error" && (
        <div className="mb-6 flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
          <AlertTriangle className="mt-0.5 size-5 shrink-0" />
          <div>
            <div className="font-semibold">Something went wrong</div>
            <div className="mt-0.5 break-words">{project.error}</div>
          </div>
        </div>
      )}
      {project.status === "done" && project.book_id && !project.stale_chapters && (
        <div className="mb-6 flex items-start gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300">
          <Info className="mt-0.5 size-5 shrink-0" />
          <div>
            Your audiobook is ready in the <Link to={`/library/${project.book_id}`} className="font-semibold underline">library</Link>. Edit
            chapters or voice settings and click “Update audiobook” – only changed chapters are narrated again.
          </div>
        </div>
      )}

      <JobPanel project={project} />

      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { value: "chapters", label: "Chapters", icon: <ListOrdered className="size-4" />, badge: <Badge>{project.chapter_count}</Badge> },
          { value: "voice", label: "Voice & audio", icon: <Mic2 className="size-4" /> },
          { value: "details", label: "Details & cover", icon: <BookOpen className="size-4" /> },
          { value: "pronunciation", label: "Pronunciation", icon: <SpellCheck className="size-4" /> },
          { value: "source", label: "Source & tools", icon: <Wrench className="size-4" /> },
        ]}
      />

      {project.status === "importing" ? (
        <LoadingBlock label="Reading the document and detecting chapters…" />
      ) : (
        <>
          {tab === "chapters" && <ChaptersTab project={project} onChange={setProject} />}
          {tab === "voice" && <VoiceTab project={project} onSaved={setProject} />}
          {tab === "details" && <DetailsTab project={project} onSaved={setProject} />}
          {tab === "pronunciation" && (
            <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
              <div>
                <p className="mb-4 text-sm text-zinc-500 dark:text-zinc-400">
                  Rules for this book only (for example character names). They take priority over your{" "}
                  <Link to="/pronunciation" className="font-medium text-brand-600 hover:underline dark:text-brand-400">
                    global pronunciation rules
                  </Link>
                  . Changing rules marks affected chapters for re-narration.
                </p>
                <RulesTable projectId={project.id} />
              </div>
              <RuleTester projectId={project.id} onPreview={(text) => api.previewProject(project.id, text)} />
            </div>
          )}
          {tab === "source" && <SourceTab project={project} onChanged={() => setProject()} />}
        </>
      )}
    </div>
  );
}

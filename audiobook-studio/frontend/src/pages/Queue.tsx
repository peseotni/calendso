import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  CloudDownload,
  FileInput,
  FolderSync,
  Headphones,
  ListTodo,
  RefreshCw,
  RotateCcw,
  ScanSearch,
  Tags,
  Trash2,
  X,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useFeedback } from "../components/feedback";
import { JobStatusBadge } from "../components/StatusBadge";
import { Button, Card, EmptyState, IconButton, LoadingBlock, PageHeader, ProgressBar, Segmented } from "../components/ui";
import { api } from "../lib/api";
import { formatDuration, timeAgo } from "../lib/format";
import type { Job } from "../lib/types";

const KIND_ICONS: Record<Job["kind"], React.ReactNode> = {
  render: <Headphones className="size-4" />,
  ingest: <FileInput className="size-4" />,
  download_model: <CloudDownload className="size-4" />,
  organize: <FolderSync className="size-4" />,
  scan: <ScanSearch className="size-4" />,
  retag: <Tags className="size-4" />,
};

function JobLog({ id }: { id: number }) {
  const job = useQuery({ queryKey: ["job", id], queryFn: () => api.job(id), refetchInterval: 2000 });
  if (!job.data) return null;
  return (
    <pre className="scrollbar-thin mt-3 max-h-72 overflow-auto rounded-lg bg-zinc-950 p-3 font-mono text-xs whitespace-pre-wrap text-zinc-200">
      {job.data.log || "No log output yet."}
    </pre>
  );
}

function JobCard({ job }: { job: Job }) {
  const feedback = useFeedback();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    void queryClient.invalidateQueries({ queryKey: ["projects"] });
  };
  const action = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: invalidate,
    onError: feedback.error,
  });
  const active = job.status === "running" || job.status === "queued";
  const link = job.project_id ? `/studio/${job.project_id}` : job.book_id ? `/library/${job.book_id}` : job.kind === "download_model" ? "/voices" : null;
  const result = job.result as { book_id?: number; message?: string };

  return (
    <Card className="p-4">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
          {KIND_ICONS[job.kind] ?? <ListTodo className="size-4" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {link ? (
              <Link to={link} className="truncate font-medium hover:underline">
                {job.title}
              </Link>
            ) : (
              <span className="truncate font-medium">{job.title}</span>
            )}
            <JobStatusBadge status={job.status} />
          </div>
          <div className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
            {job.status === "queued" && `Queued ${timeAgo(job.created_at)}`}
            {job.status === "running" && `Started ${timeAgo(job.started_at)}`}
            {!active && job.finished_at && `Finished ${timeAgo(job.finished_at)}`}
            {job.elapsed_seconds ? ` · ${formatDuration(job.elapsed_seconds)}` : ""}
            {job.status === "running" && job.eta_seconds ? ` · ~${formatDuration(job.eta_seconds)} left` : ""}
          </div>
          {active && (
            <div className="mt-3">
              <ProgressBar value={job.progress} indeterminate={job.status === "queued"} />
              <div className="mt-1.5 flex justify-between gap-3 text-xs text-zinc-500">
                <span className="truncate">{job.message}</span>
                <span className="tabular-nums">{Math.round(job.progress * 100)}%</span>
              </div>
            </div>
          )}
          {job.status === "done" && result.message && <div className="mt-1 text-sm text-zinc-600 dark:text-zinc-300">{result.message}</div>}
          {job.status === "error" && <div className="mt-1 text-sm break-words text-red-600 dark:text-red-400">{job.error}</div>}
          {job.status === "done" && job.kind === "render" && result.book_id && (
            <Link to={`/library/${result.book_id}`} className="mt-2 inline-flex text-sm font-medium text-brand-600 hover:underline dark:text-brand-400">
              Listen now →
            </Link>
          )}
          {open && <JobLog id={job.id} />}
        </div>
        <div className="flex shrink-0 items-center">
          <IconButton label="Show log" onClick={() => setOpen(!open)} active={open}>
            <ChevronDown className={open ? "size-4 rotate-180" : "size-4"} />
          </IconButton>
          {active && (
            <IconButton label="Cancel" onClick={() => action.mutate(() => api.cancelJob(job.id))}>
              <X className="size-4" />
            </IconButton>
          )}
          {(job.status === "error" || job.status === "cancelled") && (
            <IconButton label="Retry" onClick={() => action.mutate(() => api.retryJob(job.id))}>
              <RotateCcw className="size-4" />
            </IconButton>
          )}
          {!active && (
            <IconButton label="Remove" onClick={() => action.mutate(() => api.deleteJob(job.id))}>
              <Trash2 className="size-4" />
            </IconButton>
          )}
        </div>
      </div>
    </Card>
  );
}

export default function Queue() {
  const [filter, setFilter] = useState<"all" | "active" | "error">("all");
  const feedback = useFeedback();
  const queryClient = useQueryClient();
  const jobs = useQuery({
    queryKey: ["jobs", filter],
    queryFn: () => api.jobs(filter === "all" ? undefined : filter),
    refetchInterval: (q) => (q.state.data?.some((j) => j.status === "running" || j.status === "queued") ? 1500 : 6000),
  });
  const clear = useMutation({
    mutationFn: api.clearJobs,
    onSuccess: (r) => {
      feedback.success(`Removed ${r.removed} finished jobs`);
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: feedback.error,
  });

  return (
    <div className="mx-auto max-w-4xl animate-fade-in">
      <PageHeader
        title="Queue"
        icon={<ListTodo className="size-5" />}
        description="Background work: imports, narration, downloads and library maintenance. Jobs continue after a restart."
        actions={
          <>
            <Button icon={<RefreshCw className="size-4" />} onClick={() => void jobs.refetch()}>
              Refresh
            </Button>
            <Button icon={<Trash2 className="size-4" />} onClick={() => clear.mutate()} loading={clear.isPending}>
              Clear finished
            </Button>
          </>
        }
      />
      <Segmented
        className="mb-4"
        value={filter}
        onChange={setFilter}
        options={[
          { value: "all", label: "All" },
          { value: "active", label: "Active" },
          { value: "error", label: "Failed" },
        ]}
      />
      {jobs.isLoading ? (
        <LoadingBlock />
      ) : !jobs.data?.length ? (
        <EmptyState icon={<ListTodo className="size-6" />} title="Nothing in the queue" description="Jobs appear here when you import or narrate books." />
      ) : (
        <div className="space-y-3">
          {jobs.data.map((job) => (
            <JobCard key={job.id} job={job} />
          ))}
        </div>
      )}
    </div>
  );
}

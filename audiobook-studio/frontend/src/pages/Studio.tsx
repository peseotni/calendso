import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Headphones, MoreVertical, Play, Plus, Trash2, Wand2, X } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Cover } from "../components/Cover";
import { Dropzone } from "../components/Dropzone";
import { useFeedback } from "../components/feedback";
import { ProjectStatusBadge } from "../components/StatusBadge";
import { Badge, Button, Card, EmptyState, IconButton, LoadingBlock, Menu, MenuItem, PageHeader, ProgressBar, Segmented } from "../components/ui";
import { api } from "../lib/api";
import { formatDuration, formatNumber, timeAgo } from "../lib/format";
import type { ProjectSummary } from "../lib/types";

const ACTIVE = new Set(["importing", "queued", "rendering"]);

export default function Studio() {
  const feedback = useFeedback();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [filter, setFilter] = useState<"all" | "active" | "draft" | "done">("all");
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: api.projects,
    refetchInterval: (q) => (q.state.data?.some((p) => ACTIVE.has(p.status)) ? 2000 : 15000),
  });

  const upload = useMutation({
    mutationFn: (files: File[]) => api.uploadProjects(files),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      if (created.length === 1) navigate(`/studio/${created[0].id}`);
      else feedback.success(`${created.length} books are being imported`);
    },
    onError: feedback.error,
  });

  const render = useMutation({
    mutationFn: (id: number) => api.renderProject(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      feedback.success("Added to the narration queue");
    },
    onError: feedback.error,
  });

  const cancel = useMutation({
    mutationFn: (id: number) => api.cancelProject(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["projects"] }),
    onError: feedback.error,
  });

  const remove = async (project: ProjectSummary) => {
    const { confirmed, checked } = await feedback.confirm({
      title: `Delete project “${project.title}”?`,
      message: "The source document, chapter edits and rendered workspace audio are deleted.",
      checkbox: project.book_id ? "Also remove the finished audiobook from the library (and disk)" : undefined,
      confirmLabel: "Delete",
      danger: true,
    });
    if (!confirmed) return;
    try {
      await api.deleteProject(project.id, checked);
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      void queryClient.invalidateQueries({ queryKey: ["books"] });
    } catch (error) {
      feedback.error(error);
    }
  };

  const list = (projects.data ?? []).filter((p) =>
    filter === "all" ? true : filter === "active" ? ACTIVE.has(p.status) : filter === "draft" ? p.status === "ready" || p.status === "error" : p.status === "done",
  );

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Studio"
        icon={<Wand2 className="size-5" />}
        description="Turn ebooks into audiobooks: review chapters, pick voices, fix pronunciation and render."
        actions={
          <Link to="/studio/new">
            <Button variant="primary" icon={<Plus className="size-4" />}>
              New audiobook
            </Button>
          </Link>
        }
      />

      <div className="mb-6">
        <Dropzone compact onFiles={(files) => upload.mutate(files)} disabled={upload.isPending}>
          <div className="flex items-center gap-3 text-sm">
            <Plus className="size-5 text-brand-600" />
            <span>
              <span className="font-semibold">{upload.isPending ? "Uploading…" : "Drop ebooks here"}</span>
              <span className="text-zinc-500"> to start new projects (several at once is fine)</span>
            </span>
          </div>
        </Dropzone>
      </div>

      <div className="mb-4 flex items-center justify-between">
        <Segmented
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: "All" },
            { value: "active", label: "In progress" },
            { value: "draft", label: "Drafts" },
            { value: "done", label: "Finished" },
          ]}
        />
        <span className="text-sm text-zinc-500">{list.length} projects</span>
      </div>

      {projects.isLoading ? (
        <LoadingBlock />
      ) : !list.length ? (
        <EmptyState
          icon={<BookOpen className="size-6" />}
          title={projects.data?.length ? "Nothing here" : "No projects yet"}
          description="Upload an EPUB, PDF, Word document, Kindle book or text file to create your first audiobook."
          action={
            <Link to="/studio/new">
              <Button variant="primary">Create audiobook</Button>
            </Link>
          }
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
          {list.map((project) => (
            <Card key={project.id} className="flex gap-4 p-4 transition hover:shadow-md">
              <Link to={`/studio/${project.id}`} className="w-24 shrink-0">
                <Cover src={project.cover_url} title={project.title} author={project.author} rounded="rounded-lg" />
              </Link>
              <div className="flex min-w-0 flex-1 flex-col">
                <div className="flex items-start gap-2">
                  <Link to={`/studio/${project.id}`} className="min-w-0 flex-1">
                    <div className="truncate font-semibold">{project.title}</div>
                    <div className="truncate text-sm text-zinc-500">{project.author || "Unknown author"}</div>
                  </Link>
                  <Menu
                    trigger={({ onClick }) => (
                      <IconButton label="Actions" onClick={onClick} className="-mt-1 -mr-2">
                        <MoreVertical className="size-4" />
                      </IconButton>
                    )}
                  >
                    {(close) => (
                      <>
                        {project.status === "rendering" || project.status === "queued" ? (
                          <MenuItem icon={<X />} onClick={() => (cancel.mutate(project.id), close())}>
                            Cancel narration
                          </MenuItem>
                        ) : (
                          <MenuItem icon={<Play />} disabled={project.status === "importing"} onClick={() => (render.mutate(project.id), close())}>
                            {project.status === "done" ? "Render again" : "Render audiobook"}
                          </MenuItem>
                        )}
                        {project.book_id && (
                          <MenuItem icon={<Headphones />} onClick={() => navigate(`/library/${project.book_id}`)}>
                            Open in library
                          </MenuItem>
                        )}
                        <MenuItem icon={<Trash2 />} danger onClick={() => (close(), void remove(project))}>
                          Delete project
                        </MenuItem>
                      </>
                    )}
                  </Menu>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <ProjectStatusBadge status={project.status} />
                  {project.source_format && <Badge>{project.source_format.toUpperCase()}</Badge>}
                </div>
                <div className="mt-auto pt-3 text-xs text-zinc-500 dark:text-zinc-400">
                  {ACTIVE.has(project.status) && project.job_progress !== null ? (
                    <div>
                      <ProgressBar value={project.job_progress} indeterminate={project.status === "queued"} />
                      <div className="mt-1 truncate">{project.job_message || "Waiting…"}</div>
                    </div>
                  ) : project.status === "error" ? (
                    <div className="line-clamp-2 text-red-600 dark:text-red-400">{project.error}</div>
                  ) : (
                    <div className="flex flex-wrap gap-x-3">
                      <span>
                        {project.included_chapters}/{project.chapter_count} chapters
                      </span>
                      <span>{formatNumber(project.word_count)} words</span>
                      <span>≈ {formatDuration(project.estimated_seconds)}</span>
                      <span>{timeAgo(project.updated_at)}</span>
                    </div>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

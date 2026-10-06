import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Combine,
  Headphones,
  Loader2,
  MoreHorizontal,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Square,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import { useFeedback } from "../../components/feedback";
import { Badge, Button, Card, Field, IconButton, Menu, MenuItem, Modal, cn } from "../../components/ui";
import { api } from "../../lib/api";
import { formatDuration, formatNumber } from "../../lib/format";
import { usePreviewPlayer } from "../../lib/hooks";
import type { Chapter, ProjectDetail } from "../../lib/types";
import { ChapterEditor } from "./ChapterEditor";

function AudioState({ chapter }: { chapter: Chapter }) {
  if (chapter.status === "rendering") return <Badge color="brand" icon={<Loader2 className="size-3 animate-spin" />}>Narrating</Badge>;
  if (chapter.status === "error") return <Badge color="red" icon={<AlertCircle className="size-3" />}>Failed</Badge>;
  if (chapter.audio_state === "ready") return <Badge color="green" icon={<CheckCircle2 className="size-3" />}>Rendered</Badge>;
  if (chapter.audio_state === "stale") return <Badge color="amber" icon={<RefreshCw className="size-3" />}>Changed</Badge>;
  return null;
}

let renderedAudio: HTMLAudioElement | null = null;

export function ChaptersTab({ project, onChange }: { project: ProjectDetail; onChange: (project?: ProjectDetail) => void }) {
  const feedback = useFeedback();
  const preview = usePreviewPlayer();
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [editing, setEditing] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [newChapter, setNewChapter] = useState({ title: "", text: "" });
  const [playingRendered, setPlayingRendered] = useState<number | null>(null);
  const locked = project.status === "rendering" || project.status === "importing";
  const chapters = project.chapters;
  const included = chapters.filter((c) => c.include);

  const run = async (action: () => Promise<ProjectDetail | unknown>, message?: string) => {
    try {
      const result = await action();
      if (message) feedback.success(message);
      onChange(result && typeof result === "object" && "chapters" in (result as object) ? (result as ProjectDetail) : undefined);
    } catch (error) {
      feedback.error(error);
    }
  };

  const toggleInclude = (chapter: Chapter) => run(() => api.updateChapter(project.id, chapter.id, { include: !chapter.include }));

  const move = (index: number, delta: number) => {
    const ids = chapters.map((c) => c.id);
    const target = index + delta;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    void run(() => api.reorderChapters(project.id, ids));
  };

  const playRendered = (chapter: Chapter) => {
    if (renderedAudio) renderedAudio.pause();
    if (playingRendered === chapter.id) {
      setPlayingRendered(null);
      return;
    }
    preview.stop();
    renderedAudio = new Audio(`/api/projects/${project.id}/chapters/${chapter.id}/audio`);
    renderedAudio.onended = () => setPlayingRendered(null);
    void renderedAudio.play();
    setPlayingRendered(chapter.id);
  };

  const allSelected = selected.size === chapters.length && chapters.length > 0;
  const selectedIds = [...selected];

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="size-4 accent-brand-600"
            checked={allSelected}
            onChange={() => setSelected(allSelected ? new Set() : new Set(chapters.map((c) => c.id)))}
          />
          {selected.size ? `${selected.size} selected` : "Select"}
        </label>
        {selected.size > 0 && (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => void run(() => api.bulkChapters(project.id, { chapter_ids: selectedIds, include: true }))}>
              Narrate
            </Button>
            <Button size="sm" onClick={() => void run(() => api.bulkChapters(project.id, { chapter_ids: selectedIds, include: false }))}>
              Skip
            </Button>
            <Button
              size="sm"
              icon={<Combine className="size-4" />}
              disabled={selected.size < 2 || locked}
              onClick={() =>
                void run(() => api.mergeChapters(project.id, selectedIds), "Chapters merged").then(() => setSelected(new Set()))
              }
            >
              Merge
            </Button>
          </div>
        )}
        <div className="ml-auto text-sm text-zinc-500 dark:text-zinc-400">
          {included.length} of {chapters.length} chapters · {formatNumber(included.reduce((s, c) => s + c.word_count, 0))} words · ≈{" "}
          {formatDuration(included.reduce((s, c) => s + c.estimated_seconds, 0))}
        </div>
      </div>

      <Card className="divide-y divide-zinc-100 overflow-hidden dark:divide-zinc-800">
        {chapters.map((chapter, index) => (
          <div
            key={chapter.id}
            className={cn(
              "group flex items-center gap-3 px-3 py-2.5 sm:px-4",
              !chapter.include && "bg-zinc-50/80 dark:bg-zinc-950/40",
            )}
          >
            <input
              type="checkbox"
              aria-label="Select chapter"
              className="hidden size-4 shrink-0 accent-brand-600 sm:block"
              checked={selected.has(chapter.id)}
              onChange={() => {
                const next = new Set(selected);
                if (next.has(chapter.id)) next.delete(chapter.id);
                else next.add(chapter.id);
                setSelected(next);
              }}
            />
            <button
              onClick={() => void toggleInclude(chapter)}
              title={chapter.include ? "Will be narrated – click to skip" : "Skipped – click to narrate"}
              className={cn(
                "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors",
                chapter.include ? "bg-brand-600" : "bg-zinc-300 dark:bg-zinc-700",
              )}
            >
              <span className={cn("inline-block size-4 rounded-full bg-white shadow transition-transform", chapter.include ? "translate-x-4.5" : "translate-x-0.5")} />
            </button>
            <span className="hidden w-6 shrink-0 text-right text-xs text-zinc-400 tabular-nums sm:inline">{index + 1}</span>
            <button onClick={() => setEditing(chapter.id)} className="min-w-0 flex-1 text-left">
              <div className={cn("flex items-center gap-2", !chapter.include && "opacity-50")}>
                <span className="truncate text-sm font-medium">{chapter.title}</span>
                {chapter.kind !== "chapter" && <Badge>{chapter.kind === "front" ? "Front matter" : "Back matter"}</Badge>}
                {chapter.voice && <Badge color="blue">{chapter.voice.split(":").pop()}</Badge>}
              </div>
              <div className={cn("truncate text-xs text-zinc-500 dark:text-zinc-400", !chapter.include && "opacity-50")}>
                {chapter.preview}
              </div>
              {chapter.status === "error" && <div className="truncate text-xs text-red-600">{chapter.error}</div>}
            </button>
            <div className="hidden shrink-0 text-right text-xs text-zinc-500 tabular-nums sm:block">
              <div>{formatNumber(chapter.word_count)} words</div>
              <div>{chapter.duration ? formatDuration(chapter.duration) : `≈ ${formatDuration(chapter.estimated_seconds)}`}</div>
            </div>
            <div className="hidden w-24 shrink-0 justify-end md:flex">
              <AudioState chapter={chapter} />
            </div>
            <div className="flex shrink-0 items-center">
              <IconButton
                label="Preview with current voice"
                onClick={() => {
                  if (renderedAudio) renderedAudio.pause();
                  setPlayingRendered(null);
                  preview.play(`c${chapter.id}`, () => api.previewChapter(project.id, chapter.id)).catch(feedback.error);
                }}
              >
                {preview.loading === `c${chapter.id}` ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : preview.playing === `c${chapter.id}` ? (
                  <Square className="size-3.5" fill="currentColor" />
                ) : (
                  <Play className="size-4" />
                )}
              </IconButton>
              {chapter.audio_state !== "none" && (
                <IconButton
                  label="Play rendered audio"
                  onClick={() => playRendered(chapter)}
                  active={playingRendered === chapter.id}
                  className="hidden sm:inline-flex"
                >
                  {playingRendered === chapter.id ? <Square className="size-3.5" fill="currentColor" /> : <Headphones className="size-4" />}
                </IconButton>
              )}
              <Menu
                trigger={({ onClick }) => (
                  <IconButton label="More" onClick={onClick}>
                    <MoreHorizontal className="size-4" />
                  </IconButton>
                )}
              >
                {(close) => (
                  <>
                    <MenuItem icon={<Pencil />} onClick={() => (setEditing(chapter.id), close())}>
                      Edit text
                    </MenuItem>
                    <MenuItem icon={<ArrowUp />} disabled={index === 0 || locked} onClick={() => (move(index, -1), close())}>
                      Move up
                    </MenuItem>
                    <MenuItem icon={<ArrowDown />} disabled={index === chapters.length - 1 || locked} onClick={() => (move(index, 1), close())}>
                      Move down
                    </MenuItem>
                    {chapter.voice && (
                      <MenuItem icon={<RefreshCw />} onClick={() => (close(), void run(() => api.updateChapter(project.id, chapter.id, { voice: "" })))}>
                        Use project voice
                      </MenuItem>
                    )}
                    <MenuItem
                      icon={<Trash2 />}
                      danger
                      disabled={locked}
                      onClick={async () => {
                        close();
                        const { confirmed } = await feedback.confirm({ title: `Delete “${chapter.title}”?`, danger: true, confirmLabel: "Delete" });
                        if (confirmed) void run(() => api.deleteChapter(project.id, chapter.id), "Chapter deleted");
                      }}
                    >
                      Delete chapter
                    </MenuItem>
                  </>
                )}
              </Menu>
            </div>
          </div>
        ))}
      </Card>

      <div className="mt-4 flex justify-between gap-3">
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Tip: front matter like copyright pages and tables of contents is skipped automatically. Toggle the switch to change
          what gets narrated.
        </p>
        <Button size="sm" icon={<Plus className="size-4" />} onClick={() => setAdding(true)} disabled={locked}>
          Add chapter
        </Button>
      </div>

      <ChapterEditor project={project} chapterId={editing} onClose={() => setEditing(null)} onSaved={onChange} />

      <Modal
        open={adding}
        onClose={() => setAdding(false)}
        title="Add chapter"
        description="For example an introduction, credits (“This audiobook was narrated by…”) or an author's note. It is added at the end."
        footer={
          <>
            <Button onClick={() => setAdding(false)}>Cancel</Button>
            <Button
              variant="primary"
              disabled={!newChapter.text.trim()}
              onClick={() =>
                void run(() => api.addChapter(project.id, newChapter), "Chapter added").then(() => {
                  setAdding(false);
                  setNewChapter({ title: "", text: "" });
                })
              }
            >
              Add
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Title">
            <input className="input" value={newChapter.title} onChange={(e) => setNewChapter({ ...newChapter, title: e.target.value })} placeholder="Credits" />
          </Field>
          <Field label="Text">
            <textarea className="input min-h-40" value={newChapter.text} onChange={(e) => setNewChapter({ ...newChapter, text: e.target.value })} />
          </Field>
        </div>
      </Modal>
    </div>
  );
}

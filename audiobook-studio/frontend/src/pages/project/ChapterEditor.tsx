import { useQuery } from "@tanstack/react-query";
import { Loader2, Play, Scissors, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useFeedback } from "../../components/feedback";
import { Button, Field, Modal, Spinner } from "../../components/ui";
import { api } from "../../lib/api";
import { formatDuration } from "../../lib/format";
import { usePreviewPlayer } from "../../lib/hooks";
import type { ProjectDetail } from "../../lib/types";

export function ChapterEditor({
  project,
  chapterId,
  onClose,
  onSaved,
}: {
  project: ProjectDetail;
  chapterId: number | null;
  onClose: () => void;
  onSaved: (project?: ProjectDetail) => void;
}) {
  const feedback = useFeedback();
  const preview = usePreviewPlayer();
  const textarea = useRef<HTMLTextAreaElement>(null);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);

  const chapter = useQuery({
    queryKey: ["chapter", project.id, chapterId],
    queryFn: () => api.chapter(project.id, chapterId!),
    enabled: chapterId !== null,
    staleTime: 0,
  });

  useEffect(() => {
    if (chapter.data) {
      setTitle(chapter.data.title);
      setText(chapter.data.text);
    }
  }, [chapter.data]);

  const dirty = chapter.data && (title !== chapter.data.title || text !== chapter.data.text);
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;

  const close = async () => {
    preview.stop();
    if (dirty) {
      const { confirmed } = await feedback.confirm({ title: "Discard your changes?", confirmLabel: "Discard", danger: true });
      if (!confirmed) return;
    }
    onClose();
  };

  const save = async () => {
    if (!chapterId) return;
    setSaving(true);
    try {
      await api.updateChapter(project.id, chapterId, { title, text });
      feedback.success("Chapter saved");
      onSaved();
      onClose();
    } catch (error) {
      feedback.error(error);
    } finally {
      setSaving(false);
    }
  };

  const selectedText = () => {
    const el = textarea.current;
    if (!el) return "";
    return el.value.slice(el.selectionStart, el.selectionEnd).trim();
  };

  const playPreview = () => {
    const selection = selectedText();
    const sample = selection || text;
    preview.play("chapter", () => api.previewChapter(project.id, chapterId!, sample.slice(0, 2500))).catch(feedback.error);
  };

  const split = async () => {
    const el = textarea.current;
    if (!el || !chapterId) return;
    const offset = el.selectionStart;
    if (offset <= 0 || offset >= text.length) {
      feedback.toast("Place the cursor where the new chapter should start.", "warning");
      return;
    }
    try {
      if (dirty) await api.updateChapter(project.id, chapterId, { title, text });
      const updated = await api.splitChapter(project.id, chapterId, offset);
      feedback.success("Chapter split in two");
      onSaved(updated);
      onClose();
    } catch (error) {
      feedback.error(error);
    }
  };

  return (
    <Modal
      open={chapterId !== null}
      onClose={() => void close()}
      size="xl"
      title="Edit chapter"
      description="Fix OCR errors, remove unwanted passages or rewrite tricky words. Select text to preview just that part."
      footer={
        <>
          <Button
            className="mr-auto"
            onClick={playPreview}
            icon={preview.loading ? <Loader2 className="size-4 animate-spin" /> : preview.playing ? <Square className="size-3.5" fill="currentColor" /> : <Play className="size-4" />}
          >
            {preview.playing ? "Stop" : "Preview"}
          </Button>
          <Button icon={<Scissors className="size-4" />} onClick={() => void split()}>
            Split at cursor
          </Button>
          <Button onClick={() => void close()}>Cancel</Button>
          <Button variant="primary" onClick={() => void save()} loading={saving} disabled={!dirty}>
            Save
          </Button>
        </>
      }
    >
      {chapter.isLoading ? (
        <div className="flex justify-center py-20">
          <Spinner />
        </div>
      ) : (
        <div className="space-y-4">
          <Field label="Chapter title">
            <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <Field
            label="Text"
            hint={`${words.toLocaleString()} words · about ${formatDuration((words / 155) * 60)} · blank lines separate paragraphs, a line with * * * adds a scene break pause`}
          >
            <textarea
              ref={textarea}
              className="input min-h-[50vh] resize-y font-serif text-[15px] leading-relaxed"
              value={text}
              onChange={(e) => setText(e.target.value)}
              spellCheck
            />
          </Field>
        </div>
      )}
    </Modal>
  );
}

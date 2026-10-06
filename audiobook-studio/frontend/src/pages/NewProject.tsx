import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ClipboardType, FileText, Upload, Wand2, X } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Dropzone } from "../components/Dropzone";
import { useFeedback } from "../components/feedback";
import { Button, Card, Field, IconButton, PageHeader, Select, Switch, Tabs } from "../components/ui";
import { api } from "../lib/api";
import { formatBytes } from "../lib/format";

export default function NewProject() {
  const [tab, setTab] = useState<"upload" | "text">("upload");
  const [files, setFiles] = useState<File[]>([]);
  const [autoRender, setAutoRender] = useState(false);
  const [ocr, setOcr] = useState("auto");
  const [text, setText] = useState({ title: "", author: "", text: "" });
  const navigate = useNavigate();
  const feedback = useFeedback();
  const queryClient = useQueryClient();

  const upload = useMutation({
    mutationFn: () => api.uploadProjects(files, { autoRender, ocr }),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      feedback.success(created.length === 1 ? "Importing your book…" : `Importing ${created.length} books…`);
      navigate(created.length === 1 ? `/studio/${created[0].id}` : "/studio");
    },
    onError: feedback.error,
  });

  const fromText = useMutation({
    mutationFn: () => api.createTextProject(text),
    onSuccess: (project) => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/studio/${project.id}`);
    },
    onError: feedback.error,
  });

  const words = text.text.trim() ? text.text.trim().split(/\s+/).length : 0;

  return (
    <div className="mx-auto max-w-3xl animate-fade-in">
      <PageHeader
        title="New audiobook"
        icon={<Wand2 className="size-5" />}
        description="Import an ebook or document. Chapters, metadata and cover art are detected automatically and you can review everything before narration."
      />
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { value: "upload", label: "Upload files", icon: <Upload className="size-4" /> },
          { value: "text", label: "Paste text", icon: <ClipboardType className="size-4" /> },
        ]}
      />
      {tab === "upload" ? (
        <div className="space-y-5">
          <Dropzone onFiles={(added) => setFiles([...files, ...added])} />
          {files.length > 0 && (
            <Card className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {files.map((file, index) => (
                <div key={`${file.name}-${index}`} className="flex items-center gap-3 px-4 py-3">
                  <FileText className="size-5 shrink-0 text-brand-600" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{file.name}</div>
                    <div className="text-xs text-zinc-500">{formatBytes(file.size)}</div>
                  </div>
                  <IconButton label="Remove" onClick={() => setFiles(files.filter((_, i) => i !== index))}>
                    <X className="size-4" />
                  </IconButton>
                </div>
              ))}
            </Card>
          )}
          <Card className="space-y-4 p-5">
            <Switch
              checked={autoRender}
              onChange={setAutoRender}
              label="Start narration right after import"
              description="Uses your default voice and settings. Skip this if you want to review chapters first."
            />
            <Field label="Scanned PDFs (OCR)" hint="Text recognition for pages without a text layer. Requires Tesseract language data on the server.">
              <Select
                value={ocr}
                onChange={setOcr}
                options={[
                  { value: "auto", label: "Automatic – only pages without text" },
                  { value: "force", label: "Always run OCR on every page" },
                  { value: "off", label: "Never" },
                ]}
              />
            </Field>
          </Card>
          <div className="flex justify-end">
            <Button variant="primary" size="lg" disabled={!files.length} loading={upload.isPending} onClick={() => upload.mutate()} icon={<Upload className="size-4" />}>
              Import {files.length > 1 ? `${files.length} books` : "book"}
            </Button>
          </div>
        </div>
      ) : (
        <Card className="space-y-4 p-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Title">
              <input className="input" value={text.title} onChange={(e) => setText({ ...text, title: e.target.value })} placeholder="My story" />
            </Field>
            <Field label="Author">
              <input className="input" value={text.author} onChange={(e) => setText({ ...text, author: e.target.value })} />
            </Field>
          </div>
          <Field label="Text" hint={`${words.toLocaleString()} words · Use “# Heading” lines or “Chapter 1” lines to create chapters. Separate paragraphs with a blank line.`}>
            <textarea
              className="input min-h-80 font-serif leading-relaxed"
              value={text.text}
              onChange={(e) => setText({ ...text, text: e.target.value })}
              placeholder={"# Chapter 1\n\nIt was a quiet morning…"}
            />
          </Field>
          <div className="flex justify-end">
            <Button variant="primary" disabled={!text.title.trim() || !text.text.trim()} loading={fromText.isPending} onClick={() => fromText.mutate()}>
              Create project
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
}

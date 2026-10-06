import { ImagePlus, Link2, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { Cover } from "./Cover";
import { useFeedback } from "./feedback";
import { Button, Modal } from "./ui";

export function CoverEditor({
  src,
  title,
  author,
  onUpload,
  onUrl,
  onRemove,
}: {
  src: string | null;
  title: string;
  author: string;
  onUpload: (file: File) => Promise<unknown>;
  onUrl: (url: string) => Promise<unknown>;
  onRemove?: () => Promise<unknown>;
}) {
  const input = useRef<HTMLInputElement>(null);
  const feedback = useFeedback();
  const [busy, setBusy] = useState(false);
  const [urlOpen, setUrlOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [dragging, setDragging] = useState(false);

  const run = async (action: () => Promise<unknown>, message: string) => {
    setBusy(true);
    try {
      await action();
      feedback.success(message);
    } catch (error) {
      feedback.error(error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const file = e.dataTransfer.files[0];
          if (file) void run(() => onUpload(file), "Cover updated");
        }}
        className={dragging ? "rounded-xl ring-4 ring-brand-500/50" : undefined}
      >
        <Cover src={src} title={title} author={author} className="shadow-lg" />
      </div>
      <input
        ref={input}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void run(() => onUpload(file), "Cover updated");
          e.target.value = "";
        }}
      />
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" icon={<ImagePlus className="size-4" />} onClick={() => input.current?.click()} loading={busy}>
          Upload
        </Button>
        <Button size="sm" icon={<Link2 className="size-4" />} onClick={() => setUrlOpen(true)}>
          From URL
        </Button>
        {onRemove && src && (
          <Button size="sm" variant="ghost" icon={<Trash2 className="size-4" />} onClick={() => void run(onRemove, "Cover removed")}>
            Remove
          </Button>
        )}
      </div>
      <Modal
        open={urlOpen}
        onClose={() => setUrlOpen(false)}
        title="Cover from URL"
        size="sm"
        footer={
          <>
            <Button onClick={() => setUrlOpen(false)}>Cancel</Button>
            <Button
              variant="primary"
              disabled={!url.trim()}
              loading={busy}
              onClick={() =>
                void run(() => onUrl(url.trim()), "Cover downloaded").then(() => {
                  setUrlOpen(false);
                  setUrl("");
                })
              }
            >
              Download
            </Button>
          </>
        }
      >
        <input className="input" placeholder="https://…/cover.jpg" value={url} onChange={(e) => setUrl(e.target.value)} autoFocus />
      </Modal>
    </div>
  );
}

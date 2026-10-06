import { UploadCloud } from "lucide-react";
import { type ReactNode, useRef, useState } from "react";
import { cn } from "./ui";

export const ACCEPTED = ".epub,.pdf,.docx,.odt,.txt,.text,.md,.markdown,.html,.htm,.xhtml,.fb2,.zip,.mobi,.azw,.azw3,.prc";

export function Dropzone({
  onFiles,
  children,
  compact,
  disabled,
}: {
  onFiles: (files: File[]) => void;
  children?: ReactNode;
  compact?: boolean;
  disabled?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => !disabled && input.current?.click()}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        if (!disabled && e.dataTransfer.files.length) onFiles([...e.dataTransfer.files]);
      }}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed text-center transition-colors",
        compact ? "px-4 py-6" : "px-6 py-14",
        dragging
          ? "border-brand-500 bg-brand-50 dark:bg-brand-500/10"
          : "border-zinc-300 bg-white hover:border-brand-400 hover:bg-brand-50/40 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:border-brand-500/60 dark:hover:bg-brand-500/5",
        disabled && "pointer-events-none opacity-60",
      )}
    >
      <input
        ref={input}
        type="file"
        multiple
        accept={ACCEPTED}
        className="hidden"
        onChange={(e) => {
          if (e.target.files?.length) onFiles([...e.target.files]);
          e.target.value = "";
        }}
      />
      {children ?? (
        <>
          <div className="mb-3 flex size-12 items-center justify-center rounded-2xl bg-brand-100 text-brand-600 dark:bg-brand-500/15 dark:text-brand-300">
            <UploadCloud className="size-6" />
          </div>
          <div className="text-sm font-semibold">Drop ebooks here or click to browse</div>
          <div className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            EPUB · PDF · DOCX · ODT · MOBI/AZW3 · FB2 · TXT · Markdown · HTML
          </div>
        </>
      )}
    </div>
  );
}

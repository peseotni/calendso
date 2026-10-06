import { Headphones } from "lucide-react";
import { useState } from "react";
import { cn } from "./ui";

const gradients = [
  "from-violet-500 to-indigo-600",
  "from-rose-500 to-orange-500",
  "from-emerald-500 to-teal-600",
  "from-sky-500 to-blue-600",
  "from-amber-500 to-red-500",
  "from-fuchsia-500 to-purple-600",
  "from-lime-500 to-emerald-600",
  "from-cyan-500 to-sky-600",
];

function hash(value: string): number {
  let h = 0;
  for (let i = 0; i < value.length; i++) h = (h * 31 + value.charCodeAt(i)) | 0;
  return Math.abs(h);
}

/**
 * Square (or portrait) cover art with a generated fallback.
 * Size it with width classes in ``className`` (e.g. ``w-24``); it fills its parent otherwise.
 */
export function Cover({
  src,
  title,
  author,
  className,
  rounded = "rounded-xl",
  portrait = false,
}: {
  src?: string | null;
  title: string;
  author?: string;
  className?: string;
  rounded?: string;
  portrait?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const aspect = portrait ? "aspect-[2/3]" : "aspect-square";
  const gradient = gradients[hash(title + (author ?? "")) % gradients.length];
  return (
    <div className={cn("relative shrink-0 overflow-hidden", rounded, className)}>
      {src && !failed ? (
        <img
          src={src}
          alt={title}
          loading="lazy"
          onError={() => setFailed(true)}
          className={cn("block w-full bg-zinc-200 object-cover dark:bg-zinc-800", aspect)}
        />
      ) : (
        <div className={cn("@container flex w-full flex-col justify-between bg-gradient-to-br p-[8%] text-white", aspect, gradient)}>
          <Headphones className="size-[18%] min-h-3 min-w-3 opacity-70" />
          <div className="min-w-0">
            <div className="line-clamp-3 text-[clamp(0.5rem,10cqw,1.25rem)] leading-tight font-semibold">{title || "Untitled"}</div>
            {author && <div className="mt-1 truncate text-[clamp(0.45rem,7cqw,0.9rem)] opacity-80">{author}</div>}
          </div>
        </div>
      )}
    </div>
  );
}

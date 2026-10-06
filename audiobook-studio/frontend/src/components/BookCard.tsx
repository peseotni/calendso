import { CheckCircle2, Heart, Pause, Play } from "lucide-react";
import { Link } from "react-router-dom";
import { formatDuration } from "../lib/format";
import type { Book } from "../lib/types";
import { usePlayer } from "../player/PlayerContext";
import { Cover } from "./Cover";
import { cn } from "./ui";

export function BookCard({
  book,
  selectable,
  selected,
  onSelect,
}: {
  book: Book;
  selectable?: boolean;
  selected?: boolean;
  onSelect?: (id: number) => void;
}) {
  const player = usePlayer();
  const isCurrent = player.book?.id === book.id;
  const progress = book.duration ? book.progress / book.duration : 0;

  return (
    <div className="group relative">
      <Link
        to={`/library/${book.id}`}
        onClick={(e) => {
          if (selectable) {
            e.preventDefault();
            onSelect?.(book.id);
          }
        }}
        className="block"
      >
        <div className={cn("relative overflow-hidden rounded-xl shadow-sm transition", selected && "ring-4 ring-brand-500")}>
          <Cover src={book.thumb_url} title={book.title} author={book.author} className="transition duration-300 group-hover:scale-[1.03]" />
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/50 via-transparent to-transparent opacity-0 transition group-hover:opacity-100" />
          {book.finished && (
            <span className="absolute top-2 left-2 rounded-full bg-emerald-500 p-0.5 text-white shadow" title="Finished">
              <CheckCircle2 className="size-4" />
            </span>
          )}
          {book.favorite && (
            <span className="absolute top-2 right-2 rounded-full bg-black/40 p-1 text-rose-400 backdrop-blur" title="Favorite">
              <Heart className="size-3.5" fill="currentColor" />
            </span>
          )}
          {progress > 0 && !book.finished && (
            <div className="absolute inset-x-0 bottom-0 h-1 bg-black/30">
              <div className="h-full bg-brand-500" style={{ width: `${progress * 100}%` }} />
            </div>
          )}
          {selectable && (
            <span
              className={cn(
                "absolute top-2 left-2 flex size-6 items-center justify-center rounded-full border-2 border-white text-white shadow",
                selected ? "bg-brand-600" : "bg-black/30",
              )}
            >
              {selected && <CheckCircle2 className="size-4" />}
            </span>
          )}
        </div>
        <div className="mt-2.5 min-w-0">
          <div className="truncate text-sm font-semibold" title={book.title}>
            {book.title}
          </div>
          <div className="truncate text-xs text-zinc-500 dark:text-zinc-400">
            {book.author || "Unknown author"}
            {book.series ? ` · ${book.series}${book.series_index ? ` #${book.series_index}` : ""}` : ""}
          </div>
          <div className="mt-0.5 text-[11px] text-zinc-400 tabular-nums">{formatDuration(book.duration)}</div>
        </div>
      </Link>
      {!selectable && book.files.length > 0 && (
        <button
          onClick={() => (isCurrent && player.playing ? player.pause() : player.play(book))}
          aria-label={isCurrent && player.playing ? "Pause" : "Play"}
          className={cn(
            "absolute right-2 bottom-[4.25rem] flex size-10 items-center justify-center rounded-full bg-white text-zinc-900 shadow-lg transition",
            isCurrent && player.playing ? "opacity-100" : "translate-y-1 opacity-0 group-hover:translate-y-0 group-hover:opacity-100",
          )}
        >
          {isCurrent && player.playing ? <Pause className="size-4" fill="currentColor" /> : <Play className="ml-0.5 size-4" fill="currentColor" />}
        </button>
      )}
    </div>
  );
}

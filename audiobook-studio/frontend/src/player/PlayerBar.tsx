import {
  ChevronDown,
  ListMusic,
  Loader2,
  Moon,
  Pause,
  Play,
  RotateCcw,
  RotateCw,
  SkipBack,
  SkipForward,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Cover } from "../components/Cover";
import { IconButton, Menu, MenuItem, cn } from "../components/ui";
import { formatDuration } from "../lib/format";
import { usePlayer } from "./PlayerContext";

const RATES = [0.75, 0.9, 1, 1.1, 1.2, 1.3, 1.5, 1.75, 2, 2.5];
const SLEEP = [5, 15, 30, 45, 60, 90];

export function PlayerBar() {
  const player = usePlayer();
  const [scrub, setScrub] = useState<number | null>(null);
  const { book } = player;
  if (!book) return null;

  const position = scrub ?? player.position;
  const duration = player.duration || 1;
  const sleepLabel =
    player.sleep?.kind === "time"
      ? `${Math.max(1, Math.round((player.sleep.until - Date.now()) / 60000))}m`
      : player.sleep?.kind === "chapter"
        ? "ch."
        : null;

  return (
    <div className="fixed inset-x-0 bottom-0 z-30 border-t border-zinc-200 bg-white/95 backdrop-blur lg:left-64 dark:border-zinc-800 dark:bg-zinc-900/95">
      {/* thin progress line for mobile */}
      <div className="h-0.5 bg-zinc-200 sm:hidden dark:bg-zinc-800">
        <div className="h-full bg-brand-500" style={{ width: `${(position / duration) * 100}%` }} />
      </div>
      <div className="mx-auto flex max-w-[1600px] items-center gap-3 px-3 py-2 sm:gap-4 sm:px-4 sm:py-2.5">
        <Link to={`/library/${book.id}`} className="flex min-w-0 flex-1 items-center gap-3 sm:w-64 sm:flex-none lg:w-72">
          <Cover src={book.thumb_url} title={book.title} author={book.author} className="size-11 shrink-0 sm:size-12" rounded="rounded-lg" />
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold">{book.title}</div>
            <div className="truncate text-xs text-zinc-500 dark:text-zinc-400">{player.chapter?.title ?? book.author}</div>
          </div>
        </Link>

        <div className="flex flex-1 flex-col items-center gap-1">
          <div className="flex items-center gap-0.5 sm:gap-1">
            <IconButton label="Previous chapter" onClick={player.prevChapter} className="hidden sm:inline-flex">
              <SkipBack className="size-4" />
            </IconButton>
            <IconButton label="Back 15 seconds" onClick={() => player.skip(-15)}>
              <RotateCcw className="size-4.5" />
            </IconButton>
            <button
              onClick={player.toggle}
              aria-label={player.playing ? "Pause" : "Play"}
              className="mx-1 flex size-10 items-center justify-center rounded-full bg-zinc-900 text-white shadow transition hover:scale-105 dark:bg-white dark:text-zinc-900"
            >
              {player.loading && !player.playing ? (
                <Loader2 className="size-5 animate-spin" />
              ) : player.playing ? (
                <Pause className="size-5" fill="currentColor" />
              ) : (
                <Play className="ml-0.5 size-5" fill="currentColor" />
              )}
            </button>
            <IconButton label="Forward 30 seconds" onClick={() => player.skip(30)}>
              <RotateCw className="size-4.5" />
            </IconButton>
            <IconButton label="Next chapter" onClick={player.nextChapter} className="hidden sm:inline-flex">
              <SkipForward className="size-4" />
            </IconButton>
          </div>
          <div className="hidden w-full max-w-2xl items-center gap-2 text-[11px] text-zinc-500 tabular-nums sm:flex dark:text-zinc-400">
            <span className="w-14 text-right">{formatDuration(position, "clock")}</span>
            <div className="relative flex-1">
              <input
                type="range"
                aria-label="Seek"
                min={0}
                max={duration}
                step={1}
                value={position}
                onChange={(e) => setScrub(Number(e.target.value))}
                onMouseUp={() => {
                  if (scrub !== null) player.seek(scrub);
                  setScrub(null);
                }}
                onTouchEnd={() => {
                  if (scrub !== null) player.seek(scrub);
                  setScrub(null);
                }}
                onKeyUp={() => {
                  if (scrub !== null) player.seek(scrub);
                  setScrub(null);
                }}
                className="relative z-10 w-full"
              />
              <div className="pointer-events-none absolute inset-x-0 top-1/2 h-0">
                {book.chapters.slice(1).map((c, i) => (
                  <span
                    key={i}
                    className="absolute -top-1.5 h-3 w-px bg-zinc-400/50"
                    style={{ left: `${(c.start / duration) * 100}%` }}
                  />
                ))}
              </div>
            </div>
            <span className="w-14">-{formatDuration(Math.max(0, duration - position), "clock")}</span>
          </div>
        </div>

        <div className="hidden items-center gap-0.5 md:flex lg:w-72 lg:justify-end">
          <Menu
            align="right"
            trigger={({ onClick }) => (
              <button
                onClick={onClick}
                className="h-8 rounded-lg px-2 text-xs font-semibold text-zinc-600 tabular-nums hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
                title="Playback speed"
              >
                {Number(player.rate.toFixed(2))}×
              </button>
            )}
          >
            {(close) =>
              RATES.map((r) => (
                <MenuItem key={r} onClick={() => (player.setRate(r), close())}>
                  <span className={cn(r === player.rate && "font-semibold text-brand-600 dark:text-brand-400")}>{r}×</span>
                </MenuItem>
              ))
            }
          </Menu>
          <Menu
            align="right"
            trigger={({ onClick }) => (
              <IconButton label="Sleep timer" onClick={onClick} active={!!player.sleep}>
                <Moon className="size-4" />
                {sleepLabel && <span className="ml-0.5 text-[10px] font-semibold">{sleepLabel}</span>}
              </IconButton>
            )}
          >
            {(close) => (
              <>
                {SLEEP.map((m) => (
                  <MenuItem key={m} onClick={() => (player.setSleep(m), close())}>
                    {m} minutes
                  </MenuItem>
                ))}
                <MenuItem onClick={() => (player.setSleep("chapter"), close())}>End of chapter</MenuItem>
                {player.sleep && <MenuItem onClick={() => (player.setSleep(null), close())}>Turn off</MenuItem>}
              </>
            )}
          </Menu>
          {book.chapters.length > 1 && (
            <Menu
              align="right"
              trigger={({ onClick }) => (
                <IconButton label="Chapters" onClick={onClick}>
                  <ListMusic className="size-4" />
                </IconButton>
              )}
            >
              {(close) => (
                <div className="scrollbar-thin max-h-80 w-72 overflow-y-auto">
                  {book.chapters.map((c, i) => (
                    <button
                      key={i}
                      onClick={() => (player.seek(c.start), close())}
                      className={cn(
                        "flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800",
                        i === player.chapterIndex && "bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-300",
                      )}
                    >
                      <span className="truncate">{c.title}</span>
                      <span className="shrink-0 text-xs text-zinc-500 tabular-nums">{formatDuration(c.start, "clock")}</span>
                    </button>
                  ))}
                </div>
              )}
            </Menu>
          )}
          <div className="group flex items-center">
            <IconButton label={player.volume ? "Mute" : "Unmute"} onClick={() => player.setVolume(player.volume ? 0 : 1)}>
              {player.volume ? <Volume2 className="size-4" /> : <VolumeX className="size-4" />}
            </IconButton>
            <input
              type="range"
              aria-label="Volume"
              min={0}
              max={1}
              step={0.05}
              value={player.volume}
              onChange={(e) => player.setVolume(Number(e.target.value))}
              className="hidden w-20 xl:block"
            />
          </div>
          <IconButton label="Close player" onClick={player.close}>
            <X className="size-4" />
          </IconButton>
        </div>
        <div className="md:hidden">
          <IconButton label="Close player" onClick={player.close}>
            <ChevronDown className="size-5" />
          </IconButton>
        </div>
      </div>
    </div>
  );
}

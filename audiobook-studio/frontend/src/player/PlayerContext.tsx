import { useQueryClient } from "@tanstack/react-query";
import {
  type ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useFeedback } from "../components/feedback";
import { api, fileUrl } from "../lib/api";
import type { Book, BookChapter } from "../lib/types";

type Sleep = { kind: "time"; until: number } | { kind: "chapter"; end: number } | null;

interface PlayerApi {
  book: Book | null;
  playing: boolean;
  loading: boolean;
  position: number;
  duration: number;
  rate: number;
  volume: number;
  sleep: Sleep;
  chapter: BookChapter | null;
  chapterIndex: number;
  play: (book: Book, at?: number) => void;
  toggle: () => void;
  pause: () => void;
  seek: (seconds: number) => void;
  skip: (delta: number) => void;
  nextChapter: () => void;
  prevChapter: () => void;
  setRate: (rate: number) => void;
  setVolume: (volume: number) => void;
  setSleep: (option: number | "chapter" | null) => void;
  close: () => void;
}

const PlayerContext = createContext<PlayerApi | null>(null);

export function usePlayer(): PlayerApi {
  const ctx = useContext(PlayerContext);
  if (!ctx) throw new Error("PlayerProvider missing");
  return ctx;
}

function offsetsFor(book: Book): number[] {
  const offsets = [0];
  for (const file of book.files) offsets.push(offsets[offsets.length - 1] + (file.duration || 0));
  return offsets;
}

function readNumber(key: string, fallback: number): number {
  try {
    const value = Number(localStorage.getItem(key));
    return Number.isFinite(value) && value > 0 ? value : fallback;
  } catch {
    return fallback;
  }
}

export function PlayerProvider({ children }: { children: ReactNode }) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const queryClient = useQueryClient();
  const feedback = useFeedback();
  const [book, setBook] = useState<Book | null>(null);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [position, setPosition] = useState(0);
  const [rate, setRateState] = useState(() => readNumber("player.rate", 1));
  const [volume, setVolumeState] = useState(() => readNumber("player.volume", 1));
  const [sleep, setSleepState] = useState<Sleep>(null);

  const bookRef = useRef<Book | null>(null);
  const fileIndexRef = useRef(0);
  const pendingSeekRef = useRef<number | null>(null);
  const autoplayRef = useRef(false);
  const lastSavedRef = useRef(0);
  const positionRef = useRef(0);

  const duration = book?.duration ?? 0;

  const chapterIndex = useMemo(() => {
    if (!book?.chapters.length) return -1;
    let index = 0;
    book.chapters.forEach((c, i) => {
      if (position >= c.start - 0.25) index = i;
    });
    return index;
  }, [book, position]);
  const chapter = book && chapterIndex >= 0 ? book.chapters[chapterIndex] : null;

  const saveProgress = useCallback(
    (finished?: boolean, keepalive = false) => {
      const current = bookRef.current;
      if (!current) return;
      const pos = positionRef.current;
      lastSavedRef.current = Date.now();
      if (keepalive) {
        fetch(`/api/books/${current.id}/progress`, {
          method: "PUT",
          keepalive: true,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ position: pos, finished: finished ?? null }),
        }).catch(() => undefined);
        return;
      }
      api
        .saveProgress(current.id, pos, finished)
        .then((updated) => {
          queryClient.setQueryData(["book", updated.id], updated);
        })
        .catch(() => undefined);
    },
    [queryClient],
  );

  const loadFile = useCallback((index: number, localTime: number, autoplay: boolean) => {
    const audio = audioRef.current;
    const current = bookRef.current;
    if (!audio || !current) return;
    fileIndexRef.current = index;
    pendingSeekRef.current = localTime;
    autoplayRef.current = autoplay;
    setLoading(true);
    audio.src = fileUrl(current.id, index);
    audio.load();
  }, []);

  const locate = useCallback(
    (global: number): [number, number] => {
      const current = bookRef.current;
      if (!current || !current.files.length) return [0, 0];
      const marks = offsetsFor(current);
      let index = 0;
      for (let i = 0; i < current.files.length; i++) {
        if (global >= marks[i]) index = i;
      }
      return [index, Math.max(0, global - marks[index])];
    },
    [],
  );

  const seek = useCallback(
    (seconds: number) => {
      const audio = audioRef.current;
      const current = bookRef.current;
      if (!audio || !current) return;
      const target = Math.max(0, Math.min(seconds, current.duration || seconds));
      const [index, local] = locate(target);
      positionRef.current = target;
      setPosition(target);
      if (index !== fileIndexRef.current || !audio.src) {
        loadFile(index, local, !audio.paused || autoplayRef.current);
      } else {
        audio.currentTime = local;
      }
    },
    [loadFile, locate],
  );

  const play = useCallback(
    (next: Book, at?: number) => {
      const audio = audioRef.current;
      if (!audio || !next.files.length) return;
      if (bookRef.current && bookRef.current.id !== next.id) saveProgress();
      if (bookRef.current?.id === next.id && at === undefined) {
        void audio.play();
        return;
      }
      bookRef.current = next;
      setBook(next);
      let start = at ?? (next.finished || next.progress >= next.duration - 5 ? 0 : next.progress);
      if (!Number.isFinite(start) || start < 0) start = 0;
      positionRef.current = start;
      setPosition(start);
      setSleepState(null);
      const [index, local] = locate(start);
      loadFile(index, local, true);
    },
    [loadFile, locate, saveProgress],
  );

  const pause = useCallback(() => audioRef.current?.pause(), []);
  const toggle = useCallback(() => {
    const audio = audioRef.current;
    if (!audio || !bookRef.current) return;
    if (audio.paused) void audio.play();
    else audio.pause();
  }, []);
  const skip = useCallback((delta: number) => seek(positionRef.current + delta), [seek]);

  const nextChapter = useCallback(() => {
    const current = bookRef.current;
    if (!current) return;
    const next = current.chapters.find((c) => c.start > positionRef.current + 1);
    if (next) seek(next.start);
  }, [seek]);

  const prevChapter = useCallback(() => {
    const current = bookRef.current;
    if (!current) return;
    const pos = positionRef.current;
    const started = [...current.chapters].reverse().find((c) => c.start <= pos - 3);
    seek(started ? started.start : 0);
  }, [seek]);

  const setRate = useCallback((value: number) => {
    setRateState(value);
    if (audioRef.current) audioRef.current.playbackRate = value;
    try {
      localStorage.setItem("player.rate", String(value));
    } catch {
      /* ignore */
    }
  }, []);

  const setVolume = useCallback((value: number) => {
    setVolumeState(value);
    if (audioRef.current) audioRef.current.volume = value;
    try {
      localStorage.setItem("player.volume", String(value));
    } catch {
      /* ignore */
    }
  }, []);

  const setSleep = useCallback(
    (option: number | "chapter" | null) => {
      if (option === null) setSleepState(null);
      else if (option === "chapter") setSleepState(chapter ? { kind: "chapter", end: chapter.end } : null);
      else setSleepState({ kind: "time", until: Date.now() + option * 60_000 });
    },
    [chapter],
  );

  const close = useCallback(() => {
    saveProgress();
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    }
    bookRef.current = null;
    setBook(null);
    setPlaying(false);
    setSleepState(null);
  }, [saveProgress]);

  // Audio element events
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.playbackRate = rate;
    audio.volume = volume;
    const onLoaded = () => {
      if (pendingSeekRef.current !== null) {
        audio.currentTime = pendingSeekRef.current;
        pendingSeekRef.current = null;
      }
      audio.playbackRate = Number(localStorage.getItem("player.rate")) || 1;
      setLoading(false);
      if (autoplayRef.current) {
        autoplayRef.current = false;
        audio.play().catch(() => setPlaying(false));
      }
    };
    const onTime = () => {
      const current = bookRef.current;
      if (!current) return;
      const global = offsetsFor(current)[fileIndexRef.current] + audio.currentTime;
      positionRef.current = global;
      setPosition(global);
      if (!audio.paused && Date.now() - lastSavedRef.current > 15_000) saveProgress();
    };
    const onPlay = () => setPlaying(true);
    const onPause = () => {
      setPlaying(false);
      saveProgress();
    };
    const onEnded = () => {
      const current = bookRef.current;
      if (!current) return;
      if (fileIndexRef.current + 1 < current.files.length) {
        loadFile(fileIndexRef.current + 1, 0, true);
      } else {
        setPlaying(false);
        saveProgress(true);
      }
    };
    const onWaiting = () => setLoading(true);
    const onPlaying = () => setLoading(false);
    const onError = () => {
      setLoading(false);
      setPlaying(false);
      if (!bookRef.current || !audio.error) return;
      if (audio.error.code === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED) {
        feedback.toast("This browser cannot play this audio format. Try Chrome, Edge, Safari or Firefox – or download the file.", "error");
      } else if (audio.error.code === MediaError.MEDIA_ERR_NETWORK) {
        feedback.toast("Network error while streaming the audiobook.", "error");
      } else {
        feedback.toast(`Playback failed: ${audio.error.message || "unknown error"}`, "error");
      }
    };
    audio.addEventListener("loadedmetadata", onLoaded);
    audio.addEventListener("timeupdate", onTime);
    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("ended", onEnded);
    audio.addEventListener("waiting", onWaiting);
    audio.addEventListener("playing", onPlaying);
    audio.addEventListener("error", onError);
    return () => {
      audio.removeEventListener("loadedmetadata", onLoaded);
      audio.removeEventListener("timeupdate", onTime);
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("waiting", onWaiting);
      audio.removeEventListener("playing", onPlaying);
      audio.removeEventListener("error", onError);
    };
  }, [loadFile, saveProgress, feedback]);

  // Sleep timer
  useEffect(() => {
    if (!sleep || !playing) return;
    if (sleep.kind === "time" && Date.now() >= sleep.until) {
      pause();
      setSleepState(null);
    } else if (sleep.kind === "chapter" && position >= sleep.end - 0.5) {
      pause();
      setSleepState(null);
    }
  }, [sleep, position, playing, pause]);

  // Save on tab close
  useEffect(() => {
    const handler = () => saveProgress(undefined, true);
    window.addEventListener("pagehide", handler);
    return () => window.removeEventListener("pagehide", handler);
  }, [saveProgress]);

  // Lock screen / media keys
  useEffect(() => {
    if (!("mediaSession" in navigator) || !book) return;
    const artwork = book.cover_url ? [{ src: book.cover_url, sizes: "512x512", type: "image/jpeg" }] : [];
    navigator.mediaSession.metadata = new MediaMetadata({
      title: chapter?.title ?? book.title,
      artist: book.author,
      album: book.title,
      artwork,
    });
    const handlers: [MediaSessionAction, MediaSessionActionHandler][] = [
      ["play", () => void audioRef.current?.play()],
      ["pause", () => audioRef.current?.pause()],
      ["seekbackward", () => skip(-15)],
      ["seekforward", () => skip(30)],
      ["previoustrack", () => prevChapter()],
      ["nexttrack", () => nextChapter()],
      ["seekto", (details) => details.seekTime !== undefined && seek(details.seekTime)],
    ];
    for (const [action, handler] of handlers) {
      try {
        navigator.mediaSession.setActionHandler(action, handler);
      } catch {
        /* unsupported action */
      }
    }
  }, [book, chapter, skip, prevChapter, nextChapter, seek]);

  const value: PlayerApi = {
    book,
    playing,
    loading,
    position,
    duration,
    rate,
    volume,
    sleep,
    chapter,
    chapterIndex,
    play,
    toggle,
    pause,
    seek,
    skip,
    nextChapter,
    prevChapter,
    setRate,
    setVolume,
    setSleep,
    close,
  };
  return (
    <PlayerContext.Provider value={value}>
      {children}
      <audio ref={audioRef} preload="metadata" className="hidden" />
    </PlayerContext.Provider>
  );
}

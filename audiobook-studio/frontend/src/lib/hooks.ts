import { useCallback, useEffect, useRef, useState } from "react";

export function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

export function useLocalStorage<T>(key: string, initial: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? initial : (JSON.parse(raw) as T);
    } catch {
      return initial;
    }
  });
  const update = useCallback(
    (next: T) => {
      setValue(next);
      try {
        localStorage.setItem(key, JSON.stringify(next));
      } catch {
        /* storage unavailable */
      }
    },
    [key],
  );
  return [value, update];
}

let activePreview: HTMLAudioElement | null = null;

/** Plays short generated previews; only one preview plays at a time. */
export function usePreviewPlayer() {
  const [loading, setLoading] = useState<string | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const urlRef = useRef<string | null>(null);

  const stop = useCallback(() => {
    if (activePreview) {
      activePreview.pause();
      activePreview = null;
    }
    setPlaying(null);
  }, []);

  useEffect(
    () => () => {
      stop();
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    },
    [stop],
  );

  const play = useCallback(
    async (key: string, load: () => Promise<Blob>) => {
      if (playing === key) {
        stop();
        return;
      }
      stop();
      setLoading(key);
      try {
        const blob = await load();
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        const url = URL.createObjectURL(blob);
        urlRef.current = url;
        const audio = new Audio(url);
        activePreview = audio;
        audio.onended = () => setPlaying((current) => (current === key ? null : current));
        setPlaying(key);
        await audio.play();
      } finally {
        setLoading((current) => (current === key ? null : current));
      }
    },
    [playing, stop],
  );

  return { play, stop, loading, playing };
}

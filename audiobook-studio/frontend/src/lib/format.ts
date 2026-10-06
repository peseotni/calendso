export function formatDuration(seconds: number, style: "long" | "clock" = "long"): string {
  if (!Number.isFinite(seconds) || seconds < 0) seconds = 0;
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (style === "clock") {
    const mm = String(m).padStart(h ? 2 : 1, "0");
    const ss = String(s).padStart(2, "0");
    return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
  }
  if (h) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m) return `${m}m${s && m < 10 ? ` ${s}s` : ""}`;
  return `${s}s`;
}

export function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** exponent;
  return `${value >= 100 || exponent === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[exponent]}`;
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat().format(value);
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  const diff = (Date.now() - then) / 1000;
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`;
  if (diff < 86400 * 30) return `${Math.round(diff / 86400)} d ago`;
  return new Date(iso).toLocaleDateString();
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function languageName(code: string): string {
  if (!code) return "";
  try {
    const names = new Intl.DisplayNames([navigator.language || "en"], { type: "language" });
    return names.of(code) ?? code;
  } catch {
    return code;
  }
}

export const FORMAT_LABELS: Record<string, string> = {
  m4b: "M4B audiobook",
  mp3: "MP3 per chapter",
  mp3_single: "Single MP3",
  opus: "Opus per chapter",
};

const ENGINE_IDS = ["kokoro", "piper", "espeak", "openai", "edge"];

/** Split a stored chapter voice ("kokoro:af_bella:0.6+am_adam:0.4") into engine and voice. */
export function splitVoiceRef(ref: string, fallbackEngine: string): { engine: string; voice: string } {
  const index = ref.indexOf(":");
  if (index > 0 && ENGINE_IDS.includes(ref.slice(0, index))) {
    return { engine: ref.slice(0, index), voice: ref.slice(index + 1) };
  }
  return { engine: fallbackEngine, voice: ref };
}

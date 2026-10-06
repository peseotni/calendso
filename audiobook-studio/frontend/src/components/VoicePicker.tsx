import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Loader2, Play, Square } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { usePreviewPlayer } from "../lib/hooks";
import type { Voice } from "../lib/types";
import { useFeedback } from "./feedback";
import { Button, cn } from "./ui";

const SAMPLES: Record<string, string> = {
  en: "Hello! This is how your audiobook will sound. The rain had stopped, and the whole valley smelled of pine and wet stone.",
  de: "Hallo! So klingt dein Hörbuch. Der Regen hatte aufgehört, und das ganze Tal duftete nach Kiefern und nassem Stein.",
  fr: "Bonjour ! Voici comment sonnera votre livre audio. La pluie avait cessé, et toute la vallée sentait le pin et la pierre mouillée.",
  es: "¡Hola! Así sonará tu audiolibro. La lluvia había parado y todo el valle olía a pino y a piedra mojada.",
  it: "Ciao! Ecco come suonerà il tuo audiolibro. La pioggia era cessata e tutta la valle profumava di pino e di pietra bagnata.",
  pt: "Olá! É assim que o seu audiolivro vai soar. A chuva tinha parado e todo o vale cheirava a pinho e a pedra molhada.",
  nl: "Hallo! Zo klinkt je luisterboek. De regen was gestopt en de hele vallei rook naar dennen en natte steen.",
  pl: "Cześć! Tak zabrzmi twój audiobook. Deszcz ustał, a cała dolina pachniała sosną i mokrym kamieniem.",
  ru: "Привет! Так будет звучать ваша аудиокнига. Дождь прекратился, и вся долина пахла соснами и мокрым камнем.",
  ja: "こんにちは。これがあなたのオーディオブックの声です。雨はやみ、谷全体が松と濡れた石の香りに包まれていました。",
  zh: "你好！这就是你的有声书的声音。雨停了，整个山谷弥漫着松树和湿石头的气味。",
  hi: "नमस्ते! आपकी ऑडियोबुक ऐसी सुनाई देगी। बारिश थम चुकी थी और पूरी घाटी में चीड़ और गीले पत्थरों की खुशबू थी।",
};

export function sampleText(language: string | undefined | null): string {
  const code = (language || "en").toLowerCase().split("-")[0];
  return SAMPLES[code] ?? SAMPLES.en;
}

export function useEngines() {
  return useQuery({ queryKey: ["engines"], queryFn: api.engines, staleTime: 30_000 });
}

export function useVoices(engine: string | undefined) {
  return useQuery({
    queryKey: ["voices", engine],
    queryFn: () => api.voices(engine),
    enabled: Boolean(engine),
    staleTime: 60_000,
  });
}

export function groupByLanguage(voices: Voice[]): [string, Voice[]][] {
  const groups = new Map<string, Voice[]>();
  for (const voice of voices) {
    const key = voice.language_name || voice.language || "Other";
    groups.set(key, [...(groups.get(key) ?? []), voice]);
  }
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
}

export function VoicePicker({
  engine,
  voice,
  onChange,
  speed = 1,
  language,
  label = "Voice",
  className,
}: {
  engine: string;
  voice: string;
  onChange: (engine: string, voice: string) => void;
  speed?: number;
  language?: string | null;
  label?: string;
  className?: string;
}) {
  const engines = useEngines();
  const voices = useVoices(engine);
  const preview = usePreviewPlayer();
  const feedback = useFeedback();

  const engineInfo = engines.data?.find((e) => e.id === engine);
  const [baseVoice, speaker] = voice.split("#");
  const list = voices.data ?? [];
  const current = list.find((v) => v.id === baseVoice);
  const grouped = useMemo(() => groupByLanguage(list), [list]);

  const choose = (nextEngine: string) => {
    if (nextEngine === engine) return;
    api
      .voices(nextEngine)
      .then((items) => {
        const lang = (current?.language || language || "en").toLowerCase().split("-")[0];
        const match =
          items.find((v) => v.recommended && v.language.toLowerCase().startsWith(lang)) ??
          items.find((v) => v.language.toLowerCase().startsWith(lang)) ??
          items[0];
        onChange(nextEngine, match?.id ?? "");
      })
      .catch(feedback.error);
  };

  const playPreview = () =>
    preview
      .play(`${engine}:${voice}`, () =>
        api.previewVoice({ engine, voice, text: sampleText(current?.language || language), speed, language: null }),
      )
      .catch(feedback.error);

  return (
    <div className={cn("space-y-3", className)}>
      <div className="grid gap-3 sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)_auto] sm:items-end">
        <label className="block">
          <span className="field-label">Engine</span>
          <select className="input" value={engine} onChange={(e) => choose(e.target.value)}>
            {(engines.data ?? []).map((e) => (
              <option key={e.id} value={e.id} disabled={!e.ready && e.id !== engine}>
                {e.name}
                {!e.ready ? " (not set up)" : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="block min-w-0">
          <span className="field-label">{label}</span>
          <select
            className="input"
            value={baseVoice}
            onChange={(e) => onChange(engine, e.target.value)}
            disabled={voices.isLoading || !list.length}
          >
            {!current && voice && <option value={baseVoice}>Custom: {voice}</option>}
            {grouped.map(([languageName, items]) => (
              <optgroup key={languageName} label={languageName}>
                {items.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                    {v.gender ? ` · ${v.gender}` : ""}
                    {v.recommended ? " ★" : ""}
                    {v.quality && !["neural", "robotic", "online", "remote"].includes(v.quality) ? ` · ${v.quality}` : ""}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>
        <Button
          type="button"
          onClick={playPreview}
          disabled={!voice || !engineInfo?.ready}
          icon={
            preview.loading ? (
              <Loader2 className="size-4 animate-spin" />
            ) : preview.playing ? (
              <Square className="size-3.5" fill="currentColor" />
            ) : (
              <Play className="size-4" />
            )
          }
        >
          {preview.playing ? "Stop" : "Preview"}
        </Button>
      </div>
      {current && current.speakers.length > 0 && (
        <label className="block">
          <span className="field-label">Speaker</span>
          <select className="input" value={speaker ?? ""} onChange={(e) => onChange(engine, e.target.value ? `${baseVoice}#${e.target.value}` : baseVoice)}>
            <option value="">Default speaker</option>
            {current.speakers.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
      )}
      {engineInfo && !engineInfo.ready && (
        <div className="flex items-start gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-500/10 dark:text-amber-300">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <span>
            {engineInfo.name}: {engineInfo.message || "not ready"}.{" "}
            <Link to={engineInfo.id === "openai" || engineInfo.id === "edge" ? "/settings" : "/voices"} className="font-medium underline">
              Set it up
            </Link>
          </span>
        </div>
      )}
      {engineInfo?.online && engineInfo.ready && (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">This engine sends text to an online service.</p>
      )}
    </div>
  );
}

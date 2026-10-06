import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  Cloud,
  CloudDownload,
  Cpu,
  Loader2,
  Mic2,
  Play,
  RefreshCw,
  Search,
  Square,
  Trash2,
  Wand,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useFeedback } from "../components/feedback";
import { Badge, Button, Card, EmptyState, Field, IconButton, PageHeader, ProgressBar, Section, Select, Slider, Spinner, cn } from "../components/ui";
import { groupByLanguage, sampleText, useEngines, useVoices, VoicePicker } from "../components/VoicePicker";
import { api } from "../lib/api";
import { usePreviewPlayer } from "../lib/hooks";
import type { EngineInfo, Job } from "../lib/types";

function useActiveJobs() {
  return useQuery({
    queryKey: ["jobs", "active"],
    queryFn: () => api.jobs("active"),
    refetchInterval: (q) => ((q.state.data?.length ?? 0) > 0 ? 1500 : 8000),
  });
}

function DownloadProgress({ jobId, jobs }: { jobId: number | null; jobs: Job[] | undefined }) {
  const job = jobs?.find((j) => j.id === jobId);
  if (!jobId) return null;
  return (
    <div className="mt-2">
      <ProgressBar value={job?.progress ?? 0} indeterminate={!job || job.status === "queued"} />
      <div className="mt-1 truncate text-xs text-zinc-500">{job?.message || "Waiting…"}</div>
    </div>
  );
}

function EngineCard({ engine }: { engine: EngineInfo }) {
  const status = !engine.available
    ? { label: "Unavailable", color: "red" as const }
    : !engine.enabled
      ? { label: engine.id === "openai" ? "Not configured" : "Disabled", color: "gray" as const }
      : engine.ready
        ? { label: "Ready", color: "green" as const }
        : { label: "Needs download", color: "amber" as const };
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-2 font-semibold">
          {engine.online ? <Cloud className="mt-1 size-4 shrink-0 text-sky-500" /> : <Cpu className="mt-1 size-4 shrink-0 text-brand-500" />}
          {engine.name}
        </div>
        <Badge color={status.color} className="shrink-0">
          {status.label}
        </Badge>
      </div>
      <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">{engine.description}</p>
      {engine.message && !engine.ready && <p className="mt-2 text-xs text-amber-600 dark:text-amber-400">{engine.message}</p>}
      {(engine.id === "openai" || engine.id === "edge") && (
        <Link to="/settings#engines" className="mt-2 inline-flex text-xs font-medium text-brand-600 hover:underline dark:text-brand-400">
          Configure in settings →
        </Link>
      )}
    </Card>
  );
}

function KokoroModels() {
  const feedback = useFeedback();
  const queryClient = useQueryClient();
  const jobs = useActiveJobs();
  const models = useQuery({
    queryKey: ["models"],
    queryFn: api.models,
    refetchInterval: (q) => (q.state.data?.kokoro.some((m) => m.job_id) ? 2000 : false),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["models"] });
    void queryClient.invalidateQueries({ queryKey: ["engines"] });
    void queryClient.invalidateQueries({ queryKey: ["voices"] });
    void queryClient.invalidateQueries({ queryKey: ["jobs"] });
  };
  const download = useMutation({ mutationFn: (id: string) => api.downloadModel("kokoro", id), onSuccess: refresh, onError: feedback.error });
  const remove = useMutation({ mutationFn: (id: string) => api.deleteModel("kokoro", id), onSuccess: refresh, onError: feedback.error });

  return (
    <Section title="Kokoro neural model" description="High quality voices for English (US & UK), Spanish, French, Italian, Portuguese, Hindi, Japanese and Chinese. Runs on CPU.">
      <div className="grid gap-3 md:grid-cols-2">
        {models.data?.kokoro.map((model) => (
          <div key={model.id} className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="font-medium">{model.label}</div>
                <div className="text-xs text-zinc-500">{model.size_mb} MB download</div>
              </div>
              {model.installed ? (
                <div className="flex items-center gap-1">
                  <Badge color="green" icon={<CheckCircle2 className="size-3" />}>
                    Installed
                  </Badge>
                  <IconButton label="Delete model" onClick={() => remove.mutate(model.id)}>
                    <Trash2 className="size-4" />
                  </IconButton>
                </div>
              ) : model.job_id ? (
                <Badge color="brand" icon={<Loader2 className="size-3 animate-spin" />}>
                  Downloading
                </Badge>
              ) : (
                <Button size="sm" variant="primary" icon={<CloudDownload className="size-4" />} onClick={() => download.mutate(model.id)}>
                  Download
                </Button>
              )}
            </div>
            <DownloadProgress jobId={model.job_id} jobs={jobs.data} />
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-400">
        Offline install: place <code>kokoro-v1.0.onnx</code> and <code>voices-v1.0.bin</code> in the <code>models/kokoro</code> folder.
      </p>
    </Section>
  );
}

function PiperCatalog() {
  const feedback = useFeedback();
  const queryClient = useQueryClient();
  const jobs = useActiveJobs();
  const [search, setSearch] = useState("");
  const [language, setLanguage] = useState("");
  const [showAll, setShowAll] = useState(false);
  const catalog = useQuery({
    queryKey: ["piper-catalog"],
    queryFn: () => api.piperCatalog(),
    refetchInterval: (q) => (q.state.data?.some((v) => v.job_id) ? 2000 : false),
    retry: false,
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["piper-catalog"] });
    void queryClient.invalidateQueries({ queryKey: ["engines"] });
    void queryClient.invalidateQueries({ queryKey: ["voices"] });
    void queryClient.invalidateQueries({ queryKey: ["jobs"] });
  };
  const download = useMutation({ mutationFn: (id: string) => api.downloadModel("piper", id), onSuccess: refresh, onError: feedback.error });
  const remove = useMutation({ mutationFn: (id: string) => api.deleteModel("piper", id), onSuccess: refresh, onError: feedback.error });

  const languages = useMemo(() => {
    const map = new Map<string, string>();
    catalog.data?.forEach((v) => map.set(v.language, v.language_name));
    return [...map.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [catalog.data]);

  const browserLanguage = (navigator.language || "en").split("-")[0];
  const filtered = (catalog.data ?? [])
    .filter((v) => (language ? v.language === language : showAll || v.installed || v.language.startsWith(browserLanguage) || v.language.startsWith("en")))
    .filter((v) => !search || `${v.id} ${v.language_name}`.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => Number(b.installed) - Number(a.installed) || Number(b.recommended) - Number(a.recommended) || a.id.localeCompare(b.id));

  return (
    <Section
      title="Piper voices"
      description="Small, fast voices (15–110 MB each) for more than 40 languages. Download only what you need."
      actions={
        <Button size="sm" variant="ghost" icon={<RefreshCw className="size-4" />} onClick={() => api.piperCatalog(true).then(refresh, feedback.error)}>
          Refresh list
        </Button>
      }
    >
      {catalog.isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : catalog.isError ? (
        <div className="rounded-lg bg-amber-50 p-4 text-sm text-amber-800 dark:bg-amber-500/10 dark:text-amber-300">
          {(catalog.error as Error).message}. Piper voices can also be installed manually by copying <code>*.onnx</code> and{" "}
          <code>*.onnx.json</code> files into <code>models/piper</code>.
        </div>
      ) : (
        <>
          <div className="mb-3 flex flex-wrap gap-2">
            <div className="relative min-w-48 flex-1">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-zinc-400" />
              <input className="input pl-9" placeholder="Search voices" value={search} onChange={(e) => setSearch(e.target.value)} />
            </div>
            <Select
              className="w-auto"
              value={language}
              onChange={setLanguage}
              options={[{ value: "", label: showAll ? "All languages" : "Suggested languages" }, ...languages.map(([code, name]) => ({ value: code, label: name || code }))]}
            />
            {!language && (
              <Button variant="ghost" onClick={() => setShowAll(!showAll)}>
                {showAll ? "Show suggested" : "Show all"}
              </Button>
            )}
          </div>
          <div className="scrollbar-thin max-h-[32rem] divide-y divide-zinc-100 overflow-y-auto rounded-xl border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
            {filtered.map((voice) => (
              <div key={voice.id} className="px-4 py-2.5">
                <div className="flex items-center gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
                      {voice.name}
                      {voice.recommended && <Badge color="brand">Recommended</Badge>}
                      <Badge>{voice.quality}</Badge>
                      {voice.speakers > 1 && <Badge color="blue">{voice.speakers} speakers</Badge>}
                    </div>
                    <div className="text-xs text-zinc-500">
                      {voice.language_name} · {voice.size_mb} MB · <span className="font-mono">{voice.id}</span>
                    </div>
                  </div>
                  {voice.installed ? (
                    <div className="flex items-center gap-1">
                      <Badge color="green" icon={<CheckCircle2 className="size-3" />}>
                        Installed
                      </Badge>
                      <IconButton label="Delete voice" onClick={() => remove.mutate(voice.id)}>
                        <Trash2 className="size-4" />
                      </IconButton>
                    </div>
                  ) : voice.job_id ? (
                    <Badge color="brand" icon={<Loader2 className="size-3 animate-spin" />}>
                      Downloading
                    </Badge>
                  ) : (
                    <Button size="sm" icon={<CloudDownload className="size-4" />} onClick={() => download.mutate(voice.id)}>
                      Get
                    </Button>
                  )}
                </div>
                <DownloadProgress jobId={voice.job_id} jobs={jobs.data} />
              </div>
            ))}
            {!filtered.length && <div className="p-6 text-center text-sm text-zinc-500">No voices match.</div>}
          </div>
        </>
      )}
    </Section>
  );
}

function VoiceTester() {
  const feedback = useFeedback();
  const queryClient = useQueryClient();
  const engines = useEngines();
  const firstReady = engines.data?.find((e) => e.ready && !e.online)?.id ?? "espeak";
  const [engine, setEngine] = useState<string | null>(null);
  const [voice, setVoice] = useState("");
  const [speed, setSpeed] = useState(1);
  const [text, setText] = useState(sampleText("en"));
  const preview = usePreviewPlayer();
  const current = engine ?? firstReady;
  const voices = useVoices(current);

  useEffect(() => {
    const list = voices.data ?? [];
    if (list.length && !list.some((v) => v.id === voice.split("#")[0])) {
      const english = list.filter((v) => v.language.toLowerCase().startsWith("en"));
      const us = english.filter((v) => v.language === "en-US");
      setVoice((us.find((v) => v.recommended) ?? english.find((v) => v.recommended) ?? us[0] ?? english[0] ?? list[0]).id);
    }
  }, [voices.data, voice]);

  const makeDefault = useMutation({
    mutationFn: () => api.updateSettings({ render_defaults: { engine: current, voice, speed } }),
    onSuccess: () => {
      feedback.success("Default voice updated");
      void queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: feedback.error,
  });

  return (
    <Section title="Voice tester" description="Try any voice with your own text." actions={<Mic2 className="size-5 text-brand-500" />}>
      <VoicePicker
        engine={current}
        voice={voice}
        speed={speed}
        onChange={(e, v) => {
          setEngine(e);
          setVoice(v);
        }}
      />
      <div className="mt-4 grid gap-4 md:grid-cols-[1fr_14rem]">
        <Field label="Text">
          <textarea className="input min-h-28" value={text} onChange={(e) => setText(e.target.value)} />
        </Field>
        <div className="space-y-4">
          <Slider label="Speed" value={speed} min={0.5} max={2} step={0.05} onChange={setSpeed} format={(v) => `${v.toFixed(2)}×`} />
          <Button
            className="w-full"
            variant="primary"
            disabled={!voice || !text.trim()}
            icon={preview.loading ? <Loader2 className="size-4 animate-spin" /> : preview.playing ? <Square className="size-3.5" fill="currentColor" /> : <Play className="size-4" />}
            onClick={() => preview.play("tester", () => api.previewVoice({ engine: current, voice, text, speed })).catch(feedback.error)}
          >
            {preview.playing ? "Stop" : "Speak"}
          </Button>
          <Button className="w-full" disabled={!voice} onClick={() => makeDefault.mutate()} loading={makeDefault.isPending}>
            Use as default voice
          </Button>
        </div>
      </div>
    </Section>
  );
}

function KokoroBlender() {
  const feedback = useFeedback();
  const queryClient = useQueryClient();
  const voices = useVoices("kokoro");
  const engines = useEngines();
  const ready = engines.data?.find((e) => e.id === "kokoro")?.ready;
  const [a, setA] = useState("af_heart");
  const [b, setB] = useState("af_bella");
  const [mix, setMix] = useState(0.5);
  const preview = usePreviewPlayer();
  if (!ready) return null;
  const blend = `${a}:${mix.toFixed(2)}+${b}:${(1 - mix).toFixed(2)}`;
  const options = (voices.data ?? []).map((v) => ({ value: v.id, label: `${v.name} (${v.language_name})` }));
  return (
    <Section title="Voice blender" description="Mix two Kokoro voices into a unique narrator." actions={<Wand className="size-5 text-brand-500" />}>
      <div className="grid gap-4 md:grid-cols-[1fr_1fr]">
        <Field label="Voice A">
          <Select value={a} onChange={setA} options={options} />
        </Field>
        <Field label="Voice B">
          <Select value={b} onChange={setB} options={options} />
        </Field>
      </div>
      <div className="mt-4">
        <Slider label="Mix" value={mix} min={0} max={1} step={0.05} onChange={setMix} format={(v) => `${Math.round(v * 100)}% A · ${Math.round((1 - v) * 100)}% B`} />
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button
          icon={preview.loading ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />}
          onClick={() => preview.play(blend, () => api.previewVoice({ engine: "kokoro", voice: blend, text: sampleText(voices.data?.find((v) => v.id === a)?.language) })).catch(feedback.error)}
        >
          Preview blend
        </Button>
        <Button
          onClick={() =>
            api.updateSettings({ render_defaults: { engine: "kokoro", voice: blend } }).then(() => {
              feedback.success("Blend saved as default voice");
              void queryClient.invalidateQueries({ queryKey: ["settings"] });
            }, feedback.error)
          }
        >
          Use as default
        </Button>
        <code className="rounded bg-zinc-100 px-2 py-1 text-xs dark:bg-zinc-800">{blend}</code>
      </div>
    </Section>
  );
}

function VoiceGallery() {
  const feedback = useFeedback();
  const preview = usePreviewPlayer();
  const engines = useEngines();
  const [engine, setEngine] = useState("all");
  const voices = useQuery({ queryKey: ["voices", "all-installed"], queryFn: () => api.voices() });
  const list = (voices.data ?? []).filter((v) => (engine === "all" ? v.engine !== "espeak" && v.engine !== "edge" : v.engine === engine));
  const groups = groupByLanguage(list);
  return (
    <Section
      title="Installed voices"
      description="Click a voice to hear it."
      actions={
        <Select
          className="w-auto"
          value={engine}
          onChange={setEngine}
          options={[{ value: "all", label: "Local neural voices" }, ...(engines.data ?? []).filter((e) => e.ready).map((e) => ({ value: e.id, label: e.name }))]}
        />
      }
    >
      {voices.isLoading ? (
        <Spinner />
      ) : !list.length ? (
        <EmptyState icon={<Mic2 className="size-5" />} title="No voices yet" description="Download Kokoro or Piper voices above." />
      ) : (
        <div className="space-y-5">
          {groups.map(([languageName, items]) => (
            <div key={languageName}>
              <div className="mb-2 text-xs font-semibold tracking-wide text-zinc-500 uppercase">{languageName}</div>
              <div className="flex flex-wrap gap-2">
                {items.map((v) => {
                  const key = `${v.engine}:${v.id}`;
                  return (
                    <button
                      key={key}
                      onClick={() => preview.play(key, () => api.previewVoice({ engine: v.engine, voice: v.id, text: sampleText(v.language) })).catch(feedback.error)}
                      className={cn(
                        "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition",
                        preview.playing === key
                          ? "border-brand-500 bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-300"
                          : "border-zinc-200 hover:border-brand-400 dark:border-zinc-700",
                      )}
                    >
                      {preview.loading === key ? (
                        <Loader2 className="size-3.5 animate-spin" />
                      ) : preview.playing === key ? (
                        <Square className="size-3" fill="currentColor" />
                      ) : (
                        <Play className="size-3.5" />
                      )}
                      {v.name}
                      {v.gender && <span className="text-xs text-zinc-400">{v.gender === "female" ? "♀" : "♂"}</span>}
                      {v.recommended && <span className="text-xs text-amber-500">★</span>}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

export default function Voices() {
  const engines = useEngines();
  return (
    <div className="animate-fade-in space-y-6">
      <PageHeader
        title="Voices"
        icon={<Mic2 className="size-5" />}
        description="Manage text-to-speech engines, download voice models and audition narrators."
      />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {engines.data?.map((engine) => (
          <EngineCard key={engine.id} engine={engine} />
        ))}
      </div>
      <KokoroModels />
      <VoiceTester />
      <KokoroBlender />
      <VoiceGallery />
      <PiperCatalog />
    </div>
  );
}

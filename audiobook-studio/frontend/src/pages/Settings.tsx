import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Copy,
  Cpu,
  FolderSearch,
  FolderTree,
  Globe,
  HardDrive,
  Inbox,
  KeyRound,
  RefreshCw,
  Rss,
  Settings as SettingsIcon,
  Sparkles,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useFeedback } from "../components/feedback";
import { RenderSettingsForm } from "../components/RenderSettingsForm";
import { SaveBar } from "../components/SaveBar";
import { Badge, Button, Field, LoadingBlock, Modal, PageHeader, ProgressBar, Section, Select, Switch } from "../components/ui";
import { api } from "../lib/api";
import { formatBytes } from "../lib/format";
import { useDebounced } from "../lib/hooks";
import type { AppSettings } from "../lib/types";
import { ScanModal } from "./Library";

function TemplatePreview({ template }: { template: string }) {
  const debounced = useDebounced(template, 400);
  const preview = useQuery({
    queryKey: ["template-preview", debounced],
    queryFn: () => api.templatePreview(debounced),
    enabled: Boolean(debounced.trim()),
  });
  return (
    <div className="mt-3 rounded-lg bg-zinc-50 p-3 font-mono text-xs text-zinc-600 dark:bg-zinc-800/60 dark:text-zinc-300">
      {(preview.data?.examples ?? []).map((example, i) => (
        <div key={i} className="truncate">
          📁 {example}/
        </div>
      ))}
    </div>
  );
}

function OrganizeModal({ open, onClose, template }: { open: boolean; onClose: () => void; template: string }) {
  const feedback = useFeedback();
  const queryClient = useQueryClient();
  const plan = useQuery({ queryKey: ["organize-plan", template], queryFn: () => api.organizePreview(template), enabled: open });
  const apply = useMutation({
    mutationFn: () => api.organize(template),
    onSuccess: () => {
      feedback.success("Reorganising your library in the background");
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["settings"] });
      onClose();
    },
    onError: feedback.error,
  });
  const moves = plan.data?.moves ?? [];
  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title="Reorganise library folders"
      description="Files are moved so that every book lives in the folder given by the template. Tags are not changed."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!moves.length} loading={apply.isPending} onClick={() => apply.mutate()}>
            Move {moves.length} books
          </Button>
        </>
      }
    >
      {plan.isLoading ? (
        <LoadingBlock />
      ) : !moves.length ? (
        <p className="text-sm text-zinc-500">Everything is already organised. 🎉</p>
      ) : (
        <div className="scrollbar-thin max-h-96 space-y-2 overflow-y-auto font-mono text-xs">
          {moves.map((move) => (
            <div key={move.book_id} className="rounded-lg border border-zinc-200 p-2 dark:border-zinc-800">
              <div className="mb-1 font-sans text-sm font-medium">{move.title}</div>
              <div className="text-zinc-500 line-through">{move.from}</div>
              <div className="text-emerald-700 dark:text-emerald-400">{move.to}</div>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}

function SecuritySection({ settings }: { settings: AppSettings }) {
  const feedback = useFeedback();
  const queryClient = useQueryClient();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const change = useMutation({
    mutationFn: (value: string) => api.changePassword(current, value),
    onSuccess: (result) => {
      feedback.success(result.enabled ? "Password saved – you'll need it on other devices." : "Password removed");
      setCurrent("");
      setNext("");
      void queryClient.invalidateQueries({ queryKey: ["settings"] });
      void queryClient.invalidateQueries({ queryKey: ["auth"] });
    },
    onError: feedback.error,
  });
  return (
    <Section
      title="Security"
      description="Protect the web interface with a password. Recommended if the server is reachable from outside your home network."
      actions={<KeyRound className="size-5 text-brand-500" />}
    >
      {settings.password_managed_by_env ? (
        <p className="text-sm text-zinc-500">The password is set with the STUDIO_PASSWORD environment variable.</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
          {settings.password_set && (
            <Field label="Current password">
              <input type="password" className="input" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" />
            </Field>
          )}
          <Field label={settings.password_set ? "New password" : "Password"}>
            <input type="password" className="input" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" />
          </Field>
          <div className="flex gap-2">
            <Button variant="primary" disabled={next.length < 4} loading={change.isPending} onClick={() => change.mutate(next)}>
              {settings.password_set ? "Change" : "Set password"}
            </Button>
            {settings.password_set && (
              <Button variant="ghost" onClick={() => change.mutate("")}>
                Remove
              </Button>
            )}
          </div>
        </div>
      )}
    </Section>
  );
}

function FeedsSection() {
  const feedback = useFeedback();
  const queryClient = useQueryClient();
  const feeds = useQuery({ queryKey: ["feeds"], queryFn: api.feeds });
  const copy = (value: string) => {
    void navigator.clipboard?.writeText(value);
    feedback.success("Copied to clipboard");
  };
  return (
    <Section
      title="Podcast feeds"
      description="Subscribe in any podcast app (AntennaPod, Pocket Casts, Apple Podcasts…) to listen on your phone. Every book also has its own feed."
      actions={<Rss className="size-5 text-brand-500" />}
    >
      {feeds.data && (
        <div className="space-y-3">
          <div className="flex gap-2">
            <input readOnly className="input font-mono text-xs" value={feeds.data.library} />
            <Button icon={<Copy className="size-4" />} onClick={() => copy(feeds.data!.library)}>
              Copy
            </Button>
          </div>
          {feeds.data.token_required && (
            <Button
              size="sm"
              variant="ghost"
              icon={<RefreshCw className="size-4" />}
              onClick={() =>
                api.regenerateFeedToken().then(() => {
                  void queryClient.invalidateQueries({ queryKey: ["feeds"] });
                  feedback.success("New feed token created – old feed links stop working.");
                }, feedback.error)
              }
            >
              Regenerate secret token
            </Button>
          )}
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            The library feed contains single-file books (M4B, single MP3). The link only works on your network unless you expose the server.
          </p>
        </div>
      )}
    </Section>
  );
}

function SystemSection() {
  const system = useQuery({ queryKey: ["system"], queryFn: api.system });
  if (!system.data) return null;
  const s = system.data;
  const disk = s.disk.library;
  return (
    <Section title="System" actions={<Cpu className="size-5 text-brand-500" />}>
      <dl className="grid grid-cols-[10rem_1fr] gap-y-2 text-sm">
        <dt className="text-zinc-500">Version</dt>
        <dd>{s.version}</dd>
        <dt className="text-zinc-500">FFmpeg</dt>
        <dd>{s.ffmpeg}</dd>
        <dt className="text-zinc-500">OCR (Tesseract)</dt>
        <dd>{s.ocr_available ? <Badge color="green">available</Badge> : <Badge>not installed</Badge>}</dd>
        <dt className="text-zinc-500">CPU cores</dt>
        <dd>
          {s.cpu_count} · {s.render_workers} narration worker{s.render_workers === 1 ? "" : "s"}
        </dd>
        <dt className="text-zinc-500">Python</dt>
        <dd>{s.python}</dd>
        {Object.entries(s.paths).map(([key, path]) => (
          <div key={key} className="contents">
            <dt className="text-zinc-500 capitalize">{key} folder</dt>
            <dd className="font-mono text-xs break-all">{path}</dd>
          </div>
        ))}
      </dl>
      {disk && disk.total > 0 && (
        <div className="mt-4">
          <div className="mb-1 flex items-center justify-between text-xs text-zinc-500">
            <span className="inline-flex items-center gap-1">
              <HardDrive className="size-3.5" /> Library disk
            </span>
            <span>
              {formatBytes(disk.free)} free of {formatBytes(disk.total)}
            </span>
          </div>
          <ProgressBar value={disk.used / disk.total} color={disk.free / disk.total < 0.1 ? "red" : "brand"} />
        </div>
      )}
    </Section>
  );
}

export default function SettingsPage() {
  const feedback = useFeedback();
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const templates = useQuery({ queryKey: ["templates"], queryFn: api.templates });
  const system = useQuery({ queryKey: ["system"], queryFn: api.system });
  const [draft, setDraft] = useState<AppSettings | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [organizeOpen, setOrganizeOpen] = useState(false);
  const [scanOpen, setScanOpen] = useState(false);

  useEffect(() => {
    if (settings.data) setDraft(settings.data);
  }, [settings.data]);

  useEffect(() => {
    if (window.location.hash) {
      document.getElementById(window.location.hash.slice(1))?.scrollIntoView({ behavior: "smooth" });
    }
  }, [draft === null]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    mutationFn: () => api.updateSettings({ ...draft, ...(apiKey ? { openai_api_key: apiKey } : {}) }),
    onSuccess: (updated) => {
      queryClient.setQueryData(["settings"], updated);
      setApiKey("");
      feedback.success("Settings saved");
      void queryClient.invalidateQueries({ queryKey: ["engines"] });
      void queryClient.invalidateQueries({ queryKey: ["voices"] });
      void queryClient.invalidateQueries({ queryKey: ["templates"] });
    },
    onError: feedback.error,
  });

  if (!draft || !settings.data) return <LoadingBlock />;
  const dirty = JSON.stringify(draft) !== JSON.stringify(settings.data) || Boolean(apiKey);
  const set = (patch: Partial<AppSettings>) => setDraft({ ...draft, ...patch });

  return (
    <div className="mx-auto max-w-4xl animate-fade-in space-y-6">
      <PageHeader title="Settings" icon={<SettingsIcon className="size-5" />} description="Defaults, library organisation, engines and security." />

      <div>
        <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold">
          <Sparkles className="size-5 text-brand-500" /> Defaults for new projects
        </h2>
        <RenderSettingsForm value={draft.render_defaults} onChange={(patch) => set({ render_defaults: { ...draft.render_defaults, ...patch } })} />
      </div>

      <Section
        title="Library organisation"
        description="How finished and imported audiobooks are filed on disk. Works great with Audiobookshelf, Plex or Jellyfin pointed at the same folder."
        actions={<FolderTree className="size-5 text-brand-500" />}
      >
        <Field label="Folder template" hint="Fields: {author} {author_sort} {title} {subtitle} {series} {series_index} {genre} {year} {narrator} {language} {publisher} {first_letter}. [ … ] is skipped when a field inside is empty; {series_index:02} pads numbers.">
          <input className="input font-mono text-sm" value={draft.library_template} onChange={(e) => set({ library_template: e.target.value })} />
        </Field>
        <div className="mt-2 flex flex-wrap gap-2">
          {templates.data?.presets.map((preset) => (
            <button
              key={preset.id}
              onClick={() => set({ library_template: preset.template })}
              className="rounded-full border border-zinc-300 px-3 py-1 text-xs hover:border-brand-500 hover:text-brand-700 dark:border-zinc-700 dark:hover:text-brand-300"
            >
              {preset.label}
            </button>
          ))}
        </div>
        <TemplatePreview template={draft.library_template} />
        <div className="mt-5 space-y-4">
          <Switch checked={draft.auto_organize} onChange={(auto_organize) => set({ auto_organize })} label="Move files when metadata changes" description="Editing author, title or series renames the folder." />
          <Switch checked={draft.write_sidecars} onChange={(write_sidecars) => set({ write_sidecars })} label="Write sidecar files" description="cover.jpg, desc.txt, reader.txt and metadata.json next to the audio for other apps." />
          <Switch
            checked={draft.keep_workspace_audio}
            onChange={(keep_workspace_audio) => set({ keep_workspace_audio })}
            label="Keep rendered chapters after narration"
            description="Lets you fix a chapter and update the book without re-narrating everything. Uses extra disk space."
          />
        </div>
        <div className="mt-5 flex flex-wrap gap-2">
          <Button icon={<FolderTree className="size-4" />} onClick={() => setOrganizeOpen(true)}>
            Reorganise existing books…
          </Button>
          <Button icon={<FolderSearch className="size-4" />} onClick={() => setScanOpen(true)}>
            Import existing audiobooks…
          </Button>
        </div>
      </Section>

      <Section title="Watch folder" description="Drop ebooks into the inbox folder (e.g. from your computer via a network share) and they are imported automatically." actions={<Inbox className="size-5 text-brand-500" />}>
        <div className="mb-4 rounded-lg bg-zinc-50 px-3 py-2 font-mono text-xs dark:bg-zinc-800/60">{system.data?.paths.inbox ?? "…"}</div>
        <div className="space-y-4">
          <Switch checked={draft.inbox_enabled} onChange={(inbox_enabled) => set({ inbox_enabled })} label="Watch the inbox folder" />
          <Switch checked={draft.inbox_auto_render} onChange={(inbox_auto_render) => set({ inbox_auto_render })} label="Narrate automatically" description="New books are rendered with the default voice right away." />
          <Field label="Check every (seconds)">
            <input type="number" min={5} max={3600} className="input w-32" value={draft.inbox_interval} onChange={(e) => set({ inbox_interval: Number(e.target.value) })} />
          </Field>
        </div>
      </Section>

      <div id="engines">
        <Section title="Engines" description="Optional engines and model variants." actions={<Cpu className="size-5 text-brand-500" />}>
          <div className="space-y-5">
            <Field label="Kokoro model variant" hint="Used when several variants are installed.">
              <Select
                value={draft.kokoro_variant}
                onChange={(kokoro_variant) => set({ kokoro_variant })}
                options={[
                  { value: "kokoro-v1.0", label: "Full precision (best quality)" },
                  { value: "kokoro-v1.0-int8", label: "int8 quantized (smaller)" },
                ]}
              />
            </Field>
            <Switch
              checked={draft.edge_enabled}
              onChange={(edge_enabled) => set({ edge_enabled })}
              label="Microsoft Edge online voices"
              description="Free online voices from Microsoft's read-aloud service. Text is sent to Microsoft; needs internet."
            />
            <div className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
              <div className="mb-1 font-medium">OpenAI-compatible speech API</div>
              <p className="mb-4 text-xs text-zinc-500 dark:text-zinc-400">
                Point to OpenAI or a self-hosted server such as Kokoro-FastAPI on a GPU machine, e.g. <code>http://gpu-box:8880/v1</code>.
              </p>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Base URL">
                  <input className="input" placeholder="https://api.openai.com/v1" value={draft.openai_base_url} onChange={(e) => set({ openai_base_url: e.target.value })} />
                </Field>
                <Field label="API key" hint={settings.data.openai_api_key_set ? "A key is saved. Enter a new one to replace it." : "Optional for local servers."}>
                  <input type="password" className="input" placeholder={settings.data.openai_api_key_set ? "••••••••" : ""} value={apiKey} onChange={(e) => setApiKey(e.target.value)} autoComplete="off" />
                </Field>
                <Field label="Model">
                  <input className="input" value={draft.openai_model} onChange={(e) => set({ openai_model: e.target.value })} />
                </Field>
                <Field label="Voices" hint="Comma separated; leave empty to auto-detect.">
                  <input className="input" placeholder="alloy, nova, af_heart" value={draft.openai_voices} onChange={(e) => set({ openai_voices: e.target.value })} />
                </Field>
              </div>
            </div>
          </div>
        </Section>
      </div>

      <Section title="Metadata" actions={<Globe className="size-5 text-brand-500" />}>
        <Switch
          checked={draft.online_metadata}
          onChange={(online_metadata) => set({ online_metadata })}
          label="Online metadata lookup"
          description="Search Open Library and Google Books for descriptions, genres and covers."
        />
      </Section>

      <FeedsSection />
      <SecuritySection settings={settings.data} />
      <SystemSection />

      <SaveBar visible={dirty} saving={save.isPending} onSave={() => save.mutate()} onDiscard={() => (setDraft(settings.data!), setApiKey(""))} />
      <OrganizeModal open={organizeOpen} onClose={() => setOrganizeOpen(false)} template={draft.library_template} />
      <ScanModal open={scanOpen} onClose={() => setScanOpen(false)} />
    </div>
  );
}

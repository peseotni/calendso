import { MessagesSquare, SlidersHorizontal, Sparkles, Volume2 } from "lucide-react";
import { FORMAT_LABELS } from "../lib/format";
import type { CleanupOptions, OutputFormat, RenderSettings } from "../lib/types";
import { Field, Section, Segmented, Select, Slider, Switch } from "./ui";
import { VoicePicker } from "./VoicePicker";

const BITRATES = ["32k", "48k", "64k", "96k", "128k"];

const CLEANUP: { key: keyof CleanupOptions; label: string; description: string }[] = [
  { key: "remove_footnote_markers", label: "Remove footnote markers", description: "Drops [12], ¹² and * references." },
  { key: "remove_urls", label: "Skip web addresses", description: "URLs and e-mail addresses are not read aloud." },
  { key: "expand_abbreviations", label: "Expand abbreviations", description: "Mr. → Mister, Dr. → Doctor, e.g. → for example (English)." },
  { key: "normalize_punctuation", label: "Tidy punctuation", description: "Dashes become pauses, repeated ?!! are reduced, stray symbols removed." },
  { key: "remove_bracketed_text", label: "Skip text in [brackets]", description: "Useful for editorial notes and citations." },
  { key: "skip_all_caps_headers", label: "Skip ALL-CAPS lines", description: "Drops short upper-case lines such as repeated headers." },
];

export function RenderSettingsForm({
  value,
  onChange,
  language,
}: {
  value: RenderSettings;
  onChange: (patch: Partial<RenderSettings>) => void;
  language?: string;
}) {
  return (
    <div className="space-y-6">
      <Section title="Narrator" description="The main voice that reads your book." actions={<Sparkles className="size-5 text-brand-500" />}>
        <VoicePicker
          engine={value.engine}
          voice={value.voice}
          speed={value.speed}
          language={value.language || language}
          onChange={(engine, voice) => onChange({ engine, voice })}
        />
        <div className="mt-5 grid gap-5 sm:grid-cols-2">
          <Slider label="Speed" value={value.speed} min={0.5} max={2} step={0.05} onChange={(speed) => onChange({ speed })} format={(v) => `${v.toFixed(2)}×`} />
          <Field label="Pronunciation language" hint="Leave empty to use the voice's language.">
            <input
              className="input"
              placeholder={language || "auto"}
              value={value.language ?? ""}
              onChange={(e) => onChange({ language: e.target.value.trim() || null })}
            />
          </Field>
        </div>
      </Section>

      <Section
        title="Dialogue voice"
        description="Read text in quotation marks with a second voice – great for fiction."
        actions={<MessagesSquare className="size-5 text-brand-500" />}
      >
        <Switch
          checked={value.dialogue_enabled}
          onChange={(dialogue_enabled) =>
            onChange({
              dialogue_enabled,
              dialogue_engine: value.dialogue_engine ?? value.engine,
              dialogue_voice: value.dialogue_voice ?? value.voice,
            })
          }
          label="Use a separate voice for dialogue"
        />
        {value.dialogue_enabled && (
          <div className="mt-4">
            <VoicePicker
              label="Dialogue voice"
              engine={value.dialogue_engine ?? value.engine}
              voice={value.dialogue_voice ?? value.voice}
              speed={value.speed}
              language={value.language || language}
              onChange={(engine, voice) => onChange({ dialogue_engine: engine, dialogue_voice: voice })}
            />
          </div>
        )}
      </Section>

      <Section title="Pacing" description="Pauses inserted between sentences, paragraphs, scene breaks and chapters." actions={<SlidersHorizontal className="size-5 text-brand-500" />}>
        <div className="grid gap-5 sm:grid-cols-2">
          <Slider label="Between sentences" value={value.sentence_pause} min={0} max={1.5} step={0.05} onChange={(sentence_pause) => onChange({ sentence_pause })} format={(v) => `${v.toFixed(2)} s`} />
          <Slider label="Between paragraphs" value={value.paragraph_pause} min={0} max={3} step={0.1} onChange={(paragraph_pause) => onChange({ paragraph_pause })} format={(v) => `${v.toFixed(1)} s`} />
          <Slider label="Scene breaks (* * *)" value={value.section_pause} min={0} max={5} step={0.1} onChange={(section_pause) => onChange({ section_pause })} format={(v) => `${v.toFixed(1)} s`} />
          <Slider label="End of chapter" value={value.chapter_pause} min={0} max={6} step={0.1} onChange={(chapter_pause) => onChange({ chapter_pause })} format={(v) => `${v.toFixed(1)} s`} />
        </div>
        <div className="mt-5">
          <Switch
            checked={value.announce_chapters}
            onChange={(announce_chapters) => onChange({ announce_chapters })}
            label="Announce chapter titles"
            description="Reads the chapter title first unless the text already starts with its heading."
          />
        </div>
      </Section>

      <Section title="Audio output" actions={<Volume2 className="size-5 text-brand-500" />}>
        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="Format">
            <Segmented<OutputFormat>
              value={value.output_format}
              onChange={(output_format) => onChange({ output_format })}
              options={(Object.keys(FORMAT_LABELS) as OutputFormat[]).map((f) => ({ value: f, label: f === "mp3_single" ? "MP3 (1 file)" : f.toUpperCase(), title: FORMAT_LABELS[f] }))}
            />
            <p className="mt-1.5 text-xs text-zinc-500 dark:text-zinc-400">
              {value.output_format === "m4b" && "One file with chapter markers and cover – the standard audiobook format."}
              {value.output_format === "mp3" && "One MP3 per chapter – plays everywhere."}
              {value.output_format === "mp3_single" && "One MP3 with embedded chapter markers."}
              {value.output_format === "opus" && "One Opus file per chapter – smallest files at great quality."}
            </p>
          </Field>
          <Field label="Bitrate" hint="64k is plenty for a single voice.">
            <Select value={value.bitrate} onChange={(bitrate) => onChange({ bitrate })} options={BITRATES.map((b) => ({ value: b, label: `${b}bps` }))} />
          </Field>
        </div>
        <div className="mt-5">
          <Switch
            checked={value.normalize}
            onChange={(normalize) => onChange({ normalize })}
            label="Normalize loudness"
            description="EBU R128 loudness normalisation (−18 LUFS) for an even listening volume."
          />
        </div>
      </Section>

      <Section title="Text clean-up" description="Applied while narrating – your text is not modified.">
        <div className="grid gap-4 sm:grid-cols-2">
          {CLEANUP.map((option) => (
            <Switch
              key={option.key}
              checked={value.cleanup[option.key]}
              onChange={(checked) => onChange({ cleanup: { ...value.cleanup, [option.key]: checked } })}
              label={option.label}
              description={option.description}
            />
          ))}
        </div>
      </Section>
    </div>
  );
}

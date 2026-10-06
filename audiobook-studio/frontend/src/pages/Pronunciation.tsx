import { useQueryClient } from "@tanstack/react-query";
import { Download, SpellCheck, Upload } from "lucide-react";
import { useRef } from "react";
import { useFeedback } from "../components/feedback";
import { RuleTester, RulesTable } from "../components/RulesTable";
import { Button, PageHeader } from "../components/ui";
import { api } from "../lib/api";
import type { LexiconRule } from "../lib/types";

export default function Pronunciation() {
  const feedback = useFeedback();
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);

  const exportRules = async () => {
    try {
      const data = await api.exportLexicon();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "pronunciation-rules.json";
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      feedback.error(error);
    }
  };

  const importRules = async (file: File) => {
    try {
      const parsed = JSON.parse(await file.text()) as { rules?: Partial<LexiconRule>[] } | Partial<LexiconRule>[];
      const rules = Array.isArray(parsed) ? parsed : parsed.rules ?? [];
      const { confirmed, checked } = await feedback.confirm({
        title: `Import ${rules.length} rules?`,
        checkbox: "Replace all existing global rules",
        confirmLabel: "Import",
      });
      if (!confirmed) return;
      const result = await api.importLexicon(rules, checked);
      feedback.success(`Imported ${result.added} rules`);
      void queryClient.invalidateQueries({ queryKey: ["lexicon"] });
    } catch (error) {
      feedback.error(error instanceof SyntaxError ? new Error("The file is not valid JSON.") : error);
    }
  };

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Pronunciation"
        icon={<SpellCheck className="size-5" />}
        description="Global find-and-replace rules applied before narration – fix names, acronyms and words the voices get wrong. Book-specific rules live in each project."
        actions={
          <>
            <input
              ref={input}
              type="file"
              accept="application/json,.json"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void importRules(file);
                e.target.value = "";
              }}
            />
            <Button icon={<Upload className="size-4" />} onClick={() => input.current?.click()}>
              Import
            </Button>
            <Button icon={<Download className="size-4" />} onClick={() => void exportRules()}>
              Export
            </Button>
          </>
        }
      />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_26rem]">
        <RulesTable />
        <div className="space-y-4">
          <RuleTester
            onPreview={async (text) => {
              const settings = await api.settings();
              return api.previewVoice({
                engine: settings.render_defaults.engine,
                voice: settings.render_defaults.voice,
                text,
                speed: settings.render_defaults.speed,
              });
            }}
          />
          <div className="rounded-xl bg-zinc-100 p-4 text-sm text-zinc-600 dark:bg-zinc-900 dark:text-zinc-300">
            <div className="mb-1 font-semibold text-zinc-800 dark:text-zinc-100">Tips</div>
            <ul className="list-inside list-disc space-y-1">
              <li>Spell names the way they sound: “Siobhan” → “Shiv-awn”.</li>
              <li>Spell out acronyms you want letter by letter: “SQL” → “S Q L”.</li>
              <li>Use a regular expression for patterns, e.g. <code>\bch\.\s</code> → “chapter ”.</li>
              <li>Leave “Say instead” empty to silently drop words.</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

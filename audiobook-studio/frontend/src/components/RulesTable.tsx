import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Play, Plus, Square, Trash2, Wand } from "lucide-react";
import { useState } from "react";
import { api } from "../lib/api";
import { useDebounced, usePreviewPlayer } from "../lib/hooks";
import type { LexiconRule } from "../lib/types";
import { useFeedback } from "./feedback";
import { Badge, Button, Card, EmptyState, IconButton, cn } from "./ui";

export function RulesTable({ projectId }: { projectId?: number }) {
  const feedback = useFeedback();
  const queryClient = useQueryClient();
  const key = ["lexicon", projectId ?? "global"];
  const rules = useQuery({ queryKey: key, queryFn: () => api.lexicon(projectId) });
  const [draft, setDraft] = useState({ pattern: "", replacement: "", is_regex: false, case_sensitive: false, whole_word: true });
  const [filter, setFilter] = useState("");

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["lexicon"] });
    if (projectId) void queryClient.invalidateQueries({ queryKey: ["project", projectId] });
  };

  const create = useMutation({
    mutationFn: () => api.createRule({ ...draft, project_id: projectId ?? null }),
    onSuccess: () => {
      setDraft({ ...draft, pattern: "", replacement: "" });
      invalidate();
    },
    onError: feedback.error,
  });

  const update = (rule: LexiconRule, patch: Partial<LexiconRule>) =>
    api.updateRule(rule.id, patch).then(invalidate, feedback.error);

  const remove = (rule: LexiconRule) => api.deleteRule(rule.id).then(invalidate, feedback.error);

  const list = (rules.data ?? []).filter(
    (r) => !filter || r.pattern.toLowerCase().includes(filter.toLowerCase()) || r.replacement.toLowerCase().includes(filter.toLowerCase()),
  );

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <form
          className="grid gap-3 lg:grid-cols-[1fr_1fr_auto] lg:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            if (draft.pattern.trim()) create.mutate();
          }}
        >
          <label className="block">
            <span className="field-label">When the text says</span>
            <input className="input" placeholder="Hermione" value={draft.pattern} onChange={(e) => setDraft({ ...draft, pattern: e.target.value })} />
          </label>
          <label className="block">
            <span className="field-label">Say instead</span>
            <input className="input" placeholder="Her-my-oh-nee" value={draft.replacement} onChange={(e) => setDraft({ ...draft, replacement: e.target.value })} />
          </label>
          <Button type="submit" variant="primary" icon={<Plus className="size-4" />} loading={create.isPending} disabled={!draft.pattern.trim()}>
            Add rule
          </Button>
          <div className="flex flex-wrap gap-4 text-xs text-zinc-600 lg:col-span-3 dark:text-zinc-300">
            {(
              [
                ["whole_word", "Whole words only"],
                ["case_sensitive", "Case sensitive"],
                ["is_regex", "Regular expression"],
              ] as const
            ).map(([field, label]) => (
              <label key={field} className="flex items-center gap-1.5">
                <input type="checkbox" className="size-3.5 accent-brand-600" checked={draft[field]} onChange={(e) => setDraft({ ...draft, [field]: e.target.checked })} />
                {label}
              </label>
            ))}
          </div>
        </form>
      </Card>

      {rules.data && rules.data.length > 6 && (
        <input className="input max-w-xs" placeholder="Filter rules…" value={filter} onChange={(e) => setFilter(e.target.value)} />
      )}

      {!rules.data?.length ? (
        <EmptyState
          icon={<Wand className="size-5" />}
          title="No pronunciation rules yet"
          description="Teach the narrator names, places and abbreviations. Rules apply when previewing and rendering."
        />
      ) : (
        <Card className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {list.map((rule) => (
            <div key={rule.id} className={cn("flex flex-wrap items-center gap-3 px-4 py-2.5", !rule.enabled && "opacity-50")}>
              <input type="checkbox" title="Enabled" className="size-4 accent-brand-600" checked={rule.enabled} onChange={(e) => void update(rule, { enabled: e.target.checked })} />
              <input
                className="input h-8 min-w-32 flex-1 py-1 font-mono text-sm"
                defaultValue={rule.pattern}
                onBlur={(e) => e.target.value !== rule.pattern && void update(rule, { pattern: e.target.value })}
              />
              <span className="text-zinc-400">→</span>
              <input
                className="input h-8 min-w-32 flex-1 py-1 text-sm"
                defaultValue={rule.replacement}
                onBlur={(e) => e.target.value !== rule.replacement && void update(rule, { replacement: e.target.value })}
              />
              <div className="flex gap-1">
                {rule.is_regex && <Badge color="blue">regex</Badge>}
                {rule.case_sensitive && <Badge>Aa</Badge>}
                {!rule.whole_word && !rule.is_regex && <Badge>partial</Badge>}
              </div>
              <IconButton label="Delete rule" onClick={() => void remove(rule)}>
                <Trash2 className="size-4" />
              </IconButton>
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}

export function RuleTester({
  projectId,
  onPreview,
}: {
  projectId?: number;
  onPreview: (text: string) => Promise<Blob>;
}) {
  const feedback = useFeedback();
  const preview = usePreviewPlayer();
  const [text, setText] = useState("Dr. Hermione met Mr. Weasley at 5 p.m. — see https://example.com[3].");
  const debounced = useDebounced(text, 400);
  const result = useQuery({
    queryKey: ["lexicon-test", projectId ?? "global", debounced],
    queryFn: () => api.testLexicon(debounced, projectId),
    enabled: debounced.trim().length > 0,
  });
  return (
    <Card className="p-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="font-semibold">Try it</h3>
        <Button
          size="sm"
          icon={preview.loading ? <Loader2 className="size-4 animate-spin" /> : preview.playing ? <Square className="size-3.5" fill="currentColor" /> : <Play className="size-4" />}
          onClick={() => preview.play("tester", () => onPreview(text)).catch(feedback.error)}
          disabled={!text.trim()}
        >
          {preview.playing ? "Stop" : "Listen"}
        </Button>
      </div>
      <textarea className="input min-h-24" value={text} onChange={(e) => setText(e.target.value)} />
      <div className="mt-3 rounded-lg bg-zinc-50 p-3 text-sm dark:bg-zinc-800/60">
        <div className="mb-1 text-xs font-medium tracking-wide text-zinc-500 uppercase">What the narrator reads</div>
        <div className="whitespace-pre-wrap">{result.data?.result ?? "…"}</div>
      </div>
    </Card>
  );
}

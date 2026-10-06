import { useMutation } from "@tanstack/react-query";
import { Globe, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Metadata, MetadataResult } from "../lib/types";
import { Cover } from "./Cover";
import { useFeedback } from "./feedback";
import { Badge, Button, EmptyState, Field, Modal, Spinner, cn } from "./ui";

const FIELDS: { key: keyof MetadataResult & keyof Metadata; label: string }[] = [
  { key: "title", label: "Title" },
  { key: "subtitle", label: "Subtitle" },
  { key: "author", label: "Author" },
  { key: "year", label: "Year" },
  { key: "publisher", label: "Publisher" },
  { key: "genre", label: "Genre" },
  { key: "isbn", label: "ISBN" },
  { key: "language", label: "Language" },
  { key: "description", label: "Description" },
  { key: "tags", label: "Tags" },
];

export function MetadataLookup({
  open,
  onClose,
  initial,
  onApply,
}: {
  open: boolean;
  onClose: () => void;
  initial: { title: string; author: string; isbn?: string };
  onApply: (patch: Partial<Metadata>, coverUrl: string | null) => Promise<void> | void;
}) {
  const feedback = useFeedback();
  const [query, setQuery] = useState(initial);
  const [selected, setSelected] = useState<MetadataResult | null>(null);
  const [fields, setFields] = useState<Set<string>>(new Set());
  const [useCover, setUseCover] = useState(true);
  const [applying, setApplying] = useState(false);

  const search = useMutation({
    mutationFn: () => api.metadataSearch(query),
    onError: feedback.error,
  });

  useEffect(() => {
    if (open) {
      setQuery(initial);
      setSelected(null);
      if (initial.title || initial.isbn) search.mutate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const select = async (result: MetadataResult) => {
    let enriched = result;
    if (result.source === "openlibrary" && !result.description) {
      try {
        const { description } = await api.metadataDescription(result.source, result.source_id);
        enriched = { ...result, description };
      } catch {
        /* optional */
      }
    }
    setSelected(enriched);
    const defaults = FIELDS.filter((f) => {
      const value = enriched[f.key];
      return Array.isArray(value) ? value.length : Boolean(value);
    }).map((f) => f.key);
    setFields(new Set(defaults.filter((k) => k !== "title" && k !== "tags")));
    setUseCover(Boolean(enriched.cover_url));
  };

  const apply = async () => {
    if (!selected) return;
    const patch: Partial<Metadata> = {};
    for (const field of FIELDS) {
      if (fields.has(field.key)) (patch as Record<string, unknown>)[field.key] = selected[field.key];
    }
    setApplying(true);
    try {
      await onApply(patch, useCover && selected.cover_url ? selected.cover_url : null);
      onClose();
    } catch (error) {
      feedback.error(error);
    } finally {
      setApplying(false);
    }
  };

  const results = search.data?.results ?? [];

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title="Find metadata online"
      description="Searches Open Library and Google Books. Pick a match and choose which fields to copy."
      footer={
        selected ? (
          <>
            <Button onClick={() => setSelected(null)}>Back to results</Button>
            <Button variant="primary" onClick={apply} loading={applying}>
              Apply selected fields
            </Button>
          </>
        ) : undefined
      }
    >
      {!selected ? (
        <>
          <form
            className="mb-5 grid gap-3 sm:grid-cols-[1fr_1fr_10rem_auto] sm:items-end"
            onSubmit={(e) => {
              e.preventDefault();
              search.mutate();
            }}
          >
            <Field label="Title">
              <input className="input" value={query.title} onChange={(e) => setQuery({ ...query, title: e.target.value })} />
            </Field>
            <Field label="Author">
              <input className="input" value={query.author} onChange={(e) => setQuery({ ...query, author: e.target.value })} />
            </Field>
            <Field label="ISBN">
              <input className="input" value={query.isbn ?? ""} onChange={(e) => setQuery({ ...query, isbn: e.target.value })} />
            </Field>
            <Button type="submit" variant="primary" icon={<Search className="size-4" />} loading={search.isPending}>
              Search
            </Button>
          </form>
          {search.isPending && (
            <div className="flex justify-center py-10">
              <Spinner />
            </div>
          )}
          {search.data?.errors.length ? (
            <p className="mb-3 text-xs text-amber-600 dark:text-amber-400">Some sources failed: {search.data.errors.join(", ")}</p>
          ) : null}
          {!search.isPending && search.isSuccess && !results.length && (
            <EmptyState icon={<Globe className="size-5" />} title="No matches" description="Try a shorter title or search by ISBN." />
          )}
          <div className="grid gap-3">
            {results.map((r, i) => (
              <button
                key={`${r.source}-${r.source_id}-${i}`}
                onClick={() => void select(r)}
                className="flex gap-4 rounded-xl border border-zinc-200 p-3 text-left transition hover:border-brand-400 hover:bg-brand-50/50 dark:border-zinc-800 dark:hover:border-brand-500/60 dark:hover:bg-brand-500/5"
              >
                <Cover src={r.cover_url || null} title={r.title} author={r.author} className="w-16" rounded="rounded-md" portrait />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{r.title}</span>
                    <Badge color={r.source === "google" ? "blue" : "green"}>{r.source === "google" ? "Google Books" : "Open Library"}</Badge>
                  </div>
                  <div className="text-sm text-zinc-600 dark:text-zinc-300">
                    {[r.author, r.year, r.publisher].filter(Boolean).join(" · ")}
                  </div>
                  {r.genre && <div className="mt-1 text-xs text-zinc-500">{r.genre}</div>}
                  {r.description && <p className="mt-1 line-clamp-2 text-xs text-zinc-500 dark:text-zinc-400">{r.description}</p>}
                </div>
              </button>
            ))}
          </div>
        </>
      ) : (
        <div className="grid gap-6 sm:grid-cols-[10rem_1fr]">
          <div>
            <Cover src={selected.cover_url || null} title={selected.title} author={selected.author} portrait />
            {selected.cover_url && (
              <label className="mt-3 flex items-center gap-2 text-sm">
                <input type="checkbox" className="size-4 accent-brand-600" checked={useCover} onChange={(e) => setUseCover(e.target.checked)} />
                Use this cover
              </label>
            )}
          </div>
          <div className="divide-y divide-zinc-200 dark:divide-zinc-800">
            {FIELDS.map((field) => {
              const value = selected[field.key];
              const display = Array.isArray(value) ? value.join(", ") : value;
              if (!display) return null;
              return (
                <label key={field.key} className="flex cursor-pointer gap-3 py-2.5">
                  <input
                    type="checkbox"
                    className="mt-0.5 size-4 accent-brand-600"
                    checked={fields.has(field.key)}
                    onChange={(e) => {
                      const next = new Set(fields);
                      if (e.target.checked) next.add(field.key);
                      else next.delete(field.key);
                      setFields(next);
                    }}
                  />
                  <span className="min-w-0">
                    <span className="block text-xs font-medium text-zinc-500 uppercase">{field.label}</span>
                    <span className={cn("block text-sm", field.key === "description" && "line-clamp-4")}>{display}</span>
                  </span>
                </label>
              );
            })}
          </div>
        </div>
      )}
    </Modal>
  );
}

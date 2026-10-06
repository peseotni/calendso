import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownAZ,
  ArrowUpAZ,
  CheckSquare,
  FolderSearch,
  Heart,
  LayoutGrid,
  Library as LibraryIcon,
  List,
  Pencil,
  Play,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { BookCard } from "../components/BookCard";
import { Cover } from "../components/Cover";
import { useFeedback } from "../components/feedback";
import { Badge, Button, EmptyState, Field, IconButton, LoadingBlock, Modal, PageHeader, ProgressBar, Segmented, Select, cn } from "../components/ui";
import { api, type BookQuery } from "../lib/api";
import { formatDuration, languageName, timeAgo } from "../lib/format";
import { useDebounced, useLocalStorage } from "../lib/hooks";
import type { Book, Collection } from "../lib/types";
import { usePlayer } from "../player/PlayerContext";

const GROUPS = [
  { value: "none", label: "No grouping" },
  { value: "author", label: "Author" },
  { value: "series", label: "Series" },
  { value: "genre", label: "Genre" },
  { value: "narrator", label: "Narrator" },
  { value: "language", label: "Language" },
  { value: "year", label: "Year" },
  { value: "collection", label: "Collection" },
  { value: "format", label: "Format" },
];
const SORTS = [
  { value: "added", label: "Recently added" },
  { value: "title", label: "Title" },
  { value: "author", label: "Author" },
  { value: "series", label: "Series" },
  { value: "duration", label: "Length" },
  { value: "year", label: "Year" },
  { value: "last_played", label: "Last played" },
  { value: "rating", label: "Rating" },
];
const FILTER_KEYS = ["author", "genre", "series", "narrator", "language", "year", "tag", "collection"] as const;

function groupKeys(book: Book, group: string, collections: Collection[]): string[] {
  switch (group) {
    case "author":
      return [book.author || "Unknown author"];
    case "series":
      return [book.series || "Standalone"];
    case "genre": {
      const genres = book.genre.split(",").map((g) => g.trim()).filter(Boolean);
      return genres.length ? genres : ["No genre"];
    }
    case "narrator":
      return [book.narrator || "Unknown narrator"];
    case "language":
      return [book.language ? languageName(book.language) : "Unknown language"];
    case "year":
      return [book.year || "Unknown year"];
    case "format":
      return [book.format.toUpperCase() || "?"];
    case "collection": {
      const names = collections.filter((c) => book.collection_ids.includes(c.id)).map((c) => c.name);
      return names.length ? names : ["Not in a collection"];
    }
    default:
      return [""];
  }
}

/** "Ursula K. Le Guin" -> "Guin Ursula K. Le" so authors sort by surname. */
function surnameFirst(name: string): string {
  const first = name.split(/\s*(?:,|&| and )\s*/)[0].trim();
  const parts = first.split(/\s+/);
  return parts.length > 1 ? `${parts[parts.length - 1]} ${parts.slice(0, -1).join(" ")}` : first;
}

function filterValueForGroup(group: string, key: string): [string, string] | null {
  if (["author", "series", "genre", "narrator", "year"].includes(group) && !/^(Unknown|Standalone|No )/.test(key)) return [group, key];
  return null;
}

export default function LibraryPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const feedback = useFeedback();
  const queryClient = useQueryClient();
  const player = usePlayer();
  const [view, setView] = useLocalStorage<"grid" | "list">("library.view", "grid");
  const [storedGroup, setStoredGroup] = useLocalStorage("library.group", "none");
  const [storedSort, setStoredSort] = useLocalStorage<{ sort: string; order: "asc" | "desc" }>("library.sort", { sort: "added", order: "desc" });
  const [search, setSearch] = useState(params.get("q") ?? "");
  const debounced = useDebounced(search, 300);
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkEdit, setBulkEdit] = useState(false);
  const [scanOpen, setScanOpen] = useState(false);

  const group = params.get("group") ?? storedGroup;
  const status = params.get("status") ?? "";
  const favorite = params.get("favorite") === "1";

  useEffect(() => setSearch(params.get("q") ?? ""), [params]);
  useEffect(() => {
    const current = params.get("q") ?? "";
    if (debounced !== current) {
      const next = new URLSearchParams(params);
      if (debounced) next.set("q", debounced);
      else next.delete("q");
      setParams(next, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced]);

  const query: BookQuery = {
    q: params.get("q") ?? undefined,
    status: status || undefined,
    favorite: favorite || undefined,
    sort: storedSort.sort,
    order: storedSort.order,
  };
  for (const key of FILTER_KEYS) {
    const value = params.get(key);
    if (value) (query as Record<string, unknown>)[key] = key === "collection" ? Number(value) : value;
  }

  const books = useQuery({ queryKey: ["books", query], queryFn: () => api.books(query) });
  const collections = useQuery({ queryKey: ["collections"], queryFn: api.collections });

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
  };

  const groups = useMemo(() => {
    const list = books.data ?? [];
    if (group === "none") return [["", list]] as [string, Book[]][];
    const map = new Map<string, Book[]>();
    for (const book of list) {
      for (const key of groupKeys(book, group, collections.data ?? [])) {
        map.set(key, [...(map.get(key) ?? []), book]);
      }
    }
    const byIndex = (a: Book, b: Book) => (parseFloat(a.series_index) || 9999) - (parseFloat(b.series_index) || 9999);
    if (group === "series") for (const items of map.values()) items.sort(byIndex);
    const sortKey = (key: string) => (group === "author" || group === "narrator" ? surnameFirst(key) : key);
    return [...map.entries()].sort(([a], [b]) => (group === "year" ? b.localeCompare(a) : sortKey(a).localeCompare(sortKey(b))));
  }, [books.data, group, collections.data]);

  const toggleSelected = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  const bulk = useMutation({
    mutationFn: (body: Parameters<typeof api.bulkBooks>[0]) => api.bulkBooks(body),
    onSuccess: (result) => {
      feedback.success(`Updated ${result.updated} books`);
      void queryClient.invalidateQueries({ queryKey: ["books"] });
      void queryClient.invalidateQueries({ queryKey: ["collections"] });
      void queryClient.invalidateQueries({ queryKey: ["facets"] });
    },
    onError: feedback.error,
  });

  const deleteSelected = async () => {
    const { confirmed, checked } = await feedback.confirm({
      title: `Remove ${selected.size} books from the library?`,
      message: "The books will be removed from the library database.",
      checkbox: "Also delete the audio files from disk",
      confirmLabel: "Remove",
      danger: true,
    });
    if (!confirmed) return;
    for (const id of selected) await api.deleteBook(id, checked);
    setSelected(new Set());
    setSelecting(false);
    void queryClient.invalidateQueries({ queryKey: ["books"] });
    feedback.success("Books removed");
  };

  const activeFilters = FILTER_KEYS.filter((k) => params.get(k));
  const total = books.data?.length ?? 0;

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Library"
        icon={<LibraryIcon className="size-5" />}
        description={`${total} audiobook${total === 1 ? "" : "s"}${books.data ? ` · ${formatDuration(books.data.reduce((s, b) => s + b.duration, 0))}` : ""}`}
        actions={
          <>
            <Button icon={<FolderSearch className="size-4" />} onClick={() => setScanOpen(true)}>
              Import existing
            </Button>
            <Link to="/studio/new">
              <Button variant="primary" icon={<Plus className="size-4" />}>
                New audiobook
              </Button>
            </Link>
          </>
        }
      />

      <div className="mb-5 flex flex-col gap-3 xl:flex-row xl:items-center">
        <div className="relative flex-1 xl:max-w-sm">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-zinc-400" />
          <input className="input pl-9" placeholder="Title, author, series, narrator…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            aria-label="Group by"
            className="w-auto"
            value={group}
            onChange={(value) => {
              setStoredGroup(value);
              setParam("group", value === "none" ? null : value);
            }}
            options={GROUPS.map((g) => ({ value: g.value, label: g.value === "none" ? g.label : `Group: ${g.label}` }))}
          />
          <Select
            aria-label="Sort"
            className="w-auto"
            value={storedSort.sort}
            onChange={(sort) => setStoredSort({ sort, order: ["title", "author", "series"].includes(sort) ? "asc" : "desc" })}
            options={SORTS}
          />
          <IconButton
            label={storedSort.order === "asc" ? "Ascending" : "Descending"}
            onClick={() => setStoredSort({ ...storedSort, order: storedSort.order === "asc" ? "desc" : "asc" })}
          >
            {storedSort.order === "asc" ? <ArrowDownAZ className="size-4.5" /> : <ArrowUpAZ className="size-4.5" />}
          </IconButton>
          <Segmented
            value={status || "all"}
            onChange={(value) => setParam("status", value === "all" ? null : value)}
            options={[
              { value: "all", label: "All" },
              { value: "unplayed", label: "New" },
              { value: "in_progress", label: "Listening" },
              { value: "finished", label: "Finished" },
            ]}
          />
          <IconButton label="Favorites only" active={favorite} onClick={() => setParam("favorite", favorite ? null : "1")}>
            <Heart className={cn("size-4.5", favorite && "fill-rose-500 text-rose-500")} />
          </IconButton>
          <Segmented
            value={view}
            onChange={setView}
            options={[
              { value: "grid", label: <LayoutGrid className="size-4" />, title: "Grid" },
              { value: "list", label: <List className="size-4" />, title: "List" },
            ]}
          />
          <Button
            size="sm"
            variant={selecting ? "subtle" : "ghost"}
            icon={<CheckSquare className="size-4" />}
            onClick={() => {
              setSelecting(!selecting);
              setSelected(new Set());
            }}
          >
            Select
          </Button>
        </div>
      </div>

      {activeFilters.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-2">
          {activeFilters.map((key) => {
            const value = params.get(key)!;
            const label = key === "collection" ? collections.data?.find((c) => c.id === Number(value))?.name ?? value : value;
            return (
              <button
                key={key}
                onClick={() => setParam(key, null)}
                className="inline-flex items-center gap-1.5 rounded-full bg-brand-100 px-3 py-1 text-xs font-medium text-brand-700 hover:bg-brand-200 dark:bg-brand-500/15 dark:text-brand-300"
              >
                <span className="capitalize">{key}:</span> {label}
                <X className="size-3.5" />
              </button>
            );
          })}
        </div>
      )}

      {selecting && (
        <div className="sticky top-16 z-10 mb-4 flex flex-wrap items-center gap-2 rounded-xl border border-brand-200 bg-brand-50/95 px-4 py-2.5 backdrop-blur dark:border-brand-500/30 dark:bg-zinc-900/95">
          <span className="mr-2 text-sm font-medium">{selected.size} selected</span>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set((books.data ?? []).map((b) => b.id)))}>
            Select all
          </Button>
          <div className="ml-auto flex flex-wrap gap-2">
            <Button size="sm" icon={<Pencil className="size-4" />} disabled={!selected.size} onClick={() => setBulkEdit(true)}>
              Edit
            </Button>
            <select
              className="input h-8 w-auto py-0 text-sm"
              value=""
              disabled={!selected.size}
              onChange={(e) => e.target.value && bulk.mutate({ book_ids: [...selected], add_collection_id: Number(e.target.value) })}
            >
              <option value="">Add to collection…</option>
              {collections.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            <Button size="sm" disabled={!selected.size} onClick={() => bulk.mutate({ book_ids: [...selected], changes: { finished: true } })}>
              Mark finished
            </Button>
            <Button size="sm" variant="danger" icon={<Trash2 className="size-4" />} disabled={!selected.size} onClick={() => void deleteSelected()}>
              Remove
            </Button>
          </div>
        </div>
      )}

      {books.isLoading ? (
        <LoadingBlock />
      ) : !total ? (
        <EmptyState
          icon={<LibraryIcon className="size-6" />}
          title={params.toString() ? "No audiobooks match" : "Your library is empty"}
          description={
            params.toString()
              ? "Try clearing the filters."
              : "Create an audiobook from an ebook in the Studio, or import audiobooks you already have."
          }
          action={
            params.toString() ? (
              <Button onClick={() => navigate("/library")}>Clear filters</Button>
            ) : (
              <div className="flex gap-2">
                <Button onClick={() => setScanOpen(true)}>Import existing</Button>
                <Link to="/studio/new">
                  <Button variant="primary">Create audiobook</Button>
                </Link>
              </div>
            )
          }
        />
      ) : (
        <div className="space-y-10">
          {groups.map(([key, items]) => {
            const filter = filterValueForGroup(group, key);
            return (
              <section key={key || "all"}>
                {group !== "none" && (
                  <div className="mb-4 flex items-center gap-3 border-b border-zinc-200 pb-2 dark:border-zinc-800">
                    <h2 className="text-lg font-semibold">{key}</h2>
                    <Badge>{items.length}</Badge>
                    <span className="text-xs text-zinc-500">{formatDuration(items.reduce((s, b) => s + b.duration, 0))}</span>
                    <div className="ml-auto flex gap-1">
                      {filter && (
                        <Button size="xs" variant="ghost" onClick={() => setParam(filter[0], filter[1])}>
                          Show only
                        </Button>
                      )}
                    </div>
                  </div>
                )}
                {view === "grid" ? (
                  <div className="grid grid-cols-2 gap-x-5 gap-y-7 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 2xl:grid-cols-7">
                    {items.map((book) => (
                      <BookCard key={book.id} book={book} selectable={selecting} selected={selected.has(book.id)} onSelect={toggleSelected} />
                    ))}
                  </div>
                ) : (
                  <div className="card overflow-hidden">
                    <table className="w-full text-sm">
                      <thead className="bg-zinc-50 text-left text-xs text-zinc-500 uppercase dark:bg-zinc-900/60">
                        <tr>
                          {selecting && <th className="w-10 px-3 py-2" />}
                          <th className="px-3 py-2">Title</th>
                          <th className="hidden px-3 py-2 md:table-cell">Series</th>
                          <th className="hidden px-3 py-2 lg:table-cell">Narrator</th>
                          <th className="hidden px-3 py-2 lg:table-cell">Genre</th>
                          <th className="px-3 py-2 text-right">Length</th>
                          <th className="hidden px-3 py-2 sm:table-cell">Added</th>
                          <th className="w-12" />
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                        {items.map((book) => (
                          <tr key={book.id} className="hover:bg-zinc-50 dark:hover:bg-zinc-800/40">
                            {selecting && (
                              <td className="px-3">
                                <input type="checkbox" className="size-4 accent-brand-600" checked={selected.has(book.id)} onChange={() => toggleSelected(book.id)} />
                              </td>
                            )}
                            <td className="px-3 py-2">
                              <Link to={`/library/${book.id}`} className="flex items-center gap-3">
                                <Cover src={book.thumb_url} title={book.title} author={book.author} className="w-10 shrink-0" rounded="rounded-md" />
                                <div className="min-w-0">
                                  <div className="truncate font-medium">{book.title}</div>
                                  <div className="truncate text-xs text-zinc-500">{book.author}</div>
                                  {book.progress > 0 && !book.finished && (
                                    <ProgressBar value={book.progress / (book.duration || 1)} className="mt-1 w-24" />
                                  )}
                                </div>
                              </Link>
                            </td>
                            <td className="hidden px-3 py-2 text-zinc-600 md:table-cell dark:text-zinc-300">
                              {book.series ? `${book.series}${book.series_index ? ` #${book.series_index}` : ""}` : "—"}
                            </td>
                            <td className="hidden px-3 py-2 text-zinc-600 lg:table-cell dark:text-zinc-300">{book.narrator || "—"}</td>
                            <td className="hidden px-3 py-2 text-zinc-600 lg:table-cell dark:text-zinc-300">{book.genre || "—"}</td>
                            <td className="px-3 py-2 text-right tabular-nums">{formatDuration(book.duration)}</td>
                            <td className="hidden px-3 py-2 text-zinc-500 sm:table-cell">{timeAgo(book.added_at)}</td>
                            <td className="px-2">
                              <IconButton label="Play" onClick={() => player.play(book)}>
                                <Play className="size-4" />
                              </IconButton>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            );
          })}
        </div>
      )}

      <BulkEditModal
        open={bulkEdit}
        count={selected.size}
        onClose={() => setBulkEdit(false)}
        onSave={(changes) => {
          bulk.mutate({ book_ids: [...selected], changes });
          setBulkEdit(false);
        }}
      />
      <ScanModal open={scanOpen} onClose={() => setScanOpen(false)} />
    </div>
  );
}

function BulkEditModal({
  open,
  count,
  onClose,
  onSave,
}: {
  open: boolean;
  count: number;
  onClose: () => void;
  onSave: (changes: Record<string, string>) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  useEffect(() => {
    if (open) setValues({});
  }, [open]);
  const fields = [
    ["author", "Author"],
    ["narrator", "Narrator"],
    ["series", "Series"],
    ["genre", "Genre"],
    ["language", "Language"],
    ["publisher", "Publisher"],
    ["year", "Year"],
  ];
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Edit ${count} books`}
      description="Only filled-in fields are changed. Files are re-tagged and moved to match your folder template."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            disabled={!Object.values(values).some((v) => v.trim())}
            onClick={() => onSave(Object.fromEntries(Object.entries(values).filter(([, v]) => v.trim())))}
          >
            Apply
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {fields.map(([key, label]) => (
          <Field key={key} label={label}>
            <input className="input" value={values[key] ?? ""} onChange={(e) => setValues({ ...values, [key]: e.target.value })} placeholder="Leave unchanged" />
          </Field>
        ))}
      </div>
    </Modal>
  );
}

export function ScanModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const feedback = useFeedback();
  const navigate = useNavigate();
  const [path, setPath] = useState("");
  const templates = useQuery({ queryKey: ["templates"], queryFn: api.templates, enabled: open });
  const scan = useMutation({
    mutationFn: () => api.scanLibrary(path.trim() || undefined),
    onSuccess: () => {
      feedback.success("Scanning for audiobooks…");
      onClose();
      navigate("/queue");
    },
    onError: feedback.error,
  });
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Import existing audiobooks"
      description="Scans a folder for M4B/M4A/MP3/Opus/FLAC audiobooks, reads their tags, chapters and covers and adds them to the library."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={() => scan.mutate()} loading={scan.isPending}>
            Start scan
          </Button>
        </>
      }
    >
      <Field
        label="Folder (on the server)"
        hint={`Leave empty to scan the library folder${templates.data ? ` (${templates.data.library_path})` : ""}. Folders like “Author/Series/Title” are recognised. Files outside the library folder are referenced in place.`}
      >
        <input className="input font-mono text-sm" placeholder="/audiobooks" value={path} onChange={(e) => setPath(e.target.value)} />
      </Field>
    </Modal>
  );
}

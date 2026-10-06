import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CheckCircle2,
  Copy,
  Download,
  FileAudio,
  FolderOpen,
  Globe,
  Heart,
  MoreHorizontal,
  Pause,
  Pencil,
  Play,
  RefreshCw,
  Rss,
  Star,
  Tags,
  Trash2,
  Wand2,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { CoverEditor } from "../components/CoverEditor";
import { useFeedback } from "../components/feedback";
import { MetadataForm, type MetadataValue } from "../components/MetadataForm";
import { MetadataLookup } from "../components/MetadataLookup";
import { Badge, Button, Card, IconButton, LoadingBlock, Menu, MenuItem, Modal, ProgressBar, cn } from "../components/ui";
import { api } from "../lib/api";
import { formatBytes, formatDate, formatDuration, languageName } from "../lib/format";
import type { Book, Metadata } from "../lib/types";
import { usePlayer } from "../player/PlayerContext";

const META_KEYS: (keyof Metadata)[] = [
  "title", "subtitle", "author", "narrator", "series", "series_index", "genre", "tags", "language", "publisher", "year", "description", "isbn",
];

export default function BookDetail() {
  const { id } = useParams();
  const bookId = Number(id);
  const navigate = useNavigate();
  const feedback = useFeedback();
  const queryClient = useQueryClient();
  const player = usePlayer();
  const [editing, setEditing] = useState(false);
  const [lookup, setLookup] = useState(false);
  const [draft, setDraft] = useState<MetadataValue>({});

  const { data: book, isLoading } = useQuery({ queryKey: ["book", bookId], queryFn: () => api.book(bookId) });
  const collections = useQuery({ queryKey: ["collections"], queryFn: api.collections });
  const feeds = useQuery({ queryKey: ["feeds"], queryFn: api.feeds });

  // Initialise the form when the editor opens; later refetches (e.g. saved
  // listening progress) must not overwrite what the user is typing.
  useEffect(() => {
    if (book && editing) setDraft(Object.fromEntries(META_KEYS.map((k) => [k, book[k]])) as MetadataValue);
  }, [editing]); // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = (updated?: Book) => {
    if (updated) queryClient.setQueryData(["book", bookId], updated);
    void queryClient.invalidateQueries({ queryKey: ["books"] });
    void queryClient.invalidateQueries({ queryKey: ["facets"] });
    void queryClient.invalidateQueries({ queryKey: ["stats"] });
  };

  const update = useMutation({
    mutationFn: (body: Parameters<typeof api.updateBook>[1]) => api.updateBook(bookId, body),
    onSuccess: (updated) => refresh(updated),
    onError: feedback.error,
  });

  if (isLoading) return <LoadingBlock />;
  if (!book) return <div className="py-20 text-center text-zinc-500">Book not found.</div>;

  const isCurrent = player.book?.id === book.id;
  const progress = book.duration ? book.progress / book.duration : 0;
  const position = isCurrent ? player.position : book.progress;

  const remove = async () => {
    const { confirmed, checked } = await feedback.confirm({
      title: `Remove “${book.title}”?`,
      message: "The book is removed from the library.",
      checkbox: "Also delete the audio files from disk",
      confirmLabel: "Remove",
      danger: true,
    });
    if (!confirmed) return;
    try {
      if (isCurrent) player.close();
      await api.deleteBook(book.id, checked);
      refresh();
      navigate("/library");
      feedback.success("Book removed");
    } catch (error) {
      feedback.error(error);
    }
  };

  const saveMetadata = async () => {
    await update.mutateAsync(draft);
    setEditing(false);
    feedback.success("Saved. Tags and folders are being updated in the background.");
  };

  const feedUrl = feeds.data?.book_template.replace("{id}", String(book.id));

  return (
    <div className="animate-fade-in">
      <button onClick={() => navigate(-1)} className="mb-5 inline-flex items-center gap-1.5 text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-white">
        <ArrowLeft className="size-4" /> Back
      </button>

      <div className="grid gap-8 lg:grid-cols-[18rem_minmax(0,1fr)] xl:grid-cols-[20rem_minmax(0,1fr)]">
        <div className="mx-auto w-full max-w-xs lg:max-w-none">
          <CoverEditor
            src={book.cover_url}
            title={book.title}
            author={book.author}
            onUpload={async (file) => refresh(await api.uploadBookCover(book.id, file))}
            onUrl={async (url) => refresh(await api.bookCoverFromUrl(book.id, url))}
          />
        </div>

        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            {book.series && (
              <Link to={`/library?series=${encodeURIComponent(book.series)}`}>
                <Badge color="brand">
                  {book.series}
                  {book.series_index ? ` · Book ${book.series_index}` : ""}
                </Badge>
              </Link>
            )}
            <Badge>{book.format.toUpperCase()}</Badge>
            {book.source === "studio" ? <Badge color="green">Made in Studio</Badge> : <Badge color="blue">Imported</Badge>}
            {book.missing && <Badge color="red">Files missing</Badge>}
            {book.finished && <Badge color="green" icon={<CheckCircle2 className="size-3" />}>Finished</Badge>}
          </div>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">{book.title}</h1>
          {book.subtitle && <p className="mt-1 text-lg text-zinc-500 dark:text-zinc-400">{book.subtitle}</p>}
          <p className="mt-2 text-base">
            {book.author ? (
              <Link to={`/library?author=${encodeURIComponent(book.author)}`} className="font-medium text-brand-700 hover:underline dark:text-brand-300">
                {book.author}
              </Link>
            ) : (
              <span className="text-zinc-500">Unknown author</span>
            )}
            {book.narrator && <span className="text-zinc-500"> · narrated by {book.narrator}</span>}
          </p>

          <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-1 text-sm text-zinc-600 dark:text-zinc-300">
            <span>{formatDuration(book.duration)}</span>
            <span>{book.chapters.length} chapters</span>
            {book.year && <span>{book.year}</span>}
            {book.language && <span>{languageName(book.language)}</span>}
            {book.genre && (
              <span className="flex flex-wrap gap-1">
                {book.genre.split(",").map((g, i) => (
                  <span key={g}>
                    {i > 0 && ", "}
                    <Link to={`/library?genre=${encodeURIComponent(g.trim())}`} className="hover:underline">
                      {g.trim()}
                    </Link>
                  </span>
                ))}
              </span>
            )}
            <span>{formatBytes(book.size)}</span>
          </div>

          <div className="mt-6 flex flex-wrap items-center gap-2">
            <Button
              size="lg"
              variant="primary"
              disabled={!book.files.length || book.missing}
              icon={isCurrent && player.playing ? <Pause className="size-5" fill="currentColor" /> : <Play className="size-5" fill="currentColor" />}
              onClick={() => (isCurrent && player.playing ? player.pause() : player.play(book))}
            >
              {isCurrent && player.playing ? "Pause" : book.progress > 0 && !book.finished ? `Resume at ${formatDuration(book.progress, "clock")}` : "Play"}
            </Button>
            <IconButton label={book.favorite ? "Unfavorite" : "Favorite"} onClick={() => update.mutate({ favorite: !book.favorite })} className="size-12">
              <Heart className={cn("size-5", book.favorite && "fill-rose-500 text-rose-500")} />
            </IconButton>
            <a href={`/api/books/${book.id}/download`}>
              <Button size="lg" icon={<Download className="size-4" />}>
                Download
              </Button>
            </a>
            <Button size="lg" icon={<Pencil className="size-4" />} onClick={() => setEditing(true)}>
              Edit
            </Button>
            <Menu
              trigger={({ onClick }) => (
                <IconButton label="More" onClick={onClick} className="size-12">
                  <MoreHorizontal className="size-5" />
                </IconButton>
              )}
            >
              {(close) => (
                <>
                  <MenuItem icon={<Globe />} onClick={() => (setLookup(true), close())}>
                    Find metadata online
                  </MenuItem>
                  <MenuItem icon={<CheckCircle2 />} onClick={() => (update.mutate({ finished: !book.finished }), close())}>
                    Mark as {book.finished ? "unfinished" : "finished"}
                  </MenuItem>
                  <MenuItem
                    icon={<RefreshCw />}
                    onClick={() => {
                      close();
                      api.retagBook(book.id).then(() => feedback.success("Rewriting tags…"), feedback.error);
                    }}
                  >
                    Rewrite file tags
                  </MenuItem>
                  {book.project_id && (
                    <MenuItem icon={<Wand2 />} onClick={() => navigate(`/studio/${book.project_id}`)}>
                      Open studio project
                    </MenuItem>
                  )}
                  {feedUrl && (
                    <MenuItem
                      icon={<Rss />}
                      onClick={() => {
                        close();
                        void navigator.clipboard?.writeText(feedUrl);
                        feedback.success("Podcast feed URL copied");
                      }}
                    >
                      Copy podcast feed URL
                    </MenuItem>
                  )}
                  <MenuItem icon={<Trash2 />} danger onClick={() => (close(), void remove())}>
                    Remove from library
                  </MenuItem>
                </>
              )}
            </Menu>
          </div>

          {(progress > 0 || isCurrent) && (
            <div className="mt-5 max-w-xl">
              <ProgressBar value={(isCurrent ? player.position : book.progress) / (book.duration || 1)} />
              <div className="mt-1 flex justify-between text-xs text-zinc-500 tabular-nums">
                <span>{formatDuration(position, "clock")}</span>
                <span>{formatDuration(Math.max(0, book.duration - position))} left</span>
              </div>
            </div>
          )}

          <div className="mt-5 flex items-center gap-1">
            {[1, 2, 3, 4, 5].map((n) => (
              <button key={n} onClick={() => update.mutate({ rating: book.rating === n ? 0 : n })} aria-label={`Rate ${n}`}>
                <Star className={cn("size-5", n <= book.rating ? "fill-amber-400 text-amber-400" : "text-zinc-300 dark:text-zinc-600")} />
              </button>
            ))}
          </div>

          {book.description && (
            <p className="mt-6 max-w-3xl text-sm leading-relaxed whitespace-pre-line text-zinc-700 dark:text-zinc-300">{book.description}</p>
          )}

          {book.tags.length > 0 && (
            <div className="mt-4 flex flex-wrap items-center gap-1.5">
              <Tags className="size-4 text-zinc-400" />
              {book.tags.map((tag) => (
                <Link key={tag} to={`/library?tag=${encodeURIComponent(tag)}`}>
                  <Badge>{tag}</Badge>
                </Link>
              ))}
            </div>
          )}

          <div className="mt-4 flex flex-wrap gap-2">
            {collections.data?.map((c) => {
              const member = book.collection_ids.includes(c.id);
              return (
                <button
                  key={c.id}
                  onClick={() =>
                    update.mutate({
                      collection_ids: member ? book.collection_ids.filter((x) => x !== c.id) : [...book.collection_ids, c.id],
                    })
                  }
                  className={cn(
                    "rounded-full border px-3 py-1 text-xs font-medium transition",
                    member
                      ? "border-brand-500 bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-300"
                      : "border-zinc-300 text-zinc-500 hover:border-zinc-400 dark:border-zinc-700",
                  )}
                >
                  {member ? "✓ " : "+ "}
                  {c.name}
                </button>
              );
            })}
          </div>

          <div className="mt-8 grid gap-6 xl:grid-cols-2">
            <Card className="p-5">
              <h2 className="mb-3 font-semibold">Chapters</h2>
              <div className="scrollbar-thin max-h-[28rem] divide-y divide-zinc-100 overflow-y-auto dark:divide-zinc-800">
                {book.chapters.map((chapter, index) => {
                  const active = isCurrent && player.chapterIndex === index;
                  return (
                    <button
                      key={index}
                      onClick={() => player.play(book, chapter.start)}
                      className={cn(
                        "flex w-full items-center gap-3 px-2 py-2.5 text-left text-sm hover:bg-zinc-50 dark:hover:bg-zinc-800/50",
                        active && "text-brand-700 dark:text-brand-300",
                      )}
                    >
                      <span className="w-6 text-right text-xs text-zinc-400 tabular-nums">{index + 1}</span>
                      {active && player.playing ? <Pause className="size-3.5" /> : <Play className="size-3.5 text-zinc-400" />}
                      <span className="flex-1 truncate">{chapter.title}</span>
                      <span className="text-xs text-zinc-500 tabular-nums">{formatDuration(chapter.end - chapter.start, "clock")}</span>
                    </button>
                  );
                })}
              </div>
            </Card>
            <Card className="p-5">
              <h2 className="mb-3 font-semibold">Files</h2>
              <div className="mb-3 flex items-start gap-2 rounded-lg bg-zinc-50 px-3 py-2 text-xs text-zinc-600 dark:bg-zinc-800/50 dark:text-zinc-300">
                <FolderOpen className="mt-0.5 size-4 shrink-0" />
                <span className="font-mono break-all">{book.path || "/"}</span>
              </div>
              <div className="scrollbar-thin max-h-80 divide-y divide-zinc-100 overflow-y-auto dark:divide-zinc-800">
                {book.files.map((file, index) => (
                  <a key={file.path} href={`/api/books/${book.id}/files/${index}`} download className="flex items-center gap-3 py-2 text-sm hover:opacity-80">
                    <FileAudio className="size-4 shrink-0 text-zinc-400" />
                    <span className="flex-1 truncate">{file.path.split("/").pop()}</span>
                    <span className="text-xs text-zinc-500 tabular-nums">{formatDuration(file.duration, "clock")}</span>
                    <span className="w-16 text-right text-xs text-zinc-500 tabular-nums">{formatBytes(file.size)}</span>
                  </a>
                ))}
              </div>
              <dl className="mt-4 grid grid-cols-2 gap-2 text-xs text-zinc-500">
                <dt>Added</dt>
                <dd className="text-right">{formatDate(book.added_at)}</dd>
                {book.last_played_at && (
                  <>
                    <dt>Last played</dt>
                    <dd className="text-right">{formatDate(book.last_played_at)}</dd>
                  </>
                )}
                {book.publisher && (
                  <>
                    <dt>Publisher</dt>
                    <dd className="text-right">{book.publisher}</dd>
                  </>
                )}
                {book.isbn && (
                  <>
                    <dt>ISBN</dt>
                    <dd className="text-right">{book.isbn}</dd>
                  </>
                )}
              </dl>
              {feedUrl && (
                <button
                  onClick={() => {
                    void navigator.clipboard?.writeText(feedUrl);
                    feedback.success("Podcast feed URL copied");
                  }}
                  className="mt-4 inline-flex items-center gap-1.5 text-xs font-medium text-brand-600 hover:underline dark:text-brand-400"
                >
                  <Copy className="size-3.5" /> Copy podcast feed for this book
                </button>
              )}
            </Card>
          </div>
        </div>
      </div>

      <Modal
        open={editing}
        onClose={() => setEditing(false)}
        size="lg"
        title="Edit metadata"
        description="Changes are written into the audio file tags and the folder is renamed according to your template."
        footer={
          <>
            <Button icon={<Globe className="size-4" />} onClick={() => setLookup(true)} className="mr-auto">
              Find online
            </Button>
            <Button onClick={() => setEditing(false)}>Cancel</Button>
            <Button variant="primary" loading={update.isPending} onClick={() => void saveMetadata()}>
              Save
            </Button>
          </>
        }
      >
        <MetadataForm value={draft} onChange={(patch) => setDraft({ ...draft, ...patch })} />
      </Modal>

      <MetadataLookup
        open={lookup}
        onClose={() => setLookup(false)}
        initial={{ title: book.title, author: book.author, isbn: book.isbn }}
        onApply={async (patch, coverUrl) => {
          if (editing) {
            setDraft({ ...draft, ...patch });
          } else {
            await update.mutateAsync(patch);
          }
          if (coverUrl) refresh(await api.bookCoverFromUrl(book.id, coverUrl));
          feedback.success("Metadata applied");
        }}
      />
    </div>
  );
}

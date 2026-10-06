import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, BookOpen, Clock, Download, FolderSync, Headphones, Mic2, Play, Sparkles, Users, Wand2 } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { BookCard } from "../components/BookCard";
import { Cover } from "../components/Cover";
import { useFeedback } from "../components/feedback";
import { ProjectStatusBadge } from "../components/StatusBadge";
import { Button, Card, LoadingBlock, ProgressBar, Stat } from "../components/ui";
import { useEngines } from "../components/VoicePicker";
import { api } from "../lib/api";
import { formatDuration, formatNumber, timeAgo } from "../lib/format";
import { usePlayer } from "../player/PlayerContext";

function SetupBanner() {
  const engines = useEngines();
  const feedback = useFeedback();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const download = useMutation({
    mutationFn: () => api.downloadModel("kokoro", "kokoro-v1.0"),
    onSuccess: () => {
      feedback.success("Downloading Kokoro voices – follow the progress in the queue.");
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      navigate("/queue");
    },
    onError: feedback.error,
  });
  const neural = engines.data?.filter((e) => (e.id === "kokoro" || e.id === "piper") && e.ready) ?? [];
  if (!engines.data || neural.length) return null;
  return (
    <div className="relative mb-8 overflow-hidden rounded-2xl bg-gradient-to-br from-brand-600 via-violet-600 to-indigo-700 p-6 text-white shadow-xl shadow-brand-600/20 sm:p-8">
      <Sparkles className="absolute -top-4 -right-4 size-40 opacity-10" />
      <div className="relative max-w-2xl">
        <h2 className="text-xl font-semibold sm:text-2xl">Install natural sounding voices</h2>
        <p className="mt-2 text-sm text-white/85 sm:text-base">
          Audiobook Studio works out of the box with the robotic eSpeak voice. For audiobook quality narration, download the
          Kokoro neural voice model (about 340 MB, runs fully offline on your CPU) or pick Piper voices for 40+ languages.
        </p>
        <div className="mt-5 flex flex-wrap gap-3">
          <Button
            size="lg"
            className="bg-white !text-brand-700 hover:bg-white/90"
            icon={<Download className="size-4" />}
            loading={download.isPending}
            onClick={() => download.mutate()}
          >
            Download Kokoro
          </Button>
          <Link to="/voices">
            <Button size="lg" variant="ghost" className="!text-white hover:!bg-white/15" icon={<Mic2 className="size-4" />}>
              Browse voices
            </Button>
          </Link>
        </div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats, refetchInterval: 15_000 });
  const jobs = useQuery({
    queryKey: ["jobs", "active"],
    queryFn: () => api.jobs("active"),
    refetchInterval: (q) => ((q.state.data?.length ?? 0) > 0 ? 2000 : 8000),
  });
  const player = usePlayer();

  if (stats.isLoading) return <LoadingBlock />;
  const data = stats.data;
  if (!data) return null;

  return (
    <div className="animate-fade-in">
      <div className="mb-8 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Welcome back</h1>
          <p className="mt-1 text-zinc-500 dark:text-zinc-400">
            {data.books
              ? `${formatNumber(data.books)} audiobooks · ${formatDuration(data.total_duration)} of listening`
              : "Let's create your first audiobook."}
          </p>
        </div>
        <div className="flex gap-2">
          <Link to="/library">
            <Button icon={<FolderSync className="size-4" />}>Library</Button>
          </Link>
          <Link to="/studio/new">
            <Button variant="primary" icon={<Wand2 className="size-4" />}>
              New audiobook
            </Button>
          </Link>
        </div>
      </div>

      <SetupBanner />

      <div className="mb-8 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Audiobooks" value={formatNumber(data.books)} icon={<BookOpen className="size-5" />} hint={`${data.added_this_week} added this week`} />
        <Stat label="Listening time" value={formatDuration(data.total_duration)} icon={<Clock className="size-5" />} hint={`${formatDuration(data.listened_seconds)} listened`} />
        <Stat label="Authors" value={formatNumber(data.authors)} icon={<Users className="size-5" />} hint={`${data.series} series`} />
        <Stat label="Words narrated" value={formatNumber(data.rendered_words)} icon={<Headphones className="size-5" />} hint={`${data.projects} studio projects`} />
      </div>

      {jobs.data && jobs.data.length > 0 && (
        <Card className="mb-8 p-5">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-semibold">In progress</h2>
            <Link to="/queue" className="text-sm font-medium text-brand-600 hover:underline dark:text-brand-400">
              Open queue
            </Link>
          </div>
          <div className="space-y-4">
            {jobs.data.slice(0, 4).map((job) => (
              <div key={job.id}>
                <div className="mb-1.5 flex items-center justify-between gap-3 text-sm">
                  <span className="truncate font-medium">{job.title}</span>
                  <span className="shrink-0 text-xs text-zinc-500 tabular-nums">
                    {job.status === "queued" ? "Queued" : `${Math.round(job.progress * 100)}%`}
                    {job.eta_seconds ? ` · ${formatDuration(job.eta_seconds)} left` : ""}
                  </span>
                </div>
                <ProgressBar value={job.progress} indeterminate={job.status === "queued"} />
                {job.message && <div className="mt-1 truncate text-xs text-zinc-500">{job.message}</div>}
              </div>
            ))}
          </div>
        </Card>
      )}

      {data.continue_listening.length > 0 && (
        <section className="mb-10">
          <h2 className="mb-4 text-lg font-semibold">Continue listening</h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {data.continue_listening.map((book) => (
              <Card key={book.id} className="flex items-center gap-3 p-3">
                <Link to={`/library/${book.id}`} className="w-16 shrink-0">
                  <Cover src={book.thumb_url} title={book.title} author={book.author} rounded="rounded-lg" />
                </Link>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-semibold">{book.title}</div>
                  <div className="truncate text-xs text-zinc-500">{book.author}</div>
                  <ProgressBar value={book.duration ? book.progress / book.duration : 0} className="mt-2" />
                  <div className="mt-1 text-[11px] text-zinc-500 tabular-nums">
                    {formatDuration(Math.max(0, book.duration - book.progress))} left
                  </div>
                </div>
                <button
                  onClick={() => player.play(book)}
                  aria-label={`Resume ${book.title}`}
                  className="flex size-10 shrink-0 items-center justify-center rounded-full bg-brand-600 text-white shadow-sm transition hover:bg-brand-500"
                >
                  <Play className="ml-0.5 size-4" fill="currentColor" />
                </button>
              </Card>
            ))}
          </div>
        </section>
      )}

      <section className="mb-10">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Recently added</h2>
          {data.recently_added.length > 0 && (
            <Link to="/library" className="inline-flex items-center gap-1 text-sm font-medium text-brand-600 hover:underline dark:text-brand-400">
              View library <ArrowRight className="size-4" />
            </Link>
          )}
        </div>
        {data.recently_added.length ? (
          <div className="grid grid-cols-2 gap-5 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6">
            {data.recently_added.slice(0, 12).map((book) => (
              <BookCard key={book.id} book={book} />
            ))}
          </div>
        ) : (
          <Card className="grid gap-6 p-6 sm:grid-cols-3">
            {[
              { icon: <Wand2 className="size-5" />, title: "1. Upload an ebook", text: "EPUB, PDF, Word, Kindle, FB2 or plain text. Chapters and metadata are detected automatically." },
              { icon: <Mic2 className="size-5" />, title: "2. Pick a voice", text: "Preview voices, adjust speed and pronunciation, give dialogue its own voice." },
              { icon: <Headphones className="size-5" />, title: "3. Listen anywhere", text: "Get a chaptered M4B or MP3s, neatly filed in your library and available as a podcast feed." },
            ].map((step) => (
              <div key={step.title}>
                <div className="mb-3 flex size-10 items-center justify-center rounded-xl bg-brand-100 text-brand-700 dark:bg-brand-500/15 dark:text-brand-300">
                  {step.icon}
                </div>
                <div className="font-semibold">{step.title}</div>
                <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">{step.text}</p>
              </div>
            ))}
          </Card>
        )}
      </section>

      {data.recent_projects.length > 0 && (
        <section className="grid gap-6 lg:grid-cols-3">
          <Card className="p-5 lg:col-span-2">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="font-semibold">Studio projects</h2>
              <Link to="/studio" className="text-sm font-medium text-brand-600 hover:underline dark:text-brand-400">
                All projects
              </Link>
            </div>
            <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {data.recent_projects.map((p) => (
                <Link key={p.id} to={`/studio/${p.id}`} className="flex items-center gap-3 py-2.5 hover:opacity-80">
                  <Cover src={p.cover_url} title={p.title} author={p.author} className="w-10 shrink-0" rounded="rounded-md" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{p.title}</div>
                    <div className="truncate text-xs text-zinc-500">
                      {p.author || "Unknown author"} · updated {timeAgo(p.updated_at)}
                    </div>
                  </div>
                  <ProjectStatusBadge status={p.status} />
                </Link>
              ))}
            </div>
          </Card>
          <Card className="p-5">
            <h2 className="mb-3 font-semibold">Top genres</h2>
            {data.top_genres.length ? (
              <div className="space-y-3">
                {data.top_genres.map((g) => (
                  <Link key={g.name} to={`/library?group=genre&genre=${encodeURIComponent(g.name)}`} className="block">
                    <div className="mb-1 flex justify-between text-sm">
                      <span>{g.name}</span>
                      <span className="text-zinc-500 tabular-nums">{g.count}</span>
                    </div>
                    <ProgressBar value={g.count / Math.max(1, data.books)} />
                  </Link>
                ))}
              </div>
            ) : (
              <p className="text-sm text-zinc-500">Add genres to your books to see them here.</p>
            )}
          </Card>
        </section>
      )}
    </div>
  );
}

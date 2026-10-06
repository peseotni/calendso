import { useQuery } from "@tanstack/react-query";
import {
  Layers,
  LayoutDashboard,
  Library,
  ListTodo,
  LogOut,
  Menu as MenuIcon,
  Mic2,
  Monitor,
  Moon,
  Search,
  Settings,
  SpellCheck,
  Sun,
  Wand2,
  X,
} from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { PlayerBar } from "../player/PlayerBar";
import { usePlayer } from "../player/PlayerContext";
import { IconButton, cn } from "./ui";

type Theme = "light" | "dark" | "system";

function applyTheme(theme: Theme) {
  const dark = theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

export function useTheme(): [Theme, (theme: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem("theme") as Theme) || "system");
  useEffect(() => {
    applyTheme(theme);
    localStorage.setItem("theme", theme);
    if (theme !== "system") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const listener = () => applyTheme("system");
    media.addEventListener("change", listener);
    return () => media.removeEventListener("change", listener);
  }, [theme]);
  return [theme, setTheme];
}

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/library", label: "Library", icon: Library },
  { to: "/studio", label: "Studio", icon: Wand2 },
  { to: "/queue", label: "Queue", icon: ListTodo, badge: true },
  { to: "/voices", label: "Voices", icon: Mic2 },
  { to: "/pronunciation", label: "Pronunciation", icon: SpellCheck },
  { to: "/collections", label: "Collections", icon: Layers },
  { to: "/settings", label: "Settings", icon: Settings },
];

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <img src="/favicon.svg" alt="" className="size-8" />
      <div className="leading-tight">
        <div className="text-sm font-semibold tracking-tight">Audiobook Studio</div>
        <div className="text-[11px] text-zinc-500 dark:text-zinc-400">Create · Organise · Listen</div>
      </div>
    </div>
  );
}

function ActiveJobsBadge() {
  const { data } = useQuery({
    queryKey: ["jobs", "active"],
    queryFn: () => api.jobs("active"),
    refetchInterval: (query) => ((query.state.data?.length ?? 0) > 0 ? 2000 : 8000),
  });
  if (!data?.length) return null;
  return (
    <span className="ml-auto inline-flex min-w-5 items-center justify-center rounded-full bg-brand-600 px-1.5 text-[11px] font-semibold text-white">
      {data.length}
    </span>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex h-full flex-col gap-6 px-4 py-5">
      <Logo />
      <ul className="flex flex-col gap-0.5">
        {NAV.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              end={item.end}
              onClick={onNavigate}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-300"
                    : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800/70 dark:hover:text-white",
                )
              }
            >
              <item.icon className="size-4.5" />
              {item.label}
              {item.badge && <ActiveJobsBadge />}
            </NavLink>
          </li>
        ))}
      </ul>
      <div className="mt-auto rounded-xl bg-gradient-to-br from-brand-600 to-indigo-600 p-4 text-white shadow-lg shadow-brand-600/20">
        <div className="text-sm font-semibold">Turn any ebook into an audiobook</div>
        <p className="mt-1 text-xs text-white/80">EPUB, PDF, Word, Kindle, FB2, Markdown and more.</p>
        <NavLink
          to="/studio/new"
          onClick={onNavigate}
          className="mt-3 inline-flex rounded-lg bg-white/15 px-3 py-1.5 text-xs font-semibold backdrop-blur hover:bg-white/25"
        >
          New audiobook →
        </NavLink>
      </div>
    </nav>
  );
}

export function Layout({ children, authEnabled, onLogout }: { children: ReactNode; authEnabled: boolean; onLogout: () => void }) {
  const [open, setOpen] = useState(false);
  const [theme, setTheme] = useTheme();
  const [search, setSearch] = useState("");
  const navigate = useNavigate();
  const location = useLocation();
  const player = usePlayer();

  useEffect(() => setOpen(false), [location.pathname]);

  const nextTheme: Record<Theme, Theme> = { light: "dark", dark: "system", system: "light" };
  const ThemeIcon = theme === "light" ? Sun : theme === "dark" ? Moon : Monitor;

  return (
    <div className="min-h-dvh">
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 border-r border-zinc-200 bg-white lg:block dark:border-zinc-800 dark:bg-zinc-900/60">
        <Sidebar />
      </aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-zinc-950/50 backdrop-blur-sm animate-fade-in" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 animate-slide-up border-r border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
            <IconButton label="Close menu" onClick={() => setOpen(false)} className="absolute top-4 right-3">
              <X className="size-5" />
            </IconButton>
            <Sidebar onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}
      <div className="lg:pl-64">
        <header className="sticky top-0 z-10 flex h-16 items-center gap-3 border-b border-zinc-200 bg-zinc-50/80 px-4 backdrop-blur sm:px-6 dark:border-zinc-800 dark:bg-zinc-950/80">
          <IconButton label="Open menu" onClick={() => setOpen(true)} className="lg:hidden">
            <MenuIcon className="size-5" />
          </IconButton>
          <form
            className="relative max-w-md flex-1"
            onSubmit={(e) => {
              e.preventDefault();
              navigate(`/library?q=${encodeURIComponent(search.trim())}`);
            }}
          >
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-zinc-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search your library…"
              className="input h-9 rounded-full bg-white pl-9 dark:bg-zinc-900"
            />
          </form>
          <div className="ml-auto flex items-center gap-1">
            <IconButton label={`Theme: ${theme}`} onClick={() => setTheme(nextTheme[theme])}>
              <ThemeIcon className="size-4.5" />
            </IconButton>
            {authEnabled && (
              <IconButton label="Sign out" onClick={onLogout}>
                <LogOut className="size-4.5" />
              </IconButton>
            )}
          </div>
        </header>
        <main className={cn("mx-auto max-w-[1600px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8", player.book ? "pb-32" : "pb-12")}>
          {children}
        </main>
      </div>
      <PlayerBar />
    </div>
  );
}

import { useQueryClient } from "@tanstack/react-query";
import { Lock } from "lucide-react";
import { useState } from "react";
import { Button } from "../components/ui";
import { api } from "../lib/api";

export default function Login() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const queryClient = useQueryClient();

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      await api.login(password);
      await queryClient.invalidateQueries();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-dvh items-center justify-center bg-gradient-to-br from-zinc-100 via-white to-brand-50 px-4 dark:from-zinc-950 dark:via-zinc-950 dark:to-brand-950/40">
      <form onSubmit={submit} className="card w-full max-w-sm animate-slide-up p-8">
        <div className="mb-6 flex flex-col items-center text-center">
          <img src="/favicon.svg" alt="" className="mb-4 size-14" />
          <h1 className="text-xl font-semibold">Audiobook Studio</h1>
          <p className="mt-1 text-sm text-zinc-500">Enter the password to continue.</p>
        </div>
        <label className="relative block">
          <Lock className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-zinc-400" />
          <input
            type="password"
            className="input pl-9"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
            autoComplete="current-password"
          />
        </label>
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
        <Button type="submit" variant="primary" className="mt-4 w-full" loading={loading} disabled={!password}>
          Sign in
        </Button>
      </form>
    </div>
  );
}

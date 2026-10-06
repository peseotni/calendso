import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { LoadingBlock } from "./components/ui";
import { api, setUnauthorizedHandler } from "./lib/api";
import BookDetail from "./pages/BookDetail";
import Collections from "./pages/Collections";
import Dashboard from "./pages/Dashboard";
import LibraryPage from "./pages/Library";
import Login from "./pages/Login";
import NewProject from "./pages/NewProject";
import NotFound from "./pages/NotFound";
import Pronunciation from "./pages/Pronunciation";
import ProjectEditor from "./pages/ProjectEditor";
import Queue from "./pages/Queue";
import SettingsPage from "./pages/Settings";
import Studio from "./pages/Studio";
import Voices from "./pages/Voices";

export default function App() {
  const queryClient = useQueryClient();
  const auth = useQuery({ queryKey: ["auth"], queryFn: api.authStatus, staleTime: 60_000 });

  useEffect(() => {
    setUnauthorizedHandler(() => queryClient.invalidateQueries({ queryKey: ["auth"] }));
  }, [queryClient]);

  if (auth.isLoading) return <LoadingBlock label="Starting Audiobook Studio…" />;
  if (auth.data?.enabled && !auth.data.authenticated) return <Login />;

  const logout = async () => {
    await api.logout();
    queryClient.clear();
    await queryClient.invalidateQueries({ queryKey: ["auth"] });
  };

  return (
    <Layout authEnabled={Boolean(auth.data?.enabled)} onLogout={logout}>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/library" element={<LibraryPage />} />
        <Route path="/library/:id" element={<BookDetail />} />
        <Route path="/studio" element={<Studio />} />
        <Route path="/studio/new" element={<NewProject />} />
        <Route path="/studio/:id" element={<ProjectEditor />} />
        <Route path="/queue" element={<Queue />} />
        <Route path="/voices" element={<Voices />} />
        <Route path="/pronunciation" element={<Pronunciation />} />
        <Route path="/collections" element={<Collections />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Layout>
  );
}

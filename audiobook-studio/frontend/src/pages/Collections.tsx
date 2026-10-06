import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Layers, MoreVertical, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useFeedback } from "../components/feedback";
import { Button, Card, EmptyState, Field, IconButton, LoadingBlock, Menu, MenuItem, Modal, PageHeader, cn } from "../components/ui";
import { api } from "../lib/api";
import type { Collection } from "../lib/types";

const COLORS = ["", "violet", "rose", "amber", "emerald", "sky"];
const COLOR_CLASSES: Record<string, string> = {
  "": "from-zinc-300 to-zinc-400 dark:from-zinc-700 dark:to-zinc-800",
  violet: "from-violet-400 to-indigo-500",
  rose: "from-rose-400 to-pink-500",
  amber: "from-amber-300 to-orange-500",
  emerald: "from-emerald-400 to-teal-500",
  sky: "from-sky-400 to-blue-500",
};

function Mosaic({ collection }: { collection: Collection }) {
  const ids = collection.cover_book_ids;
  if (!ids.length) {
    return (
      <div className={cn("flex aspect-[4/3] items-center justify-center rounded-xl bg-gradient-to-br text-white", COLOR_CLASSES[collection.color] ?? COLOR_CLASSES[""])}>
        <Layers className="size-10 opacity-80" />
      </div>
    );
  }
  return (
    <div className="grid aspect-[4/3] grid-cols-2 grid-rows-2 gap-1 overflow-hidden rounded-xl bg-zinc-200 dark:bg-zinc-800">
      {[0, 1, 2, 3].map((i) =>
        ids[i] ? (
          <img key={i} src={`/api/books/${ids[i]}/cover?size=thumb`} alt="" className="size-full object-cover" loading="lazy" />
        ) : (
          <div key={i} className={cn("bg-gradient-to-br", COLOR_CLASSES[collection.color] ?? COLOR_CLASSES[""])} />
        ),
      )}
    </div>
  );
}

export default function Collections() {
  const feedback = useFeedback();
  const queryClient = useQueryClient();
  const collections = useQuery({ queryKey: ["collections"], queryFn: api.collections });
  const [editing, setEditing] = useState<Partial<Collection> | null>(null);

  const save = useMutation({
    mutationFn: (value: Partial<Collection>) =>
      value.id
        ? api.updateCollection(value.id, { name: value.name!, description: value.description, color: value.color })
        : api.createCollection({ name: value.name!, description: value.description, color: value.color }),
    onSuccess: () => {
      setEditing(null);
      void queryClient.invalidateQueries({ queryKey: ["collections"] });
    },
    onError: feedback.error,
  });

  const remove = async (collection: Collection) => {
    const { confirmed } = await feedback.confirm({
      title: `Delete “${collection.name}”?`,
      message: "The books stay in your library.",
      danger: true,
      confirmLabel: "Delete",
    });
    if (!confirmed) return;
    await api.deleteCollection(collection.id).catch(feedback.error);
    void queryClient.invalidateQueries({ queryKey: ["collections"] });
  };

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Collections"
        icon={<Layers className="size-5" />}
        description="Group books into shelves like “Bedtime stories”, “Book club” or “Up next”."
        actions={
          <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setEditing({ name: "", description: "", color: "violet" })}>
            New collection
          </Button>
        }
      />
      {collections.isLoading ? (
        <LoadingBlock />
      ) : !collections.data?.length ? (
        <EmptyState
          icon={<Layers className="size-6" />}
          title="No collections yet"
          description="Create a collection, then add books from the library (select mode) or a book's page."
          action={
            <Button variant="primary" onClick={() => setEditing({ name: "", description: "", color: "violet" })}>
              Create collection
            </Button>
          }
        />
      ) : (
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
          {collections.data.map((collection) => (
            <Card key={collection.id} className="group p-3">
              <Link to={`/library?collection=${collection.id}`}>
                <Mosaic collection={collection} />
              </Link>
              <div className="mt-3 flex items-start gap-2 px-1">
                <Link to={`/library?collection=${collection.id}`} className="min-w-0 flex-1">
                  <div className="truncate font-semibold">{collection.name}</div>
                  <div className="truncate text-sm text-zinc-500">
                    {collection.book_count} book{collection.book_count === 1 ? "" : "s"}
                    {collection.description ? ` · ${collection.description}` : ""}
                  </div>
                </Link>
                <Menu
                  trigger={({ onClick }) => (
                    <IconButton label="Actions" onClick={onClick}>
                      <MoreVertical className="size-4" />
                    </IconButton>
                  )}
                >
                  {(close) => (
                    <>
                      <MenuItem icon={<Pencil />} onClick={() => (setEditing(collection), close())}>
                        Edit
                      </MenuItem>
                      <MenuItem icon={<Trash2 />} danger onClick={() => (close(), void remove(collection))}>
                        Delete
                      </MenuItem>
                    </>
                  )}
                </Menu>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Modal
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing?.id ? "Edit collection" : "New collection"}
        size="sm"
        footer={
          <>
            <Button onClick={() => setEditing(null)}>Cancel</Button>
            <Button variant="primary" disabled={!editing?.name?.trim()} loading={save.isPending} onClick={() => editing && save.mutate(editing)}>
              Save
            </Button>
          </>
        }
      >
        {editing && (
          <div className="space-y-4">
            <Field label="Name">
              <input className="input" value={editing.name ?? ""} onChange={(e) => setEditing({ ...editing, name: e.target.value })} autoFocus />
            </Field>
            <Field label="Description">
              <input className="input" value={editing.description ?? ""} onChange={(e) => setEditing({ ...editing, description: e.target.value })} />
            </Field>
            <Field label="Colour">
              <div className="flex gap-2">
                {COLORS.map((color) => (
                  <button
                    key={color || "none"}
                    onClick={() => setEditing({ ...editing, color })}
                    className={cn(
                      "size-8 rounded-full bg-gradient-to-br ring-offset-2 dark:ring-offset-zinc-900",
                      COLOR_CLASSES[color],
                      editing.color === color && "ring-2 ring-brand-500",
                    )}
                    aria-label={color || "default"}
                  />
                ))}
              </div>
            </Field>
          </div>
        )}
      </Modal>
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Metadata } from "../lib/types";
import { Field } from "./ui";

export const COMMON_GENRES = [
  "Fiction", "Literary Fiction", "Classics", "Science Fiction", "Fantasy", "Mystery", "Thriller", "Crime",
  "Horror", "Romance", "Historical Fiction", "Adventure", "Young Adult", "Children", "Humor", "Poetry",
  "Drama", "Biography", "Memoir", "History", "Science", "Philosophy", "Psychology", "Self-Help", "Business",
  "Religion", "Travel", "Nonfiction", "Short Stories", "Education",
];

const LANGUAGES = [
  ["en", "English"], ["en-US", "English (US)"], ["en-GB", "English (UK)"], ["de", "German"], ["fr", "French"],
  ["es", "Spanish"], ["it", "Italian"], ["pt", "Portuguese"], ["nl", "Dutch"], ["pl", "Polish"], ["ru", "Russian"],
  ["sv", "Swedish"], ["ja", "Japanese"], ["zh", "Chinese"], ["hi", "Hindi"],
];

export type MetadataValue = Partial<Metadata>;

export function MetadataForm({
  value,
  onChange,
  showNarrator = true,
}: {
  value: MetadataValue;
  onChange: (patch: MetadataValue) => void;
  showNarrator?: boolean;
}) {
  const facets = useQuery({ queryKey: ["facets"], queryFn: api.facets, staleTime: 60_000 });
  const genres = [...new Set([...(facets.data?.genre.map((g) => g.value) ?? []), ...COMMON_GENRES])];
  const text = (key: keyof Metadata) => ({
    value: (value[key] as string | undefined) ?? "",
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange({ [key]: e.target.value }),
  });

  return (
    <div className="grid gap-4 sm:grid-cols-6">
      <Field label="Title" className="sm:col-span-4">
        <input className="input" {...text("title")} />
      </Field>
      <Field label="Year" className="sm:col-span-2">
        <input className="input" inputMode="numeric" maxLength={10} {...text("year")} />
      </Field>
      <Field label="Subtitle" className="sm:col-span-6">
        <input className="input" {...text("subtitle")} />
      </Field>
      <Field label="Author(s)" hint="Separate several authors with commas" className="sm:col-span-3">
        <input className="input" list="author-options" {...text("author")} />
        <datalist id="author-options">
          {facets.data?.author.map((a) => <option key={a.value} value={a.value} />)}
        </datalist>
      </Field>
      {showNarrator && (
        <Field label="Narrator" className="sm:col-span-3">
          <input className="input" {...text("narrator")} />
        </Field>
      )}
      <Field label="Series" className="sm:col-span-4">
        <input className="input" list="series-options" {...text("series")} />
        <datalist id="series-options">
          {facets.data?.series.map((s) => <option key={s.value} value={s.value} />)}
        </datalist>
      </Field>
      <Field label="Book #" className="sm:col-span-2">
        <input className="input" inputMode="decimal" maxLength={8} {...text("series_index")} />
      </Field>
      <Field label="Genre" hint="Comma separated for several" className="sm:col-span-3">
        <input className="input" list="genre-options" {...text("genre")} />
        <datalist id="genre-options">
          {genres.map((g) => <option key={g} value={g} />)}
        </datalist>
      </Field>
      <Field label="Language" className="sm:col-span-3">
        <input className="input" list="language-options" {...text("language")} />
        <datalist id="language-options">
          {LANGUAGES.map(([code, name]) => (
            <option key={code} value={code}>
              {name}
            </option>
          ))}
        </datalist>
      </Field>
      <Field label="Publisher" className="sm:col-span-3">
        <input className="input" {...text("publisher")} />
      </Field>
      <Field label="ISBN" className="sm:col-span-3">
        <input className="input" {...text("isbn")} />
      </Field>
      <Field label="Tags" hint="Comma separated" className="sm:col-span-6">
        <input
          className="input"
          value={(value.tags ?? []).join(", ")}
          onChange={(e) => onChange({ tags: e.target.value.split(",").map((t) => t.trimStart()) })}
          onBlur={(e) =>
            onChange({
              tags: e.target.value
                .split(",")
                .map((t) => t.trim())
                .filter(Boolean),
            })
          }
        />
      </Field>
      <Field label="Description" className="sm:col-span-6">
        <textarea className="input min-h-28 resize-y" {...text("description")} />
      </Field>
    </div>
  );
}

import { Button } from "./ui";

export function SaveBar({
  visible,
  saving,
  onSave,
  onDiscard,
  label = "You have unsaved changes",
  extra,
}: {
  visible: boolean;
  saving?: boolean;
  onSave: () => void;
  onDiscard: () => void;
  label?: string;
  extra?: React.ReactNode;
}) {
  if (!visible) return null;
  return (
    <div className="sticky bottom-24 z-20 mt-6 flex animate-slide-up flex-wrap items-center gap-3 rounded-xl border border-zinc-200 bg-white/95 px-4 py-3 shadow-xl backdrop-blur dark:border-zinc-700 dark:bg-zinc-900/95">
      <span className="text-sm font-medium">{label}</span>
      <div className="ml-auto flex flex-wrap gap-2">
        {extra}
        <Button onClick={onDiscard}>Discard</Button>
        <Button variant="primary" onClick={onSave} loading={saving}>
          Save changes
        </Button>
      </div>
    </div>
  );
}

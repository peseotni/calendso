import { useEffect, useState } from "react";
import { Button, Modal } from "../../components/ui";
import { VoicePicker } from "../../components/VoicePicker";
import { splitVoiceRef } from "../../lib/format";
import type { ProjectDetail } from "../../lib/types";

/** Choose a different narrator for one or more chapters (stored as "engine:voice"). */
export function ChapterVoiceModal({
  project,
  chapterIds,
  onClose,
  onSave,
}: {
  project: ProjectDetail;
  chapterIds: number[];
  onClose: () => void;
  /** Resolves to true when the change was saved; an empty voice resets to the project voice. */
  onSave: (voice: string) => Promise<boolean>;
}) {
  const open = chapterIds.length > 0;
  const chapters = project.chapters.filter((c) => chapterIds.includes(c.id));
  const first = chapters[0];
  const hasOverride = chapters.some((c) => c.voice);
  const [engine, setEngine] = useState(project.settings.engine);
  const [voice, setVoice] = useState(project.settings.voice);
  const [saving, setSaving] = useState<"voice" | "reset" | null>(null);

  useEffect(() => {
    if (!open) return;
    const current = first?.voice ? splitVoiceRef(first.voice, project.settings.engine) : project.settings;
    setEngine(current.engine);
    setVoice(current.voice);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async (value: string, kind: "voice" | "reset") => {
    setSaving(kind);
    try {
      if (await onSave(value)) onClose();
    } finally {
      setSaving(null);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={chapterIds.length > 1 ? `Voice for ${chapterIds.length} chapters` : `Voice for “${first?.title ?? ""}”`}
      description="Use a different narrator here, e.g. for a prologue, letters or an interlude. Other settings (speed, pauses) stay the same."
      footer={
        <>
          {hasOverride && (
            <Button className="mr-auto" onClick={() => void save("", "reset")} loading={saving === "reset"} disabled={saving !== null}>
              Use project voice
            </Button>
          )}
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            onClick={() => void save(`${engine}:${voice}`, "voice")}
            loading={saving === "voice"}
            disabled={!voice || saving !== null}
          >
            Use this voice
          </Button>
        </>
      }
    >
      <VoicePicker
        engine={engine}
        voice={voice}
        speed={project.settings.speed}
        language={project.settings.language || project.language}
        onChange={(nextEngine, nextVoice) => {
          setEngine(nextEngine);
          setVoice(nextVoice);
        }}
      />
    </Modal>
  );
}

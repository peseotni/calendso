import { CheckCircle2, CircleAlert, Clock, Loader2, Pencil } from "lucide-react";
import type { JobStatus, ProjectStatus } from "../lib/types";
import { Badge, type BadgeColor } from "./ui";

const PROJECT: Record<ProjectStatus, { label: string; color: BadgeColor; icon: React.ReactNode }> = {
  importing: { label: "Importing", color: "blue", icon: <Loader2 className="size-3 animate-spin" /> },
  ready: { label: "Draft", color: "gray", icon: <Pencil className="size-3" /> },
  queued: { label: "Queued", color: "amber", icon: <Clock className="size-3" /> },
  rendering: { label: "Narrating", color: "brand", icon: <Loader2 className="size-3 animate-spin" /> },
  done: { label: "Done", color: "green", icon: <CheckCircle2 className="size-3" /> },
  error: { label: "Error", color: "red", icon: <CircleAlert className="size-3" /> },
};

export function ProjectStatusBadge({ status }: { status: ProjectStatus }) {
  const info = PROJECT[status] ?? PROJECT.ready;
  return (
    <Badge color={info.color} icon={info.icon}>
      {info.label}
    </Badge>
  );
}

const JOB: Record<JobStatus, { label: string; color: BadgeColor }> = {
  queued: { label: "Queued", color: "amber" },
  running: { label: "Running", color: "brand" },
  done: { label: "Done", color: "green" },
  error: { label: "Failed", color: "red" },
  cancelled: { label: "Cancelled", color: "gray" },
};

export function JobStatusBadge({ status }: { status: JobStatus }) {
  const info = JOB[status];
  return (
    <Badge color={info.color} icon={status === "running" ? <Loader2 className="size-3 animate-spin" /> : undefined}>
      {info.label}
    </Badge>
  );
}

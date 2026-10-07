const WORKSPACE_NAMES: Record<string, string> = { ws_local: "Yerel", ws_demo: "Örnek" };

export function formatWorkspaceName(id: string, name?: string | null): string {
  if (name?.trim()) return name.trim();
  if (WORKSPACE_NAMES[id]) return WORKSPACE_NAMES[id];
  const cleaned = id.replace(/^ws_/, "").replace(/[-_]+/g, " ").trim();
  if (!cleaned) return id;
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

export type WorkspaceItem = {
  id: string;
  name?: string;
  documents: number;
};
export type Screen = "summary" | "questions" | "collections" | "documents" | "settings" | "try" | "jobs" | "providers" | "contract" | "detail";

export type UploadPhase =
  | "idle"
  | "waiting"
  | "hashing"
  | "registering"
  | "uploading"
  | "confirming"
  | "queued"
  | "running"
  | "done"
  | "partial"
  | "failed"
  | "error";
export type UploadState = {
  id?: string;
  phase: UploadPhase;
  fileName?: string;
  message?: string;
  jobId?: string;
};
export type DocumentRow = {
  id: string;
  versionId?: string;
  jobId?: string;
  title: string;
  file: string;
  type: string;
  status: string;
  version: string;
  pages: number;
  updated: string;
  versionCount: number;
};

export type Mode = "live" | "demo";

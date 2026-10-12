export type WorkspaceModelSettings = {
  enabled: boolean;
  base_url: string;
  model: string;
  credential_id: string;
  credential_ready: boolean;
  settings_version: number;
  reasoning_effort?: "none" | "minimal" | "low" | "medium" | "high" | null;
  max_tokens?: number | null;
};

export type CredentialProfile = { id: string; label: string; ready: boolean };
export type WorkspaceModelUpdate = Pick<WorkspaceModelSettings, "enabled" | "base_url" | "model" | "credential_id" | "reasoning_effort" | "max_tokens">;
export type WorkspaceSettingsProps = {
  apiUrl: string;
  workspaceId: string;
  mode: "live" | "demo";
  onSaved?: (settings: WorkspaceModelSettings) => void;
};

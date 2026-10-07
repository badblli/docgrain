export type WorkspaceModelSettings = {
  enabled: boolean;
  base_url: string;
  model: string;
  credential_id: string;
  credential_ready: boolean;
  settings_version: number;
};

export type CredentialProfile = { id: string; label: string; ready: boolean };
export type WorkspaceModelUpdate = Pick<WorkspaceModelSettings, "enabled" | "base_url" | "model" | "credential_id">;
export type WorkspaceSettingsProps = {
  apiUrl: string;
  workspaceId: string;
  mode: "live" | "demo";
  onSaved?: (settings: WorkspaceModelSettings) => void;
};

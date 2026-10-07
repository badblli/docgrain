export type TrySource = {
  id: string;
  document_name: string;
  locator: string;
  quote: string;
  document_id: string;
  source_version_id: string;
  knowledge_revision_id: string;
};

export type TryAnswer = {
  answer: string;
  abstained: boolean;
  workspace_id: string;
  revision_id: string;
  mode: "approved";
  sources: TrySource[];
};

export type TryProps = {
  apiUrl: string;
  workspaceId: string;
  mode: "live" | "demo" | null;
};

export type ModelState = {
  enabled: boolean;
  base_url: string;
  model: string;
  credential_ready: boolean;
};

export type PublishedListing = {
  workspace_id: string;
  revision_id: string;
  mode: "approved";
  collections: { key: string; record_count: number }[];
};

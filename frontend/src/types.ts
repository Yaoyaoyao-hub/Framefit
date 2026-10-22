export type NormBox = { x: number; y: number; width: number; height: number };

export type Item = NormBox & {
  id: string;
  frame_id: string;
  category_prompt: string;
  category: string;
  label: string;
  confidence: number | null;
  crop_url: string | null;
  manual: boolean;
};

export type Frame = {
  id: string;
  session_id: string | null;
  image_url: string;
  width: number;
  height: number;
  source_url: string | null;
  source_kind: string;
  created_at: string;
  items: Item[];
};

export type ProductSnapshot = {
  title: string;
  source: string | null;
  url: string;
  price: number | null;
  currency: string | null;
  result_type: "product" | "similar_style";
  image_asset_id?: string;
};

export type Version = {
  id: string;
  session_id: string;
  parent_version_id: string | null;
  asset_id: string;
  image_url: string;
  created_at: string;
  category: string | null;
  label: string;
  origin: "root" | "inspiration" | "product";
  is_root: boolean;
  product: ProductSnapshot | null;
};

export type SessionDetail = {
  id: string;
  created_at: string;
  revision: number;
  image_url: string;
  width: number;
  height: number;
  root_version_id: string;
  active_version_id: string;
  active_job_id: string | null;
  unseen_result_version_id: string | null;
  versions: Version[];
  frames?: Frame[];
};

export type SessionSummary = {
  id: string;
  created_at: string;
  image_url: string;
  active_version_id: string;
};

export type Job = {
  id: string;
  session_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "interrupted";
  origin: string;
  category: string;
  source_version_id: string;
  result_version_id: string | null;
  applied_to_active: boolean;
  error_message: string | null;
  retryable: boolean;
  provider: string | null;
};

export type SearchResult = {
  title: string;
  source: string | null;
  image: string | null;
  thumbnail: string | null;
  url: string;
  price: number | null;
  currency: string | null;
  result_type: "product" | "similar_style";
};

export type Capabilities = {
  mode: "demo" | "mixed" | "real";
  demo_data: boolean;
  disclosure: string;
  detection: { available: boolean; source: string; detail: string | null };
  try_on: { available: boolean; source: string; reason: string | null };
  search: { available: boolean; source: string; reason: string | null };
  categories: Record<string, { adapter: string; gender_required: boolean; styles: string[]; change_shoes: boolean }>;
  reference_kind: "crop" | "frame";
  prompts: string[];
  limits: { max_upload_bytes: number; max_generations_per_session: number; max_storage_bytes: number };
  external_processing: string;
};

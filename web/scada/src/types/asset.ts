export interface ControlItem {
  displayName: string;
  image: string;
  width: number;
  height: number;
}

export interface ControlCandidate {
  displayName: string;
  image: string;
  width: number;
  height: number;
  similarity: number;
  source: string;
}

export interface KeywordResult {
  keyword: string;
  candidates: ControlCandidate[];
  canGenerate: boolean;
}

export type GenerationStatusValue =
  | "queued"
  | "running"
  | "ready"
  | "failed"
  | "confirmed"
  | "discarded"
  | "expired";

export interface GenerationCreateRequest {
  query: string;
  name: string;
}

export interface GenerationCreateResponse {
  generation_id: string;
  status: GenerationStatusValue;
}

export interface GenerationStatusResponse {
  generation_id: string;
  name: string;
  status: GenerationStatusValue;
  seed: number | null;
  created_at: string | null;
  expires_at: string | null;
  preview_url: string | null;
  error: string | null;
  error_code: string | null;
}

export interface GenerationState {
  generationId: string | null;
  status: GenerationStatusValue;
  seed: number | null;
  previewUrl: string | null;
  error: string | null;
}

export interface ControlSearchRequest {
  query: string;
}

export interface ControlSearchResponse {
  keywords: KeywordResult[];
  missed: string[];
}

export interface MaterialItem {
  displayName: string;
  image: string;
  width: number;
  height: number;
  source: string;
  similarity: number;
}

export interface MaterialListResponse {
  total: number;
  items: MaterialItem[];
}

export interface ApiResponse<T = unknown> {
  code: number;
  message: string;
  data: T;
}

export type PipelineStepStatus = "wait" | "run" | "done" | "skip";

export interface PipelineStep {
  id: number;
  name: string;
  detail: string;
  status: PipelineStepStatus;
}

export interface AssetQueryResult {
  entities: {
    deviceType: string;
    state: string;
  };
  rewrite: string;
  matches: ControlItem[];
  missed: string[];
}
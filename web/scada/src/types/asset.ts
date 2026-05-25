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
  count: number;
  candidates: ControlCandidate[];
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
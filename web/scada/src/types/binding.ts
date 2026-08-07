import type { LayoutJsonData } from "./layout";

export interface BindingRequestRow {
  row_number: number;
  displayName: string;
  propertyName: string;
}

export interface BindingPreviewResponse {
  encoding: string;
  total_rows: number;
  requests: BindingRequestRow[];
}

export interface BindingCandidate {
  binding_id: string;
  propertyName: string;
  projectName: string;
  deviceName: string;
  dataType: string;
  writable: boolean;
  unit: string;
  score: number;
  evidence: string[];
}

export interface BindingTarget {
  node_i: number;
  node_id: unknown;
  displayName: string;
  handler: string;
  existing: unknown;
}

export interface BindingPanelItem {
  label: string;
  bind: {
    type: "designer";
    path: string;
    key: string;
    label: string;
    proj: { id: string; name: string };
    dev: { id: string; name: string };
    param: {
      id: string;
      name: string;
      unit: string;
      writable: boolean;
      dataType: string;
      dataTypeDesc: string;
    };
  };
}

export interface BindingMatchItem {
  row_number: number;
  target_node_i: number | null;
  requested_displayName: string;
  requested_propertyName: string;
  candidates: BindingCandidate[];
  suggested_binding_id: string | null;
  lead: number;
  confidence: string;
}

export interface BindingMatchResponse {
  targets: BindingTarget[];
  items: BindingMatchItem[];
  blocked: boolean;
  errors: string[];
}

export interface BindingAssignment {
  row_number: number;
  binding_id: string;
}

export interface BindingBuildPreview {
  node_i: number;
  displayName: string;
  handler: string;
  before: unknown;
  after: BindingPanelItem[];
}

export interface BindingBuildResponse {
  bound_json: LayoutJsonData | null;
  previews: BindingBuildPreview[];
  errors: string[];
  warnings: string[];
}

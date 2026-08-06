import type { LayoutJsonData } from "./layout";

export interface BindingProperty {
  projectId: string;
  projectName: string;
  deviceId: string;
  deviceName: string;
  propertyId: string;
  propertyName: string;
  dataType: string;
  writable: boolean;
  unit: string;
  dataTypeDesc: string;
}

export interface BindingColumnSuggestion {
  field: string;
  column: string | number | null;
  source: "exact" | "fuzzy";
}

export interface BindingColumnAmbiguity {
  column: string | number | null;
  header: string;
  matched_fields: string[];
  detail: string;
}

export interface BindingMapping {
  suggestions: BindingColumnSuggestion[];
  ambiguities: BindingColumnAmbiguity[];
  missing: string[];
}

export interface BindingPreviewResponse {
  encoding: string;
  headers: string[];
  total_rows: number;
  rows: string[][];
  mapping: BindingMapping;
}

export interface BindingNormalizeResponse {
  properties: BindingProperty[];
  errors: string[];
  blocked: boolean;
  blocking: string[];
}

export interface BindingCandidate {
  projectId: string;
  projectName: string;
  deviceId: string;
  deviceName: string;
  propertyId: string;
  propertyName: string;
  dataType: string;
  writable: boolean;
  unit: string;
  dataTypeDesc: string;
  device_name_similarity: number;
  property_name_similarity: number;
  score: number;
  lead: number;
  confidence: string;
  evidence: string[];
  key: string;
}

export interface BindingExpectation {
  id: string;
  displayName: string;
  deviceName: string;
  property: string;
  dataType: string;
  writable: boolean;
  required: boolean;
  path: string;
  label: string;
}

export interface BindingPanel {
  node_i: number;
  node_id: string;
  displayName: string;
  instance: number;
  existing_panel_list: BindingPanelItem[] | null;
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
  panel_node_i: number;
  panel_displayName: string;
  panel_instance: number;
  expectation_id: string;
  expectation_property: string;
  expectation_required: boolean;
  candidates: BindingCandidate[];
  suggested: string | null;
  confidence: string;
  confirmed: boolean;
}

export interface BindingMatchResponse {
  panels: BindingPanel[];
  expectations: BindingExpectation[];
  items: BindingMatchItem[];
}

export interface BindingAssignment {
  panel_node_i: number;
  expectation_id: string;
  candidate: BindingProperty;
}

export interface BindingBuildPreview {
  node_i: number;
  displayName: string;
  instance: number;
  panel_list: BindingPanelItem[];
  has_existing: boolean;
}

export interface BindingBuildResponse {
  bound_json: LayoutJsonData | null;
  previews: BindingBuildPreview[];
  errors: string[];
  warnings: string[];
}

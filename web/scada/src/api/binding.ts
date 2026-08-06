import { post, postForm } from "./client.ts";
import type {
  BindingAssignment,
  BindingBuildResponse,
  BindingMatchResponse,
  BindingNormalizeResponse,
  BindingPreviewResponse,
  BindingProperty,
} from "../types/binding";
import type { LayoutJsonData } from "../types/layout";

export interface BindingColumnMapping {
  field: string;
  column: string | number | null;
}

export function previewCsv(file: File): Promise<BindingPreviewResponse> {
  const form = new FormData();
  form.append("file", file);
  return postForm<BindingPreviewResponse>("/api/binding/csv/preview", form);
}

export function normalizeCsv(
  file: File,
  mapping: BindingColumnMapping[]
): Promise<BindingNormalizeResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("mapping", JSON.stringify(mapping));
  return postForm<BindingNormalizeResponse>("/api/binding/csv/normalize", form);
}

export function matchBinding(
  jsonData: LayoutJsonData,
  properties: BindingProperty[]
): Promise<BindingMatchResponse> {
  return post<BindingMatchResponse>("/api/binding/match", {
    json_data: jsonData,
    properties,
  });
}

export function buildBinding(
  jsonData: LayoutJsonData,
  properties: BindingProperty[],
  assignments: BindingAssignment[]
): Promise<BindingBuildResponse> {
  return post<BindingBuildResponse>("/api/binding/build", {
    json_data: jsonData,
    properties,
    assignments,
  });
}

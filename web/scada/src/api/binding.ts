import { post, postForm } from "./client.ts";
import type {
  BindingAssignment,
  BindingBuildResponse,
  BindingMatchResponse,
  BindingPreviewResponse,
  BindingRequestRow,
} from "../types/binding";
import type { LayoutJsonData } from "../types/layout";

export function previewCsv(file: File): Promise<BindingPreviewResponse> {
  const form = new FormData();
  form.append("file", file);
  return postForm<BindingPreviewResponse>("/api/binding/csv/preview", form);
}

export function matchBinding(
  jsonData: LayoutJsonData,
  requests: BindingRequestRow[]
): Promise<BindingMatchResponse> {
  return post<BindingMatchResponse>("/api/binding/match", {
    json_data: jsonData,
    requests,
  });
}

export function buildBinding(
  jsonData: LayoutJsonData,
  requests: BindingRequestRow[],
  assignments: BindingAssignment[]
): Promise<BindingBuildResponse> {
  return post<BindingBuildResponse>("/api/binding/build", {
    json_data: jsonData,
    requests,
    assignments,
  });
}

import { get, post, del } from "./client";
import type { MaterialListResponse } from "../types/asset";

export function listMaterials(): Promise<MaterialListResponse> {
  return get<MaterialListResponse>("/api/material/list");
}

export function getQueryResults(): Promise<MaterialListResponse> {
  return get<MaterialListResponse>("/api/material/query-results");
}

export function saveQueryResults(query: string, controls: { displayName: string; image: string; width: number; height: number; similarity: number; source: string }[]): Promise<{ saved: number }> {
  return post<{ saved: number }>("/api/material/query-results", { query, controls });
}

export function clearQueryResults(): Promise<{ cleared: boolean }> {
  return del<{ cleared: boolean }>("/api/material/query-results");
}
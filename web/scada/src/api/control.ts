import { post } from "./client";
import type { ControlSearchResponse } from "../types/asset";

export function searchControls(query: string): Promise<ControlSearchResponse> {
  return post<ControlSearchResponse>("/api/control/search", { query });
}
import { post, get, del } from "./client.ts";
import type {
  GenerationCreateResponse,
  GenerationStatusResponse,
  MaterialItem,
} from "../types/asset.ts";

export function createGeneration(query: string, name: string): Promise<GenerationCreateResponse> {
  return post<GenerationCreateResponse>(
    "/api/control/generations",
    { query, name }
  );
}

export function getGeneration(generationId: string): Promise<GenerationStatusResponse> {
  return get<GenerationStatusResponse>(`/api/control/generations/${generationId}`);
}

export function regenerateGeneration(generationId: string): Promise<GenerationCreateResponse> {
  return post<GenerationCreateResponse>(`/api/control/generations/${generationId}/regenerate`, {});
}

export function confirmGeneration(generationId: string): Promise<MaterialItem> {
  return post<MaterialItem>(`/api/control/generations/${generationId}/confirm`, {});
}

export function discardGeneration(generationId: string): Promise<void> {
  return del<void>(`/api/control/generations/${generationId}`);
}

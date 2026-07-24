import { post } from "./client";

export interface ValidationErrorItem {
  path: string;
  message: string;
  error_type: string;
}

export interface ValidateResponse {
  valid: boolean;
  summary: string;
  errors: ValidationErrorItem[];
  warnings: ValidationErrorItem[];
}

export function validateRequest(category: string, jsonData: Record<string, unknown>): Promise<ValidateResponse> {
  return post<ValidateResponse>("/api/validate", { category, json_data: jsonData });
}
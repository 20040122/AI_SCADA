import { get, post } from "./client";

export interface ValidationItem {
  path: string;
  message: string;
  error_type: string;
  source: string;
}

export interface ValidateResponse {
  valid: boolean;
  summary: string;
  errors: ValidationItem[];
  warnings: ValidationItem[];
}

export function validateRequest(category: string, jsonData: Record<string, unknown>): Promise<ValidateResponse> {
  return post<ValidateResponse>("/api/validate", { category, json_data: jsonData });
}

export interface RuleProperty {
  path: string;
  type: string;
  required: boolean;
  description: string;
  enum?: string[];
}

export interface RuleCategoryMeta {
  category: string;
  label: string;
  title: string;
  description: string;
  properties: RuleProperty[];
  derived_rules: string[];
  sample_valid: Record<string, unknown>;
  sample_invalid: Record<string, unknown>;
}

export interface RulesResponse {
  categories: RuleCategoryMeta[];
}

export function getRules(): Promise<RulesResponse> {
  return get<RulesResponse>("/api/validate/rules");
}

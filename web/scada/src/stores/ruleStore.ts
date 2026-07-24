import { create } from "zustand";
import type { ValidateResponse } from "../api/validate";
import { validateRequest } from "../api/validate";

interface RuleStore {
  activeCategory: string;
  validatorInput: string;
  result: ValidateResponse | null;
  loading: boolean;
  error: string | null;
  setActiveCategory: (id: string) => void;
  setValidatorInput: (input: string) => void;
  runValidate: (category: string) => Promise<void>;
}

export const useRuleStore = create<RuleStore>((set) => ({
  activeCategory: "control",
  validatorInput: "",
  result: null,
  loading: false,
  error: null,

  setActiveCategory: (id: string) => set({ activeCategory: id }),

  setValidatorInput: (input: string) => set({ validatorInput: input }),

  runValidate: async (category: string) => {
    set({ loading: true, error: null, result: null });
    try {
      let jsonData: Record<string, unknown>;
      try {
        jsonData = JSON.parse(useRuleStore.getState().validatorInput);
      } catch {
        set({ loading: false, error: "JSON 格式错误，请检查输入" });
        return;
      }
      const result = await validateRequest(category, jsonData);
      set({ result, loading: false });
    } catch (err) {
      set({ loading: false, error: err instanceof Error ? err.message : "校验请求失败" });
    }
  },
}));
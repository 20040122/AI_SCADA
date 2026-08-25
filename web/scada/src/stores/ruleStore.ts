import { create } from "zustand";
import type { RuleCategoryMeta, ValidateResponse } from "../api/validate";
import { getRules, validateRequest } from "../api/validate";

interface RuleStore {
  activeCategory: string;
  validatorInput: string;
  result: ValidateResponse | null;
  loading: boolean;
  error: string | null;
  categories: RuleCategoryMeta[];
  categoriesLoaded: boolean;
  setActiveCategory: (id: string) => void;
  setValidatorInput: (input: string) => void;
  runValidate: (category: string) => Promise<void>;
  loadCategories: () => Promise<void>;
}

export const useRuleStore = create<RuleStore>((set) => ({
  activeCategory: "control",
  validatorInput: "",
  result: null,
  loading: false,
  error: null,
  categories: [],
  categoriesLoaded: false,

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

  loadCategories: async () => {
    set({ loading: true, error: null });
    try {
      const response = await getRules();
      const active = useRuleStore.getState().activeCategory;
      const exists = response.categories.some((c) => c.category === active);
      set({
        categories: response.categories,
        categoriesLoaded: true,
        activeCategory: exists ? active : response.categories[0]?.category ?? "control",
        loading: false,
      });
    } catch (err) {
      set({
        loading: false,
        error: err instanceof Error ? err.message : "规则加载失败",
        categoriesLoaded: true,
      });
    }
  },
}));

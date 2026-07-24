import { create } from "zustand";
import type {
  KeywordResult,
  MaterialItem,
  PipelineStep,
  PipelineStepStatus,
} from "../types/asset";

const INITIAL_PIPELINE: PipelineStep[] = [
  { id: 1, name: "LLM 提取", detail: "从描述提取控件关键词", status: "wait" },
  { id: 2, name: "向量检索", detail: "ChromaDB 相似度匹配 (≥0.55)", status: "wait" },
  { id: 3, name: "质检入库", detail: "点击卡片确认后写入数据库", status: "wait" },
];

interface AssetStore {
  query: string;
  setQuery: (q: string) => void;

  materialLib: MaterialItem[];
  setMaterialLib: (items: MaterialItem[]) => void;

  keywordResults: KeywordResult[];
  setKeywordResults: (results: KeywordResult[]) => void;
  removeKeyword: (keyword: string) => void;

  missedKeywords: string[];
  setMissedKeywords: (kw: string[]) => void;

  queryResults: MaterialItem[];
  setQueryResults: (items: MaterialItem[]) => void;

  selectedAsset: MaterialItem | null;
  setSelectedAsset: (item: MaterialItem | null) => void;

  pipeline: PipelineStep[];
  setPipelineStep: (id: number, status: PipelineStepStatus) => void;
  resetPipeline: () => void;

  isLoading: boolean;
  setIsLoading: (v: boolean) => void;

  error: string | null;
  setError: (e: string | null) => void;

  activeTab: string;
  setActiveTab: (t: string) => void;
}

export const useAssetStore = create<AssetStore>((set) => ({
  query: "",
  setQuery: (q) => set({ query: q }),

  materialLib: [],
  setMaterialLib: (items) => set({ materialLib: items }),

  keywordResults: [],
  setKeywordResults: (results) => set({ keywordResults: results }),
  removeKeyword: (keyword: string) =>
    set((s) => ({
      keywordResults: s.keywordResults.filter((kr) => kr.keyword !== keyword),
    })),

  missedKeywords: [],
  setMissedKeywords: (kw) => set({ missedKeywords: kw }),

  queryResults: [],
  setQueryResults: (items) => set({ queryResults: items }),

  selectedAsset: null,
  setSelectedAsset: (item) => set({ selectedAsset: item }),

  pipeline: [...INITIAL_PIPELINE],
  setPipelineStep: (id, status) =>
    set((s) => ({
      pipeline: s.pipeline.map((step) =>
        step.id === id ? { ...step, status } : step
      ),
    })),
  resetPipeline: () => set({ pipeline: INITIAL_PIPELINE.map((s) => ({ ...s, status: "wait" as PipelineStepStatus })) }),

  isLoading: false,
  setIsLoading: (v) => set({ isLoading: v }),

  error: null,
  setError: (e) => set({ error: e }),

  activeTab: "asset",
  setActiveTab: (t) => set({ activeTab: t }),
}));
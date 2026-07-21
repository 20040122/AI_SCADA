import { create } from "zustand";
import type {
  CanvasNode,
  DecorationNode,
  LayoutGenerateResponse,
  LayoutJsonData,
  LayoutZone,
  QualityIssue,
  WorkflowStep,
} from "../types/layout";
import { extractDecorationsFromJsonData, extractNodesFromJsonData } from "../utils/layoutNodes";

const INITIAL_WORKFLOW: WorkflowStep[] = [
  { id: 1, name: "LLM 解析", detail: "从场景描述提取设备类型、数量、关系", status: "wait" },
  { id: 2, name: "布局计算", detail: "力导向算法 + 约束规则引擎", status: "wait" },
  { id: 3, name: "质检验证", detail: "重叠/溢出/Schema 规则校验", status: "wait" },
];

interface LayoutStore {
  query: string;
  title: string;
  canvasWidth: number;
  canvasHeight: number;

  jsonData: LayoutJsonData | null;
  zones: LayoutZone[];
  qualityIssues: QualityIssue[];
  missingControls: string[];

  nodes: CanvasNode[];
  decorations: DecorationNode[];

  workflow: WorkflowStep[];

  isLoading: boolean;
  error: string | null;

  fileName: string;

  setQuery: (q: string) => void;
  setTitle: (t: string) => void;
  setCanvasWidth: (w: number) => void;
  setCanvasHeight: (h: number) => void;
  setLayoutResult: (res: LayoutGenerateResponse) => void;
  setWorkflowStep: (id: number, status: WorkflowStep["status"]) => void;
  resetWorkflow: () => void;
  clearCanvas: () => void;
  setIsLoading: (v: boolean) => void;
  setError: (e: string | null) => void;
}

export const useLayoutStore = create<LayoutStore>((set) => ({
  query: "",
  title: "",
  canvasWidth: 1920,
  canvasHeight: 1080,

  jsonData: null,
  zones: [],
  qualityIssues: [],
  missingControls: [],

  nodes: [],
  decorations: [],

  workflow: INITIAL_WORKFLOW.map((s) => ({ ...s })),

  isLoading: false,
  error: null,

  fileName: "",

  setQuery: (q) => set({ query: q }),
  setTitle: (t) => set({ title: t }),
  setCanvasWidth: (w) => set({ canvasWidth: w }),
  setCanvasHeight: (h) => set({ canvasHeight: h }),
  setLayoutResult: (res) =>
    set({
      jsonData: res.json_data,
      zones: res.zones,
      qualityIssues: res.quality_issues,
      missingControls: res.missing_controls,
      nodes: extractNodesFromJsonData(res.json_data),
      decorations: extractDecorationsFromJsonData(res.json_data),
      fileName: res.file_name,
    }),

  setWorkflowStep: (id, status) =>
    set((s) => ({
      workflow: s.workflow.map((step) =>
        step.id === id ? { ...step, status } : step
      ),
    })),
  resetWorkflow: () =>
    set({ workflow: INITIAL_WORKFLOW.map((s) => ({ ...s })) }),

  clearCanvas: () =>
    set({
      jsonData: null,
      zones: [],
      qualityIssues: [],
      missingControls: [],
      nodes: [],
      decorations: [],
      fileName: "",
    }),

  setIsLoading: (v) => set({ isLoading: v }),
  setError: (e) => set({ error: e }),
}));

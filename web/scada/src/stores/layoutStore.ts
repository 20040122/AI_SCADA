import { create } from "zustand";
import type {
  CanvasNode,
  LayoutGenerateResponse,
  LayoutJsonData,
  LayoutZone,
  QualityIssue,
  WorkflowStep,
  ControlSpec,
} from "../types/layout";
import { extractNodesFromJsonData } from "../utils/layoutNodes";

const INITIAL_WORKFLOW: WorkflowStep[] = [
  { id: 1, name: "LLM 解析", detail: "从场景描述提取设备类型、数量、关系", status: "wait" },
  { id: 2, name: "布局计算", detail: "力导向算法 + 约束规则引擎", status: "wait" },
  { id: 3, name: "质检验证", detail: "重叠/溢出/Schema 规则校验", status: "wait" },
];

interface LayoutStore {
  query: string;
  canvasWidth: number;
  canvasHeight: number;

  jsonData: LayoutJsonData | null;
  zones: LayoutZone[];
  qualityIssues: QualityIssue[];
  missingControls: string[];

  nodes: CanvasNode[];

  workflow: WorkflowStep[];

  isLoading: boolean;
  error: string | null;

  controls: ControlSpec[];
  fileName: string;

  setQuery: (q: string) => void;
  setCanvasWidth: (w: number) => void;
  setCanvasHeight: (h: number) => void;
  setControls: (c: ControlSpec[]) => void;
  setLayoutResult: (res: LayoutGenerateResponse) => void;
  setWorkflowStep: (id: number, status: WorkflowStep["status"]) => void;
  resetWorkflow: () => void;
  clearCanvas: () => void;
  setIsLoading: (v: boolean) => void;
  setError: (e: string | null) => void;
}

export const useLayoutStore = create<LayoutStore>((set) => ({
  query: "",
  canvasWidth: 1000,
  canvasHeight: 800,

  jsonData: null,
  zones: [],
  qualityIssues: [],
  missingControls: [],

  nodes: [],

  workflow: INITIAL_WORKFLOW.map((s) => ({ ...s })),

  isLoading: false,
  error: null,

  controls: [],
  fileName: "",

  setQuery: (q) => set({ query: q }),
  setCanvasWidth: (w) => set({ canvasWidth: w }),
  setCanvasHeight: (h) => set({ canvasHeight: h }),
  setControls: (c) => set({ controls: c }),

  setLayoutResult: (res) =>
    set({
      jsonData: res.json_data,
      zones: res.zones,
      qualityIssues: res.quality_issues,
      missingControls: res.missing_controls,
      nodes: extractNodesFromJsonData(res.json_data),
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
      fileName: "",
    }),

  setIsLoading: (v) => set({ isLoading: v }),
  setError: (e) => set({ error: e }),
}));

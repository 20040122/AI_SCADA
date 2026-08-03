import { create } from "zustand";
import type {
  CanvasNode,
  DecorationNode,
  LayoutGenerateResponse,
  LayoutJsonData,
  LayoutZone,
  PipeData,
  QualityIssue,
  UploadCanvasResponse,
  UploadCorrection,
  WorkflowStep,
  WorkflowStatus,
} from "../types/layout.ts";
import { extractDecorationsFromJsonData, extractNodesFromJsonData } from "../utils/layoutNodes.ts";

const INITIAL_WORKFLOW: WorkflowStep[] = [
  { id: 1, name: "加载可用素材", detail: "读取 query_results，为空则生成失败", status: "wait" },
  { id: 2, name: "并行生成背景画布与布局意图 IR", detail: "生成背景画布与布局意图 IR", status: "wait" },
  { id: 3, name: "根据布局意图和素材计算设备坐标", detail: "根据布局意图和素材计算设备坐标", status: "wait" },
  { id: 4, name: "生成管线连接", detail: "生成管线连接", status: "wait" },
  { id: 5, name: "拼装最终 JSON 并完成 Schema 校验", detail: "拼装最终 JSON 并完成 Schema 校验", status: "wait" },
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
  pipe_data: PipeData | null;

  workflow: WorkflowStep[];
  workflowStatus: WorkflowStatus;

  isLoading: boolean;
  error: string | null;

  fileName: string;

  corrections: UploadCorrection[];
  uploadWarnings: string[];

  setQuery: (q: string) => void;
  setTitle: (t: string) => void;
  setCanvasWidth: (w: number) => void;
  setCanvasHeight: (h: number) => void;
  setLayoutResult: (res: LayoutGenerateResponse) => void;
  applyUploadResult: (res: UploadCanvasResponse) => void;
  setWorkflowStep: (id: number, status: WorkflowStep["status"]) => void;
  setWorkflowStatus: (s: WorkflowStatus) => void;
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
  pipe_data: null,

  workflow: INITIAL_WORKFLOW.map((s) => ({ ...s })),
  workflowStatus: "idle",

  isLoading: false,
  error: null,

  fileName: "",

  corrections: [],
  uploadWarnings: [],

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
      pipe_data: res.pipe_data ?? null,
      fileName: res.file_name,
      corrections: [],
      uploadWarnings: [],
    }),

  applyUploadResult: (res) =>
    set({
      jsonData: res.json_data,
      nodes: extractNodesFromJsonData(res.json_data),
      decorations: extractDecorationsFromJsonData(res.json_data),
      corrections: res.corrections,
      uploadWarnings: res.warnings,
    }),

  setWorkflowStep: (id, status) =>
    set((s) => ({
      workflow: s.workflow.map((step) =>
        step.id === id ? { ...step, status } : step
      ),
    })),
  setWorkflowStatus: (s) => set({ workflowStatus: s }),
  resetWorkflow: () =>
    set({ workflow: INITIAL_WORKFLOW.map((s) => ({ ...s })), workflowStatus: "idle" }),

  clearCanvas: () =>
    set({
      jsonData: null,
      zones: [],
      qualityIssues: [],
      missingControls: [],
      nodes: [],
      decorations: [],
      pipe_data: null,
      fileName: "",
      corrections: [],
      uploadWarnings: [],
      workflowStatus: "idle",
    }),

  setIsLoading: (v) => set({ isLoading: v }),
  setError: (e) => set({ error: e }),
}));

import type { JsonPatchOp } from "./refine";

export interface ControlSpec {
  displayName: string;
  image?: string;
  width?: number;
  height?: number;
}

export interface LayoutGenerateRequest {
  query: string;
  controls?: ControlSpec[];
  canvasWidth: number;
  canvasHeight: number;
  title: string;
}

export interface QualityIssue {
  severity: string;
  issue_type: string;
  message: string;
  controls: string[];
}

export interface LayoutZone {
  name: string;
  x: number;
  y: number;
  width: number;
  height: number;
  controls: string[];
}

export interface ContentRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface LayoutNodeData {
  c: string;
  i: number;
  p: {
    displayName?: string;
    image?: string;
    position?: { x: number; y: number };
    width?: number;
    height?: number;
  };
  s?: Record<string, unknown>;
  a?: Record<string, unknown>;
}

export interface DecorationNode {
  type: "image" | "text";
  image?: string;
  text?: string;
  x: number;
  y: number;
  width: number;
  height: number;
  displayName?: string;
  color?: string;
  fontSize?: string;
  fontWeight?: string;
  textAlign?: string;
  opacity?: number;
  verticalAlign?: string;
}

export interface LayoutJsonData {
  v: string;
  p: Record<string, unknown>;
  a: {
    width: number;
    height: number;
    fitContent?: boolean;
    rectSelectable?: boolean;
    zoomable?: boolean;
    pannable?: boolean;
  };
  d: LayoutNodeData[];
  contentRect?: ContentRect;
}

export interface LayoutGenerateResponse {
  json_data: LayoutJsonData;
  content_rect: ContentRect;
  quality_issues: QualityIssue[];
  zones: LayoutZone[];
  missing_controls: string[];
  file_name: string;
}

export interface RefineRequest {
  instruction: string;
  jsonData: LayoutJsonData;
  selectedNodeI?: number;
}

export interface RefineResponse {
  patch: JsonPatchOp[];
  message: string;
}

export interface WorkflowStep {
  id: number;
  name: string;
  detail: string;
  status: "wait" | "run" | "done" | "skip";
}

export interface CanvasNode {
  id: string;
  displayName: string;
  image: string;
  x: number;
  y: number;
  width: number;
  height: number;
  color: string;
}

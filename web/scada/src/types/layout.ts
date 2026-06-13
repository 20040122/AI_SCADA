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
    displayName: string;
    image?: string;
    position: { x: number; y: number };
    width?: number;
    height?: number;
  };
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
}

export interface RefineRequest {
  nodes: LayoutNodeData[];
  canvasWidth: number;
  canvasHeight: number;
}

export interface RefineResponse {
  nodes: LayoutNodeData[];
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

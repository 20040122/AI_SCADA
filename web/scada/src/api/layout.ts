import { post } from "./client.ts";
import { buildUploadBody } from "./uploadBody.ts";
import type { LayoutGenerateRequest, LayoutGenerateResponse, RefineRequest, RefineResponse, LayoutJsonData, PipeData, UploadCanvasResponse } from "../types/layout";

export function generateLayout(req: LayoutGenerateRequest): Promise<LayoutGenerateResponse> {
  return post<LayoutGenerateResponse>(
    "/api/canvas/layout",
    {
      query: req.query,
      title: req.title,
      canvas_width: req.canvasWidth,
      canvas_height: req.canvasHeight,
    },
    { timeoutMs: 120000 }
  );
}

export function refineLayout(req: RefineRequest): Promise<RefineResponse> {
  const body: Record<string, unknown> = {
    instruction: req.instruction,
    json_data: req.jsonData,
  };
  if (req.selectedNodeIds && req.selectedNodeIds.length > 0) {
    body.selected_node_ids = req.selectedNodeIds;
  } else if (req.selectedNodeI !== undefined) {
    body.selected_node_i = req.selectedNodeI;
  }
  return post<RefineResponse>("/api/canvas/refine", body);
}

export function uploadCanvas(fileName: string, jsonData: LayoutJsonData, pipeData?: PipeData | null): Promise<UploadCanvasResponse> {
  return post<UploadCanvasResponse>("/api/canvas/upload", buildUploadBody(fileName, jsonData, pipeData));
}

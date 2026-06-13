import { post } from "./client";
import type { LayoutGenerateRequest, LayoutGenerateResponse, RefineRequest, RefineResponse } from "../types/layout";

export function generateLayout(req: LayoutGenerateRequest): Promise<LayoutGenerateResponse> {
  return post<LayoutGenerateResponse>("/api/canvas/layout", {
    query: req.query,
    controls: req.controls,
    canvas_width: req.canvasWidth,
    canvas_height: req.canvasHeight,
  });
}

export function refineLayout(req: RefineRequest): Promise<RefineResponse> {
  return post<RefineResponse>("/api/canvas/refine", {
    nodes: req.nodes,
    canvas_width: req.canvasWidth,
    canvas_height: req.canvasHeight,
  });
}

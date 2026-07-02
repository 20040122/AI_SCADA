import { post } from "./client";
import type { LayoutGenerateRequest, LayoutGenerateResponse, RefineRequest, RefineResponse, LayoutJsonData } from "../types/layout";

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

const HMI_UPLOAD_URL = "http://daoscada.local/hmi-ui/upload/";

export async function uploadToSystem(jsonData: LayoutJsonData, fileName: string): Promise<void> {
  const formData = new FormData();
  formData.append("path", `displays/Agent/${fileName}`);
  formData.append("content", JSON.stringify(jsonData, null, 2));

  const res = await fetch(HMI_UPLOAD_URL, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`上传失败 (${res.status}): ${text}`);
  }
}

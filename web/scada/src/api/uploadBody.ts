import type { LayoutJsonData, PipeData } from "../types/layout";

export interface UploadBody {
  file_name: string;
  json_data: LayoutJsonData;
  pipe_data: PipeData;
}

export function buildUploadBody(
  fileName: string,
  jsonData: LayoutJsonData,
  pipeData?: PipeData | null
): UploadBody {
  return {
    file_name: fileName,
    json_data: jsonData,
    pipe_data: pipeData ?? { connections: [] },
  };
}

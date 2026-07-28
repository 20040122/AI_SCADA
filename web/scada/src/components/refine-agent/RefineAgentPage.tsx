import { useEffect } from "react";
import { useLayoutStore } from "../../stores/layoutStore";
import { useRefineStore } from "../../stores/refineStore";
import CenterPanel from "./CenterPanel";
import RightPanel from "./RightPanel";

export default function RefineAgentPage() {
  const layoutNodes = useLayoutStore((s) => s.nodes);
  const layoutJson = useLayoutStore((s) => s.jsonData);
  const layoutFileName = useLayoutStore((s) => s.fileName);
  const layoutPipes = useLayoutStore((s) => s.pipe_data);
  const {
    workingJson,
    sourceFileName,
    isRefining,
    pendingPatch,
    loadFromLayoutData,
  } = useRefineStore();

  useEffect(() => {
    if (
      !layoutJson ||
      !layoutFileName ||
      isRefining ||
      pendingPatch !== null ||
      (workingJson !== null && sourceFileName === layoutFileName)
    ) return;

    loadFromLayoutData(
      layoutNodes,
      layoutJson.a?.width || 1000,
      layoutJson.a?.height || 800,
      layoutJson,
      layoutFileName,
      layoutPipes
    );
  }, [
    isRefining,
    layoutFileName,
    layoutJson,
    layoutNodes,
    layoutPipes,
    loadFromLayoutData,
    pendingPatch,
    sourceFileName,
    workingJson,
  ]);

  return (
    <div className="flex flex-1 h-full overflow-hidden">
      <CenterPanel />
      <RightPanel />
    </div>
  );
}

import { useEffect } from "react";
import { useLayoutStore } from "../../stores/layoutStore";
import { useRefineStore } from "../../stores/refineStore";
import { resolveBindingSource, useBindingStore } from "../../stores/bindingStore";
import LeftPanel from "./LeftPanel";
import CenterPanel from "./CenterPanel";
import RightPanel from "./RightPanel";

export default function BindingAgentPage() {
  const layoutRevision = useLayoutStore((s) => s.revision);
  const layoutJson = useLayoutStore((s) => s.jsonData);
  const layoutFileName = useLayoutStore((s) => s.fileName);
  const layoutPipes = useLayoutStore((s) => s.pipe_data);

  const refineRevision = useRefineStore((s) => s.revision);
  const refineJson = useRefineStore((s) => s.workingJson);
  const refinePipes = useRefineStore((s) => s.workingPipes);
  const refineSourceFileName = useRefineStore((s) => s.sourceFileName);
  const refinePendingPatch = useRefineStore((s) => s.pendingPatch);

  const blocked = refinePendingPatch !== null ? "refine_pending" : null;

  useEffect(() => {
    const layout = useLayoutStore.getState();
    const refine = useRefineStore.getState();
    const sync = useBindingStore.getState().syncSource;

    const source = resolveBindingSource(layout, refine);
    if (!source) return;
    sync(source.sourceType, source.revision, source.canvas, source.pipes, source.fileName);
  }, [
    layoutFileName,
    layoutJson,
    layoutPipes,
    layoutRevision,
    refineJson,
    refinePendingPatch,
    refinePipes,
    refineRevision,
    refineSourceFileName,
  ]);

  return (
    <div className="flex flex-1 h-full overflow-hidden">
      <LeftPanel blocked={blocked} />
      <CenterPanel blocked={blocked} />
      <RightPanel blocked={blocked} />
    </div>
  );
}

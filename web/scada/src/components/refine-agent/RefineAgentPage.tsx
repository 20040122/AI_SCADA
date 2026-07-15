import { useEffect } from "react";
import { useLayoutStore } from "../../stores/layoutStore";
import { useRefineStore } from "../../stores/refineStore";
import CenterPanel from "./CenterPanel";
import RightPanel from "./RightPanel";

export default function RefineAgentPage() {
  const layoutNodes = useLayoutStore((s) => s.nodes);
  const layoutJson = useLayoutStore((s) => s.jsonData);
  const { workingNodes, loadFromLayoutData } = useRefineStore();

  useEffect(() => {
    if (layoutNodes.length > 0 && workingNodes.length === 0) {
      loadFromLayoutData(
        layoutNodes,
        layoutJson?.a?.width || 1000,
        layoutJson?.a?.height || 800,
        layoutJson
      );
    }
  }, []);

  return (
    <div className="flex flex-1 h-full overflow-hidden">
      <CenterPanel />
      <RightPanel />
    </div>
  );
}

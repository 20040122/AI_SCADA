import LeftPanel from "./LeftPanel";
import CenterPanel from "./CenterPanel";
import RightPanel from "./RightPanel";

export default function LayoutAgentPage() {
  return (
    <div className="flex flex-1 h-full overflow-hidden">
      <LeftPanel />
      <CenterPanel />
      <RightPanel />
    </div>
  );
}

import AgentCanvas from "../canvas/AgentCanvas";
import { useRefineStore } from "../../stores/refineStore";
import { useLayoutStore } from "../../stores/layoutStore";
import { notify } from "../../utils/notification";

export default function CenterPanel() {
  const {
    workingNodes,
    canvasWidth,
    canvasHeight,
    selectedNodeId,
    setSelectedNodeId,
    moveNode,
    loadFromLayoutData,
  } = useRefineStore();

  const layoutNodes = useLayoutStore((s) => s.nodes);
  const layoutJson = useLayoutStore((s) => s.jsonData);

  const handleSelectNode = (id: string) => {
    setSelectedNodeId(id);
    const node = workingNodes.find((n) => n.id === id);
    if (node) {
      notify(`已选中: ${node.displayName}`, "s");
    }
  };

  const handleLoadFromLayout = () => {
    if (layoutNodes.length > 0 && layoutJson) {
      loadFromLayoutData(
        layoutNodes,
        layoutJson?.a?.width || 1000,
        layoutJson?.a?.height || 800,
        layoutJson
      );
      notify("已加载布局 Agent 画布", "s");
    } else {
      notify("布局 Agent 暂无内容", "w");
    }
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden min-w-0">
      <AgentCanvas
        title="组态画布"
        nodes={workingNodes}
        canvasWidth={canvasWidth}
        canvasHeight={canvasHeight}
        emptyText="请先在布局 Agent 生成画布"
        emptyIcon="🎨"
        selectedNodeId={selectedNodeId}
        onSelectNode={handleSelectNode}
        onMoveNode={moveNode}
        defaultReadableZoom={0.55}
      />
      {workingNodes.length > 0 && (
        <div className="shrink-0 px-3 py-[5px] border-t border-[var(--border)] bg-[var(--bg2)] flex items-center gap-3">
          <div className="flex gap-1 items-center text-[9px] text-[var(--text3)] font-mono">
            <span className="inline-block w-[6px] h-[6px] rounded-full bg-[var(--accent)]" />
            点击控件选中 → 右侧输入微调指令
          </div>
          {layoutNodes.length > 0 && (
            <button
              className="text-[9px] px-[8px] py-[2px] rounded-[3px] border border-[var(--border2)] bg-[var(--bg3)] text-[var(--text3)] font-mono cursor-pointer transition-[0.15s] hover:border-[var(--accent2)] hover:text-[var(--accent)]"
              onClick={handleLoadFromLayout}
            >
              重新加载布局
            </button>
          )}
        </div>
      )}
    </div>
  );
}

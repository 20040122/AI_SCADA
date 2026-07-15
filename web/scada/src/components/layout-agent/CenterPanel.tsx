import { useLayoutStore } from "../../stores/layoutStore";
import AgentCanvas from "../canvas/AgentCanvas";

const STATUS_MAP: Record<string, { label: string; cls: string }> = {
  wait: { label: "等待", cls: "bg-[rgba(58,80,104,0.3)] text-[var(--text3)]" },
  run: { label: "执行中", cls: "bg-[rgba(77,184,212,0.13)] text-[var(--accent)]" },
  done: { label: "完成", cls: "bg-[rgba(62,207,122,0.13)] text-[var(--success)]" },
  skip: { label: "跳过", cls: "bg-[rgba(58,80,104,0.3)] text-[var(--text3)]" },
};

export function WorkflowSteps() {
  const { workflow } = useLayoutStore();

  return (
    <div className="flex flex-col gap-1">
      {workflow.map((step) => {
        const status = STATUS_MAP[step.status];
        return (
          <div
            key={step.id}
            className="flex items-center gap-2 p-[6px_8px] bg-[var(--bg3)] border border-[var(--border)] rounded-[4px]"
          >
            <div className="w-5 h-5 rounded-full bg-[rgba(77,184,212,0.1)] border border-[var(--accent2)] text-[var(--accent)] text-[9px] font-mono flex items-center justify-center shrink-0">
              {step.id}
            </div>
            <span className="flex-1 text-[11px] text-[var(--text)]">{step.name}</span>
            <span
              className={`text-[9px] px-[6px] py-[2px] rounded-[2px] font-mono shrink-0 ${
                step.status === "run" ? "animate-[pulse_1.5s_infinite]" : ""
              } ${status.cls}`}
            >
              {status.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export default function CenterPanel() {
  const { nodes, decorations, jsonData } = useLayoutStore();
  const hasResult = nodes.length > 0;

  const canvasW = jsonData?.a?.width || 0;
  const canvasH = jsonData?.a?.height || 0;

  return (
    <AgentCanvas
      title={hasResult ? `画布预览 (${canvasW}×${canvasH})` : '画布预览'}
      nodes={nodes}
      decorations={decorations}
      canvasWidth={canvasW}
      canvasHeight={canvasH}
      emptyText="输入场景描述后点击「生成布局」"
      emptyIcon="🎨"
    />
  );
}

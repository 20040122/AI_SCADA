import { useAssetStore } from "../../stores/assetStore";
import type { PipelineStepStatus } from "../../types/asset";

const STATUS_MAP: Record<PipelineStepStatus, { label: string; cls: string }> = {
  wait: { label: "等待", cls: "bg-[rgba(58,80,104,0.3)] text-[var(--text3)]" },
  run: { label: "执行中", cls: "bg-[rgba(77,184,212,0.13)] text-[var(--accent)]" },
  done: { label: "完成", cls: "bg-[rgba(62,207,122,0.13)] text-[var(--success)]" },
  skip: { label: "跳过", cls: "bg-[rgba(58,80,104,0.3)] text-[var(--text3)]" },
};

export default function PipelineSteps() {
  const { pipeline } = useAssetStore();

  return (
    <div className="flex flex-col gap-1">
      {pipeline.map((step) => {
        const status = STATUS_MAP[step.status];
        return (
          <div
            key={step.id}
            className="flex gap-2 items-start p-[7px] bg-[var(--bg3)] border border-[var(--border)] rounded-[4px] relative"
          >
            <div className="w-5 h-5 rounded-full bg-[rgba(77,184,212,0.1)] border border-[var(--accent2)] text-[var(--accent)] text-[9px] font-mono flex items-center justify-center shrink-0 mt-px">
              {step.id}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-[11px] text-[var(--text)] mb-[2px]">{step.name}</div>
              <div className="text-[9px] text-[var(--text3)] font-mono">{step.detail}</div>
            </div>
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
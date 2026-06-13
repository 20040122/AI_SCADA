import { useLayoutStore } from "../../stores/layoutStore";
import type { CanvasNode } from "../../types/layout";
import { useEffect, useState, useRef } from "react";

function hashColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue}, 50%, 55%)`;
}

const STATUS_MAP: Record<string, { label: string; cls: string }> = {
  wait: { label: "等待", cls: "bg-[rgba(58,80,104,0.3)] text-[var(--text3)]" },
  run: { label: "执行中", cls: "bg-[rgba(77,184,212,0.13)] text-[var(--accent)]" },
  done: { label: "完成", cls: "bg-[rgba(62,207,122,0.13)] text-[var(--success)]" },
  skip: { label: "跳过", cls: "bg-[rgba(58,80,104,0.3)] text-[var(--text3)]" },
};

const ZONE_COLORS = [
  "rgba(77,184,212,0.06)",
  "rgba(62,184,143,0.06)",
  "rgba(232,168,64,0.06)",
  "rgba(91,184,232,0.06)",
  "rgba(224,85,85,0.06)",
  "rgba(184,138,232,0.06)",
];

function CanvasWidget({ node, scale, offsetX, offsetY }: {
  node: CanvasNode;
  scale: number;
  offsetX: number;
  offsetY: number;
}) {
  const color = hashColor(node.displayName);

  return (
    <div
      className="absolute cursor-pointer transition-all duration-200 hover:z-10 hover:shadow-[0_0_0_2px_var(--accent)] select-none"
      style={{
        left: offsetX + node.x * scale,
        top: offsetY + node.y * scale,
        width: node.width * scale,
        height: node.height * scale,
        background: `linear-gradient(135deg, ${color}22, ${color}11)`,
        border: `1px solid ${color}66`,
        borderRadius: "2px",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        overflow: "hidden",
      }}
    >
      <span
        className="font-mono text-center whitespace-nowrap overflow-hidden text-ellipsis"
        style={{
          fontSize: `${Math.max(7, 10 * scale)}px`,
          color: "#c8d6e5",
          maxWidth: "90%",
          lineHeight: 1.3,
        }}
      >
        {node.displayName}
      </span>
    </div>
  );
}

function ZoneOverlay({ zone, index, scale, offsetX, offsetY }: {
  zone: { x: number; y: number; width: number; height: number; name: string };
  index: number;
  scale: number;
  offsetX: number;
  offsetY: number;
}) {
  const color = ZONE_COLORS[index % ZONE_COLORS.length];
  return (
    <div
      className="absolute pointer-events-none"
      style={{
        left: offsetX + zone.x * scale,
        top: offsetY + zone.y * scale,
        width: zone.width * scale,
        height: zone.height * scale,
        background: color,
        border: "1px dashed rgba(77,184,212,0.15)",
        borderRadius: "3px",
      }}
    >
      <span
        className="absolute text-[8px] font-mono text-[var(--text3)] opacity-30"
        style={{ top: 2, left: 4 }}
      >
        {zone.name}
      </span>
    </div>
  );
}

function WorkflowSteps() {
  const { workflow } = useLayoutStore();

  return (
    <div className="flex gap-2">
      {workflow.map((step) => {
        const status = STATUS_MAP[step.status];
        return (
          <div
            key={step.id}
            className="flex gap-2 items-start p-[7px] bg-[var(--bg3)] border border-[var(--border)] rounded-[4px] flex-1"
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

export default function CenterPanel() {
  const { nodes, zones, jsonData } = useLayoutStore();
  const hasResult = nodes.length > 0;

  const canvasW = jsonData?.a?.width || 0;
  const canvasH = jsonData?.a?.height || 0;

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="p-[10px] border-b border-[var(--border)] bg-[var(--bg2)] flex items-center gap-2 shrink-0">
        <span className="text-[13px] font-medium text-[var(--text)]">
          画布预览 {canvasW > 0 && `(${canvasW}×${canvasH})`}
        </span>
        <div className="ml-auto flex gap-2 items-center">
          {hasResult ? (
            <span className="text-[9px] px-[6px] py-[2px] rounded-[10px] border border-[rgba(77,184,212,0.3)] text-[var(--text3)] font-mono">
              {nodes.length} 个控件
            </span>
          ) : (
            <span className="text-[10px] text-[var(--text3)] font-mono">
              等待生成
            </span>
          )}
        </div>
      </div>

      <div className="flex-1 min-h-0 relative overflow-hidden" style={{ background: "#f5f6f8" }}>
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            backgroundImage:
              "linear-gradient(rgba(0,0,0,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(0,0,0,0.06) 1px, transparent 1px)",
            backgroundSize: "30px 30px",
          }}
        />

        {hasResult && canvasW > 0 && canvasH > 0 && (
          <CanvasContent nodes={nodes} zones={zones} canvasW={canvasW} canvasH={canvasH} />
        )}

        {!hasResult && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <div className="text-[36px] opacity-20 mb-2">🎨</div>
              <div className="text-[11px] text-[var(--text3)] font-mono">
                输入场景描述后点击「生成布局」
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="border-t border-[var(--border)] p-[8px_12px] bg-[var(--bg2)] shrink-0">
        <div className="text-[10px] text-[var(--text3)] font-mono mb-1 tracking-[1px] uppercase">
          Agent 流程
        </div>
        <WorkflowSteps />
      </div>
    </div>
  );
}

function CanvasContent({ nodes, zones, canvasW, canvasH }: {
  nodes: CanvasNode[];
  zones: { x: number; y: number; width: number; height: number; name: string }[];
  canvasW: number;
  canvasH: number;
}) {
  const MARGIN = 24;

  return (
    <ResizableCanvas targetW={canvasW} targetH={canvasH} margin={MARGIN}>
      {(scale, offsetX, offsetY) => (
        <>
          {zones.map((zone, i) => (
            <ZoneOverlay key={zone.name} zone={zone} index={i} scale={scale} offsetX={offsetX} offsetY={offsetY} />
          ))}
          {nodes.map((node) => (
            <CanvasWidget key={node.id} node={node} scale={scale} offsetX={offsetX} offsetY={offsetY} />
          ))}
        </>
      )}
    </ResizableCanvas>
  );
}

function ResizableCanvas({
  targetW,
  targetH,
  margin,
  children,
}: {
  targetW: number;
  targetH: number;
  margin: number;
  children: (scale: number, offsetX: number, offsetY: number) => React.ReactNode;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ w: 0, h: 0 });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setDims({
          w: entry.contentRect.width,
          h: entry.contentRect.height,
        });
      }
    });
    ro.observe(el);
    setDims({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  const containerW = dims.w - margin * 2;
  const containerH = dims.h - margin * 2;
  const scaleX = targetW > 0 ? containerW / targetW : 1;
  const scaleY = targetH > 0 ? containerH / targetH : 1;
  const scale = Math.min(scaleX, scaleY);

  const scaledW = targetW * scale;
  const scaledH = targetH * scale;
  const offsetX = margin + (containerW - scaledW) / 2;
  const offsetY = margin + (containerH - scaledH) / 2;

  return (
    <div ref={containerRef} className="absolute inset-0 overflow-hidden">
      {children(scale, offsetX, offsetY)}
    </div>
  );
}

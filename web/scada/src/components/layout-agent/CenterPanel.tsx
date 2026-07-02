import { useLayoutStore } from "../../stores/layoutStore";
import type { CanvasNode } from "../../types/layout";
import { memo, useEffect, useState, useRef } from "react";
import { toPngUrl } from "../../utils/assetPreview";

const STATUS_MAP: Record<string, { label: string; cls: string }> = {
  wait: { label: "等待", cls: "bg-[rgba(58,80,104,0.3)] text-[var(--text3)]" },
  run: { label: "执行中", cls: "bg-[rgba(77,184,212,0.13)] text-[var(--accent)]" },
  done: { label: "完成", cls: "bg-[rgba(62,207,122,0.13)] text-[var(--success)]" },
  skip: { label: "跳过", cls: "bg-[rgba(58,80,104,0.3)] text-[var(--text3)]" },
};

const MIN_ZOOM = 0.35;
const MAX_ZOOM = 2;
const DEFAULT_READABLE_ZOOM = 0.72;

function clampZoom(value: number) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}

function formatZoom(scale: number) {
  return `${Math.round(scale * 100)}%`;
}

const CanvasWidget = memo(function CanvasWidget({ node, scale, offsetX, offsetY }: {
  node: CanvasNode;
  scale: number;
  offsetX: number;
  offsetY: number;
}) {
  const w = node.width * scale;
  const h = node.height * scale;
  const x = offsetX + (node.x - node.width / 2) * scale;
  const y = offsetY + (node.y - node.height / 2) * scale;
  const fontSize = Math.min(13, Math.max(9, 11 * scale));
  const compact = w < 88 || h < 44;
  const [imgError, setImgError] = useState(false);
  const previewUrl = node.image ? toPngUrl(node.image) : "";
  const hasPreview = !!(previewUrl && !imgError);

  return (
    <div
      className="absolute cursor-pointer transition-all duration-200 hover:z-10 select-none"
      style={{
        transform: `translate(${x}px, ${y}px)`,
        width: w,
        height: h,
        background: hasPreview ? "transparent" : `linear-gradient(180deg, ${node.color}66 0%, ${node.color}33 100%)`,
        border: hasPreview ? "none" : `1px solid ${node.color}cc`,
        borderRadius: `${Math.max(4, 6 * scale)}px`,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        overflow: "hidden",
        willChange: "transform",
        boxShadow: hasPreview ? "none" : "0 8px 18px rgba(15,23,42,0.08)",
      }}
    >
      {hasPreview && (
        <img
          src={previewUrl}
          alt={node.displayName}
          className="absolute inset-0 w-full h-full pointer-events-none"
          style={{ objectFit: "contain", padding: Math.max(2, 4 * scale) }}
          onError={() => setImgError(true)}
        />
      )}
      <span
        className="font-mono text-center whitespace-nowrap overflow-hidden text-ellipsis rounded-full relative"
        style={{
          fontSize: `${fontSize}px`,
          color: "#0f172a",
          maxWidth: compact ? "96%" : "88%",
          lineHeight: 1.3,
          padding: compact ? "1px 5px" : "2px 8px",
          background: "rgba(255,255,255,0.78)",
          boxShadow: "0 1px 2px rgba(15,23,42,0.08)",
        }}
      >
        {node.displayName}
      </span>
    </div>
  );
});

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
  const { nodes, jsonData } = useLayoutStore();
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

      <div
        className="flex-1 min-h-0 relative overflow-hidden"
        style={{ background: "linear-gradient(180deg, #eef3f9 0%, #e8edf5 100%)" }}
      >
        {hasResult && canvasW > 0 && canvasH > 0 && (
          <CanvasContent nodes={nodes} canvasW={canvasW} canvasH={canvasH} />
        )}

        {!hasResult && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center rounded-[18px] border border-[rgba(148,163,184,0.18)] bg-[rgba(255,255,255,0.72)] shadow-[0_14px_40px_rgba(15,23,42,0.08)] px-8 py-7">
              <div className="text-[36px] opacity-20 mb-2">🎨</div>
              <div className="text-[11px] text-[var(--text3)] font-mono">
                输入场景描述后点击「生成布局」
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const CanvasContent = memo(function CanvasContent({ nodes, canvasW, canvasH }: {
  nodes: CanvasNode[];
  canvasW: number;
  canvasH: number;
}) {
  const MARGIN = 36;

  return (
    <ResizableCanvas targetW={canvasW} targetH={canvasH} margin={MARGIN}>
      {(scale, offsetX, offsetY) => (
        <>
          {nodes.map((node) => (
            <CanvasWidget key={node.id} node={node} scale={scale} offsetX={offsetX} offsetY={offsetY} />
          ))}
        </>
      )}
    </ResizableCanvas>
  );
});

const ResizableCanvas = memo(function ResizableCanvas({
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
  const viewportRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ w: 0, h: 0 });
  const [zoomMode, setZoomMode] = useState<"smart" | "fit" | "actual" | "manual">("smart");
  const [manualZoom, setManualZoom] = useState(1);

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

  const containerW = Math.max(0, dims.w - margin * 2);
  const containerH = Math.max(0, dims.h - margin * 2);
  const fitScaleX = targetW > 0 ? containerW / targetW : 1;
  const fitScaleY = targetH > 0 ? containerH / targetH : 1;
  const fitScale = Number.isFinite(Math.min(fitScaleX, fitScaleY)) && Math.min(fitScaleX, fitScaleY) > 0
    ? Math.max(0.05, Math.min(fitScaleX, fitScaleY))
    : 1;
  const smartScale = clampZoom(Math.min(1, Math.max(fitScale, DEFAULT_READABLE_ZOOM)));
  const scale = zoomMode === "fit"
    ? fitScale
    : zoomMode === "actual"
      ? 1
      : zoomMode === "manual"
        ? clampZoom(manualZoom)
        : smartScale;

  const scaledW = targetW * scale;
  const scaledH = targetH * scale;
  const innerW = Math.max(scaledW + margin * 2, dims.w);
  const innerH = Math.max(scaledH + margin * 2, dims.h);
  const offsetX = Math.max((innerW - scaledW) / 2, margin);
  const offsetY = Math.max((innerH - scaledH) / 2, margin);
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || !dims.w || !dims.h) return;
    const frame = requestAnimationFrame(() => {
      viewport.scrollLeft = Math.max(0, (innerW - dims.w) / 2);
      viewport.scrollTop = Math.max(0, (innerH - dims.h) / 2);
    });
    return () => cancelAnimationFrame(frame);
  }, [dims.h, dims.w, innerH, innerW, scale]);

  const updateManualZoom = (nextZoom: number) => {
    setZoomMode("manual");
    setManualZoom(clampZoom(nextZoom));
  };

  return (
    <div className="absolute inset-0 flex flex-col overflow-hidden">
      <div className="shrink-0 px-4 py-3 border-b border-[rgba(148,163,184,0.18)] bg-[rgba(255,255,255,0.64)] backdrop-blur-[10px]">
        <div className="flex items-center gap-2">
          <span className="text-[10px] tracking-[0.14em] uppercase text-[var(--text3)] font-mono">
            Preview
          </span>
          <div className="ml-auto flex items-center gap-2">
            <button
              className="w-7 h-7 rounded-[8px] border border-[rgba(148,163,184,0.24)] bg-[rgba(255,255,255,0.82)] text-[14px] text-[var(--text2)] cursor-pointer transition-[0.15s] hover:border-[rgba(77,184,212,0.45)] hover:text-[var(--accent)] disabled:opacity-40 disabled:cursor-not-allowed"
              onClick={() => updateManualZoom(scale - 0.12)}
              disabled={scale <= MIN_ZOOM}
              type="button"
            >
              -
            </button>
            <span className="w-[52px] text-center text-[11px] text-[var(--text)] font-mono">
              {formatZoom(scale)}
            </span>
            <button
              className="w-7 h-7 rounded-[8px] border border-[rgba(148,163,184,0.24)] bg-[rgba(255,255,255,0.82)] text-[14px] text-[var(--text2)] cursor-pointer transition-[0.15s] hover:border-[rgba(77,184,212,0.45)] hover:text-[var(--accent)] disabled:opacity-40 disabled:cursor-not-allowed"
              onClick={() => updateManualZoom(scale + 0.12)}
              disabled={scale >= MAX_ZOOM}
              type="button"
            >
              +
            </button>
            <button
              className={`px-[10px] h-7 rounded-[8px] border text-[10px] font-mono cursor-pointer transition-[0.15s] ${
                zoomMode === "fit"
                  ? "border-[rgba(77,184,212,0.4)] bg-[rgba(77,184,212,0.1)] text-[var(--accent)]"
                  : "border-[rgba(148,163,184,0.24)] bg-[rgba(255,255,255,0.82)] text-[var(--text3)] hover:border-[rgba(77,184,212,0.45)] hover:text-[var(--accent)]"
              }`}
              onClick={() => setZoomMode("fit")}
              type="button"
            >
              适配
            </button>
            <button
              className={`px-[10px] h-7 rounded-[8px] border text-[10px] font-mono cursor-pointer transition-[0.15s] ${
                zoomMode === "actual"
                  ? "border-[rgba(77,184,212,0.4)] bg-[rgba(77,184,212,0.1)] text-[var(--accent)]"
                  : "border-[rgba(148,163,184,0.24)] bg-[rgba(255,255,255,0.82)] text-[var(--text3)] hover:border-[rgba(77,184,212,0.45)] hover:text-[var(--accent)]"
              }`}
              onClick={() => setZoomMode("actual")}
              type="button"
            >
              1:1
            </button>
          </div>
        </div>
      </div>

      <div ref={containerRef} className="relative flex-1 min-h-0 overflow-hidden">
        <div ref={viewportRef} className="absolute inset-0 overflow-auto">
          <div className="relative min-w-full min-h-full" style={{ width: innerW, height: innerH }}>
            <div
              className="absolute overflow-hidden"
              style={{
                transform: `translate(${offsetX}px, ${offsetY}px)`,
                width: scaledW,
                height: scaledH,
                borderRadius: "18px",
                border: "1px solid rgba(148,163,184,0.24)",
                background: "linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(248,250,252,0.98) 100%)",
                boxShadow: "0 24px 48px rgba(15,23,42,0.14)",
              }}
            >
            </div>
            {children(scale, offsetX, offsetY)}
          </div>
        </div>
      </div>
    </div>
  );
});

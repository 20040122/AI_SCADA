import type { CanvasNode, DecorationNode, PipeData, PipeConnection } from "../../types/layout";
import { memo, useEffect, useState, useRef, useMemo } from "react";
import { toPngUrl } from "../../utils/assetPreview";
import { partitionDecorationsForPipes } from "../../utils/canvasLayers";
import { routePipe } from "../../utils/pipeRouter";
import type { Obstacle } from "../../utils/pipeRouter";

const MIN_ZOOM = 0.35;
const MAX_ZOOM = 2;
const DEFAULT_READABLE_ZOOM = 0.72;

function clampZoom(value: number) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}

function formatZoom(scale: number) {
  return `${Math.round(scale * 100)}%`;
}

const CanvasWidget = memo(function CanvasWidget({ node, scale, offsetX, offsetY, isSelected, onClick, onDragNode }: {
  node: CanvasNode;
  scale: number;
  offsetX: number;
  offsetY: number;
  isSelected?: boolean;
  onClick?: () => void;
  onDragNode?: (x: number, y: number) => void;
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
  const draggable = !!onDragNode;
  const dragState = useRef<{ startX: number; startY: number; nodeX: number; nodeY: number; moved: boolean } | null>(null);

  const handlePointerDown = (e: React.PointerEvent) => {
    if (!draggable) return;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    dragState.current = { startX: e.clientX, startY: e.clientY, nodeX: node.x, nodeY: node.y, moved: false };
  };
  const handlePointerMove = (e: React.PointerEvent) => {
    const ds = dragState.current;
    if (!ds) return;
    const dx = (e.clientX - ds.startX) / scale;
    const dy = (e.clientY - ds.startY) / scale;
    if (Math.abs(dx) > 1 || Math.abs(dy) > 1) ds.moved = true;
    if (ds.moved) onDragNode!(ds.nodeX + dx, ds.nodeY + dy);
  };
  const handlePointerUp = () => {
    const ds = dragState.current;
    dragState.current = null;
    if (ds && !ds.moved && onClick) onClick();
  };

  return (
    <div
      className={`absolute select-none transition-[box-shadow] duration-200 hover:z-10 ${draggable ? "cursor-grab active:cursor-grabbing" : "cursor-pointer"}`}
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
        touchAction: draggable ? "none" : undefined,
        boxShadow: isSelected
          ? "0 0 0 2px var(--accent), 0 0 0 4px rgba(77,184,212,.15)"
          : hasPreview
            ? "none"
            : "0 8px 18px rgba(15,23,42,0.08)",
        zIndex: isSelected ? 20 : undefined,
      }}
      onPointerDown={draggable ? handlePointerDown : undefined}
      onPointerMove={draggable ? handlePointerMove : undefined}
      onPointerUp={draggable ? handlePointerUp : undefined}
      onClick={draggable ? undefined : onClick}
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

const DecorationImage = memo(function DecorationImage({ node, scale, offsetX, offsetY }: {
  node: DecorationNode;
  scale: number;
  offsetX: number;
  offsetY: number;
}) {
  const w = node.width * scale;
  const h = node.height * scale;
  const x = offsetX + (node.x - node.width / 2) * scale;
  const y = offsetY + (node.y - node.height / 2) * scale;
  const url = node.image ? toPngUrl(node.image) : "";

  return (
    <div
      className="absolute pointer-events-none"
      style={{ transform: `translate(${x}px, ${y}px)`, width: w, height: h }}
    >
      {url && <img src={url} alt="" className="w-full h-full" style={{ objectFit: "contain" }} />}
    </div>
  );
});

const DecorationText = memo(function DecorationText({ node, scale, offsetX, offsetY }: {
  node: DecorationNode;
  scale: number;
  offsetX: number;
  offsetY: number;
}) {
  const w = node.width * scale;
  const h = node.height * scale;
  const x = offsetX + (node.x - node.width / 2) * scale;
  const y = offsetY + (node.y - node.height / 2) * scale;
  const fontSize = node.fontSize ? `${parseFloat(node.fontSize) * scale}px` : undefined;

  return (
    <div
      className="absolute pointer-events-none flex"
      style={{
        transform: `translate(${x}px, ${y}px)`,
        width: w,
        height: h,
        color: node.color || "rgb(255,255,255)",
        fontSize: fontSize || `${14 * scale}px`,
        fontWeight: node.fontWeight || "bold",
        textAlign: (node.textAlign as any) || "center",
        opacity: node.opacity ?? 1,
        alignItems: node.verticalAlign === "top" ? "flex-start" : "center",
        justifyContent: "center",
        lineHeight: 1.3,
      }}
    >
      {node.text}
    </div>
  );
});

const LEAD = 20;
const ARROW_THRESHOLD = 40;
const ARROW_SIZE = 8;

function getEdgeCenter(node: CanvasNode, port: string): { x: number; y: number } {
  switch (port) {
    case "right": return { x: node.x + node.width / 2, y: node.y };
    case "left": return { x: node.x - node.width / 2, y: node.y };
    case "top": return { x: node.x, y: node.y - node.height / 2 };
    case "bottom": return { x: node.x, y: node.y + node.height / 2 };
    default: return { x: node.x, y: node.y };
  }
}

function getLeadEnd(edge: { x: number; y: number }, port: string): { x: number; y: number } {
  switch (port) {
    case "right": return { x: edge.x + LEAD, y: edge.y };
    case "left": return { x: edge.x - LEAD, y: edge.y };
    case "top": return { x: edge.x, y: edge.y - LEAD };
    case "bottom": return { x: edge.x, y: edge.y + LEAD };
    default: return edge;
  }
}

interface Seg { x1: number; y1: number; x2: number; y2: number; }

interface PipeArrow { x: number; y: number; angle: number; }

function computeArrows(segments: Seg[]): PipeArrow[] {
  const arrows: PipeArrow[] = [];
  for (const seg of segments) {
    const dx = seg.x2 - seg.x1;
    const dy = seg.y2 - seg.y1;
    const len = Math.sqrt(dx * dx + dy * dy);
    if (len >= ARROW_THRESHOLD) {
      arrows.push({
        x: (seg.x1 + seg.x2) / 2,
        y: (seg.y1 + seg.y2) / 2,
        angle: Math.atan2(dy, dx) * 180 / Math.PI,
      });
    }
  }
  return arrows;
}

const PipesLayer = memo(function PipesLayer({ pipeData, nodes, canvasW, canvasH, scale, offsetX, offsetY }: {
  pipeData: PipeData;
  nodes: CanvasNode[];
  canvasW: number;
  canvasH: number;
  scale: number;
  offsetX: number;
  offsetY: number;
}) {
  const nodeMap = useMemo(() => {
    const map = new Map<string, CanvasNode>();
    for (const node of nodes) {
      const a = node.a;
      if (!a) continue;
      const g = String(a["layout.group"] ?? "");
      const n = String(a["layout.node"] ?? "");
      const inst = a["layout.instance"];
      if (g && n && inst != null) {
        map.set(`${g}|${n}|${inst}`, node);
      }
    }
    return map;
  }, [nodes]);

  const { unique, duplicateCount } = useMemo(() => {
    const seen = new Set<string>();
    const unique: PipeConnection[] = [];
    let dup = 0;
    for (const conn of pipeData.connections) {
      const key = `${conn.source.group}|${conn.source.node}|${conn.source.instance}|${conn.source.port}|${conn.target.group}|${conn.target.node}|${conn.target.instance}|${conn.target.port}`;
      if (seen.has(key)) dup++;
      else { seen.add(key); unique.push(conn); }
    }
    return { unique, duplicateCount: dup };
  }, [pipeData]);

  const scaledW = canvasW * scale;
  const scaledH = canvasH * scale;

  const obstacleList: Obstacle[] = useMemo(() => {
    return nodes.map(n => ({ x: n.x, y: n.y, width: n.width, height: n.height }));
  }, [nodes]);

  const pathDefs = useMemo(() => {
    const entries: { path: string; arrows: PipeArrow[] }[] = [];
    let invalid = 0;
    for (const conn of unique) {
      const sk = `${conn.source.group}|${conn.source.node}|${conn.source.instance}`;
      const tk = `${conn.target.group}|${conn.target.node}|${conn.target.instance}`;
      const src = nodeMap.get(sk);
      const tgt = nodeMap.get(tk);
      if (!src || !tgt) { invalid++; continue; }
      const se = getEdgeCenter(src, conn.source.port);
      const te = getEdgeCenter(tgt, conn.target.port);
      const sl = getLeadEnd(se, conn.source.port);
      const tl = getLeadEnd(te, conn.target.port);
      const segs = routePipe(sl.x, sl.y, tl.x, tl.y, obstacleList, canvasW, canvasH);
      let d = `M ${sl.x},${sl.y}`;
      for (const seg of segs) d += ` L ${seg.x2},${seg.y2}`;
      entries.push({ path: d, arrows: computeArrows(segs) });
    }
    return { entries, invalid };
  }, [unique, nodeMap, obstacleList, canvasW, canvasH]);

  return (
    <>
      <svg
        className="absolute pointer-events-none overflow-visible"
        style={{
          transform: `translate(${offsetX}px, ${offsetY}px)`,
          width: scaledW,
          height: scaledH,
          top: 0, left: 0,
        }}
        viewBox={`0 0 ${canvasW} ${canvasH}`}
        preserveAspectRatio="none"
      >
        <defs>
          <marker id="pipeArrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#d93a3a" />
          </marker>
        </defs>
        {pathDefs.entries.map((e, i) => (
          <g key={i}>
            <path d={e.path} stroke="#d93a3a" strokeWidth={2} fill="none" strokeLinejoin="round" strokeLinecap="round" />
            {e.arrows.map((a, j) => (
              <g key={j} transform={`translate(${a.x}, ${a.y}) rotate(${a.angle})`}>
                <polygon points={`${-ARROW_SIZE},${-ARROW_SIZE * 0.4} ${0},0 ${-ARROW_SIZE},${ARROW_SIZE * 0.4}`} fill="#d93a3a" />
              </g>
            ))}
          </g>
        ))}
      </svg>
      <div className="absolute bottom-2 right-2 text-[9px] text-[var(--text3)] font-mono bg-[rgba(255,255,255,0.72)] px-2 py-1 rounded-[4px]">
        {pathDefs.entries.length} 条管线
        {duplicateCount > 0 && ` · 合并 ${duplicateCount} 条重复`}
        {pathDefs.invalid > 0 && ` · 跳过 ${pathDefs.invalid} 条无效`}
      </div>
    </>
  );
});

const CanvasContent = memo(function CanvasContent({ nodes, decorations, canvasW, canvasH, selectedNodeId, onSelectNode, onMoveNode, defaultReadableZoom, pipes }: {
  nodes: CanvasNode[];
  decorations: DecorationNode[];
  canvasW: number;
  canvasH: number;
  selectedNodeId?: string | null;
  onSelectNode?: (id: string) => void;
  onMoveNode?: (id: string, x: number, y: number) => void;
  defaultReadableZoom?: number;
  pipes?: PipeData | null;
}) {
  const MARGIN = 36;
  const { backgrounds, foregrounds } = useMemo(
    () => partitionDecorationsForPipes(decorations, canvasW, canvasH),
    [decorations, canvasW, canvasH],
  );

  return (
    <ResizableCanvas targetW={canvasW} targetH={canvasH} margin={MARGIN} defaultReadableZoom={defaultReadableZoom}>
      {(scale, offsetX, offsetY) => (
        <>
          {backgrounds.map((d, i) => (
            <DecorationImage key={`background-img-${i}`} node={d} scale={scale} offsetX={offsetX} offsetY={offsetY} />
          ))}
          {pipes && pipes.connections.length > 0 && (
            <PipesLayer
              pipeData={pipes}
              nodes={nodes}
              canvasW={canvasW}
              canvasH={canvasH}
              scale={scale}
              offsetX={offsetX}
              offsetY={offsetY}
            />
          )}
          {foregrounds.map((d, i) =>
            d.type === "image" ? (
              <DecorationImage key={`deco-img-${i}`} node={d} scale={scale} offsetX={offsetX} offsetY={offsetY} />
            ) : (
              <DecorationText key={`deco-txt-${i}`} node={d} scale={scale} offsetX={offsetX} offsetY={offsetY} />
            )
          )}
          {nodes.map((node) => (
            <CanvasWidget
              key={node.id}
              node={node}
              scale={scale}
              offsetX={offsetX}
              offsetY={offsetY}
              isSelected={selectedNodeId === node.id}
              onClick={onSelectNode ? () => onSelectNode(node.id) : undefined}
              onDragNode={onMoveNode ? (x, y) => onMoveNode(node.id, x, y) : undefined}
            />
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
  defaultReadableZoom,
}: {
  targetW: number;
  targetH: number;
  margin: number;
  children: (scale: number, offsetX: number, offsetY: number) => React.ReactNode;
  defaultReadableZoom?: number;
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
  const smartScale = clampZoom(Math.min(1, Math.max(fitScale, defaultReadableZoom ?? DEFAULT_READABLE_ZOOM)));
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

export interface AgentCanvasProps {
  nodes: CanvasNode[];
  decorations?: DecorationNode[];
  canvasWidth: number;
  canvasHeight: number;
  title: string;
  emptyText: string;
  emptyIcon?: string;
  selectedNodeId?: string | null;
  onSelectNode?: (id: string) => void;
  onMoveNode?: (id: string, x: number, y: number) => void;
  defaultReadableZoom?: number;
  pipes?: PipeData | null;
}

export default function AgentCanvas(props: AgentCanvasProps) {
  const { nodes, decorations = [], canvasWidth, canvasHeight, title, emptyText, emptyIcon, selectedNodeId, onSelectNode, onMoveNode, defaultReadableZoom, pipes } = props;
  const hasResult = nodes.length > 0;

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="p-[10px] border-b border-[var(--border)] bg-[var(--bg2)] flex items-center gap-2 shrink-0">
        <span className="text-[13px] font-medium text-[var(--text)]">{title}</span>
        <div className="ml-auto flex gap-2 items-center">
          {hasResult ? (
            <span className="text-[9px] px-[6px] py-[2px] rounded-[10px] border border-[rgba(77,184,212,0.3)] text-[var(--text3)] font-mono">
              {nodes.length} 个控件
            </span>
          ) : null}
        </div>
      </div>

      <div
        className="flex-1 min-h-0 relative overflow-hidden"
        style={{ background: "linear-gradient(180deg, #eef3f9 0%, #e8edf5 100%)" }}
      >
        {hasResult && canvasWidth > 0 && canvasHeight > 0 && (
          <CanvasContent
            nodes={nodes}
            decorations={decorations}
            canvasW={canvasWidth}
            canvasH={canvasHeight}
            selectedNodeId={selectedNodeId}
            onSelectNode={onSelectNode}
            onMoveNode={onMoveNode}
            defaultReadableZoom={defaultReadableZoom}
            pipes={pipes}
          />
        )}

        {!hasResult && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center rounded-[18px] border border-[rgba(148,163,184,0.18)] bg-[rgba(255,255,255,0.72)] shadow-[0_14px_40px_rgba(15,23,42,0.08)] px-8 py-7">
              <div className="text-[36px] opacity-20 mb-2">{emptyIcon || '🎨'}</div>
              <div className="text-[11px] text-[var(--text3)] font-mono">
                {emptyText}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

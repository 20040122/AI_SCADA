import type { CanvasNode, DecorationNode, PipeData, PipeConnection } from "../../types/layout";
import { memo, useEffect, useState, useRef, useMemo, useCallback } from "react";
import { toPngUrl } from "../../utils/assetPreview";
import { partitionDecorationsForPipes } from "../../utils/canvasLayers";
import { routePipe } from "../../utils/pipeRouter";
import type { Obstacle } from "../../utils/pipeRouter";
import { getLeadLength, getEdgeCenter, getLeadEnd } from "../../utils/pipeGeometry.ts";
import { captureDragSnapshot, computeDragPositions } from "../../utils/dragGeometry";

const MIN_ZOOM = 0.35;
const MAX_ZOOM = 2;
const DEFAULT_READABLE_ZOOM = 0.72;
const CLICK_THRESHOLD = 3;

function clampZoom(value: number) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}

function formatZoom(scale: number) {
  return `${Math.round(scale * 100)}%`;
}

const CanvasWidget = memo(function CanvasWidget({ node, scale, offsetX, offsetY, isSelected, onClick, onDragMove, onDragEnd, interactionLocked }: {
  node: CanvasNode;
  scale: number;
  offsetX: number;
  offsetY: number;
  isSelected?: boolean;
  onClick?: (metaKey: boolean) => void;
  onDragMove?: (rawDx: number, rawDy: number) => void;
  onDragEnd?: () => void;
  interactionLocked?: boolean;
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
  const draggable = !!onDragMove;
  const dragState = useRef<{ startX: number; startY: number; moved: boolean } | null>(null);

  const handlePointerDown = (e: React.PointerEvent) => {
    if (!draggable) return;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    dragState.current = { startX: e.clientX, startY: e.clientY, moved: false };
  };
  const handlePointerMove = (e: React.PointerEvent) => {
    const ds = dragState.current;
    if (!ds) return;
    const rawDx = e.clientX - ds.startX;
    const rawDy = e.clientY - ds.startY;
    const screenDist = Math.sqrt(rawDx * rawDx + rawDy * rawDy);
    if (screenDist > CLICK_THRESHOLD) {
      ds.moved = true;
      onDragMove!(rawDx, rawDy);
    }
  };
  const handlePointerUp = (e: React.PointerEvent) => {
    const ds = dragState.current;
    dragState.current = null;
    onDragEnd?.();
    if (ds && !ds.moved && onClick) {
      onClick(e.metaKey || e.ctrlKey);
    }
  };
  const handlePointerCancel = () => {
    dragState.current = null;
    onDragEnd?.();
  };

  return (
    <div
      className={`absolute select-none transition-[box-shadow] duration-200 hover:z-10 ${draggable && !interactionLocked ? "cursor-grab active:cursor-grabbing" : "cursor-pointer"}`}
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
      onPointerCancel={draggable ? handlePointerCancel : undefined}
      onClick={draggable ? undefined : (onClick ? () => onClick(false) : undefined)}
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

const HANDLE_SIZE = 10;

const ResizeHandle = memo(function ResizeHandle({ cx, cy, cursor, onPointerDown }: {
  cx: number;
  cy: number;
  cursor: string;
  onPointerDown: (e: React.PointerEvent) => void;
}) {
  return (
    <div
      className="absolute z-30"
      style={{
        transform: `translate(${cx - HANDLE_SIZE / 2}px, ${cy - HANDLE_SIZE / 2}px)`,
        width: HANDLE_SIZE,
        height: HANDLE_SIZE,
        cursor,
        touchAction: "none",
      }}
      onPointerDown={onPointerDown}
    >
      <div
        className="w-full h-full rounded-sm border-2 border-white"
        style={{ background: "var(--accent)", boxShadow: "0 1px 3px rgba(0,0,0,0.3)" }}
      />
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
        textAlign: (node.textAlign as React.CSSProperties['textAlign']) || "center",
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

const ARROW_THRESHOLD = 40;
const ARROW_SIZE = 8;

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
      const srcLead = getLeadLength(src);
      const tgtLead = getLeadLength(tgt);
      const sl = getLeadEnd(se, conn.source.port, srcLead);
      const tl = getLeadEnd(te, conn.target.port, tgtLead);
      const segs = routePipe(sl.x, sl.y, tl.x, tl.y, obstacleList, canvasW, canvasH);
      let d = `M ${se.x},${se.y} L ${sl.x},${sl.y}`;
      for (const seg of segs) d += ` L ${seg.x2},${seg.y2}`;
      d += ` L ${te.x},${te.y}`;
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

type Corner = "nw" | "ne" | "sw" | "se";

const CORNER_CURSORS: Record<Corner, string> = {
  nw: "nwse-resize",
  ne: "nesw-resize",
  sw: "nesw-resize",
  se: "nwse-resize",
};

function getOppositeCorner(corner: Corner): { left: boolean; top: boolean } {
  return {
    left: corner === "ne" || corner === "se",
    top: corner === "sw" || corner === "se",
  };
}

function computeResize(
  corner: Corner,
  node: CanvasNode,
  dx: number, dy: number,
  canvasW: number, canvasH: number
): { x: number; y: number; width: number; height: number } {
  const opp = getOppositeCorner(corner);
  const fixedLeft = opp.left;
  const fixedTop = opp.top;

  let newW: number;
  let newH: number;
  let newX: number;
  let newY: number;

  if (fixedLeft) {
    newW = node.width - dx;
    newX = node.x + dx / 2;
  } else {
    newW = node.width + dx;
    newX = node.x + dx / 2;
  }
  if (fixedTop) {
    newH = node.height - dy;
    newY = node.y + dy / 2;
  } else {
    newH = node.height + dy;
    newY = node.y + dy / 2;
  }

  newW = Math.max(10, newW);
  newH = Math.max(10, newH);

  const halfW = newW / 2;
  const halfH = newH / 2;
  newX = Math.max(halfW, Math.min(canvasW - halfW, newX));
  newY = Math.max(halfH, Math.min(canvasH - halfH, newY));

  return { x: newX, y: newY, width: newW, height: newH };
}

function round2(v: number): number {
  return Math.round(v * 100) / 100;
}

const CanvasContent = memo(function CanvasContent({ nodes, decorations, canvasW, canvasH, selectedNodeIds, onSelectNode, onMoveNodes, onResizeNode, defaultReadableZoom, pipes, interactionLocked }: {
  nodes: CanvasNode[];
  decorations: DecorationNode[];
  canvasW: number;
  canvasH: number;
  selectedNodeIds?: string[];
  onSelectNode?: (id: string, metaKey: boolean) => void;
  onMoveNodes?: (positions: { id: string; x: number; y: number }[]) => void;
  onResizeNode?: (id: string, x: number, y: number, width: number, height: number) => void;
  defaultReadableZoom?: number;
  pipes?: PipeData | null;
  interactionLocked?: boolean;
}) {
  const MARGIN = 36;
  const { backgrounds, foregrounds } = useMemo(
    () => partitionDecorationsForPipes(decorations, canvasW, canvasH),
    [decorations, canvasW, canvasH],
  );

  const selectionSet = useMemo(() => new Set(selectedNodeIds || []), [selectedNodeIds]);

  const isSingleSelection = selectedNodeIds?.length === 1;
  const singleSelectedNode = isSingleSelection
    ? nodes.find((n) => n.id === selectedNodeIds![0])
    : null;

  const dragContextRef = useRef<{
    targetIds: string[];
    snapshot: ReturnType<typeof captureDragSnapshot>;
    nodeSizes: Map<string, { width: number; height: number }>;
    zoomAtStart: number;
  } | null>(null);
  const resizeAnimRef = useRef<number | null>(null);
  const resizeLastRef = useRef<{ x: number; y: number; w: number; h: number } | null>(null);
  const scaleRef = useRef(1);
  const getScale = () => scaleRef.current;

  const handleDragMove = useCallback((id: string, rawDx: number, rawDy: number) => {
    if (interactionLocked || !onMoveNodes) return;
    if (!dragContextRef.current) {
      const wasSel = selectionSet.has(id);
      const targetIds = wasSel ? (selectedNodeIds || []) : [id];
      if (targetIds.length === 0) return;
      const snapshot = captureDragSnapshot(targetIds, nodes);
      const nodeSizes = new Map(nodes.map((n) => [n.id, { width: n.width, height: n.height }]));
      dragContextRef.current = { targetIds, snapshot, nodeSizes, zoomAtStart: getScale() };
    }
    const ctx = dragContextRef.current!;
    const dx = rawDx / ctx.zoomAtStart;
    const dy = rawDy / ctx.zoomAtStart;
    const positions = computeDragPositions(ctx.snapshot, ctx.nodeSizes, dx, dy, canvasW, canvasH);
    onMoveNodes(positions);
  }, [interactionLocked, onMoveNodes, selectionSet, selectedNodeIds, nodes, canvasW, canvasH]);

  const handleDragEnd = useCallback(() => {
    dragContextRef.current = null;
  }, []);

  const handleClick = useCallback((id: string, metaKey: boolean) => {
    dragContextRef.current = null;
    if (interactionLocked || !onSelectNode) return;
    onSelectNode(id, metaKey);
  }, [interactionLocked, onSelectNode]);

  const handleBlankClick = useCallback(() => {
    dragContextRef.current = null;
    if (interactionLocked || !onSelectNode) return;
    onSelectNode("", false);
  }, [interactionLocked, onSelectNode]);

  const handleResizePointerDown = useCallback((corner: Corner, e: React.PointerEvent) => {
    if (interactionLocked || !onResizeNode || !singleSelectedNode) return;
    e.preventDefault();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    const startX = e.clientX;
    const startY = e.clientY;

    const onMove = (ev: PointerEvent) => {
      ev.preventDefault();
      const scale = getScale();
      const dx = (ev.clientX - startX) / scale;
      const dy = (ev.clientY - startY) / scale;
      const result = computeResize(corner, singleSelectedNode, dx, dy, canvasW, canvasH);

      if (resizeAnimRef.current !== null) cancelAnimationFrame(resizeAnimRef.current);
      resizeLastRef.current = { x: result.x, y: result.y, w: result.width, h: result.height };
      resizeAnimRef.current = requestAnimationFrame(() => {
        const last = resizeLastRef.current;
        if (last) {
          onResizeNode(singleSelectedNode.id, last.x, last.y, last.w, last.h);
        }
      });
    };

    const onUp = () => {
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      if (resizeAnimRef.current !== null) cancelAnimationFrame(resizeAnimRef.current);
      resizeAnimRef.current = null;
      const last = resizeLastRef.current;
      resizeLastRef.current = null;
      if (last) {
        onResizeNode(singleSelectedNode.id, round2(last.x), round2(last.y), round2(last.w), round2(last.h));
      }
    };

    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
  }, [interactionLocked, onResizeNode, singleSelectedNode, canvasW, canvasH]);

  const showResizeHandles = singleSelectedNode && !interactionLocked;

  return (
    <ResizableCanvas targetW={canvasW} targetH={canvasH} margin={MARGIN} defaultReadableZoom={defaultReadableZoom}>
      {(scale, offsetX, offsetY) => {
        scaleRef.current = scale;
        return (
          <div
            className="absolute inset-0"
            onPointerDown={(e) => {
              if (e.target === e.currentTarget && !interactionLocked) {
                handleBlankClick();
              }
            }}
          >
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
                isSelected={selectionSet.has(node.id)}
                onClick={onSelectNode ? (metaKey) => handleClick(node.id, metaKey) : undefined}
                onDragMove={onMoveNodes ? (rawDx, rawDy) => handleDragMove(node.id, rawDx, rawDy) : undefined}
                onDragEnd={onMoveNodes ? handleDragEnd : undefined}
                interactionLocked={interactionLocked}
              />
            ))}
            {showResizeHandles && (() => {
              const n = singleSelectedNode;
              const left = offsetX + (n.x - n.width / 2) * scale;
              const top = offsetY + (n.y - n.height / 2) * scale;
              const right = offsetX + (n.x + n.width / 2) * scale;
              const bottom = offsetY + (n.y + n.height / 2) * scale;
              return (
                <>
                  <ResizeHandle cx={left} cy={top} cursor={CORNER_CURSORS.nw} onPointerDown={(e) => handleResizePointerDown("nw", e)} />
                  <ResizeHandle cx={right} cy={top} cursor={CORNER_CURSORS.ne} onPointerDown={(e) => handleResizePointerDown("ne", e)} />
                  <ResizeHandle cx={left} cy={bottom} cursor={CORNER_CURSORS.sw} onPointerDown={(e) => handleResizePointerDown("sw", e)} />
                  <ResizeHandle cx={right} cy={bottom} cursor={CORNER_CURSORS.se} onPointerDown={(e) => handleResizePointerDown("se", e)} />
                </>
              );
            })()}
          </div>
        );
      }}
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
  selectedNodeIds?: string[];
  onSelectNode?: (id: string, metaKey: boolean) => void;
  onMoveNodes?: (positions: { id: string; x: number; y: number }[]) => void;
  onResizeNode?: (id: string, x: number, y: number, width: number, height: number) => void;
  defaultReadableZoom?: number;
  pipes?: PipeData | null;
  interactionLocked?: boolean;
}

export default function AgentCanvas(props: AgentCanvasProps) {
  const { nodes, decorations = [], canvasWidth, canvasHeight, title, emptyText, emptyIcon, selectedNodeIds, onSelectNode, onMoveNodes, onResizeNode, defaultReadableZoom, pipes, interactionLocked } = props;
  const hasResult = nodes.length > 0;

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="p-[10px] border-b border-[var(--border)] bg-[var(--bg2)] flex items-center gap-2 shrink-0">
        <span className="text-[13px] font-medium text-[var(--text)]">{title}</span>
        <div className="ml-auto flex gap-2 items-center">
          {hasResult ? (
            <>
              <span className="text-[9px] px-[6px] py-[2px] rounded-[10px] border border-[rgba(77,184,212,0.3)] text-[var(--text3)] font-mono">
                {nodes.length} 个控件
              </span>
              {selectedNodeIds && selectedNodeIds.length > 0 && (
                <span className="text-[9px] px-[6px] py-[2px] rounded-[10px] border border-[var(--accent)] text-[var(--accent)] font-mono">
                  已选 {selectedNodeIds.length}
                </span>
              )}
            </>
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
            selectedNodeIds={selectedNodeIds}
            onSelectNode={onSelectNode}
            onMoveNodes={onMoveNodes}
            onResizeNode={onResizeNode}
            defaultReadableZoom={defaultReadableZoom}
            pipes={pipes}
            interactionLocked={interactionLocked}
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

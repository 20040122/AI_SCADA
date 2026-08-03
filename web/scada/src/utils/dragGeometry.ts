export interface DragSnapshot {
  positions: { id: string; x: number; y: number }[];
}

export function captureDragSnapshot(
  ids: string[],
  nodes: { id: string; x: number; y: number }[]
): DragSnapshot {
  const nodeMap = new Map(nodes.map((n) => [n.id, n]));
  return {
    positions: ids.map((id) => {
      const n = nodeMap.get(id);
      return { id, x: n?.x ?? 0, y: n?.y ?? 0 };
    }),
  };
}

function round2(v: number): number {
  return Math.round(v * 100) / 100;
}

function computeBoundingBox(
  positions: { x: number; y: number; width: number; height: number }[]
): { minX: number; minY: number; maxX: number; maxY: number } | null {
  if (positions.length === 0) return null;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const p of positions) {
    const l = p.x - p.width / 2;
    const r = p.x + p.width / 2;
    const t = p.y - p.height / 2;
    const b = p.y + p.height / 2;
    if (l < minX) minX = l;
    if (t < minY) minY = t;
    if (r > maxX) maxX = r;
    if (b > maxY) maxY = b;
  }
  return { minX, minY, maxX, maxY };
}

export type ResizeHandleType = "nw" | "ne" | "sw" | "se" | "n" | "s" | "e" | "w";

const MIN_RATIO_SIZE = 10;

export function computeRatioResize(
  handle: ResizeHandleType,
  node: { x: number; y: number; width: number; height: number },
  dx: number,
  dy: number,
  canvasW: number,
  canvasH: number,
  aspect: number
): { x: number; y: number; width: number; height: number } {
  const ratio = Number.isFinite(aspect) && aspect > 0 ? aspect : 1;

  let left = node.x - node.width / 2;
  let right = node.x + node.width / 2;
  let top = node.y - node.height / 2;
  let bottom = node.y + node.height / 2;

  if (handle === "nw") { left += dx; top += dy; }
  else if (handle === "ne") { right += dx; top += dy; }
  else if (handle === "sw") { left += dx; bottom += dy; }
  else if (handle === "se") { right += dx; bottom += dy; }
  else if (handle === "n") { top += dy; }
  else if (handle === "s") { bottom += dy; }
  else if (handle === "e") { right += dx; }
  else if (handle === "w") { left += dx; }

  const boxW = Math.max(MIN_RATIO_SIZE, right - left);
  const boxH = Math.max(MIN_RATIO_SIZE, bottom - top);

  let newW = Math.min(boxW, boxH * ratio);
  let newH = newW / ratio;

  const scale = Math.min(1, canvasW / newW, canvasH / newH);
  if (scale < 1) {
    newW *= scale;
    newH *= scale;
  }

  const halfW = newW / 2;
  const halfH = newH / 2;
  let x: number;
  let y: number;

  if (handle === "e" || handle === "w") {
    x = handle === "e" ? left + halfW : right - halfW;
    y = node.y;
  } else if (handle === "s" || handle === "n") {
    x = node.x;
    y = handle === "s" ? top + halfH : bottom - halfH;
  } else {
    const leftFixed = handle === "ne" || handle === "se";
    const topFixed = handle === "sw" || handle === "se";
    x = leftFixed ? left + halfW : right - halfW;
    y = topFixed ? top + halfH : bottom - halfH;
  }

  x = Math.max(halfW, Math.min(canvasW - halfW, x));
  y = Math.max(halfH, Math.min(canvasH - halfH, y));

  return { x: round2(x), y: round2(y), width: round2(newW), height: round2(newH) };
}

export function computeDragPositions(
  snapshot: DragSnapshot,
  nodeSizes: Map<string, { width: number; height: number }>,
  totalDx: number,
  totalDy: number,
  canvasW: number,
  canvasH: number
): { id: string; x: number; y: number }[] {
  if (snapshot.positions.length === 0) return [];

  const proposed: { x: number; y: number; width: number; height: number }[] = [];
  for (const p of snapshot.positions) {
    const size = nodeSizes.get(p.id);
    proposed.push({
      x: p.x + totalDx,
      y: p.y + totalDy,
      width: size?.width ?? 0,
      height: size?.height ?? 0,
    });
  }

  const bb = computeBoundingBox(proposed);
  let clampedDx = totalDx;
  let clampedDy = totalDy;
  if (bb) {
    clampedDx = totalDx - Math.min(0, bb.minX) - Math.max(0, bb.maxX - canvasW);
    clampedDy = totalDy - Math.min(0, bb.minY) - Math.max(0, bb.maxY - canvasH);
  }

  return snapshot.positions.map((p) => ({
    id: p.id,
    x: round2(p.x + clampedDx),
    y: round2(p.y + clampedDy),
  }));
}

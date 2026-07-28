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

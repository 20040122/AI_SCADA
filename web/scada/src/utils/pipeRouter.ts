export interface Obstacle {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Segment {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

const MARGIN = 10;
const OUTER_MARGIN = 60;
const TURN_PENALTY = 20;

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

function expandRect(ob: Obstacle): Rect {
  return {
    x: ob.x - ob.width / 2 - MARGIN,
    y: ob.y - ob.height / 2 - MARGIN,
    w: ob.width + MARGIN * 2,
    h: ob.height + MARGIN * 2,
  };
}

function pointInRects(px: number, py: number, rects: Rect[]): boolean {
  for (const r of rects) {
    if (px >= r.x && px < r.x + r.w && py >= r.y && py < r.y + r.h) return true;
  }
  return false;
}

function hSegClear(y: number, x1: number, x2: number, rects: Rect[]): boolean {
  const lo = Math.min(x1, x2);
  const hi = Math.max(x1, x2);
  for (const r of rects) {
    if (y >= r.y && y < r.y + r.h && hi > r.x && lo < r.x + r.w) return false;
  }
  return true;
}

function vSegClear(x: number, y1: number, y2: number, rects: Rect[]): boolean {
  const lo = Math.min(y1, y2);
  const hi = Math.max(y1, y2);
  for (const r of rects) {
    if (x >= r.x && x < r.x + r.w && hi > r.y && lo < r.y + r.h) return false;
  }
  return true;
}

function pathToSegments(path: Array<{ x: number; y: number }>): Segment[] {
  const segs: Segment[] = [];
  for (let i = 0; i < path.length - 1; i++) {
    segs.push({ x1: path[i].x, y1: path[i].y, x2: path[i + 1].x, y2: path[i + 1].y });
  }
  return segs;
}

function mergeCollinear(segs: Segment[]): Segment[] {
  if (segs.length <= 1) return segs;
  const result: Segment[] = [];
  let cur = segs[0];
  for (let i = 1; i < segs.length; i++) {
    const s = segs[i];
    const sameH = cur.y1 === cur.y2 && s.y1 === s.y2 && cur.y1 === s.y1;
    const sameV = cur.x1 === cur.x2 && s.x1 === s.x2 && cur.x1 === s.x1;
    if (sameH || sameV) {
      cur = { x1: cur.x1, y1: cur.y1, x2: s.x2, y2: s.y2 };
    } else {
      result.push(cur);
      cur = s;
    }
  }
  result.push(cur);
  return result;
}

function directOrthogonal(sx: number, sy: number, tx: number, ty: number): Segment[] {
  return [
    { x1: sx, y1: sy, x2: tx, y2: sy },
    { x1: tx, y1: sy, x2: tx, y2: ty },
  ];
}

export function routePipe(
  sx: number, sy: number,
  tx: number, ty: number,
  obstacles: Obstacle[],
  canvasW: number,
  canvasH: number,
): Segment[] {
  if (sx === tx && sy === ty) return [];

  const rects = obstacles.map(expandRect);

  const gridXs = new Set<number>();
  const gridYs = new Set<number>();

  gridXs.add(sx); gridXs.add(tx);
  gridYs.add(sy); gridYs.add(ty);
  gridXs.add(0); gridXs.add(canvasW);
  gridYs.add(0); gridYs.add(canvasH);
  gridXs.add(-OUTER_MARGIN); gridXs.add(canvasW + OUTER_MARGIN);
  gridYs.add(-OUTER_MARGIN); gridYs.add(canvasH + OUTER_MARGIN);

  for (const r of rects) {
    gridXs.add(r.x); gridXs.add(r.x + r.w);
    gridYs.add(r.y); gridYs.add(r.y + r.h);
  }

  const xs = [...gridXs].sort((a, b) => a - b);
  const ys = [...gridYs].sort((a, b) => a - b);

  const startKey = `${sx},${sy}`;
  const endKey = `${tx},${ty}`;

  const gScore = new Map<string, number>([[startKey, 0]]);
  const fScore = new Map<string, number>([[startKey, Math.abs(sx - tx) + Math.abs(sy - ty)]]);
  const cameFrom = new Map<string, string>();
  const dirFrom = new Map<string, 'h' | 'v' | null>();

  const open = new Set<string>([startKey]);
  const closed = new Set<string>();

  while (open.size > 0) {
    let current: string | null = null;
    let bestF = Infinity;
    for (const k of open) {
      const f = fScore.get(k) ?? Infinity;
      if (f < bestF) { bestF = f; current = k; }
    }

    if (!current) break;
    if (current === endKey) break;

    open.delete(current);
    closed.add(current);

    const [cx, cy] = current.split(',').map(Number);
    const currentG = gScore.get(current) ?? Infinity;
    const currentDir = dirFrom.get(current) ?? null;

    const xi = xs.indexOf(cx);
    const yi = ys.indexOf(cy);

    if (xi < 0 || yi < 0) continue;

    for (const ni of [xi - 1, xi + 1]) {
      if (ni < 0 || ni >= xs.length) continue;
      const nx = xs[ni];
      const nKey = `${nx},${cy}`;
      if (closed.has(nKey)) continue;
      if (pointInRects(nx, cy, rects)) continue;
      if (!hSegClear(cy, cx, nx, rects)) continue;

      const dist = Math.abs(nx - cx);
      const penalty = currentDir === 'v' ? TURN_PENALTY : 0;
      const ng = currentG + dist + penalty;

      if (ng < (gScore.get(nKey) ?? Infinity)) {
        cameFrom.set(nKey, current);
        dirFrom.set(nKey, 'h');
        gScore.set(nKey, ng);
        fScore.set(nKey, ng + Math.abs(nx - tx) + Math.abs(cy - ty));
        open.add(nKey);
      }
    }

    for (const ni of [yi - 1, yi + 1]) {
      if (ni < 0 || ni >= ys.length) continue;
      const ny = ys[ni];
      const nKey = `${cx},${ny}`;
      if (closed.has(nKey)) continue;
      if (pointInRects(cx, ny, rects)) continue;
      if (!vSegClear(cx, cy, ny, rects)) continue;

      const dist = Math.abs(ny - cy);
      const penalty = currentDir === 'h' ? TURN_PENALTY : 0;
      const ng = currentG + dist + penalty;

      if (ng < (gScore.get(nKey) ?? Infinity)) {
        cameFrom.set(nKey, current);
        dirFrom.set(nKey, 'v');
        gScore.set(nKey, ng);
        fScore.set(nKey, ng + Math.abs(cx - tx) + Math.abs(ny - ty));
        open.add(nKey);
      }
    }
  }

  if (!cameFrom.has(endKey)) {
    return directOrthogonal(sx, sy, tx, ty);
  }

  const path: Array<{ x: number; y: number }> = [];
  let cur: string | undefined = endKey;
  while (cur) {
    const [x, y] = cur.split(',').map(Number);
    path.push({ x, y });
    cur = cameFrom.get(cur);
  }
  path.reverse();

  return mergeCollinear(pathToSegments(path));
}

import assert from "node:assert/strict";
import test from "node:test";
import { routePipe } from "../src/utils/pipeRouter.ts";
import type { Obstacle } from "../src/utils/pipeRouter.ts";

function rect(x: number, y: number, width: number, height: number): Obstacle {
  return { x, y, width, height };
}

function obstacleBounds(ob: Obstacle, margin = 10) {
  return {
    left: ob.x - ob.width / 2 - margin,
    right: ob.x + ob.width / 2 + margin,
    top: ob.y - ob.height / 2 - margin,
    bottom: ob.y + ob.height / 2 + margin,
  };
}

function segmentCrossesObstacle(x1: number, y1: number, x2: number, y2: number, obstacles: Obstacle[]): boolean {
  for (const ob of obstacles) {
    const b = obstacleBounds(ob);
    if (y1 === y2) {
      if (y1 >= b.top && y1 < b.bottom && Math.max(x1, x2) > b.left && Math.min(x1, x2) < b.right) return true;
    } else if (x1 === x2) {
      if (x1 >= b.left && x1 < b.right && Math.max(y1, y2) > b.top && Math.min(y1, y2) < b.bottom) return true;
    }
  }
  return false;
}

function segmentsValid(segs: Array<{ x1: number; y1: number; x2: number; y2: number }>, obstacles: Obstacle[]): boolean {
  for (const s of segs) {
    if (s.x1 === s.x2 && s.y1 === s.y2) return false;
    if (s.x1 !== s.x2 && s.y1 !== s.y2) return false;
    if (segmentCrossesObstacle(s.x1, s.y1, s.x2, s.y2, obstacles)) return false;
  }
  return true;
}

const canvasW = 1920;
const canvasH = 1080;

test("routes a simple orthogonal path when no obstacles", () => {
  const segs = routePipe(100, 100, 300, 200, [], canvasW, canvasH);
  assert.equal(segs.length, 2);
  assert.equal(segs[0].x1, 100); assert.equal(segs[0].y1, 100);
  assert.equal(segs[0].x2, 300); assert.equal(segs[0].y2, 100);
  assert.equal(segs[1].x1, 300); assert.equal(segs[1].y1, 100);
  assert.equal(segs[1].x2, 300); assert.equal(segs[1].y2, 200);
  assert.ok(segmentsValid(segs, []));
});

test("routes a simple orthogonal path when no obstacles vertical-first", () => {
  const segs = routePipe(100, 100, 100, 300, [], canvasW, canvasH);
  assert.equal(segs.length, 1);
  assert.equal(segs[0].x1, 100); assert.equal(segs[0].y1, 100);
  assert.equal(segs[0].x2, 100); assert.equal(segs[0].y2, 300);
  assert.ok(segmentsValid(segs, []));
});

test("routes a simple orthogonal path when no obstacles horizontal-first", () => {
  const segs = routePipe(100, 100, 300, 100, [], canvasW, canvasH);
  assert.equal(segs.length, 1);
  assert.equal(segs[0].x1, 100); assert.equal(segs[0].y1, 100);
  assert.equal(segs[0].x2, 300); assert.equal(segs[0].y2, 100);
  assert.ok(segmentsValid(segs, []));
});

test("avoids a single obstacle in the middle", () => {
  const obstacle = rect(600, 200, 100, 80);
  const segs = routePipe(100, 200, 700, 200, [obstacle], canvasW, canvasH);
  assert.ok(segmentsValid(segs, [obstacle]));
  assert.ok(segs.length >= 3);
});

test("avoids multiple obstacles", () => {
  const obstacles = [
    rect(250, 180, 100, 100),
    rect(450, 180, 100, 100),
    rect(350, 300, 100, 100),
  ];
  const segs = routePipe(50, 200, 800, 200, obstacles, canvasW, canvasH);
  assert.ok(segmentsValid(segs, obstacles));
});

test("routes around obstacle between source and target on same horizontal line", () => {
  const obstacle = rect(400, 150, 100, 100);
  const segs = routePipe(100, 150, 700, 150, [obstacle], canvasW, canvasH);
  assert.ok(segmentsValid(segs, [obstacle]));
});

test("routes around obstacle between source and target on same vertical line", () => {
  const obstacle = rect(300, 400, 100, 100);
  const segs = routePipe(300, 100, 300, 700, [obstacle], canvasW, canvasH);
  assert.ok(segmentsValid(segs, [obstacle]));
});

test("lead end outside expanded obstacle allows path to start outward", () => {
  const obstacle = rect(800, 200, 200, 200);
  const segs = routePipe(620, 300, 1000, 300, [obstacle], canvasW, canvasH);
  assert.ok(segmentsValid(segs, [obstacle]));
});

test("routes around wall obstacle via canvas edge", () => {
  const obstacles = [
    rect(300, 540, 50, 1000),
  ];
  const segs = routePipe(20, 50, 600, 50, obstacles, canvasW, canvasH);
  assert.ok(segmentsValid(segs, obstacles));
});

test("routes around full-width barrier via canvas outer margin", () => {
  const obstacles = [
    rect(960, 300, 1900, 50),
  ];
  const segs = routePipe(20, 20, 1900, 600, obstacles, canvasW, canvasH);
  assert.ok(segmentsValid(segs, obstacles));
});

test("multiple obstacles forming a barrier", () => {
  const obstacles = [
    rect(300, 200, 100, 140),
    rect(300, 400, 100, 140),
    rect(300, 600, 100, 140),
  ];
  const segs = routePipe(100, 400, 800, 400, obstacles, canvasW, canvasH);
  assert.ok(segmentsValid(segs, obstacles));
});

test("no zero-length segments", () => {
  const obstacles = [rect(400, 200, 100, 100), rect(600, 200, 100, 100)];
  const segs = routePipe(50, 200, 900, 200, obstacles, canvasW, canvasH);
  for (const s of segs) {
    assert.ok(s.x1 !== s.x2 || s.y1 !== s.y2);
  }
});

test("path is continuous", () => {
  const obstacles = [rect(300, 200, 100, 100), rect(500, 300, 100, 100)];
  const segs = routePipe(50, 200, 800, 400, obstacles, canvasW, canvasH);
  for (let i = 1; i < segs.length; i++) {
    assert.equal(segs[i].x1, segs[i - 1].x2);
    assert.equal(segs[i].y1, segs[i - 1].y2);
  }
});

test("all segments are orthogonal", () => {
  const obstacles = [rect(400, 200, 100, 100), rect(500, 400, 100, 100)];
  const segs = routePipe(50, 200, 800, 500, obstacles, canvasW, canvasH);
  for (const s of segs) {
    assert.ok(s.x1 === s.x2 || s.y1 === s.y2);
  }
});

test("same start and end returns empty", () => {
  const segs = routePipe(100, 100, 100, 100, [], canvasW, canvasH);
  assert.equal(segs.length, 0);
});

test("routes around obstacle near target", () => {
  const obstacle = rect(600, 500, 120, 120);
  const segs = routePipe(100, 100, 700, 560, [obstacle], canvasW, canvasH);
  assert.ok(segmentsValid(segs, [obstacle]));
});

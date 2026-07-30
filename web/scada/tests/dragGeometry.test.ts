import assert from "node:assert/strict";
import test from "node:test";
import { captureDragSnapshot, computeDragPositions } from "../src/utils/dragGeometry.ts";

test("single node moves cumulative delta = final delta", () => {
  const snapshot = captureDragSnapshot(["n1"], [{ id: "n1", x: 100, y: 200 }]);
  const sizes = new Map([["n1", { width: 60, height: 40 }]]);

  const r1 = computeDragPositions(snapshot, sizes, 10, 10, 1000, 800);
  assert.equal(r1[0].x, 110);
  assert.equal(r1[0].y, 210);

  const r2 = computeDragPositions(snapshot, sizes, 20, 20, 1000, 800);
  assert.equal(r2[0].x, 120);
  assert.equal(r2[0].y, 220);

  const r3 = computeDragPositions(snapshot, sizes, 30, 30, 1000, 800);
  assert.equal(r3[0].x, 130);
  assert.equal(r3[0].y, 230);
});

test("cumulative delta 10/20/30 produces final 30px not 60px", () => {
  const snapshot = captureDragSnapshot(["n1"], [{ id: "n1", x: 100, y: 100 }]);
  const sizes = new Map([["n1", { width: 60, height: 40 }]]);

  computeDragPositions(snapshot, sizes, 10, 10, 1000, 800);
  computeDragPositions(snapshot, sizes, 20, 20, 1000, 800);
  const r3 = computeDragPositions(snapshot, sizes, 30, 30, 1000, 800);

  assert.equal(r3[0].x, 130);
  assert.equal(r3[0].y, 130);
});

test("idempotent: same delta produces same result", () => {
  const snapshot = captureDragSnapshot(["n1"], [{ id: "n1", x: 100, y: 100 }]);
  const sizes = new Map([["n1", { width: 60, height: 40 }]]);

  const r1 = computeDragPositions(snapshot, sizes, 50, 50, 1000, 800);
  const r2 = computeDragPositions(snapshot, sizes, 50, 50, 1000, 800);

  assert.equal(r1[0].x, r2[0].x);
  assert.equal(r1[0].y, r2[0].y);
});

test("multiple nodes maintain relative spacing", () => {
  const snapshot = captureDragSnapshot(
    ["n1", "n2"],
    [{ id: "n1", x: 100, y: 100 }, { id: "n2", x: 300, y: 200 }]
  );
  const sizes = new Map([
    ["n1", { width: 60, height: 40 }],
    ["n2", { width: 80, height: 50 }],
  ]);

  const result = computeDragPositions(snapshot, sizes, 50, 30, 1000, 800);
  assert.equal(result[0].id, "n1");
  assert.equal(result[0].x, 150);
  assert.equal(result[0].y, 130);
  assert.equal(result[1].id, "n2");
  assert.equal(result[1].x, 350);
  assert.equal(result[1].y, 230);

  const spacingX = result[1].x - result[0].x;
  const spacingY = result[1].y - result[0].y;
  assert.equal(spacingX, 200, "horizontal spacing must be preserved");
  assert.equal(spacingY, 100, "vertical spacing must be preserved");
});

test("clamps group bounding box to canvas edges", () => {
  const snapshot = captureDragSnapshot(
    ["n1"],
    [{ id: "n1", x: 15, y: 15 }]
  );
  const sizes = new Map([["n1", { width: 60, height: 40 }]]);

  const result = computeDragPositions(snapshot, sizes, -50, -50, 300, 200);
  assert.equal(result[0].x, 30, "n1 left edge at 0, center at 30");
  assert.equal(result[0].y, 20, "n1 top edge at 0, center at 20");
});

test("clamp does not jump when dragging back from edge", () => {
  const snapshot = captureDragSnapshot(
    ["n1"],
    [{ id: "n1", x: 100, y: 100 }]
  );
  const sizes = new Map([["n1", { width: 60, height: 40 }]]);

  const r1 = computeDragPositions(snapshot, sizes, -100, -100, 300, 200);
  assert.equal(r1[0].x, 30, "clamped at left edge");

  const r2 = computeDragPositions(snapshot, sizes, -50, -50, 300, 200);
  assert.equal(r2[0].x, 50, "back from edge without jump");
  assert.equal(r2[0].y, 50, "back from edge without jump");
});

test("rounds to 2 decimal places", () => {
  const snapshot = captureDragSnapshot(["n1"], [{ id: "n1", x: 100, y: 100 }]);
  const sizes = new Map([["n1", { width: 60, height: 40 }]]);

  const result = computeDragPositions(snapshot, sizes, 10 / 3, 10 / 3, 1000, 800);
  assert.equal(result[0].x, 103.33);
  assert.equal(result[0].y, 103.33);
});

test("zoom correction: 55% zoom, 30px screen delta -> 54.55 canvas delta", () => {
  const snapshot = captureDragSnapshot(["n1"], [{ id: "n1", x: 200, y: 200 }]);
  const sizes = new Map([["n1", { width: 60, height: 40 }]]);
  const zoom = 0.55;
  const screenDx = 30;
  const canvasDx = screenDx / zoom;

  const result = computeDragPositions(snapshot, sizes, canvasDx, 0, 1000, 800);
  assert.equal(result[0].x, 254.55);
  assert.equal(result[0].y, 200);
});

test("empty snapshot returns empty array", () => {
  const snapshot = captureDragSnapshot([], []);
  const sizes = new Map();
  const result = computeDragPositions(snapshot, sizes, 10, 10, 1000, 800);
  assert.equal(result.length, 0);
});

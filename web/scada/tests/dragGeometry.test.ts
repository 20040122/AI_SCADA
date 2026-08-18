import assert from "node:assert/strict";
import test from "node:test";
import { captureDragSnapshot, computeDragPositions, computeRatioResize } from "../src/utils/dragGeometry.ts";

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

test("se corner resize keeps ratio and opposite corner anchored", () => {
  const node = { x: 300, y: 300, width: 200, height: 100 };
  const result = computeRatioResize("se", node, 100, 50, 1000, 800, 2);
  assert.equal(result.width, 300);
  assert.equal(result.height, 150);
  assert.equal(result.x, 350);
  assert.equal(result.y, 325);
  assert.equal(result.x - result.width / 2, 200, "left edge anchored");
  assert.equal(result.y - result.height / 2, 250, "top edge anchored");
});

test("nw corner inward drag keeps ratio and opposite corner anchored", () => {
  const node = { x: 300, y: 300, width: 200, height: 100 };
  const result = computeRatioResize("nw", node, -50, -30, 1000, 800, 2);
  assert.equal(result.width, 250);
  assert.equal(result.height, 125);
  assert.equal(result.x, 275);
  assert.equal(result.y, 287.5);
  assert.equal(result.x + result.width / 2, 400, "right edge anchored");
  assert.equal(result.y + result.height / 2, 350, "bottom edge anchored");
});

test("e edge drag shrink keeps ratio and left edge anchored", () => {
  const node = { x: 300, y: 300, width: 200, height: 100 };
  const result = computeRatioResize("e", node, -60, 0, 1000, 800, 2);
  assert.equal(result.width, 140);
  assert.equal(result.height, 70);
  assert.equal(result.x, 270);
  assert.equal(result.y, 300, "vertical center unchanged");
  assert.equal(result.x - result.width / 2, 200, "left edge anchored");
});

test("e edge drag grows ratio-mismatched node toward material ratio", () => {
  const node = { x: 300, y: 300, width: 200, height: 100 };
  const result = computeRatioResize("e", node, 100, 0, 1000, 800, 2.2);
  assert.equal(result.width, 220);
  assert.equal(result.height, 100);
  assert.equal(result.x, 310);
  assert.equal(result.y, 300);
  assert.equal(result.x - result.width / 2, 200, "left edge anchored");
});

test("s edge drag keeps ratio and top edge anchored", () => {
  const node = { x: 300, y: 300, width: 200, height: 100 };
  const result = computeRatioResize("s", node, 0, -40, 1000, 800, 2);
  assert.equal(result.width, 120);
  assert.equal(result.height, 60);
  assert.equal(result.x, 300, "horizontal center unchanged");
  assert.equal(result.y, 280);
  assert.equal(result.y - result.height / 2, 250, "top edge anchored");
});

test("oversized drag is clipped by uniform scale only", () => {
  const node = { x: 150, y: 150, width: 100, height: 50 };
  const result = computeRatioResize("se", node, 1000, 1000, 300, 300, 2);
  assert.equal(result.width, 300);
  assert.equal(result.height, 150);
  assert.equal(result.width / result.height, 2);
  assert.ok(result.x >= result.width / 2);
  assert.ok(result.x <= 300 - result.width / 2);
  assert.ok(result.y >= result.height / 2);
  assert.ok(result.y <= 300 - result.height / 2);
});

test("height-bound drag inscribes largest in-box ratio rect", () => {
  const node = { x: 300, y: 300, width: 200, height: 100 };
  const result = computeRatioResize("se", node, 100, 200, 1000, 800, 2.2);
  assert.equal(result.width, 300);
  assert.equal(result.height, 136.36);
  assert.ok(Math.abs(result.width / result.height - 2.2) < 0.001);
});

test("invalid aspect falls back to ratio 1", () => {
  const node = { x: 300, y: 300, width: 200, height: 100 };
  const result = computeRatioResize("se", node, 100, 50, 1000, 800, 0);
  assert.equal(result.width, 150);
  assert.equal(result.height, 150);
  const result2 = computeRatioResize("se", node, 100, 50, 1000, 800, NaN);
  assert.equal(result2.width, 150);
  assert.equal(result2.height, 150);
});

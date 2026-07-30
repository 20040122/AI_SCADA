import assert from "node:assert/strict";
import test from "node:test";
import type { CanvasNode } from "../src/types/layout.ts";
import { getLeadLength, getLeadEnd } from "../src/utils/pipeGeometry.ts";

function makeNode(w: number, h: number): CanvasNode {
  return { id: "t", displayName: "", image: "", x: 0, y: 0, width: w, height: h, color: "#888" };
}

test("getLeadLength clamp at 20 for small controls", () => {
  const node = makeNode(30, 20);
  assert.equal(getLeadLength(node), 20);
});

test("getLeadLength uses 20% of min dimension for medium controls", () => {
  const node = makeNode(150, 100);
  assert.equal(getLeadLength(node), 20);
});

test("getLeadLength clamps at 60 for large controls", () => {
  const node = makeNode(500, 300);
  assert.equal(getLeadLength(node), 60);
});

test("getLeadLength half-width 200 gives 40", () => {
  const node = makeNode(200, 300);
  assert.equal(getLeadLength(node), 40);
});

test("getLeadEnd right port extends horizontally", () => {
  const edge = { x: 100, y: 200 };
  const end = getLeadEnd(edge, "right", 40);
  assert.equal(end.x, 140);
  assert.equal(end.y, 200);
});

test("getLeadEnd left port extends horizontally left", () => {
  const edge = { x: 100, y: 200 };
  const end = getLeadEnd(edge, "left", 40);
  assert.equal(end.x, 60);
  assert.equal(end.y, 200);
});

test("getLeadEnd top port extends upward", () => {
  const edge = { x: 100, y: 200 };
  const end = getLeadEnd(edge, "top", 40);
  assert.equal(end.x, 100);
  assert.equal(end.y, 160);
});

test("getLeadEnd bottom port extends downward", () => {
  const edge = { x: 100, y: 200 };
  const end = getLeadEnd(edge, "bottom", 40);
  assert.equal(end.x, 100);
  assert.equal(end.y, 240);
});

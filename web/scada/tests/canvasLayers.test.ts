import assert from "node:assert/strict";
import test from "node:test";
import { partitionDecorationsForPipes } from "../src/utils/canvasLayers.ts";
import type { DecorationNode } from "../src/types/layout.ts";

const background: DecorationNode = {
  type: "image",
  image: "assets/Agent/画面背景.png",
  x: 960,
  y: 540,
  width: 1920,
  height: 1080,
};

const titleBar: DecorationNode = {
  type: "image",
  image: "assets/Agent/标题栏.png",
  x: 960,
  y: 46,
  width: 1920,
  height: 93,
};

const title: DecorationNode = {
  type: "text",
  text: "冷冻站",
  x: 960,
  y: 37,
  width: 500,
  height: 60,
};

test("places a full-canvas image behind pipes", () => {
  const result = partitionDecorationsForPipes(
    [background, titleBar, title],
    1920,
    1080,
  );

  assert.deepEqual(result.backgrounds, [background]);
  assert.deepEqual(result.foregrounds, [titleBar, title]);
});

test("keeps images in the foreground when they do not cover the canvas", () => {
  const result = partitionDecorationsForPipes([titleBar], 1920, 1080);

  assert.deepEqual(result.backgrounds, []);
  assert.deepEqual(result.foregrounds, [titleBar]);
});

test("does not classify backgrounds without valid canvas dimensions", () => {
  const result = partitionDecorationsForPipes([background], 0, 0);

  assert.deepEqual(result.backgrounds, []);
  assert.deepEqual(result.foregrounds, [background]);
});

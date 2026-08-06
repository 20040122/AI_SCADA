import assert from "node:assert/strict";
import test from "node:test";
import { resolveBindingSource } from "../src/stores/bindingStore.ts";
import type { LayoutSnapshot, RefineSnapshot } from "../src/stores/bindingStore.ts";
import type { LayoutJsonData } from "../src/types/layout.ts";

function makeJson(): LayoutJsonData {
  return {
    v: "1",
    p: { layers: [], autoAdjustIndex: false, hierarchicalRendering: false },
    a: { width: 1920, height: 1080, fitContent: false, rectSelectable: false, pannable: false, zoomable: false },
    d: [],
    contentRect: { x: 0, y: 0, width: 0, height: 0 },
  };
}

function layout(overrides?: Partial<LayoutSnapshot>): LayoutSnapshot {
  return {
    revision: 3,
    jsonData: makeJson(),
    fileName: "画面.json",
    pipe_data: null,
    ...overrides,
  };
}

function refine(overrides?: Partial<RefineSnapshot>): RefineSnapshot {
  return {
    revision: 7,
    workingJson: null,
    sourceFileName: null,
    workingPipes: null,
    pendingPatch: null,
    ...overrides,
  };
}

test("pending Patch blocks source sync entirely", () => {
  const source = resolveBindingSource(
    layout(),
    refine({ workingJson: makeJson(), sourceFileName: "画面.json", pendingPatch: {} })
  );
  assert.equal(source, null);
});

test("refined draft takes priority when it matches layout file name", () => {
  const refined = makeJson();
  const source = resolveBindingSource(
    layout(),
    refine({ workingJson: refined, sourceFileName: "画面.json", workingPipes: { connections: [] } })
  );
  assert.ok(source);
  assert.equal(source!.sourceType, "refine");
  assert.equal(source!.revision, 7);
  assert.equal(source!.canvas, refined);
  assert.deepEqual(source!.pipes, { connections: [] });
  assert.equal(source!.fileName, "画面.json");
});

test("falls back to layout draft when refine has no working json", () => {
  const source = resolveBindingSource(layout(), refine());
  assert.ok(source);
  assert.equal(source!.sourceType, "layout");
  assert.equal(source!.revision, 3);
  assert.ok(source!.canvas);
  assert.equal(source!.fileName, "画面.json");
});

test("falls back to layout draft when refine file name differs", () => {
  const source = resolveBindingSource(
    layout(),
    refine({ workingJson: makeJson(), sourceFileName: "其他.json" })
  );
  assert.ok(source);
  assert.equal(source!.sourceType, "layout");
});

test("returns empty layout source when nothing is available", () => {
  const source = resolveBindingSource(
    layout({ jsonData: null, fileName: "" }),
    refine()
  );
  assert.ok(source);
  assert.equal(source!.sourceType, "layout");
  assert.equal(source!.canvas, null);
  assert.equal(source!.pipes, null);
  assert.equal(source!.fileName, "");
});

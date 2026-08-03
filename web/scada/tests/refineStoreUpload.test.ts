import assert from "node:assert/strict";
import test from "node:test";
import { useRefineStore } from "../src/stores/refineStore.ts";
import type { CanvasNode, LayoutJsonData, UploadCanvasResponse } from "../src/types/layout.ts";

function resetStore() {
  useRefineStore.setState({
    workingNodes: [],
    decorations: [],
    workingPipes: null,
    workingJson: null,
    sourceFileName: null,
    canvasWidth: 1920,
    canvasHeight: 1080,
    selectedNodeIds: [],
    messages: [],
    history: [],
    isRefining: false,
    pendingPatch: null,
  });
}

function makeNode(): CanvasNode {
  return {
    id: "node-17092",
    displayName: "液压泵",
    image: "symbols/pump.json",
    x: 300,
    y: 300,
    width: 300,
    height: 150,
    color: "#888",
    a: { "layout.node": true, "layout.group": "g1", "layout.instance": 0, "layout.sourceWidth": 154, "layout.sourceHeight": 70 },
  };
}

function makeJson(controlH: number): LayoutJsonData {
  return {
    v: "1",
    p: { layers: [], autoAdjustIndex: false, hierarchicalRendering: false },
    a: { width: 1920, height: 1080, fitContent: false, rectSelectable: false, pannable: false, zoomable: false },
    d: [
      {
        c: "ht.Node",
        i: 17092,
        p: { displayName: "液压泵", image: "symbols/pump.json", position: { x: 300, y: 300 }, width: 300, height: controlH },
        a: { "layout.node": true, "layout.group": "g1", "layout.instance": 0, "layout.sourceWidth": 154, "layout.sourceHeight": 70 },
      },
    ],
    contentRect: { x: 100, y: 100, width: 400, height: 200 },
  };
}

function makeUploadResponse(): UploadCanvasResponse {
  return {
    file_name: "画面.json",
    json_data: makeJson(136.36),
    corrections: [
      {
        node_i: 17092,
        display_name: "液压泵",
        image: "symbols/pump.json",
        before: { width: 300, height: 150 },
        after: { width: 300, height: 136.36 },
      },
    ],
    warnings: [],
  };
}

test("applyUploadResult writes normalized JSON back into refine store", () => {
  resetStore();
  useRefineStore.getState().loadFromLayoutData([makeNode()], 1920, 1080, makeJson(150), "画面.json");
  assert.equal(useRefineStore.getState().workingJson?.d[0].p.height, 150);

  useRefineStore.getState().applyUploadResult(makeUploadResponse());

  const state = useRefineStore.getState();
  assert.equal(state.workingJson?.d[0].p.height, 136.36);
  assert.equal(state.workingNodes[0].height, 136.36);
  assert.equal(state.sourceFileName, "画面.json");
});

test("applyUploadResult keeps pendingPatch blocking state intact", () => {
  resetStore();
  useRefineStore.getState().loadFromLayoutData([makeNode()], 1920, 1080, makeJson(150), "画面.json");
  useRefineStore.getState().applyPatch(
    [{ op: "replace", path: "/d/0/p/width", value: 200 }],
    "refine-ai-1"
  );
  assert.ok(useRefineStore.getState().pendingPatch !== null);

  useRefineStore.getState().applyUploadResult(makeUploadResponse());

  assert.ok(useRefineStore.getState().pendingPatch !== null);
  assert.equal(useRefineStore.getState().pendingPatch?.messageId, "refine-ai-1");
});

test("applyUploadResult keeps workingPipes", () => {
  resetStore();
  useRefineStore.getState().loadFromLayoutData([makeNode()], 1920, 1080, makeJson(150), "画面.json", {
    connections: [],
  });
  useRefineStore.getState().applyUploadResult(makeUploadResponse());

  assert.deepEqual(useRefineStore.getState().workingPipes, { connections: [] });
});

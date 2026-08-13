import assert from "node:assert/strict";
import test from "node:test";
import { useRefineStore } from "../src/stores/refineStore.ts";
import type { CanvasNode, LayoutJsonData, PipeData } from "../src/types/layout.ts";
import type { JsonPatchOp } from "../src/types/refine.ts";

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
    id: "node-20399",
    displayName: "状态面板",
    image: "symbols/panel.json",
    x: 960,
    y: 540,
    width: 120,
    height: 44.44,
    color: "#888",
    a: { "layout.node": true, "layout.group": "g1", "layout.instance": 1 },
  };
}

function makeJson(): LayoutJsonData {
  return {
    v: "1",
    p: { layers: [], autoAdjustIndex: false, hierarchicalRendering: false },
    a: {
      width: 1920,
      height: 1080,
      fitContent: false,
      rectSelectable: false,
      pannable: false,
      zoomable: false,
      "layout.materials": [
        { displayName: "状态面板", image: "symbols/panel.json", width: 162, height: 60 },
      ],
    },
    d: [
      {
        c: "ht.Node",
        i: 20399,
        p: {
          displayName: "状态面板",
          image: "symbols/panel.json",
          position: { x: 960, y: 540 },
          width: 120,
          height: 44.44,
        },
        a: { "layout.node": true, "layout.group": "g1", "layout.instance": 1 },
      },
    ],
    contentRect: { x: 740, y: 517.78, width: 280, height: 44.44 },
  };
}

function makeAddPatch(): JsonPatchOp[] {
  return [
    {
      op: "add",
      path: "/d/-",
      value: {
        c: "ht.Node",
        i: 20400,
        p: {
          displayName: "状态面板2",
          image: "symbols/panel.json",
          position: { x: 800, y: 540 },
          width: 120,
          height: 44.44,
        },
        a: { "layout.node": "refine_20400", "layout.group": "g1", "layout.instance": 1 },
      },
    },
    { op: "replace", path: "/contentRect", value: { x: 740, y: 517.78, width: 280, height: 44.44 } },
  ];
}

test("applyPatch appends /d/- nodes and keeps anchor selection", () => {
  resetStore();
  useRefineStore.getState().loadFromLayoutData(
    [makeNode()],
    1920,
    1080,
    makeJson(),
    "画面.json",
    { connections: [] } as PipeData
  );
  useRefineStore.getState().setSelection(["node-20399"]);

  useRefineStore.getState().applyPatch(makeAddPatch(), "refine-ai-1");

  const state = useRefineStore.getState();
  assert.equal(state.workingNodes.length, 2);
  assert.equal(state.workingJson?.d.length, 2);
  assert.equal(state.workingJson?.d[1].i, 20400);
  assert.equal(state.workingJson?.d[1].p?.displayName, "状态面板2");
  assert.equal(state.workingJson?.a["layout.materials"]?.length, 1);
  assert.deepEqual(state.selectedNodeIds, ["node-20399"]);
  assert.ok(state.pendingPatch !== null);
  assert.equal(state.pendingPatch?.messageId, "refine-ai-1");
});

test("applyPatch keeps pipe data unchanged for added nodes", () => {
  resetStore();
  const pipes: PipeData = {
    connections: [
      {
        id: "p1",
        source: { group: "g1", node: "r", instance: 1, port: "out" },
        target: { group: "g1", node: "r", instance: 1, port: "in" },
      },
    ],
  };
  useRefineStore.getState().loadFromLayoutData([makeNode()], 1920, 1080, makeJson(), "画面.json", pipes);
  useRefineStore.getState().setSelection(["node-20399"]);

  useRefineStore.getState().applyPatch(makeAddPatch(), "refine-ai-1");

  assert.deepEqual(useRefineStore.getState().workingPipes, pipes);
});

test("acceptPatch commits added nodes and records history", () => {
  resetStore();
  useRefineStore.getState().loadFromLayoutData([makeNode()], 1920, 1080, makeJson(), "画面.json");
  useRefineStore.getState().setSelection(["node-20399"]);
  useRefineStore.getState().applyPatch(makeAddPatch(), "refine-ai-1");

  useRefineStore.getState().acceptPatch("refine-ai-1");

  const state = useRefineStore.getState();
  assert.equal(state.pendingPatch, null);
  assert.equal(state.workingNodes.length, 2);
  assert.equal(state.history.length, 1);
  assert.ok(state.history[0].patch.includes('"/d/-"'));
});

test("rejectPatch restores snapshot without added nodes", () => {
  resetStore();
  useRefineStore.getState().loadFromLayoutData([makeNode()], 1920, 1080, makeJson(), "画面.json");
  useRefineStore.getState().setSelection(["node-20399"]);
  useRefineStore.getState().applyPatch(makeAddPatch(), "refine-ai-1");
  assert.equal(useRefineStore.getState().workingNodes.length, 2);

  useRefineStore.getState().rejectPatch("refine-ai-1");

  const state = useRefineStore.getState();
  assert.equal(state.pendingPatch, null);
  assert.equal(state.workingNodes.length, 1);
  assert.equal(state.workingJson?.d.length, 1);
  assert.deepEqual(state.selectedNodeIds, ["node-20399"]);
});

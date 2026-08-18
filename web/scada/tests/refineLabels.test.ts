import assert from "node:assert/strict";
import test from "node:test";
import { extractNodesFromJsonData } from "../src/utils/layoutNodes.ts";
import { useRefineStore } from "../src/stores/refineStore.ts";
import type { LayoutJsonData } from "../src/types/layout.ts";

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

function makeNodeJson(s?: Record<string, unknown>): LayoutJsonData {
  const node: Record<string, unknown> = {
    c: "ht.Node",
    i: 17092,
    p: {
      displayName: "液压泵",
      image: "symbols/pump.json",
      position: { x: 300, y: 300 },
      width: 300,
      height: 150,
    },
    a: { "layout.node": true, "layout.group": "g1", "layout.instance": 0 },
  };
  if (s) node.s = s;
  return {
    v: "1",
    p: {},
    a: { width: 1920, height: 1080 },
    d: [node],
  };
}

test("extractNodesFromJsonData reads inline label fields", () => {
  const nodes = extractNodesFromJsonData(
    makeNodeJson({
      label: "入口阀",
      "label.color": "rgb(255,255,255)",
      "label.font": "18px arial, sans-serif",
    })
  );
  assert.equal(nodes[0].label, "入口阀");
  assert.equal(nodes[0].labelColor, "rgb(255,255,255)");
  assert.equal(nodes[0].labelFont, "18px arial, sans-serif");
});

test("extractNodesFromJsonData shows no label when s.label missing", () => {
  const nodes = extractNodesFromJsonData(makeNodeJson());
  assert.equal(nodes[0].label, "");
  assert.equal(nodes[0].displayName, "液压泵");
  assert.equal(nodes[0].labelColor, "rgb(255,255,255)");
  assert.equal(nodes[0].labelFont, "18px arial, sans-serif");
});

test("extractNodesFromJsonData keeps displayName as identity when label differs", () => {
  const nodes = extractNodesFromJsonData(makeNodeJson({ label: "自定义名" }));
  assert.equal(nodes[0].label, "自定义名");
  assert.equal(nodes[0].displayName, "液压泵");
});

test("applyPatch first-time full style add renders label", () => {
  resetStore();
  useRefineStore.getState().loadFromLayoutData(
    extractNodesFromJsonData(makeNodeJson()),
    1920,
    1080,
    makeNodeJson(),
    "画面.json"
  );
  useRefineStore.getState().applyPatch(
    [
      {
        op: "add",
        path: "/d/0/s",
        value: {
          label: "入口阀",
          "label.color": "rgb(255,255,255)",
          "label.font": "18px arial, sans-serif",
        },
      },
    ],
    "refine-ai-1"
  );
  const state = useRefineStore.getState();
  assert.equal(state.workingNodes[0].label, "入口阀");
  assert.equal(state.workingNodes[0].labelColor, "rgb(255,255,255)");
  assert.equal(state.workingNodes[0].labelFont, "18px arial, sans-serif");
  assert.deepEqual(state.workingJson?.d[0].s, {
    label: "入口阀",
    "label.color": "rgb(255,255,255)",
    "label.font": "18px arial, sans-serif",
  });
});

test("rejectPatch reverts first-time full style add", () => {
  resetStore();
  useRefineStore.getState().loadFromLayoutData(
    extractNodesFromJsonData(makeNodeJson()),
    1920,
    1080,
    makeNodeJson(),
    "画面.json"
  );
  useRefineStore.getState().applyPatch(
    [
      {
        op: "add",
        path: "/d/0/s",
        value: {
          label: "入口阀",
          "label.color": "rgb(255,255,255)",
          "label.font": "18px arial, sans-serif",
        },
      },
    ],
    "refine-ai-1"
  );
  useRefineStore.getState().rejectPatch("refine-ai-1");
  const state = useRefineStore.getState();
  assert.equal(state.workingNodes[0].label, "");
  assert.equal(state.workingJson?.d[0].s, undefined);
});

test("applyPatch style sub-path patch updates label without touching other keys", () => {
  resetStore();
  const json = makeNodeJson({ opacity: 1, "label.color": "red" });
  useRefineStore.getState().loadFromLayoutData(
    extractNodesFromJsonData(json),
    1920,
    1080,
    json,
    "画面.json"
  );
  useRefineStore.getState().applyPatch(
    [
      { op: "add", path: "/d/0/s/label", value: "入口阀" },
      { op: "replace", path: "/d/0/s/label.color", value: "rgb(255,255,255)" },
      { op: "add", path: "/d/0/s/label.font", value: "18px arial, sans-serif" },
    ],
    "refine-ai-1"
  );
  const state = useRefineStore.getState();
  assert.equal(state.workingNodes[0].label, "入口阀");
  assert.equal(state.workingNodes[0].labelColor, "rgb(255,255,255)");
  assert.equal(state.workingJson?.d[0].s?.["opacity"], 1);
});

test("applyPatch removing legacy label clears its decoration", () => {
  resetStore();
  const json = makeNodeJson();
  json.d.push({
    c: "ht.Text",
    i: 17093,
    p: { position: { x: 300, y: 226 }, width: 200, height: 32 },
    s: { text: "液压泵" },
    a: { "layout.role": "control-label", "layout.labelFor": 17092 },
  });
  useRefineStore.getState().loadFromLayoutData(
    extractNodesFromJsonData(json),
    1920,
    1080,
    json,
    "画面.json"
  );
  assert.ok(useRefineStore.getState().decorations.length > 0);
  useRefineStore.getState().applyPatch(
    [{ op: "remove", path: "/d/1" }],
    "refine-ai-1"
  );
  const state = useRefineStore.getState();
  assert.equal(state.decorations.length, 0);
  assert.equal(state.workingJson?.d.length, 1);
});

test("moveNodes keeps inline label and legacy label linkage", () => {
  resetStore();
  const json = makeNodeJson({ label: "入口阀" });
  json.d.push({
    c: "ht.Text",
    i: 17093,
    p: { position: { x: 300, y: 226 }, width: 200, height: 32 },
    s: { text: "旧标签" },
    a: { "layout.role": "control-label", "layout.labelFor": 17092 },
  });
  const nodes = extractNodesFromJsonData(json);
  useRefineStore.getState().loadFromLayoutData(nodes, 1920, 1080, json, "画面.json");
  useRefineStore.getState().moveNodes(["node-17092"], 20, 0);
  const state = useRefineStore.getState();
  assert.equal(state.workingNodes[0].x, 320);
  assert.equal(state.workingNodes[0].label, "入口阀");
  const legacy = state.workingJson?.d.find((n) => n.i === 17093);
  assert.equal(legacy?.p?.position?.x, 320);
});

test("resizeNode keeps inline label rendered on node", () => {
  resetStore();
  const json = makeNodeJson({ label: "入口阀" });
  useRefineStore.getState().loadFromLayoutData(
    extractNodesFromJsonData(json),
    1920,
    1080,
    json,
    "画面.json"
  );
  useRefineStore.getState().resizeNode("node-17092", 300, 300, 200, 100);
  const state = useRefineStore.getState();
  assert.equal(state.workingNodes[0].width, 200);
  assert.equal(state.workingNodes[0].label, "入口阀");
  assert.equal(state.workingJson?.d[0].p?.width, 200);
});

import assert from "node:assert/strict";
import test from "node:test";
import { useRefineStore } from "../src/stores/refineStore.ts";
import type { CanvasNode, PipeData, PipeConnection, LayoutJsonData } from "../src/types/layout.ts";
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

function makeNode(
  id: string,
  group: string,
  nodeName: string,
  instance: number,
  x = 100,
  y = 100,
): CanvasNode {
  return {
    id,
    displayName: `Node-${id}`,
    image: "",
    x,
    y,
    width: 60,
    height: 40,
    color: "#888",
    a: { "layout.group": group, "layout.node": nodeName, "layout.instance": instance },
  };
}

function makeConnection(
  id: string,
  sg: string, sn: string, si: number, sp: string,
  tg: string, tn: string, ti: number, tp: string,
): PipeConnection {
  return {
    id,
    source: { group: sg, node: sn, instance: si, port: sp },
    target: { group: tg, node: tn, instance: ti, port: tp },
  };
}

test("loadFromLayoutData deep-copies pipes and isolates from layoutStore", () => {
  resetStore();

  const pipes: PipeData = {
    connections: [
      makeConnection("c1", "g1", "n1", 1, "right", "g1", "n2", 1, "left"),
    ],
  };

  const nodes = [
    makeNode("node-0", "g1", "n1", 1),
    makeNode("node-1", "g1", "n2", 1),
  ];

  useRefineStore.getState().loadFromLayoutData(
    nodes,
    1000,
    800,
    { v: "1", p: {}, a: { width: 1000, height: 800 }, d: [] },
    "test.json",
    pipes,
  );

  const state = useRefineStore.getState();
  assert.ok(state.workingPipes !== null);
  assert.equal(state.workingPipes.connections.length, 1);
  assert.equal(state.workingPipes.connections[0].id, "c1");

  pipes.connections.push(makeConnection("c2", "g1", "n3", 1, "right", "g1", "n4", 1, "left"));
  assert.equal(state.workingPipes.connections.length, 1,
    "mutating original pipe_data must not affect refine snapshot");
});

test("loadFromLayoutData accepts no pipes", () => {
  resetStore();

  useRefineStore.getState().loadFromLayoutData(
    [makeNode("node-0", "g1", "n1", 1)],
    1000, 800, null, "test.json",
  );

  assert.equal(useRefineStore.getState().workingPipes, null);
});

test("clearCanvas clears workingPipes", () => {
  resetStore();

  useRefineStore.getState().loadFromLayoutData(
    [makeNode("node-0", "g1", "n1", 1)],
    1000, 800,
    { v: "1", p: {}, a: { width: 1000, height: 800 }, d: [] },
    "test.json",
    { connections: [makeConnection("c1", "g1", "n1", 1, "right", "g1", "n2", 1, "left")] },
  );

  assert.notEqual(useRefineStore.getState().workingPipes, null);

  useRefineStore.getState().clearCanvas();
  assert.equal(useRefineStore.getState().workingPipes, null);
  assert.equal(useRefineStore.getState().workingNodes.length, 0);
});

test("moveNodes does not change pipe data", () => {
  resetStore();

  const pipes: PipeData = {
    connections: [
      makeConnection("c1", "g1", "n1", 1, "right", "g1", "n2", 1, "left"),
    ],
  };

  const nodes = [
    makeNode("node-0", "g1", "n1", 1, 100, 100),
    makeNode("node-1", "g1", "n2", 1, 200, 200),
  ];

  useRefineStore.getState().loadFromLayoutData(
    nodes, 1000, 800,
    { v: "1", p: {}, a: { width: 1000, height: 800 }, d: [] },
    "test.json", pipes,
  );

  useRefineStore.getState().moveNodes(["node-0"], 50, 50);

  const state = useRefineStore.getState();
  assert.equal(state.workingPipes!.connections.length, 1);
  assert.equal(state.workingPipes!.connections[0].id, "c1",
    "moveNodes must not alter pipe connections");
});

test("applyPatch removes connections for deleted nodes", () => {
  resetStore();

  const pipes: PipeData = {
    connections: [
      makeConnection("c1", "g1", "n1", 1, "right", "g1", "n2", 1, "left"),
      makeConnection("c2", "g1", "n2", 1, "right", "g1", "n3", 1, "left"),
    ],
  };

  const jsonData: LayoutJsonData = {
    v: "1",
    p: {},
    a: { width: 1000, height: 800 },
    d: [
      { c: "ht.Valve", i: 0, p: { displayName: "Valve1", position: { x: 100, y: 100 } }, a: { "layout.group": "g1", "layout.node": "n1", "layout.instance": 1 } },
      { c: "ht.Valve", i: 1, p: { displayName: "Valve2", position: { x: 200, y: 200 } }, a: { "layout.group": "g1", "layout.node": "n2", "layout.instance": 1 } },
      { c: "ht.Valve", i: 2, p: { displayName: "Valve3", position: { x: 300, y: 300 } }, a: { "layout.group": "g1", "layout.node": "n3", "layout.instance": 1 } },
    ],
  };

  useRefineStore.getState().loadFromLayoutData(
    extractNodes(jsonData), 1000, 800, jsonData, "test.json", pipes,
  );

  assert.equal(useRefineStore.getState().workingPipes!.connections.length, 2);

  const patch: JsonPatchOp[] = [{ op: "remove", path: "/d/1" }];

  useRefineStore.getState().applyPatch(patch, "msg-1");

  const state = useRefineStore.getState();
  assert.equal(state.workingNodes.length, 2);
  assert.equal(state.workingPipes!.connections.length, 0,
    "both c1 (n1->n2) and c2 (n2->n3) removed because n2 is gone");

  assert.ok(state.pendingPatch !== null);
  assert.equal(state.pendingPatch.pipesSnapshot!.connections.length, 2,
    "snapshot must preserve original pipes");
});

function extractNodes(json: LayoutJsonData): CanvasNode[] {
  return json.d.filter((n) => n.p?.position).map((n, idx) => ({
    id: `node-${n.i ?? idx}`,
    displayName: n.p.displayName || "",
    image: "",
    x: n.p.position!.x,
    y: n.p.position!.y,
    width: n.p.width || 60,
    height: n.p.height || 40,
    color: "#888",
    a: n.a ? { ...n.a } : undefined,
  }));
}

test("rejectPatch restores original pipes", () => {
  resetStore();

  const pipes: PipeData = {
    connections: [
      makeConnection("c1", "g1", "n1", 1, "right", "g1", "n2", 1, "left"),
    ],
  };

  const jsonData: LayoutJsonData = {
    v: "1", p: {}, a: { width: 1000, height: 800 },
    d: [
      { c: "ht.Valve", i: 0, p: { displayName: "V1", position: { x: 100, y: 100 } }, a: { "layout.group": "g1", "layout.node": "n1", "layout.instance": 1 } },
      { c: "ht.Valve", i: 1, p: { displayName: "V2", position: { x: 200, y: 200 } }, a: { "layout.group": "g1", "layout.node": "n2", "layout.instance": 1 } },
    ],
  };

  useRefineStore.getState().loadFromLayoutData(
    extractNodes(jsonData), 1000, 800, jsonData, "test.json", pipes,
  );

  useRefineStore.getState().applyPatch([{ op: "remove", path: "/d/1" }], "msg-1");
  assert.equal(useRefineStore.getState().workingPipes!.connections.length, 0,
    "c1 removed because n2 (target) is deleted");

  useRefineStore.getState().rejectPatch("msg-1");
  const state = useRefineStore.getState();
  assert.equal(state.workingPipes!.connections.length, 1,
    "reject must restore original pipes");
  assert.equal(state.workingPipes!.connections[0].id, "c1");
  assert.equal(state.pendingPatch, null);
});

test("acceptPatch keeps filtered pipes", () => {
  resetStore();

  const pipes: PipeData = {
    connections: [
      makeConnection("c1", "g1", "n1", 1, "right", "g1", "n2", 1, "left"),
      makeConnection("c2", "g1", "n1", 1, "right", "g1", "n3", 1, "left"),
    ],
  };

  const jsonData: LayoutJsonData = {
    v: "1", p: {}, a: { width: 1000, height: 800 },
    d: [
      { c: "ht.Valve", i: 0, p: { displayName: "V1", position: { x: 100, y: 100 } }, a: { "layout.group": "g1", "layout.node": "n1", "layout.instance": 1 } },
      { c: "ht.Valve", i: 1, p: { displayName: "V2", position: { x: 200, y: 200 } }, a: { "layout.group": "g1", "layout.node": "n2", "layout.instance": 1 } },
      { c: "ht.Valve", i: 2, p: { displayName: "V3", position: { x: 300, y: 300 } }, a: { "layout.group": "g1", "layout.node": "n3", "layout.instance": 1 } },
    ],
  };

  useRefineStore.getState().loadFromLayoutData(
    extractNodes(jsonData), 1000, 800, jsonData, "test.json", pipes,
  );

  useRefineStore.getState().applyPatch([{ op: "remove", path: "/d/1" }], "msg-1");
  assert.equal(useRefineStore.getState().workingPipes!.connections.length, 1,
    "c1 (n1->n2) removed, c2 (n1->n3) kept");

  useRefineStore.getState().acceptPatch("msg-1");
  const state = useRefineStore.getState();
  assert.equal(state.workingPipes!.connections.length, 1,
    "accept must keep the filtered pipes");
  assert.equal(state.pendingPatch, null);
});

test("delete node without pipes does not error", () => {
  resetStore();

  const jsonData: LayoutJsonData = {
    v: "1", p: {}, a: { width: 1000, height: 800 },
    d: [
      { c: "ht.Valve", i: 0, p: { displayName: "V1", position: { x: 100, y: 100 } }, a: { "layout.group": "g1", "layout.node": "n1", "layout.instance": 1 } },
      { c: "ht.Valve", i: 1, p: { displayName: "V2", position: { x: 200, y: 200 } }, a: { "layout.group": "g1", "layout.node": "n2", "layout.instance": 1 } },
    ],
  };

  useRefineStore.getState().loadFromLayoutData(
    extractNodes(jsonData), 1000, 800, jsonData, "test.json",
  );

  useRefineStore.getState().applyPatch([{ op: "remove", path: "/d/1" }], "msg-1");

  const state = useRefineStore.getState();
  assert.equal(state.workingNodes.length, 1);
  assert.equal(state.workingPipes, null,
    "workingPipes stays null when no pipes were loaded");
});

test("duplicate and invalid connections preserved when no node deleted", () => {
  resetStore();

  const pipes: PipeData = {
    connections: [
      makeConnection("c1", "g1", "n1", 1, "right", "g1", "n2", 1, "left"),
      makeConnection("c1-dup", "g1", "n1", 1, "right", "g1", "n2", 1, "left"),
      makeConnection("c2", "g1", "n2", 1, "right", "g1", "nonexistent", 99, "left"),
    ],
  };

  const jsonData: LayoutJsonData = {
    v: "1", p: {}, a: { width: 1000, height: 800 },
    d: [
      { c: "ht.Valve", i: 0, p: { displayName: "V1", position: { x: 100, y: 100 } }, a: { "layout.group": "g1", "layout.node": "n1", "layout.instance": 1 } },
      { c: "ht.Valve", i: 1, p: { displayName: "V2", position: { x: 200, y: 200 } }, a: { "layout.group": "g1", "layout.node": "n2", "layout.instance": 1 } },
    ],
  };

  useRefineStore.getState().loadFromLayoutData(
    extractNodes(jsonData), 1000, 800, jsonData, "test.json", pipes,
  );

  assert.equal(useRefineStore.getState().workingPipes!.connections.length, 3,
    "all connections (including duplicates and invalid) present in initial load");

  useRefineStore.getState().applyPatch([
    { op: "replace", path: "/d/0/p/position/x", value: 999 },
  ], "msg-1");

  const state = useRefineStore.getState();
  assert.equal(state.workingPipes!.connections.length, 3,
    "no connections removed when patch does not delete any node");
});

test("setSelection and toggleSelection work", () => {
  resetStore();

  useRefineStore.getState().loadFromLayoutData(
    [makeNode("node-0", "g1", "n1", 1), makeNode("node-1", "g1", "n2", 1)],
    1000, 800, null, "test.json",
  );

  useRefineStore.getState().setSelection(["node-0"]);
  assert.deepEqual(useRefineStore.getState().selectedNodeIds, ["node-0"]);

  useRefineStore.getState().toggleSelection("node-1");
  assert.deepEqual(useRefineStore.getState().selectedNodeIds, ["node-0", "node-1"]);

  useRefineStore.getState().toggleSelection("node-0");
  assert.deepEqual(useRefineStore.getState().selectedNodeIds, ["node-1"]);

  useRefineStore.getState().clearSelection();
  assert.deepEqual(useRefineStore.getState().selectedNodeIds, []);
});

test("moveNodes moves multiple nodes", () => {
  resetStore();

  const jsonData: LayoutJsonData = {
    v: "1", p: {}, a: { width: 1000, height: 800 },
    d: [
      { c: "ht.Valve", i: 0, p: { displayName: "V1", position: { x: 100, y: 100 } }, a: { "layout.group": "g1", "layout.node": "n1", "layout.instance": 1 } },
      { c: "ht.Valve", i: 1, p: { displayName: "V2", position: { x: 200, y: 200 } }, a: { "layout.group": "g1", "layout.node": "n2", "layout.instance": 1 } },
    ],
  };

  useRefineStore.getState().loadFromLayoutData(
    extractNodes(jsonData), 1000, 800, jsonData, "test.json",
  );

  useRefineStore.getState().moveNodes(["node-0", "node-1"], 50, -30);

  const state = useRefineStore.getState();
  assert.equal(state.workingNodes[0].x, 150);
  assert.equal(state.workingNodes[0].y, 70);
  assert.equal(state.workingNodes[1].x, 250);
  assert.equal(state.workingNodes[1].y, 170);
});

test("moveNodes is locked during refine", () => {
  resetStore();

  const jsonData: LayoutJsonData = {
    v: "1", p: {}, a: { width: 1000, height: 800 },
    d: [
      { c: "ht.Valve", i: 0, p: { displayName: "V1", position: { x: 100, y: 100 } }, a: { "layout.group": "g1", "layout.node": "n1", "layout.instance": 1 } },
    ],
  };

  useRefineStore.getState().loadFromLayoutData(
    extractNodes(jsonData), 1000, 800, jsonData, "test.json",
  );

  useRefineStore.setState({ isRefining: true });
  useRefineStore.getState().moveNodes(["node-0"], 50, 0);
  assert.equal(useRefineStore.getState().workingNodes[0].x, 100,
    "moveNodes must be ignored when isRefining");
});

test("moveNodesAbsolute updates node positions idempotently", () => {
  resetStore();

  const jsonData: LayoutJsonData = {
    v: "1", p: {}, a: { width: 1000, height: 800 },
    d: [
      { c: "ht.Valve", i: 0, p: { displayName: "V1", position: { x: 100, y: 100 } }, a: { "layout.group": "g1", "layout.node": "n1", "layout.instance": 1 } },
      { c: "ht.Valve", i: 1, p: { displayName: "V2", position: { x: 200, y: 200 } }, a: { "layout.group": "g1", "layout.node": "n2", "layout.instance": 1 } },
    ],
  };

  useRefineStore.getState().loadFromLayoutData(
    extractNodes(jsonData), 1000, 800, jsonData, "test.json",
  );

  useRefineStore.getState().moveNodesAbsolute([
    { id: "node-0", x: 150, y: 70 },
    { id: "node-1", x: 300, y: 180 },
  ]);

  const state = useRefineStore.getState();
  assert.equal(state.workingNodes[0].x, 150);
  assert.equal(state.workingNodes[0].y, 70);
  assert.equal(state.workingNodes[1].x, 300);
  assert.equal(state.workingNodes[1].y, 180);

  assert.equal(state.workingJson!.d[0].p!.position.x, 150);
  assert.equal(state.workingJson!.d[0].p!.position.y, 70);
  assert.equal(state.workingJson!.d[1].p!.position.x, 300);
  assert.equal(state.workingJson!.d[1].p!.position.y, 180);
});

test("moveNodesAbsolute is idempotent", () => {
  resetStore();

  const jsonData: LayoutJsonData = {
    v: "1", p: {}, a: { width: 1000, height: 800 },
    d: [
      { c: "ht.Valve", i: 0, p: { displayName: "V1", position: { x: 100, y: 100 } } },
    ],
  };

  useRefineStore.getState().loadFromLayoutData(
    extractNodes(jsonData), 1000, 800, jsonData, "test.json",
  );

  const updates = [{ id: "node-0", x: 200, y: 200 }];
  useRefineStore.getState().moveNodesAbsolute(updates);
  useRefineStore.getState().moveNodesAbsolute(updates);
  useRefineStore.getState().moveNodesAbsolute(updates);

  assert.equal(useRefineStore.getState().workingNodes[0].x, 200,
    "repeated same update must not move further");
});

test("moveNodesAbsolute is locked during refining", () => {
  resetStore();

  useRefineStore.getState().loadFromLayoutData(
    [makeNode("node-0", "g1", "n1", 1)],
    1000, 800, null, "test.json",
  );

  useRefineStore.setState({ isRefining: true });
  useRefineStore.getState().moveNodesAbsolute([{ id: "node-0", x: 999, y: 999 }]);

  assert.equal(useRefineStore.getState().workingNodes[0].x, 100,
    "moveNodesAbsolute must be ignored when isRefining");
});

test("moveNodesAbsolute does not change pipe data", () => {
  resetStore();

  const pipes: PipeData = {
    connections: [
      makeConnection("c1", "g1", "n1", 1, "right", "g1", "n2", 1, "left"),
    ],
  };

  const nodes = [
    makeNode("node-0", "g1", "n1", 1, 100, 100),
    makeNode("node-1", "g1", "n2", 1, 200, 200),
  ];

  useRefineStore.getState().loadFromLayoutData(
    nodes, 1000, 800,
    { v: "1", p: {}, a: { width: 1000, height: 800 }, d: [] },
    "test.json", pipes,
  );

  useRefineStore.getState().moveNodesAbsolute([
    { id: "node-0", x: 150, y: 150 },
    { id: "node-1", x: 250, y: 250 },
  ]);

  const state = useRefineStore.getState();
  assert.equal(state.workingPipes!.connections.length, 1);
  assert.equal(state.workingPipes!.connections[0].id, "c1",
    "moveNodesAbsolute must not alter pipe connections");
});

test("resizeNode updates node and json", () => {
  resetStore();

  const jsonData: LayoutJsonData = {
    v: "1", p: {}, a: { width: 1000, height: 800 },
    d: [
      { c: "ht.Valve", i: 0, p: { displayName: "V1", position: { x: 100, y: 100 }, width: 60, height: 40 }, a: { "layout.group": "g1", "layout.node": "n1", "layout.instance": 1 } },
    ],
  };

  useRefineStore.getState().loadFromLayoutData(
    extractNodes(jsonData), 1000, 800, jsonData, "test.json",
  );

  useRefineStore.getState().resizeNode("node-0", 110, 90, 80, 60);
  const state = useRefineStore.getState();
  assert.equal(state.workingNodes[0].x, 110);
  assert.equal(state.workingNodes[0].y, 90);
  assert.equal(state.workingNodes[0].width, 80);
  assert.equal(state.workingNodes[0].height, 60);
});

test("applyPatch filters deleted ids from selectedNodeIds", () => {
  resetStore();

  const jsonData: LayoutJsonData = {
    v: "1", p: {}, a: { width: 1000, height: 800 },
    d: [
      { c: "ht.Valve", i: 0, p: { displayName: "V1", position: { x: 100, y: 100 } }, a: { "layout.group": "g1", "layout.node": "n1", "layout.instance": 1 } },
      { c: "ht.Valve", i: 1, p: { displayName: "V2", position: { x: 200, y: 200 } }, a: { "layout.group": "g1", "layout.node": "n2", "layout.instance": 1 } },
    ],
  };

  useRefineStore.getState().loadFromLayoutData(
    extractNodes(jsonData), 1000, 800, jsonData, "test.json",
  );

  useRefineStore.getState().setSelection(["node-0", "node-1"]);
  useRefineStore.getState().applyPatch([{ op: "remove", path: "/d/1" }], "msg-1");

  assert.deepEqual(useRefineStore.getState().selectedNodeIds, ["node-0"],
    "deleted IDs must be filtered out");
});

test("rejectPatch restores selectedNodeIds snapshot", () => {
  resetStore();

  const jsonData: LayoutJsonData = {
    v: "1", p: {}, a: { width: 1000, height: 800 },
    d: [
      { c: "ht.Valve", i: 0, p: { displayName: "V1", position: { x: 100, y: 100 } }, a: { "layout.group": "g1", "layout.node": "n1", "layout.instance": 1 } },
      { c: "ht.Valve", i: 1, p: { displayName: "V2", position: { x: 200, y: 200 } }, a: { "layout.group": "g1", "layout.node": "n2", "layout.instance": 1 } },
    ],
  };

  useRefineStore.getState().loadFromLayoutData(
    extractNodes(jsonData), 1000, 800, jsonData, "test.json",
  );

  useRefineStore.getState().setSelection(["node-0", "node-1"]);
  useRefineStore.getState().applyPatch([{ op: "remove", path: "/d/1" }], "msg-1");

  useRefineStore.getState().rejectPatch("msg-1");
  assert.deepEqual(useRefineStore.getState().selectedNodeIds, ["node-0", "node-1"],
    "reject must restore original selection snapshot");
});

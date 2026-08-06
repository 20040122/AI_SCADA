import assert from "node:assert/strict";
import test from "node:test";
import { useBindingStore } from "../src/stores/bindingStore.ts";
import { useLayoutStore } from "../src/stores/layoutStore.ts";
import { useRefineStore } from "../src/stores/refineStore.ts";
import type {
  BindingBuildResponse,
  BindingCandidate,
  BindingMatchItem,
  BindingMatchResponse,
  BindingNormalizeResponse,
  BindingProperty,
} from "../src/types/binding.ts";
import type { LayoutJsonData, PipeData, UploadCanvasResponse } from "../src/types/layout.ts";

function makeJson(): LayoutJsonData {
  return {
    v: "1",
    p: { layers: [], autoAdjustIndex: false, hierarchicalRendering: false },
    a: { width: 1920, height: 1080, fitContent: false, rectSelectable: false, pannable: false, zoomable: false },
    d: [
      {
        c: "ht.Node",
        i: 0,
        p: { displayName: "状态面板", image: "symbols/panel.json", position: { x: 0, y: 0 }, width: 200, height: 100 },
        a: { "layout.node": true, "layout.group": "g1", "layout.instance": 0 },
      },
    ],
    contentRect: { x: 0, y: 0, width: 200, height: 100 },
  };
}

function makeProperty(propertyId: string, propertyName: string): BindingProperty {
  return {
    projectId: "p1",
    projectName: "项目A",
    deviceId: "d1",
    deviceName: "空气罐",
    propertyId,
    propertyName,
    dataType: "int",
    writable: false,
    unit: "°C",
    dataTypeDesc: "整型",
  };
}

function makeCandidate(propertyId: string, propertyName: string, score: number): BindingCandidate {
  return {
    ...makeProperty(propertyId, propertyName),
    device_name_similarity: 1,
    property_name_similarity: score,
    score,
    lead: score,
    confidence: score >= 0.85 ? "high" : "low",
    evidence: ["规范化完全相等"],
    key: `p1#d1#${propertyId}`,
  };
}

function makeMatchItem(expectationId: string, candidates: BindingCandidate[]): BindingMatchItem {
  return {
    panel_node_i: 0,
    panel_displayName: "状态面板",
    panel_instance: 1,
    expectation_id: expectationId,
    expectation_property: candidates[0].propertyName,
    expectation_required: true,
    candidates,
    suggested: candidates[0].key,
    confidence: candidates[0].confidence,
    confirmed: false,
  };
}

function makeMatchResponse(): BindingMatchResponse {
  return {
    panels: [{ node_i: 0, node_id: "node-0", displayName: "状态面板", instance: 1, existing_panel_list: null }],
    expectations: [
      { id: "e1", displayName: "状态面板", deviceName: "空气罐", property: "空气罐温度", dataType: "int", writable: false, required: true, path: "", label: "" },
      { id: "e2", displayName: "状态面板", deviceName: "空气罐", property: "空气罐压力", dataType: "double", writable: false, required: true, path: "", label: "" },
    ],
    items: [
      makeMatchItem("e1", [makeCandidate("t", "空气罐温度", 0.95), makeCandidate("t2", "空气罐温度2", 0.6)]),
      makeMatchItem("e2", [makeCandidate("p", "空气罐压力", 0.7)]),
    ],
  };
}

function makeNormalizeResponse(): BindingNormalizeResponse {
  return {
    properties: [makeProperty("t", "空气罐温度"), makeProperty("p", "空气罐压力")],
    errors: [],
    blocked: false,
    blocking: [],
  };
}

function makeBuildResponse(): BindingBuildResponse {
  return {
    bound_json: makeJson(),
    previews: [],
    errors: [],
    warnings: [],
  };
}

function makeUploadResponse(): UploadCanvasResponse {
  return {
    file_name: "画面_bound.json",
    json_data: makeJson(),
    corrections: [],
    warnings: [],
  };
}

function resetStores() {
  useBindingStore.getState().reset();
  useLayoutStore.setState({
    jsonData: null,
    zones: [],
    qualityIssues: [],
    missingControls: [],
    nodes: [],
    decorations: [],
    pipe_data: null,
    fileName: "",
    corrections: [],
    uploadWarnings: [],
    revision: 0,
  });
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
    revision: 0,
  });
}

function withFetchMock(handler: (url: string, init: RequestInit) => Promise<unknown>) {
  const original = globalThis.fetch;
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    const data = await handler(url, init ?? {});
    return {
      ok: true,
      status: 200,
      json: async () => ({ data }),
    } as Response;
  }) as typeof fetch;
  return () => {
    globalThis.fetch = original;
  };
}

test("syncSource snapshots source and derives target file name", () => {
  resetStores();
  const b = useBindingStore.getState();
  b.syncSource("layout", 1, makeJson(), null, "画面.json");
  const s = useBindingStore.getState();
  assert.equal(s.sourceType, "layout");
  assert.equal(s.sourceRevision, 1);
  assert.ok(s.canvas);
  assert.equal(s.fileName, "画面.json");
  assert.equal(s.targetFileName, "画面_bound.json");
});

test("same source revision is a no-op and keeps derived state", () => {
  resetStores();
  useBindingStore.getState().syncSource("layout", 1, makeJson(), null, "画面.json");
  useBindingStore.setState({ boundJson: makeJson() });
  useBindingStore.getState().syncSource("layout", 1, makeJson(), null, "画面.json");
  assert.ok(useBindingStore.getState().boundJson);
});

test("revision change clears match items and bound JSON", () => {
  resetStores();
  const b = useBindingStore.getState();
  b.syncSource("layout", 1, makeJson(), null, "画面.json");
  useBindingStore.setState({ items: [makeMatchItem("e1", [makeCandidate("t", "空气罐温度", 0.95)])], boundJson: makeJson() });
  b.syncSource("layout", 2, makeJson(), null, "画面.json");
  const s = useBindingStore.getState();
  assert.equal(s.sourceRevision, 2);
  assert.equal(s.items.length, 0);
  assert.equal(s.boundJson, null);
  assert.equal(s.targetFileName, "画面_bound.json");
});

test("column mapping confirms and clears downstream on change", () => {
  resetStores();
  const b = useBindingStore.getState();
  b.syncSource("layout", 1, makeJson(), null, "画面.json");
  b.setColumnMapping([{ field: "projectId", column: 0 }]);
  assert.equal(useBindingStore.getState().columnMapping.length, 1);

  b.applyNormalize(makeNormalizeResponse());
  assert.equal(useBindingStore.getState().normalized.length, 2);

  b.setColumnMapping([{ field: "projectId", column: 1 }]);
  const s = useBindingStore.getState();
  assert.equal(s.normalized.length, 0);
  assert.equal(s.columnMapping[0].column, 1);
});

test("blocked normalize keeps blocking reason", () => {
  resetStores();
  const b = useBindingStore.getState();
  b.syncSource("layout", 1, makeJson(), null, "画面.json");
  b.applyNormalize({
    properties: [],
    errors: [],
    blocked: true,
    blocking: ["缺少必填列映射"],
  });
  const s = useBindingStore.getState();
  assert.equal(s.normalizeBlocked, true);
  assert.deepEqual(s.normalizeBlocking, ["缺少必填列映射"]);
});

test("runMatch guards when no canvas or no normalized properties", async () => {
  resetStores();
  await useBindingStore.getState().runMatch();
  assert.equal(useBindingStore.getState().items.length, 0);

  const b = useBindingStore.getState();
  b.syncSource("layout", 1, makeJson(), null, "画面.json");
  await useBindingStore.getState().runMatch();
  assert.equal(useBindingStore.getState().items.length, 0);
});

test("runMatch stores candidates and pre-selects suggestions", async () => {
  resetStores();
  const restore = withFetchMock(async (url) => {
    assert.match(url, /\/api\/binding\/match$/);
    return makeMatchResponse();
  });
  try {
    const b = useBindingStore.getState();
    b.syncSource("layout", 1, makeJson(), null, "画面.json");
    b.applyNormalize(makeNormalizeResponse());
    await useBindingStore.getState().runMatch();
    const s = useBindingStore.getState();
    assert.equal(s.items.length, 2);
    assert.equal(s.items[0].selectedKey, "p1#d1#t");
    assert.equal(s.items[1].selectedKey, "p1#d1#p");
    assert.equal(s.items[0].confirmed, false);
    assert.equal(s.items[0].confidence, "high");
    assert.equal(s.items[1].confidence, "low");
  } finally {
    restore();
  }
});

test("selectCandidate replaces candidate and unconfirms item", () => {
  resetStores();
  const b = useBindingStore.getState();
  b.syncSource("layout", 1, makeJson(), null, "画面.json");
  useBindingStore.setState({ items: [makeMatchItem("e1", [makeCandidate("t", "空气罐温度", 0.95), makeCandidate("t2", "空气罐温度2", 0.6)])] });
  useBindingStore.getState().confirmItem(0, "e1");
  assert.equal(useBindingStore.getState().items[0].confirmed, true);

  useBindingStore.getState().selectCandidate(0, "e1", "p1#d1#t2");
  const s = useBindingStore.getState();
  assert.equal(s.items[0].selectedKey, "p1#d1#t2");
  assert.equal(s.items[0].confirmed, false);
});

test("confirmItem confirms the selected candidate", () => {
  resetStores();
  const b = useBindingStore.getState();
  b.syncSource("layout", 1, makeJson(), null, "画面.json");
  useBindingStore.setState({ items: [makeMatchItem("e1", [makeCandidate("t", "空气罐温度", 0.95)])] });
  useBindingStore.getState().confirmItem(0, "e1");
  assert.equal(useBindingStore.getState().items[0].confirmed, true);
});

test("confirmAllHigh only confirms high confidence items", () => {
  resetStores();
  const b = useBindingStore.getState();
  b.syncSource("layout", 1, makeJson(), null, "画面.json");
  useBindingStore.setState({
    items: [
      makeMatchItem("e1", [makeCandidate("t", "空气罐温度", 0.95)]),
      makeMatchItem("e2", [makeCandidate("p", "空气罐压力", 0.7)]),
    ],
  });
  useBindingStore.getState().confirmAllHigh();
  const items = useBindingStore.getState().items;
  assert.equal(items[0].confirmed, true);
  assert.equal(items[1].confirmed, false);
});

test("runBuild sends only confirmed assignments and stores result", async () => {
  resetStores();
  let body: string | null = null;
  const restore = withFetchMock(async (url, init) => {
    assert.match(url, /\/api\/binding\/build$/);
    body = String(init.body);
    return makeBuildResponse();
  });
  try {
    const b = useBindingStore.getState();
    b.syncSource("layout", 1, makeJson(), null, "画面.json");
    useBindingStore.setState({
      items: [
        makeMatchItem("e1", [makeCandidate("t", "空气罐温度", 0.95)]),
        makeMatchItem("e2", [makeCandidate("p", "空气罐压力", 0.7)]),
      ],
    });
    useBindingStore.getState().confirmItem(0, "e1");
    await useBindingStore.getState().runBuild();
    const s = useBindingStore.getState();
    assert.ok(body);
    const parsed = JSON.parse(body!) as { assignments: unknown[] };
    assert.equal(parsed.assignments.length, 1);
    assert.ok(s.boundJson);
    assert.deepEqual(s.buildErrors, []);
    assert.equal(s.uploadResult, null);
  } finally {
    restore();
  }
});

test("upload failure keeps bound JSON for in-place retry", () => {
  resetStores();
  const b = useBindingStore.getState();
  b.syncSource("layout", 1, makeJson(), null, "画面.json");
  useBindingStore.setState({ boundJson: makeJson() });
  useBindingStore.getState().setUploadError("上传超时");
  const s = useBindingStore.getState();
  assert.ok(s.boundJson);
  assert.equal(s.uploadError, "上传超时");

  useBindingStore.getState().setUploadResult(makeUploadResponse());
  const after = useBindingStore.getState();
  assert.equal(after.uploadError, null);
  assert.equal(after.uploadResult?.file_name, "画面_bound.json");
});

test("upload only updates the binding store, not layout/refine", () => {
  resetStores();
  useLayoutStore.getState().setLayoutResult({
    json_data: makeJson(),
    content_rect: { x: 0, y: 0, width: 200, height: 100 },
    quality_issues: [],
    zones: [],
    missing_controls: [],
    file_name: "画面.json",
    pipe_data: null,
  });
  useRefineStore.getState().loadFromLayoutData([], 1920, 1080, makeJson(), "画面.json");

  const layoutRevBefore = useLayoutStore.getState().revision;
  const refineRevBefore = useRefineStore.getState().revision;

  useBindingStore.getState().setUploadResult(makeUploadResponse());

  assert.equal(useLayoutStore.getState().revision, layoutRevBefore);
  assert.equal(useRefineStore.getState().revision, refineRevBefore);
  assert.ok(useLayoutStore.getState().jsonData);
  assert.equal(useLayoutStore.getState().fileName, "画面.json");
  assert.equal(useBindingStore.getState().uploadResult?.file_name, "画面_bound.json");
});

test("pipe snapshot is deep-copied on sync", () => {
  resetStores();
  const pipes: PipeData = { connections: [{ id: "c1", source: { group: "g", node: "n", instance: 0, port: "out" }, target: { group: "g", node: "m", instance: 0, port: "in" } }] };
  useBindingStore.getState().syncSource("layout", 1, makeJson(), pipes, "画面.json");
  const s = useBindingStore.getState();
  assert.deepEqual(s.pipes, pipes);
  s.pipes!.connections[0].id = "mutated";
  assert.equal(useBindingStore.getState().pipes?.connections[0].id, "mutated");
});

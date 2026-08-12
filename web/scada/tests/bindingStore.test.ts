import assert from "node:assert/strict";
import test from "node:test";
import { useBindingStore } from "../src/stores/bindingStore.ts";
import { useLayoutStore } from "../src/stores/layoutStore.ts";
import { useRefineStore } from "../src/stores/refineStore.ts";
import type {
  BindingBuildResponse,
  BindingCandidate,
  BindingMatchResponse,
  BindingPreviewResponse,
  BindingRequestRow,
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

function makeRequests(): BindingRequestRow[] {
  return [
    { row_number: 2, displayName: "状态面板", propertyName: "空气罐温度" },
    { row_number: 3, displayName: "状态面板", propertyName: "空气罐压力" },
  ];
}

function makePreview(): BindingPreviewResponse {
  return { encoding: "utf-8", total_rows: 2, requests: makeRequests() };
}

function makeCandidate(bindingId: string, propertyName: string, score: number): BindingCandidate {
  return {
    binding_id: bindingId,
    propertyName,
    projectName: "Agent",
    deviceName: "空气罐",
    dataType: "int",
    writable: false,
    unit: "°C",
    score,
    evidence: ["属性名精确匹配"],
  };
}

function makeMatchItem(rowNumber: number, candidates: BindingCandidate[]): BindingMatchResponse["items"][number] {
  return {
    row_number: rowNumber,
    target_node_i: 0,
    requested_displayName: "状态面板",
    requested_propertyName: candidates[0].propertyName,
    candidates,
    suggested_binding_id: candidates.length === 1 ? candidates[0].binding_id : null,
    lead: candidates.length === 1 ? candidates[0].score : 0,
    confidence: candidates.length === 1 ? "high" : "none",
  };
}

function makeMatchResponse(items?: BindingMatchResponse["items"]): BindingMatchResponse {
  return {
    targets: [{ node_i: 0, node_id: 0, displayName: "状态面板", handler: "panel_list", existing: null }],
    items: items ?? [
      makeMatchItem(2, [makeCandidate("air_tank_temperature", "空气罐温度", 1)]),
      makeMatchItem(3, [makeCandidate("air_tank_pressure", "空气罐压力", 0.9)]),
    ],
    blocked: false,
    errors: [],
  };
}

function makeBuildResponse(): BindingBuildResponse {
  return {
    bound_json: makeJson(),
    previews: [],
    errors: [],
    warnings: [],
    applied_count: 2,
    skipped_count: 0,
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

test("revision change clears candidates, confirm and build results", () => {
  resetStores();
  const b = useBindingStore.getState();
  b.syncSource("layout", 1, makeJson(), null, "画面.json");
  useBindingStore.setState({ items: [makeMatchItem(2, [makeCandidate("t", "空气罐温度", 1)])], boundJson: makeJson() });
  b.syncSource("layout", 2, makeJson(), null, "画面.json");
  const s = useBindingStore.getState();
  assert.equal(s.sourceRevision, 2);
  assert.equal(s.items.length, 0);
  assert.equal(s.boundJson, null);
  assert.equal(s.targetFileName, "画面_bound.json");
});

test("csv file change clears preview, requests and match", () => {
  resetStores();
  const b = useBindingStore.getState();
  b.syncSource("layout", 1, makeJson(), null, "画面.json");
  b.setPreview(makePreview());
  b.setCsvFile(new File(["x"], "a.csv"));
  assert.ok(useBindingStore.getState().csvFile);
  assert.equal(useBindingStore.getState().preview, null);
  assert.deepEqual(useBindingStore.getState().requests, []);
});

test("setPreview stores backend requests and clears build results", () => {
  resetStores();
  const b = useBindingStore.getState();
  b.syncSource("layout", 1, makeJson(), null, "画面.json");
  b.setPreview(makePreview());
  const s = useBindingStore.getState();
  assert.equal(s.preview?.total_rows, 2);
  assert.deepEqual(s.requests, makeRequests());
});

test("runMatch guards when no canvas or no requests", async () => {
  resetStores();
  await useBindingStore.getState().runMatch();
  assert.equal(useBindingStore.getState().items.length, 0);

  const b = useBindingStore.getState();
  b.syncSource("layout", 1, makeJson(), null, "画面.json");
  await useBindingStore.getState().runMatch();
  assert.equal(useBindingStore.getState().items.length, 0);
});

test("runMatch sends requests and pre-selects suggestion without confirming", async () => {
  resetStores();
  let body: string | null = null;
  const restore = withFetchMock(async (url, init) => {
    assert.match(url, /\/api\/binding\/match$/);
    body = String(init.body);
    return makeMatchResponse();
  });
  try {
    const b = useBindingStore.getState();
    b.syncSource("layout", 1, makeJson(), null, "画面.json");
    b.setPreview(makePreview());
    await useBindingStore.getState().runMatch();
    const s = useBindingStore.getState();
    assert.equal(s.items.length, 2);
    assert.equal(s.items[0].selectedBindingId, "air_tank_temperature");
    assert.equal(s.items[1].selectedBindingId, "air_tank_pressure");
    assert.equal(s.items[0].confirmed, false);
    assert.equal(s.items[0].confidence, "high");
    assert.ok(body);
    const parsed = JSON.parse(body!) as { requests: BindingRequestRow[] };
    assert.deepEqual(parsed.requests, makeRequests());
  } finally {
    restore();
  }
});

test("multi-exact match has no preselect", async () => {
  resetStores();
  const restore = withFetchMock(async () => {
    return makeMatchResponse([
      makeMatchItem(2, [
        makeCandidate("air_tank_temperature", "空气罐温度", 1),
        makeCandidate("air_tank_temperature_2", "空气罐温度", 1),
      ]),
    ]);
  });
  try {
    const b = useBindingStore.getState();
    b.syncSource("layout", 1, makeJson(), null, "画面.json");
    b.setPreview(makePreview());
    await useBindingStore.getState().runMatch();
    const s = useBindingStore.getState();
    assert.equal(s.items[0].suggested_binding_id, null);
    assert.equal(s.items[0].selectedBindingId, null);
    assert.equal(s.items[0].confirmed, false);
  } finally {
    restore();
  }
});

test("runMatch stores blocked errors from backend", async () => {
  resetStores();
  const restore = withFetchMock(async () => {
    return { ...makeMatchResponse([]), blocked: true, errors: ["第 2 行: 未找到匹配属性 空气罐温度"] };
  });
  try {
    const b = useBindingStore.getState();
    b.syncSource("layout", 1, makeJson(), null, "画面.json");
    b.setPreview(makePreview());
    await useBindingStore.getState().runMatch();
    const s = useBindingStore.getState();
    assert.equal(s.match?.blocked, true);
    assert.ok(s.match?.errors.length === 1);
  } finally {
    restore();
  }
});

test("selectCandidate replaces candidate and revokes confirm and build", () => {
  resetStores();
  const b = useBindingStore.getState();
  b.syncSource("layout", 1, makeJson(), null, "画面.json");
  useBindingStore.setState({
    items: [
      { ...makeMatchItem(2, [makeCandidate("t", "空气罐温度", 1), makeCandidate("t2", "空气罐温度", 0.9)]), selectedBindingId: "t", confirmed: false },
    ],
  });
  useBindingStore.getState().confirmItem(2);
  useBindingStore.setState({ boundJson: makeJson() });
  assert.equal(useBindingStore.getState().items[0].confirmed, true);

  useBindingStore.getState().selectCandidate(2, "t2");
  const s = useBindingStore.getState();
  assert.equal(s.items[0].selectedBindingId, "t2");
  assert.equal(s.items[0].confirmed, false);
  assert.equal(s.boundJson, null);
});

test("confirmItem confirms the selected candidate only", () => {
  resetStores();
  const b = useBindingStore.getState();
  b.syncSource("layout", 1, makeJson(), null, "画面.json");
  useBindingStore.setState({
    items: [
      { ...makeMatchItem(2, [makeCandidate("t", "空气罐温度", 1)]), selectedBindingId: "t", confirmed: false },
      { ...makeMatchItem(3, [makeCandidate("p", "空气罐压力", 1)]), selectedBindingId: "p", confirmed: false },
    ],
  });
  useBindingStore.getState().confirmItem(2);
  const items = useBindingStore.getState().items;
  assert.equal(items[0].confirmed, true);
  assert.equal(items[1].confirmed, false);
});

test("runBuild sends only row_number and binding_id for confirmed rows", async () => {
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
    b.setPreview(makePreview());
    useBindingStore.setState({
      items: [
        { ...makeMatchItem(2, [makeCandidate("t", "空气罐温度", 1)]), selectedBindingId: "t", confirmed: false },
        { ...makeMatchItem(3, [makeCandidate("p", "空气罐压力", 1)]), selectedBindingId: "p", confirmed: false },
      ],
    });
    useBindingStore.getState().confirmItem(2);
    await useBindingStore.getState().runBuild();
    const s = useBindingStore.getState();
    assert.ok(body);
    const parsed = JSON.parse(body!) as { requests: BindingRequestRow[]; assignments: { row_number: number; binding_id: string }[] };
    assert.deepEqual(parsed.requests, makeRequests());
    assert.deepEqual(parsed.assignments, [{ row_number: 2, binding_id: "t" }]);
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

test("runBuild stores structured counts and changes clear them", async () => {
  resetStores();
  const restore = withFetchMock(async () => {
    return { ...makeBuildResponse(), applied_count: 1, skipped_count: 1 };
  });
  try {
    const b = useBindingStore.getState();
    b.syncSource("layout", 1, makeJson(), null, "画面.json");
    b.setPreview(makePreview());
    useBindingStore.setState({
      items: [
        { ...makeMatchItem(2, [makeCandidate("t", "空气罐温度", 1)]), selectedBindingId: "t", confirmed: false },
        { ...makeMatchItem(3, [makeCandidate("p", "空气罐压力", 1)]), selectedBindingId: "p", confirmed: false },
      ],
    });
    useBindingStore.getState().confirmItem(2);
    await useBindingStore.getState().runBuild();
    let s = useBindingStore.getState();
    assert.equal(s.appliedCount, 1);
    assert.equal(s.skippedCount, 1);
    assert.ok(s.boundJson);

    useBindingStore.getState().confirmItem(3);
    s = useBindingStore.getState();
    assert.equal(s.appliedCount, 0);
    assert.equal(s.skippedCount, 0);
    assert.equal(s.boundJson, null);
  } finally {
    restore();
  }
});

test("csv change clears structured counts", () => {
  resetStores();
  const b = useBindingStore.getState();
  b.syncSource("layout", 1, makeJson(), null, "画面.json");
  useBindingStore.setState({ appliedCount: 3, skippedCount: 5 });
  useBindingStore.getState().setCsvFile(new File(["x"], "a.csv"));
  const s = useBindingStore.getState();
  assert.equal(s.appliedCount, 0);
  assert.equal(s.skippedCount, 0);
});

test("suggested but unconfirmed rows never enter assignments", async () => {
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
    b.setPreview(makePreview());
    useBindingStore.setState({
      items: [
        { ...makeMatchItem(2, [makeCandidate("t", "空气罐温度", 1)]), selectedBindingId: "t", confirmed: true },
        { ...makeMatchItem(3, [makeCandidate("p", "空气罐压力", 1)]), selectedBindingId: "p", confirmed: false },
      ],
    });
    await useBindingStore.getState().runBuild();
    assert.ok(body);
    const parsed = JSON.parse(body!) as { assignments: { row_number: number; binding_id: string }[] };
    assert.deepEqual(parsed.assignments, [{ row_number: 2, binding_id: "t" }]);
  } finally {
    restore();
  }
});

test("confirmAllSelected confirms preselected and manual rows including low confidence and duplicate ids", () => {
  resetStores();
  const b = useBindingStore.getState();
  b.syncSource("layout", 1, makeJson(), null, "画面.json");
  useBindingStore.setState({
    items: [
      { ...makeMatchItem(2, [makeCandidate("t", "空气罐温度", 1)]), selectedBindingId: "t", confirmed: false },
      {
        ...makeMatchItem(3, [makeCandidate("p1", "空气罐压力", 0.9), makeCandidate("p2", "空气罐压力", 0.8)]),
        confidence: "low",
        selectedBindingId: "p2",
        confirmed: false,
      },
      { ...makeMatchItem(4, [makeCandidate("dup", "液位", 1)]), selectedBindingId: "dup", confirmed: false },
      { ...makeMatchItem(5, [makeCandidate("dup", "液位2", 0.9)]), selectedBindingId: "dup", confirmed: false },
    ],
  });
  const res = useBindingStore.getState().confirmAllSelected();
  assert.deepEqual(res, { newlyConfirmedCount: 4, unselectedCount: 0 });
  const s = useBindingStore.getState();
  assert.ok(s.items.every((it) => it.confirmed));
  assert.equal(s.items[1].selectedBindingId, "p2");
  assert.equal(s.items[1].confidence, "low");
  assert.equal(s.items[3].selectedBindingId, "dup");
});

test("confirmAllSelected skips confirmed rows and keeps unselected rows unconfirmed", () => {
  resetStores();
  const b = useBindingStore.getState();
  b.syncSource("layout", 1, makeJson(), null, "画面.json");
  useBindingStore.setState({
    items: [
      { ...makeMatchItem(2, [makeCandidate("t", "空气罐温度", 1)]), selectedBindingId: "t", confirmed: true },
      { ...makeMatchItem(3, [makeCandidate("p", "空气罐压力", 1)]), selectedBindingId: "p", confirmed: false },
      { ...makeMatchItem(4, [makeCandidate("x", "液位", 1)]), selectedBindingId: null, confirmed: false },
      { ...makeMatchItem(5, [makeCandidate("y", "流量", 1)]), selectedBindingId: "stale", confirmed: false },
    ],
  });
  const res = useBindingStore.getState().confirmAllSelected();
  assert.deepEqual(res, { newlyConfirmedCount: 1, unselectedCount: 2 });
  const s = useBindingStore.getState();
  assert.equal(s.items[0].confirmed, true);
  assert.equal(s.items[1].confirmed, true);
  assert.equal(s.items[2].confirmed, false);
  assert.equal(s.items[3].confirmed, false);
});

test("confirmAllSelected clears build and upload state on actual changes", () => {
  resetStores();
  const b = useBindingStore.getState();
  b.syncSource("layout", 1, makeJson(), null, "画面.json");
  useBindingStore.setState({
    items: [
      { ...makeMatchItem(2, [makeCandidate("t", "空气罐温度", 1)]), selectedBindingId: "t", confirmed: false },
      { ...makeMatchItem(3, [makeCandidate("p", "空气罐压力", 1)]), selectedBindingId: null, confirmed: false },
    ],
    boundJson: makeJson(),
    buildPreviews: [],
    buildErrors: ["旧错误"],
    buildWarnings: ["旧警告"],
    appliedCount: 3,
    skippedCount: 5,
    uploadResult: makeUploadResponse(),
    uploadError: "旧上传错误",
  });
  const res = useBindingStore.getState().confirmAllSelected();
  assert.deepEqual(res, { newlyConfirmedCount: 1, unselectedCount: 1 });
  const s = useBindingStore.getState();
  assert.equal(s.boundJson, null);
  assert.deepEqual(s.buildErrors, []);
  assert.deepEqual(s.buildWarnings, []);
  assert.equal(s.appliedCount, 0);
  assert.equal(s.skippedCount, 0);
  assert.equal(s.uploadResult, null);
  assert.equal(s.uploadError, null);
});

test("confirmAllSelected keeps state unchanged when nothing new to confirm", () => {
  resetStores();
  const b = useBindingStore.getState();
  b.syncSource("layout", 1, makeJson(), null, "画面.json");
  useBindingStore.setState({
    items: [
      { ...makeMatchItem(2, [makeCandidate("t", "空气罐温度", 1)]), selectedBindingId: "t", confirmed: true },
      { ...makeMatchItem(3, [makeCandidate("p", "空气罐压力", 1)]), selectedBindingId: null, confirmed: false },
    ],
    boundJson: makeJson(),
  });
  const itemsBefore = useBindingStore.getState().items;
  const res = useBindingStore.getState().confirmAllSelected();
  assert.deepEqual(res, { newlyConfirmedCount: 0, unselectedCount: 1 });
  const s = useBindingStore.getState();
  assert.equal(s.items, itemsBefore);
  assert.ok(s.boundJson);
});

test("confirmAllSelected is a no-op when every row is already confirmed", () => {
  resetStores();
  const b = useBindingStore.getState();
  b.syncSource("layout", 1, makeJson(), null, "画面.json");
  useBindingStore.setState({
    items: [
      { ...makeMatchItem(2, [makeCandidate("t", "空气罐温度", 1)]), selectedBindingId: "t", confirmed: true },
    ],
    boundJson: makeJson(),
  });
  const res = useBindingStore.getState().confirmAllSelected();
  assert.deepEqual(res, { newlyConfirmedCount: 0, unselectedCount: 0 });
  assert.ok(useBindingStore.getState().boundJson);
});

test("runBuild after confirmAllSelected sends only confirmed rows", async () => {
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
    b.setPreview(makePreview());
    useBindingStore.setState({
      items: [
        { ...makeMatchItem(2, [makeCandidate("t", "空气罐温度", 1)]), selectedBindingId: "t", confirmed: false },
        { ...makeMatchItem(3, [makeCandidate("p", "空气罐压力", 1)]), selectedBindingId: "p", confirmed: false },
        { ...makeMatchItem(4, [makeCandidate("x", "液位", 1)]), selectedBindingId: null, confirmed: false },
      ],
    });
    useBindingStore.getState().confirmAllSelected();
    await useBindingStore.getState().runBuild();
    assert.ok(body);
    const parsed = JSON.parse(body!) as { assignments: { row_number: number; binding_id: string }[] };
    assert.deepEqual(parsed.assignments, [
      { row_number: 2, binding_id: "t" },
      { row_number: 3, binding_id: "p" },
    ]);
  } finally {
    restore();
  }
});

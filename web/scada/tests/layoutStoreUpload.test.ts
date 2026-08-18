import assert from "node:assert/strict";
import test from "node:test";
import { useLayoutStore } from "../src/stores/layoutStore.ts";
import type { LayoutGenerateResponse, LayoutJsonData, UploadCanvasResponse } from "../src/types/layout.ts";

function resetStore() {
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
  });
}

function makeJson(controlW: number, controlH: number): LayoutJsonData {
  return {
    v: "1",
    p: { layers: [], autoAdjustIndex: false, hierarchicalRendering: false },
    a: { width: 1920, height: 1080, fitContent: false, rectSelectable: false, pannable: false, zoomable: false },
    d: [
      {
        c: "ht.Node",
        i: 17092,
        p: { displayName: "液压泵", image: "symbols/pump.json", position: { x: 300, y: 300 }, width: controlW, height: controlH },
        a: { "layout.node": true, "layout.group": "g1", "layout.instance": 0, "layout.sourceWidth": 154, "layout.sourceHeight": 70 },
      },
    ],
    contentRect: { x: 100, y: 100, width: 400, height: 200 },
  };
}

function makeLayoutResult(): LayoutGenerateResponse {
  return {
    json_data: makeJson(300, 150),
    content_rect: { x: 100, y: 100, width: 400, height: 200 },
    quality_issues: [],
    zones: [],
    missing_controls: [],
    file_name: "画面.json",
    pipe_data: null,
  };
}

function makeUploadResponse(): UploadCanvasResponse {
  return {
    file_name: "画面.json",
    json_data: makeJson(300, 136.36),
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

test("applyUploadResult writes normalized JSON back and re-extracts nodes", () => {
  resetStore();
  useLayoutStore.getState().setLayoutResult(makeLayoutResult());
  assert.equal(useLayoutStore.getState().nodes[0].height, 150);

  useLayoutStore.getState().applyUploadResult(makeUploadResponse());

  const state = useLayoutStore.getState();
  assert.equal(state.jsonData?.d[0].p.height, 136.36);
  assert.equal(state.nodes[0].height, 136.36);
  assert.equal(state.nodes[0].width, 300);
  assert.equal(state.nodes[0].id, "node-17092");
  assert.equal(state.fileName, "画面.json");
});

test("applyUploadResult stores corrections and warnings", () => {
  resetStore();
  useLayoutStore.getState().setLayoutResult(makeLayoutResult());
  useLayoutStore.getState().applyUploadResult(makeUploadResponse());

  const state = useLayoutStore.getState();
  assert.equal(state.corrections.length, 1);
  assert.equal(state.corrections[0].node_i, 17092);
  assert.equal(state.corrections[0].display_name, "液压泵");
  assert.deepEqual(state.corrections[0].before, { width: 300, height: 150 });
  assert.deepEqual(state.corrections[0].after, { width: 300, height: 136.36 });
  assert.deepEqual(state.uploadWarnings, []);
});

test("new layout result clears previous corrections", () => {
  resetStore();
  useLayoutStore.getState().setLayoutResult(makeLayoutResult());
  useLayoutStore.getState().applyUploadResult(makeUploadResponse());
  assert.equal(useLayoutStore.getState().corrections.length, 1);

  useLayoutStore.getState().setLayoutResult(makeLayoutResult());
  assert.equal(useLayoutStore.getState().corrections.length, 0);
  assert.equal(useLayoutStore.getState().uploadWarnings.length, 0);
});

test("clearCanvas resets corrections and warnings", () => {
  resetStore();
  useLayoutStore.getState().setLayoutResult(makeLayoutResult());
  useLayoutStore.getState().applyUploadResult(makeUploadResponse());
  useLayoutStore.getState().clearCanvas();

  const state = useLayoutStore.getState();
  assert.equal(state.jsonData, null);
  assert.equal(state.corrections.length, 0);
  assert.equal(state.uploadWarnings.length, 0);
  assert.equal(state.nodes.length, 0);
});

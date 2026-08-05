import assert from "node:assert/strict";
import test from "node:test";
import { buildUploadBody } from "../src/api/uploadBody.ts";
import type { LayoutJsonData, PipeData } from "../src/types/layout.ts";

function makeJson(): LayoutJsonData {
  return {
    v: "1",
    p: { layers: [], autoAdjustIndex: false, hierarchicalRendering: false },
    a: { width: 1920, height: 1080, fitContent: false, rectSelectable: false, pannable: false, zoomable: false },
    d: [],
    contentRect: { x: 0, y: 0, width: 0, height: 0 },
  };
}

function makePipeData(): PipeData {
  return {
    connections: [
      {
        id: "pipe-1",
        source: { group: "g1", node: "泵1", instance: 0, port: "out" },
        target: { group: "g1", node: "泵2", instance: 0, port: "in" },
      },
    ],
  };
}

test("buildUploadBody carries pipe_data when provided", () => {
  const json = makeJson();
  const pipes = makePipeData();
  const body = buildUploadBody("画面.json", json, pipes);
  assert.equal(body.file_name, "画面.json");
  assert.equal(body.json_data, json);
  assert.deepEqual(body.pipe_data, pipes);
});

test("buildUploadBody sends explicit empty connections when no pipes", () => {
  const json = makeJson();
  const body = buildUploadBody("画面.json", json, null);
  assert.deepEqual(body.pipe_data, { connections: [] });
});

test("buildUploadBody defaults to explicit empty connections when pipe_data omitted", () => {
  const json = makeJson();
  const body = buildUploadBody("画面.json", json);
  assert.deepEqual(body.pipe_data, { connections: [] });
});

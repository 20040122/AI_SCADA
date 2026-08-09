import assert from "node:assert/strict";
import test from "node:test";
import { post } from "../src/api/client.ts";
import { generateLayout } from "../src/api/layout.ts";

function captureFetch() {
  const original = globalThis.fetch;
  const calls: { url: string; init?: RequestInit }[] = [];
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    return {
      ok: true,
      status: 200,
      json: async () => ({ data: { ok: true } }),
    } as Response;
  }) as typeof fetch;
  return {
    calls,
    restore: () => {
      globalThis.fetch = original;
    },
  };
}

function captureTimeouts() {
  const original = globalThis.setTimeout;
  const delays: number[] = [];
  globalThis.setTimeout = ((handler: TimerHandler, delay?: number) => {
    delays.push(delay ?? 0);
    return 1 as unknown as ReturnType<typeof setTimeout>;
  }) as typeof setTimeout;
  return {
    delays,
    restore: () => {
      globalThis.setTimeout = original;
    },
  };
}

test("generateLayout registers a 120000ms timeout", async () => {
  const fetchMock = captureFetch();
  const timeoutMock = captureTimeouts();
  try {
    await generateLayout({
      query: "2台泵",
      title: "泵站",
      canvasWidth: 1920,
      canvasHeight: 1080,
    });
    assert.equal(timeoutMock.delays[0], 120000);
    assert.equal(fetchMock.calls.length, 1);
    assert.equal(fetchMock.calls[0].url, "/api/canvas/layout");
    const headers = new Headers(fetchMock.calls[0].init?.headers);
    assert.equal(headers.get("Content-Type"), "application/json");
  } finally {
    fetchMock.restore();
    timeoutMock.restore();
  }
});

test("post without options keeps the default 60000ms timeout", async () => {
  const fetchMock = captureFetch();
  const timeoutMock = captureTimeouts();
  try {
    await post("/api/binding/match", { json_data: {}, properties: [] });
    assert.equal(timeoutMock.delays[0], 60000);
    assert.equal(fetchMock.calls.length, 1);
    const headers = new Headers(fetchMock.calls[0].init?.headers);
    assert.equal(headers.get("Content-Type"), "application/json");
  } finally {
    fetchMock.restore();
    timeoutMock.restore();
  }
});

test("post accepts an explicit timeoutMs option", async () => {
  const fetchMock = captureFetch();
  const timeoutMock = captureTimeouts();
  try {
    await post("/api/canvas/refine", { instruction: "x" }, { timeoutMs: 90000 });
    assert.equal(timeoutMock.delays[0], 90000);
    assert.equal(fetchMock.calls.length, 1);
  } finally {
    fetchMock.restore();
    timeoutMock.restore();
  }
});

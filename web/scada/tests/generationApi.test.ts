import assert from "node:assert/strict";
import test from "node:test";
import {
  createGeneration,
  getGeneration,
  regenerateGeneration,
  confirmGeneration,
  discardGeneration,
} from "../src/api/generation.ts";
import { apiUrl } from "../src/api/client.ts";
import { apiErrorStatus } from "../src/utils/apiError.ts";

function mockFetch(handler: (url: string, init?: RequestInit) => Partial<Response>) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const original = globalThis.fetch;
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return {
      ok: true,
      status: 200,
      json: async () => ({ data: handler(url, init) }),
    } as Response;
  }) as typeof fetch;
  return {
    calls,
    restore: () => {
      globalThis.fetch = original;
    },
  };
}

test("createGeneration posts query and name", async () => {
  const m = mockFetch(() => ({ generation_id: "g1", status: "queued" }));
  try {
    const res = await createGeneration("离心泵", "离心泵");
    assert.equal(res.generation_id, "g1");
    assert.equal(m.calls.length, 1);
    assert.equal(m.calls[0].url, "/api/control/generations");
    assert.equal(m.calls[0].init?.method, "POST");
    assert.deepEqual(JSON.parse(String(m.calls[0].init?.body)), {
      query: "离心泵",
      name: "离心泵",
    });
  } finally {
    m.restore();
  }
});

test("getGeneration uses GET with id in path", async () => {
  const m = mockFetch(() => ({
    generation_id: "g1",
    name: "离心泵",
    status: "ready",
    seed: 42,
    created_at: "2026-01-01T00:00:00+00:00",
    expires_at: null,
    preview_url: "/api/control/generations/g1/preview",
    error: null,
    error_code: null,
  }));
  try {
    const res = await getGeneration("g1");
    assert.equal(res.status, "ready");
    assert.equal(m.calls[0].url, "/api/control/generations/g1");
    assert.equal(m.calls[0].init?.method ?? "GET", "GET");
    assert.equal(res.preview_url, "/api/control/generations/g1/preview");
  } finally {
    m.restore();
  }
});

test("regenerateGeneration posts to regenerate path", async () => {
  const m = mockFetch(() => ({ generation_id: "g1", status: "queued" }));
  try {
    const res = await regenerateGeneration("g1");
    assert.equal(res.status, "queued");
    assert.equal(m.calls[0].url, "/api/control/generations/g1/regenerate");
    assert.equal(m.calls[0].init?.method, "POST");
  } finally {
    m.restore();
  }
});

test("confirmGeneration posts to confirm path and returns material item", async () => {
  const m = mockFetch(() => ({
    displayName: "离心泵",
    image: "assets/Agent/离心泵.png",
    width: 128,
    height: 128,
    source: "ai-generated",
    similarity: 1.0,
  }));
  try {
    const item = await confirmGeneration("g1");
    assert.equal(item.displayName, "离心泵");
    assert.equal(item.image, "assets/Agent/离心泵.png");
    assert.equal(m.calls[0].url, "/api/control/generations/g1/confirm");
    assert.equal(m.calls[0].init?.method, "POST");
  } finally {
    m.restore();
  }
});

test("discardGeneration uses DELETE", async () => {
  const m = mockFetch(() => null);
  try {
    await discardGeneration("g1");
    assert.equal(m.calls[0].url, "/api/control/generations/g1");
    assert.equal(m.calls[0].init?.method, "DELETE");
  } finally {
    m.restore();
  }
});

test("apiUrl joins base with preview path", () => {
  assert.equal(apiUrl("/api/control/generations/g1/preview"), "/api/control/generations/g1/preview");
});

test("apiErrorStatus extracts status from API errors", () => {
  assert.equal(apiErrorStatus(new Error("API Error 410: gone")), 410);
  assert.equal(apiErrorStatus(new Error("API Error 409: conflict")), 409);
  assert.equal(apiErrorStatus(new Error("network down")), null);
  assert.equal(apiErrorStatus("plain string"), null);
  assert.equal(apiErrorStatus(null), null);
});

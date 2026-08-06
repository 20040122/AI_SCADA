import assert from "node:assert/strict";
import test from "node:test";
import { post, postForm } from "../src/api/client.ts";

test("FormData requests do not force a JSON Content-Type", async () => {
  let capturedHeaders: HeadersInit | undefined;
  const original = globalThis.fetch;
  globalThis.fetch = (async (_url: string, init?: RequestInit) => {
    capturedHeaders = init?.headers;
    return {
      ok: true,
      status: 200,
      json: async () => ({ data: { ok: true } }),
    } as Response;
  }) as typeof fetch;
  try {
    const form = new FormData();
    form.append("file", new Blob(["a,b\n1,2"], { type: "text/csv" }), "x.csv");
    await postForm("/api/binding/csv/preview", form);
    const headers = new Headers(capturedHeaders);
    assert.equal(headers.has("Content-Type"), false);
  } finally {
    globalThis.fetch = original;
  }
});

test("JSON requests keep the application/json Content-Type", async () => {
  let capturedHeaders: HeadersInit | undefined;
  const original = globalThis.fetch;
  globalThis.fetch = (async (_url: string, init?: RequestInit) => {
    capturedHeaders = init?.headers;
    return {
      ok: true,
      status: 200,
      json: async () => ({ data: { ok: true } }),
    } as Response;
  }) as typeof fetch;
  try {
    await post("/api/binding/match", { json_data: {}, properties: [] });
    const headers = new Headers(capturedHeaders);
    assert.equal(headers.get("Content-Type"), "application/json");
  } finally {
    globalThis.fetch = original;
  }
});

test("postForm returns the response payload", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = (async () => {
    return {
      ok: true,
      status: 200,
      json: async () => ({ data: { encoding: "utf-8" } }),
    } as Response;
  }) as typeof fetch;
  try {
    const form = new FormData();
    const res = await postForm<{ encoding: string }>("/api/binding/csv/preview", form);
    assert.equal(res.encoding, "utf-8");
  } finally {
    globalThis.fetch = original;
  }
});

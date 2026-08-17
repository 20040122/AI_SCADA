import assert from "node:assert/strict";
import test from "node:test";
import { useAssetStore } from "../src/stores/assetStore.ts";
import type { MaterialItem } from "../src/types/asset.ts";

function resetStore() {
  useAssetStore.setState({
    keywordResults: [],
    generations: {},
    queryResults: [],
    missedKeywords: [],
    pipeline: useAssetStore.getState().pipeline,
  });
}

function makeItem(name: string): MaterialItem {
  return {
    displayName: name,
    image: `assets/Agent/${name}.png`,
    width: 128,
    height: 128,
    source: "ai-generated",
    similarity: 1.0,
  };
}

test("setGeneration merges partial state per keyword", () => {
  resetStore();
  const store = useAssetStore.getState();
  store.setGeneration("飞机", { generationId: "g1", status: "queued" });
  store.setGeneration("飞机", { previewUrl: "/preview", seed: 42 });
  const g = useAssetStore.getState().generations["飞机"];
  assert.equal(g.generationId, "g1");
  assert.equal(g.status, "queued");
  assert.equal(g.previewUrl, "/preview");
  assert.equal(g.seed, 42);
});

test("keywords keep independent generation states", () => {
  resetStore();
  const store = useAssetStore.getState();
  store.setGeneration("飞机", { generationId: "g1", status: "queued" });
  store.setGeneration("潜水艇", { generationId: "g2", status: "ready" });
  const gens = useAssetStore.getState().generations;
  assert.equal(gens["飞机"].status, "queued");
  assert.equal(gens["潜水艇"].status, "ready");
});

test("clearGeneration removes single keyword state", () => {
  resetStore();
  const store = useAssetStore.getState();
  store.setGeneration("飞机", { generationId: "g1", status: "failed", error: "x" });
  store.setGeneration("潜水艇", { generationId: "g2", status: "queued" });
  store.clearGeneration("飞机");
  const gens = useAssetStore.getState().generations;
  assert.equal(gens["飞机"], undefined);
  assert.equal(gens["潜水艇"].generationId, "g2");
});

test("clearGenerations resets all generation state (stops old polling)", () => {
  resetStore();
  const store = useAssetStore.getState();
  store.setGeneration("飞机", { generationId: "g1", status: "running" });
  store.setGeneration("潜水艇", { generationId: "g2", status: "queued" });
  store.clearGenerations();
  assert.deepEqual(useAssetStore.getState().generations, {});
});

test("addQueryResult prepends and dedupes by displayName", () => {
  resetStore();
  const store = useAssetStore.getState();
  store.addQueryResult(makeItem("水泵"));
  store.addQueryResult(makeItem("风机"));
  store.addQueryResult(makeItem("水泵"));
  const items = useAssetStore.getState().queryResults;
  assert.equal(items.length, 2);
  assert.equal(items[0].displayName, "水泵");
  assert.equal(items[1].displayName, "风机");
});

test("confirm flow removes keyword and adds query result", () => {
  resetStore();
  const store = useAssetStore.getState();
  store.setKeywordResults([
    { keyword: "飞机", candidates: [], canGenerate: true },
    { keyword: "水泵", candidates: [], canGenerate: false },
  ]);
  store.setGeneration("飞机", { generationId: "g1", status: "ready", previewUrl: "/p" });

  store.addQueryResult(makeItem("飞机"));
  store.removeKeyword("飞机");
  store.clearGeneration("飞机");
  store.setPipelineStep(3, "done");

  const state = useAssetStore.getState();
  assert.deepEqual(
    state.keywordResults.map((k) => k.keyword),
    ["水泵"]
  );
  assert.equal(state.generations["飞机"], undefined);
  assert.equal(state.queryResults[0].displayName, "飞机");
  assert.equal(state.pipeline.find((s) => s.id === 3)?.status, "done");
});

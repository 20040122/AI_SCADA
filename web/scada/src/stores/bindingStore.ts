import { create } from "zustand";
import type {
  BindingAssignment,
  BindingBuildPreview,
  BindingBuildResponse,
  BindingCandidate,
  BindingMatchItem,
  BindingMatchResponse,
  BindingNormalizeResponse,
  BindingPreviewResponse,
  BindingProperty,
} from "../types/binding";
import type { LayoutJsonData, PipeData, UploadCanvasResponse } from "../types/layout";
import { buildBinding, matchBinding } from "../api/binding.ts";
import type { BindingColumnMapping } from "../api/binding.ts";

export type BindingSourceType = "layout" | "refine";

interface LocalMatchItem extends BindingMatchItem {
  selectedKey: string | null;
}

export interface BindingSourceSnapshot {
  sourceType: BindingSourceType;
  revision: number;
  canvas: LayoutJsonData | null;
  pipes: PipeData | null;
  fileName: string;
}

export interface LayoutSnapshot {
  revision: number;
  jsonData: LayoutJsonData | null;
  fileName: string;
  pipe_data: PipeData | null;
}

export interface RefineSnapshot {
  revision: number;
  workingJson: LayoutJsonData | null;
  sourceFileName: string | null;
  workingPipes: PipeData | null;
  pendingPatch: unknown;
}

export function resolveBindingSource(
  layout: LayoutSnapshot,
  refine: RefineSnapshot
): BindingSourceSnapshot | null {
  if (refine.pendingPatch !== null) return null;
  const refineReady =
    !!refine.workingJson &&
    !!refine.sourceFileName &&
    refine.sourceFileName === layout.fileName;
  if (refineReady) {
    return {
      sourceType: "refine",
      revision: refine.revision,
      canvas: refine.workingJson,
      pipes: refine.workingPipes,
      fileName: refine.sourceFileName ?? "",
    };
  }
  if (layout.jsonData && layout.fileName) {
    return {
      sourceType: "layout",
      revision: layout.revision,
      canvas: layout.jsonData,
      pipes: layout.pipe_data,
      fileName: layout.fileName,
    };
  }
  return {
    sourceType: "layout",
    revision: layout.revision,
    canvas: null,
    pipes: null,
    fileName: "",
  };
}

function deriveTargetFileName(fileName: string): string {
  const name = fileName.trim();
  if (!name) return "";
  if (name.endsWith(".json")) {
    return `${name.slice(0, -5)}_bound.json`;
  }
  return `${name}_bound.json`;
}

function candidateByKey(item: LocalMatchItem, key: string | null): BindingCandidate | null {
  if (!key) return null;
  return item.candidates.find((c) => c.key === key) ?? null;
}

function resetDerived(
  base: Pick<BindingStoreState, "sourceType" | "sourceRevision" | "canvas" | "pipes" | "fileName">
): Partial<BindingStore> {
  return {
    ...base,
    match: null,
    items: [],
    boundJson: null,
    buildPreviews: [],
    buildErrors: [],
    buildWarnings: [],
    targetFileName: deriveTargetFileName(base.fileName),
    uploadResult: null,
    uploadError: null,
  };
}

export interface BindingStore {
  sourceType: BindingSourceType | null;
  sourceRevision: number;
  canvas: LayoutJsonData | null;
  pipes: PipeData | null;
  fileName: string;

  csvFile: File | null;
  preview: BindingPreviewResponse | null;
  columnMapping: BindingColumnMapping[];
  normalized: BindingProperty[];
  normalizeErrors: string[];
  normalizeBlocked: boolean;
  normalizeBlocking: string[];

  match: BindingMatchResponse | null;
  items: LocalMatchItem[];

  boundJson: LayoutJsonData | null;
  buildPreviews: BindingBuildPreview[];
  buildErrors: string[];
  buildWarnings: string[];
  targetFileName: string;
  uploadResult: UploadCanvasResponse | null;
  uploadError: string | null;

  isLoading: boolean;
  error: string | null;

  syncSource: (
    sourceType: BindingSourceType,
    revision: number,
    canvas: LayoutJsonData | null,
    pipes: PipeData | null,
    fileName: string
  ) => void;
  setCsvFile: (file: File | null) => void;
  setPreview: (preview: BindingPreviewResponse) => void;
  setColumnMapping: (mapping: BindingColumnMapping[]) => void;
  applyNormalize: (res: BindingNormalizeResponse) => void;
  runMatch: () => Promise<void>;
  selectCandidate: (panelNodeI: number, expectationId: string, candidateKey: string) => void;
  confirmItem: (panelNodeI: number, expectationId: string) => void;
  confirmAllHigh: () => void;
  runBuild: () => Promise<void>;
  setTargetFileName: (name: string) => void;
  setUploadResult: (res: UploadCanvasResponse | null) => void;
  setUploadError: (e: string | null) => void;
  setLoading: (v: boolean) => void;
  setError: (e: string | null) => void;
  reset: () => void;
}

interface BindingStoreState {
  sourceType: BindingSourceType | null;
  sourceRevision: number;
  canvas: LayoutJsonData | null;
  pipes: PipeData | null;
  fileName: string;
}

export const useBindingStore = create<BindingStore>((set, get) => ({
  sourceType: null,
  sourceRevision: -1,
  canvas: null,
  pipes: null,
  fileName: "",

  csvFile: null,
  preview: null,
  columnMapping: [],
  normalized: [],
  normalizeErrors: [],
  normalizeBlocked: false,
  normalizeBlocking: [],

  match: null,
  items: [],

  boundJson: null,
  buildPreviews: [],
  buildErrors: [],
  buildWarnings: [],
  targetFileName: "",
  uploadResult: null,
  uploadError: null,

  isLoading: false,
  error: null,

  syncSource: (sourceType, revision, canvas, pipes, fileName) => {
    const s = get();
    if (s.sourceType === sourceType && s.sourceRevision === revision) return;
    const base: BindingStoreState = {
      sourceType,
      sourceRevision: revision,
      canvas: canvas ? JSON.parse(JSON.stringify(canvas)) as LayoutJsonData : null,
      pipes: pipes ? JSON.parse(JSON.stringify(pipes)) as PipeData : null,
      fileName,
    };
    set(resetDerived(base));
  },

  setCsvFile: (file) => {
    if (file === null) {
      set({
        csvFile: null,
        preview: null,
        columnMapping: [],
        normalized: [],
        normalizeErrors: [],
        normalizeBlocked: false,
        normalizeBlocking: [],
        match: null,
        items: [],
        boundJson: null,
        buildPreviews: [],
        buildErrors: [],
        buildWarnings: [],
        uploadResult: null,
        uploadError: null,
      });
      return;
    }
    set({
      csvFile: file,
      preview: null,
      columnMapping: [],
      normalized: [],
      normalizeErrors: [],
      normalizeBlocked: false,
      normalizeBlocking: [],
      match: null,
      items: [],
      boundJson: null,
      buildPreviews: [],
      buildErrors: [],
      buildWarnings: [],
      uploadResult: null,
      uploadError: null,
    });
  },

  setPreview: (preview) => set({ preview }),

  setColumnMapping: (mapping) => {
    const s = get();
    if (s.columnMapping.length === mapping.length &&
        s.columnMapping.every((m, i) => m.field === mapping[i]?.field && m.column === mapping[i]?.column)) {
      return;
    }
    set({
      columnMapping: mapping,
      normalized: [],
      normalizeErrors: [],
      normalizeBlocked: false,
      normalizeBlocking: [],
      match: null,
      items: [],
      boundJson: null,
      buildPreviews: [],
      buildErrors: [],
      buildWarnings: [],
      uploadResult: null,
      uploadError: null,
    });
  },

  applyNormalize: (res) => {
    set({
      normalized: res.properties,
      normalizeErrors: res.errors,
      normalizeBlocked: res.blocked,
      normalizeBlocking: res.blocking,
      match: null,
      items: [],
      boundJson: null,
      buildPreviews: [],
      buildErrors: [],
      buildWarnings: [],
      uploadResult: null,
      uploadError: null,
    });
  },

  runMatch: async () => {
    const s = get();
    if (!s.canvas || s.normalized.length === 0) return;
    set({ isLoading: true, error: null });
    try {
      const res = await matchBinding(s.canvas, s.normalized);
      const items: LocalMatchItem[] = res.items.map((item) => ({
        ...item,
        selectedKey: item.suggested,
      }));
      set({ match: res, items, boundJson: null, buildPreviews: [], buildErrors: [], buildWarnings: [], uploadResult: null, uploadError: null });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    } finally {
      set({ isLoading: false });
    }
  },

  selectCandidate: (panelNodeI, expectationId, candidateKey) => {
    set((s) => {
      const item = s.items.find(
        (it) => it.panel_node_i === panelNodeI && it.expectation_id === expectationId
      );
      if (!item || !candidateByKey(item, candidateKey)) return s;
      return {
        items: s.items.map((it) =>
          it.panel_node_i === panelNodeI && it.expectation_id === expectationId
            ? { ...it, selectedKey: candidateKey, confirmed: false }
            : it
        ),
        boundJson: null,
        buildPreviews: [],
        buildErrors: [],
        buildWarnings: [],
        uploadResult: null,
        uploadError: null,
      };
    });
  },

  confirmItem: (panelNodeI, expectationId) => {
    set((s) => {
      const item = s.items.find(
        (it) => it.panel_node_i === panelNodeI && it.expectation_id === expectationId
      );
      if (!item) return s;
      const key = item.selectedKey ?? item.suggested;
      if (!key || !candidateByKey(item, key)) return s;
      return {
        items: s.items.map((it) =>
          it.panel_node_i === panelNodeI && it.expectation_id === expectationId
            ? { ...it, confirmed: true }
            : it
        ),
        boundJson: null,
        buildPreviews: [],
        buildErrors: [],
        buildWarnings: [],
        uploadResult: null,
        uploadError: null,
      };
    });
  },

  confirmAllHigh: () => {
    set((s) => {
      let changed = false;
      const items = s.items.map((it) => {
        if (it.confirmed || it.confidence !== "high") return it;
        const key = it.selectedKey ?? it.suggested;
        if (!key || !candidateByKey(it, key)) return it;
        changed = true;
        return { ...it, confirmed: true };
      });
      if (!changed) return s;
      return {
        items,
        boundJson: null,
        buildPreviews: [],
        buildErrors: [],
        buildWarnings: [],
        uploadResult: null,
        uploadError: null,
      };
    });
  },

  runBuild: async () => {
    const s = get();
    if (!s.canvas) return;
    const assignments: BindingAssignment[] = [];
    for (const item of s.items) {
      if (!item.confirmed) continue;
      const key = item.selectedKey ?? item.suggested;
      const candidate = key ? candidateByKey(item, key) : null;
      if (!candidate) continue;
      assignments.push({
        panel_node_i: item.panel_node_i,
        expectation_id: item.expectation_id,
        candidate,
      });
    }
    set({ isLoading: true, error: null });
    try {
      const res: BindingBuildResponse = await buildBinding(s.canvas, s.normalized, assignments);
      set({
        boundJson: res.bound_json,
        buildPreviews: res.previews,
        buildErrors: res.errors,
        buildWarnings: res.warnings,
        uploadResult: null,
        uploadError: null,
      });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    } finally {
      set({ isLoading: false });
    }
  },

  setTargetFileName: (name) => set({ targetFileName: name }),

  setUploadResult: (res) => set({ uploadResult: res, uploadError: null }),

  setUploadError: (e) => set({ uploadError: e }),

  setLoading: (v) => set({ isLoading: v }),
  setError: (e) => set({ error: e }),

  reset: () =>
    set({
      sourceType: null,
      sourceRevision: -1,
      canvas: null,
      pipes: null,
      fileName: "",
      csvFile: null,
      preview: null,
      columnMapping: [],
      normalized: [],
      normalizeErrors: [],
      normalizeBlocked: false,
      normalizeBlocking: [],
      match: null,
      items: [],
      boundJson: null,
      buildPreviews: [],
      buildErrors: [],
      buildWarnings: [],
      targetFileName: "",
      uploadResult: null,
      uploadError: null,
      isLoading: false,
      error: null,
    }),
}));

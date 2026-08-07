import { create } from "zustand";
import type {
  BindingBuildPreview,
  BindingBuildResponse,
  BindingCandidate,
  BindingMatchItem,
  BindingMatchResponse,
  BindingPreviewResponse,
  BindingRequestRow,
} from "../types/binding";
import type { LayoutJsonData, PipeData, UploadCanvasResponse } from "../types/layout";
import { buildBinding, matchBinding } from "../api/binding.ts";

export type BindingSourceType = "layout" | "refine";

interface LocalMatchItem extends BindingMatchItem {
  selectedBindingId: string | null;
  confirmed: boolean;
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

function candidateByBindingId(
  item: LocalMatchItem,
  bindingId: string | null
): BindingCandidate | null {
  if (!bindingId) return null;
  return item.candidates.find((c) => c.binding_id === bindingId) ?? null;
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

function clearCsvDerived(): Partial<BindingStore> {
  return {
    preview: null,
    requests: [],
    match: null,
    items: [],
    boundJson: null,
    buildPreviews: [],
    buildErrors: [],
    buildWarnings: [],
    uploadResult: null,
    uploadError: null,
  };
}

function clearBuildResult(): Partial<BindingStore> {
  return {
    boundJson: null,
    buildPreviews: [],
    buildErrors: [],
    buildWarnings: [],
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
  requests: BindingRequestRow[];

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
  runMatch: () => Promise<void>;
  selectCandidate: (rowNumber: number, bindingId: string) => void;
  confirmItem: (rowNumber: number) => void;
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
  requests: [],

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
      canvas: canvas ? (JSON.parse(JSON.stringify(canvas)) as LayoutJsonData) : null,
      pipes: pipes ? (JSON.parse(JSON.stringify(pipes)) as PipeData) : null,
      fileName,
    };
    set(resetDerived(base));
  },

  setCsvFile: (file) => {
    if (file === null) {
      set({ csvFile: null, ...clearCsvDerived() });
      return;
    }
    set({ csvFile: file, ...clearCsvDerived() });
  },

  setPreview: (preview) => {
    set({ preview, requests: preview.requests, ...clearBuildResult() });
  },

  runMatch: async () => {
    const s = get();
    if (!s.canvas || s.requests.length === 0) return;
    set({ isLoading: true, error: null });
    try {
      const res = await matchBinding(s.canvas, s.requests);
      const items: LocalMatchItem[] = res.items.map((item) => ({
        ...item,
        selectedBindingId: item.suggested_binding_id,
        confirmed: false,
      }));
      set({ match: res, items, ...clearBuildResult() });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    } finally {
      set({ isLoading: false });
    }
  },

  selectCandidate: (rowNumber, bindingId) => {
    set((s) => {
      const item = s.items.find((it) => it.row_number === rowNumber);
      if (!item || !candidateByBindingId(item, bindingId)) return s;
      return {
        items: s.items.map((it) =>
          it.row_number === rowNumber
            ? { ...it, selectedBindingId: bindingId, confirmed: false }
            : it
        ),
        ...clearBuildResult(),
      };
    });
  },

  confirmItem: (rowNumber) => {
    set((s) => {
      const item = s.items.find((it) => it.row_number === rowNumber);
      if (!item) return s;
      const key = item.selectedBindingId;
      if (!key || !candidateByBindingId(item, key)) return s;
      return {
        items: s.items.map((it) =>
          it.row_number === rowNumber ? { ...it, confirmed: true } : it
        ),
        ...clearBuildResult(),
      };
    });
  },

  runBuild: async () => {
    const s = get();
    if (!s.canvas || s.requests.length === 0) return;
    const assignments = s.items
      .filter((it) => it.confirmed && it.selectedBindingId)
      .map((it) => ({ row_number: it.row_number, binding_id: it.selectedBindingId as string }));
    set({ isLoading: true, error: null });
    try {
      const res: BindingBuildResponse = await buildBinding(s.canvas, s.requests, assignments);
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
      requests: [],
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

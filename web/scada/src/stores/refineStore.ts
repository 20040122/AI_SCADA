import { create } from "zustand";
import type { CanvasNode, LayoutJsonData } from "../types/layout";
import type { JsonPatchOp, RefineMessage, RefineHistoryItem } from "../types/refine";
import { extractDecorationsFromJsonData, extractNodesFromJsonData } from "../utils/layoutNodes";
import type { DecorationNode } from "../types/layout";

interface PendingPatch {
  messageId: string;
  jsonSnapshot: LayoutJsonData;
  selectedNodeId: string | null;
  patch: JsonPatchOp[];
}

function nodeIdToI(nodeId: string): number {
  return parseInt(nodeId.replace("node-", ""));
}

function findJsonIndex(json: LayoutJsonData | null, nodeId: string): number {
  if (!json) return -1;
  const ni = nodeIdToI(nodeId);
  return json.d.findIndex((n) => n.i === ni);
}

function cloneLayout(json: LayoutJsonData): LayoutJsonData {
  return JSON.parse(JSON.stringify(json)) as LayoutJsonData;
}

function applyOpImmutable(obj: LayoutJsonData, op: JsonPatchOp): LayoutJsonData {
  const parts = op.path.split("/").filter(Boolean);
  if (parts.length === 0) {
    if (op.op === "remove") return { ...obj, d: [] };
    return obj;
  }
  const clone = { ...obj, d: [...obj.d] };
  let cur: Record<string, unknown> | unknown[] = clone as unknown as Record<string, unknown>;
  for (let i = 0; i < parts.length - 1; i++) {
    const key = parts[i];
    const next: unknown = Array.isArray(cur) ? cur[Number(key)] : cur[key];
    if (next === null || typeof next !== "object") return obj;
    const nextClone: Record<string, unknown> | unknown[] = Array.isArray(next)
      ? [...next]
      : { ...(next as Record<string, unknown>) };
    if (Array.isArray(cur)) cur[Number(key)] = nextClone;
    else cur[key] = nextClone;
    cur = nextClone;
  }
  const lastKey = parts[parts.length - 1];
  if (Array.isArray(cur)) {
    const index = Number(lastKey);
    if (!Number.isInteger(index)) return obj;
    if (op.op === "remove") cur.splice(index, 1);
    else cur[index] = op.value;
  } else if (op.op === "remove") {
    delete cur[lastKey];
  } else {
    cur[lastKey] = op.value;
  }
  return clone;
}

interface RefineStore {
  workingNodes: CanvasNode[];
  decorations: DecorationNode[];
  workingJson: LayoutJsonData | null;
  sourceFileName: string | null;
  canvasWidth: number;
  canvasHeight: number;
  selectedNodeId: string | null;
  messages: RefineMessage[];
  history: RefineHistoryItem[];
  isRefining: boolean;
  pendingPatch: PendingPatch | null;

  loadFromLayoutData: (
    nodes: CanvasNode[],
    width: number,
    height: number,
    layoutJson: LayoutJsonData | null,
    sourceFileName: string
  ) => void;
  setSelectedNodeId: (id: string | null) => void;
  moveNode: (id: string, x: number, y: number) => void;
  addMessage: (msg: RefineMessage) => void;
  setRefining: (value: boolean) => void;
  applyPatch: (patch: JsonPatchOp[], messageId: string) => void;
  acceptPatch: (messageId: string) => void;
  rejectPatch: (messageId: string) => void;
  clearCanvas: () => void;
}

export const useRefineStore = create<RefineStore>((set) => ({
  workingNodes: [],
  decorations: [],
  workingJson: null,
  sourceFileName: null,
  canvasWidth: 1920,
  canvasHeight: 1080,
  selectedNodeId: null,
  messages: [],
  history: [],
  isRefining: false,
  pendingPatch: null,

  loadFromLayoutData: (nodes, width, height, layoutJson, sourceFileName) => {
    const workingJson = layoutJson ? cloneLayout(layoutJson) : null;
    set({
      workingNodes: nodes.map((n) => ({ ...n })),
      decorations: extractDecorationsFromJsonData(workingJson),
      workingJson,
      sourceFileName: sourceFileName || null,
      canvasWidth: width,
      canvasHeight: height,
      selectedNodeId: null,
      messages: [],
      history: [],
      isRefining: false,
      pendingPatch: null,
    });
  },

  setSelectedNodeId: (id) => set({ selectedNodeId: id }),

  moveNode: (id, x, y) => {
    set((state) => {
      if (state.isRefining || state.pendingPatch) return state;

      const newNodes = state.workingNodes.map((n) =>
        n.id === id ? { ...n, x, y } : n
      );
      let newJson = state.workingJson;
      if (newJson) {
        const jsonIdx = findJsonIndex(newJson, id);
        if (jsonIdx >= 0) {
          newJson = {
            ...newJson,
            d: newJson.d.map((n, idx) =>
              idx === jsonIdx
                ? { ...n, p: { ...n.p, position: { ...n.p.position, x, y } } }
                : n
            ),
          };
        }
      }
      return { workingNodes: newNodes, workingJson: newJson };
    });
  },

  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  setRefining: (value) => set({ isRefining: value }),

  applyPatch: (patch, messageId) => {
    set((state) => {
      if (!state.workingJson || patch.length === 0 || state.pendingPatch) return state;

      const jsonSnapshot = cloneLayout(state.workingJson);
      const selectedNodeId = state.selectedNodeId;

      let newJson = state.workingJson;
      for (const op of patch) {
        newJson = applyOpImmutable(newJson, op);
      }

      const newNodes = extractNodesFromJsonData(newJson);
      const newDecorations = extractDecorationsFromJsonData(newJson);
      return {
        workingNodes: newNodes,
        decorations: newDecorations,
        workingJson: newJson,
        selectedNodeId:
          selectedNodeId && newNodes.some((node) => node.id === selectedNodeId)
            ? selectedNodeId
            : null,
        pendingPatch: {
          messageId,
          jsonSnapshot,
          selectedNodeId,
          patch,
        },
      };
    });
  },

  acceptPatch: (messageId) => {
    set((state) => {
      if (!state.pendingPatch || state.pendingPatch.messageId !== messageId) return state;

      const messages = state.messages.map((message) =>
        message.id === messageId
          ? { ...message, accepted: true, canAccept: false }
          : message
      );
      const historyItem: RefineHistoryItem = {
        description: "微调操作",
        patch: JSON.stringify(state.pendingPatch.patch),
        timestamp: new Date().toLocaleTimeString("zh", {
          hour: "2-digit",
          minute: "2-digit",
        }),
      };

      return {
        messages,
        history: [historyItem, ...state.history],
        pendingPatch: null,
      };
    });
  },

  rejectPatch: (messageId) => {
    set((state) => {
      if (!state.pendingPatch || state.pendingPatch.messageId !== messageId) return state;

      const snapshot = state.pendingPatch;
      const workingJson = cloneLayout(snapshot.jsonSnapshot);
      const workingNodes = extractNodesFromJsonData(workingJson);
      const decorations = extractDecorationsFromJsonData(workingJson);
      const messages = state.messages.map((message) =>
        message.id === messageId
          ? { ...message, rejected: true, canAccept: false }
          : message
      );
      return {
        workingNodes,
        decorations,
        workingJson,
        selectedNodeId:
          snapshot.selectedNodeId && workingNodes.some((node) => node.id === snapshot.selectedNodeId)
            ? snapshot.selectedNodeId
            : null,
        messages,
        pendingPatch: null,
      };
    });
  },

  clearCanvas: () =>
    set({
      workingNodes: [],
      decorations: [],
      workingJson: null,
      sourceFileName: null,
      selectedNodeId: null,
      messages: [],
      history: [],
      isRefining: false,
      pendingPatch: null,
    }),
}));

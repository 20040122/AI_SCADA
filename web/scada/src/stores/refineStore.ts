import { create } from "zustand";
import type { CanvasNode, LayoutJsonData, PipeData } from "../types/layout.ts";
import type { JsonPatchOp, RefineMessage, RefineHistoryItem } from "../types/refine.ts";
import { extractDecorationsFromJsonData, extractNodesFromJsonData } from "../utils/layoutNodes.ts";
import type { DecorationNode } from "../types/layout.ts";

interface PendingPatch {
  messageId: string;
  jsonSnapshot: LayoutJsonData;
  pipesSnapshot: PipeData | null;
  selectedNodeIds: string[];
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
    if (lastKey === "-" && op.op === "add") {
      (cur as unknown[]).push(op.value);
    } else {
      const index = Number(lastKey);
      if (!Number.isInteger(index)) return obj;
      if (op.op === "remove") cur.splice(index, 1);
      else cur[index] = op.value;
    }
  } else if (op.op === "remove") {
    delete cur[lastKey];
  } else {
    cur[lastKey] = op.value;
  }
  return clone;
}

function nodeToPipeKey(node: CanvasNode): string | null {
  const a = node.a;
  if (!a) return null;
  const g = String(a["layout.group"] ?? "");
  const n = String(a["layout.node"] ?? "");
  const inst = a["layout.instance"];
  if (g && n && inst != null) {
    return `${g}|${n}|${inst}`;
  }
  return null;
}

function filterRemovedConnections(pipes: PipeData | null, oldNodes: CanvasNode[], newNodes: CanvasNode[]): PipeData | null {
  if (!pipes || pipes.connections.length === 0) return pipes;
  const oldKeys = new Set<string>();
  for (const node of oldNodes) {
    const key = nodeToPipeKey(node);
    if (key) oldKeys.add(key);
  }
  const newKeys = new Set<string>();
  for (const node of newNodes) {
    const key = nodeToPipeKey(node);
    if (key) newKeys.add(key);
  }
  const deletedKeys = new Set<string>();
  for (const key of oldKeys) {
    if (!newKeys.has(key)) deletedKeys.add(key);
  }
  if (deletedKeys.size === 0) return pipes;
  const filtered = pipes.connections.filter((conn) => {
    const sk = `${conn.source.group}|${conn.source.node}|${conn.source.instance}`;
    const tk = `${conn.target.group}|${conn.target.node}|${conn.target.instance}`;
    return !deletedKeys.has(sk) && !deletedKeys.has(tk);
  });
  return { connections: filtered };
}

function filterValidIds(ids: string[], nodes: CanvasNode[]): string[] {
  const valid = new Set(nodes.map((n) => n.id));
  return ids.filter((id) => valid.has(id));
}

interface RefineStore {
  workingNodes: CanvasNode[];
  decorations: DecorationNode[];
  workingPipes: PipeData | null;
  workingJson: LayoutJsonData | null;
  sourceFileName: string | null;
  canvasWidth: number;
  canvasHeight: number;
  selectedNodeIds: string[];
  messages: RefineMessage[];
  history: RefineHistoryItem[];
  isRefining: boolean;
  pendingPatch: PendingPatch | null;

  loadFromLayoutData: (
    nodes: CanvasNode[],
    width: number,
    height: number,
    layoutJson: LayoutJsonData | null,
    sourceFileName: string,
    pipes?: PipeData | null
  ) => void;
  setSelection: (ids: string[]) => void;
  toggleSelection: (id: string) => void;
  clearSelection: () => void;
  moveNodes: (ids: string[], dx: number, dy: number) => void;
  moveNodesAbsolute: (updates: { id: string; x: number; y: number }[]) => void;
  resizeNode: (id: string, x: number, y: number, width: number, height: number) => void;
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

  loadFromLayoutData: (nodes, width, height, layoutJson, sourceFileName, pipes) => {
    const workingJson = layoutJson ? cloneLayout(layoutJson) : null;
    set({
      workingNodes: nodes.map((n) => ({ ...n })),
      decorations: extractDecorationsFromJsonData(workingJson),
      workingPipes: pipes ? JSON.parse(JSON.stringify(pipes)) as PipeData : null,
      workingJson,
      sourceFileName: sourceFileName || null,
      canvasWidth: width,
      canvasHeight: height,
      selectedNodeIds: [],
      messages: [],
      history: [],
      isRefining: false,
      pendingPatch: null,
    });
  },

  setSelection: (ids) => set({ selectedNodeIds: ids }),

  toggleSelection: (id) => set((state) => {
    const idx = state.selectedNodeIds.indexOf(id);
    if (idx >= 0) {
      const next = [...state.selectedNodeIds];
      next.splice(idx, 1);
      return { selectedNodeIds: next };
    }
    return { selectedNodeIds: [...state.selectedNodeIds, id] };
  }),

  clearSelection: () => set({ selectedNodeIds: [] }),

  moveNodes: (ids, dx, dy) => {
    set((state) => {
      if (state.isRefining || state.pendingPatch) return state;

      const idSet = new Set(ids);
      const movedIs = new Set<number>();
      for (const id of ids) {
        movedIs.add(nodeIdToI(id));
      }
      const newNodes = state.workingNodes.map((n) =>
        idSet.has(n.id) ? { ...n, x: Math.round((n.x + dx) * 100) / 100, y: Math.round((n.y + dy) * 100) / 100 } : n
      );
      let newJson = state.workingJson;
      if (newJson) {
        newJson = {
          ...newJson,
          d: newJson.d.map((n) => {
            const nodeId = `node-${n.i}`;
            if (idSet.has(nodeId) && n.p?.position) {
              return {
                ...n,
                p: {
                  ...n.p,
                  position: {
                    ...n.p.position,
                    x: Math.round((n.p.position.x + dx) * 100) / 100,
                    y: Math.round((n.p.position.y + dy) * 100) / 100,
                  },
                },
              };
            }
            if (n.a?.["layout.role"] === "control-label" && n.p?.position) {
              const labelFor = n.a["layout.labelFor"] as number;
              if (movedIs.has(labelFor)) {
                return {
                  ...n,
                  p: {
                    ...n.p,
                    position: {
                      ...n.p.position,
                      x: Math.round((n.p.position.x + dx) * 100) / 100,
                      y: Math.round((n.p.position.y + dy) * 100) / 100,
                    },
                  },
                };
              }
            }
            return n;
          }),
        };
      }
      const newDecorations = newJson ? extractDecorationsFromJsonData(newJson) : state.decorations;
      return { workingNodes: newNodes, workingJson: newJson, decorations: newDecorations };
    });
  },

  moveNodesAbsolute: (updates) => {
    set((state) => {
      if (state.isRefining || state.pendingPatch) return state;
      const updateMap = new Map(updates.map((u) => [u.id, u]));
      const deltas = new Map<string, { dx: number; dy: number }>();
      for (const u of updates) {
        const old = state.workingNodes.find((n) => n.id === u.id);
        if (old) {
          deltas.set(u.id, { dx: u.x - old.x, dy: u.y - old.y });
        }
      }
      const newNodes = state.workingNodes.map((n) => {
        const u = updateMap.get(n.id);
        return u ? { ...n, x: u.x, y: u.y } : n;
      });
      let newJson = state.workingJson;
      if (newJson) {
        newJson = {
          ...newJson,
          d: newJson.d.map((n) => {
            const nodeId = `node-${n.i}`;
            const u = updateMap.get(nodeId);
            if (u && n.p?.position) {
              return {
                ...n,
                p: {
                  ...n.p,
                  position: { x: u.x, y: u.y },
                },
              };
            }
            if (n.a?.["layout.role"] === "control-label" && n.p?.position) {
              const labelFor = n.a["layout.labelFor"];
              const labelForId = `node-${labelFor}`;
              const delta = deltas.get(labelForId);
              if (delta) {
                return {
                  ...n,
                  p: {
                    ...n.p,
                    position: {
                      ...n.p.position,
                      x: Math.round((n.p.position.x + delta.dx) * 100) / 100,
                      y: Math.round((n.p.position.y + delta.dy) * 100) / 100,
                    },
                  },
                };
              }
            }
            return n;
          }),
        };
      }
      const newDecorations = newJson ? extractDecorationsFromJsonData(newJson) : state.decorations;
      return { workingNodes: newNodes, workingJson: newJson, decorations: newDecorations };
    });
  },

  resizeNode: (id, x, y, width, height) => {
    set((state) => {
      if (state.isRefining || state.pendingPatch) return state;

      const oldNode = state.workingNodes.find((n) => n.id === id);
      const dx = oldNode ? x - oldNode.x : 0;
      const dy = oldNode ? y - oldNode.y : 0;
      const newNodes = state.workingNodes.map((n) =>
        n.id === id ? { ...n, x, y, width, height } : n
      );
      let newJson = state.workingJson;
      if (newJson) {
        const jsonIdx = findJsonIndex(newJson, id);
        if (jsonIdx >= 0) {
          const movedI = nodeIdToI(id);
          newJson = {
            ...newJson,
            d: newJson.d.map((n, idx) => {
              if (idx === jsonIdx) {
                return {
                  ...n,
                  p: {
                    ...n.p,
                    position: { x, y },
                    width,
                    height,
                  },
                };
              }
              if (n.a?.["layout.role"] === "control-label" && n.p?.position) {
                const labelFor = n.a["layout.labelFor"] as number;
                if (labelFor === movedI) {
                  return {
                    ...n,
                    p: {
                      ...n.p,
                      position: {
                        ...n.p.position,
                        x: Math.round((n.p.position.x + dx) * 100) / 100,
                        y: Math.round((n.p.position.y + dy) * 100) / 100,
                      },
                    },
                  };
                }
              }
              return n;
            }),
          };
        }
      }
      const newDecorations = newJson ? extractDecorationsFromJsonData(newJson) : state.decorations;
      return { workingNodes: newNodes, workingJson: newJson, decorations: newDecorations };
    });
  },

  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  setRefining: (value) => set({ isRefining: value }),

  applyPatch: (patch, messageId) => {
    set((state) => {
      if (!state.workingJson || patch.length === 0 || state.pendingPatch) return state;

      const jsonSnapshot = cloneLayout(state.workingJson);
      const pipesSnapshot = state.workingPipes;
      const selectedNodeIds = [...state.selectedNodeIds];

      let newJson = state.workingJson;
      for (const op of patch) {
        newJson = applyOpImmutable(newJson, op);
      }

      const newNodes = extractNodesFromJsonData(newJson);
      const newDecorations = extractDecorationsFromJsonData(newJson);
      const newPipes = filterRemovedConnections(state.workingPipes, state.workingNodes, newNodes);
      return {
        workingNodes: newNodes,
        decorations: newDecorations,
        workingPipes: newPipes,
        workingJson: newJson,
        selectedNodeIds: filterValidIds(selectedNodeIds, newNodes),
        pendingPatch: {
          messageId,
          jsonSnapshot,
          pipesSnapshot,
          selectedNodeIds,
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
        workingPipes: snapshot.pipesSnapshot ? JSON.parse(JSON.stringify(snapshot.pipesSnapshot)) as PipeData : null,
        workingJson,
        selectedNodeIds: filterValidIds(snapshot.selectedNodeIds, workingNodes),
        messages,
        pendingPatch: null,
      };
    });
  },

  clearCanvas: () =>
    set({
      workingNodes: [],
      decorations: [],
      workingPipes: null,
      workingJson: null,
      sourceFileName: null,
      selectedNodeIds: [],
      messages: [],
      history: [],
      isRefining: false,
      pendingPatch: null,
    }),
}));

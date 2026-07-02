import { create } from "zustand";
import type { CanvasNode, LayoutJsonData, LayoutNodeData } from "../types/layout";
import type { JsonPatchOp, RefineMessage, RefineHistoryItem } from "../types/refine";
import { extractNodesFromJsonData } from "../utils/layoutNodes";

interface PatchSnapshot {
  canvasNode: CanvasNode;
  layoutNode?: LayoutNodeData | null;
}

function nodeIdToI(nodeId: string): number {
  return parseInt(nodeId.replace("node-", ""));
}

function findJsonIndex(json: LayoutJsonData | null, nodeId: string): number {
  if (!json) return -1;
  const ni = nodeIdToI(nodeId);
  return json.d.findIndex((n) => n.i === ni);
}

function applyOpImmutable(obj: LayoutJsonData, op: JsonPatchOp): LayoutJsonData {
  const parts = op.path.split("/").filter(Boolean);
  if (parts.length === 0) {
    if (op.op === "remove") return { ...obj, d: [] };
    return obj;
  }
  const clone: any = { ...obj, d: [...obj.d] };
  let cur: any = clone;
  for (let i = 0; i < parts.length - 1; i++) {
    const key = parts[i];
    const next = cur[key];
    cur[key] = Array.isArray(next) ? [...next] : { ...next };
    cur = cur[key];
  }
  const lastKey = parts[parts.length - 1];
  if (op.op === "remove") {
    if (Array.isArray(cur)) cur.splice(parseInt(lastKey), 1);
    else delete cur[lastKey];
  } else {
    cur[lastKey] = op.value;
  }
  return clone as LayoutJsonData;
}

interface RefineStore {
  workingNodes: CanvasNode[];
  workingJson: LayoutJsonData | null;
  canvasWidth: number;
  canvasHeight: number;
  selectedNodeId: string | null;
  messages: RefineMessage[];
  history: RefineHistoryItem[];
  lastSnapshot: PatchSnapshot | null;

  loadFromLayoutData: (nodes: CanvasNode[], width: number, height: number, layoutJson?: LayoutJsonData | null) => void;
  setSelectedNodeId: (id: string | null) => void;
  moveNode: (id: string, x: number, y: number) => void;
  addMessage: (msg: RefineMessage) => void;
  addHistory: (item: RefineHistoryItem) => void;
  appendPatchMessage: (userText: string, patch: JsonPatchOp[], patchStr: string, msgId: string) => void;
  applyPatch: (patch: JsonPatchOp[]) => void;
  rejectLastPatch: () => void;
  acceptLastPatch: () => void;
  clearCanvas: () => void;
}

let msgCounter = 0;
function nextMsgId() {
  return `refine-msg-${++msgCounter}`;
}

export const useRefineStore = create<RefineStore>((set, get) => ({
  workingNodes: [],
  workingJson: null,
  canvasWidth: 1000,
  canvasHeight: 800,
  selectedNodeId: null,
  messages: [],
  history: [],
  lastSnapshot: null,

  loadFromLayoutData: (nodes, width, height, layoutJson) => {
    set({
      workingNodes: nodes.map((n) => ({ ...n })),
      workingJson: layoutJson ? JSON.parse(JSON.stringify(layoutJson)) : null,
      canvasWidth: width,
      canvasHeight: height,
      selectedNodeId: null,
      messages: [],
      history: [],
      lastSnapshot: null,
    });
    msgCounter = 0;
  },

  setSelectedNodeId: (id) => set({ selectedNodeId: id }),

  moveNode: (id, x, y) => {
    set((state) => {
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
  addHistory: (item) => set((s) => ({ history: [item, ...s.history] })),

  appendPatchMessage: (userText, patch, patchStr, msgId) => {
    const state = get();
    const w = state.workingNodes.find((n) => n.id === state.selectedNodeId);
    const ctx = w
      ? `已选中 <strong>${w.displayName}</strong>，当前坐标 x:${w.x} y:${w.y} w:${w.width} h:${w.height}。`
      : "";

    const aiMsg: RefineMessage = {
      id: msgId || nextMsgId(),
      role: "ai",
      content: ctx + `AI 已生成 JSON Patch：`,
      patch,
      patchStr,
      canAccept: true,
      accepted: false,
      rejected: false,
    };

    const userMsg: RefineMessage = {
      id: nextMsgId(),
      role: "user",
      content: userText,
    };

    set((s) => ({
      messages: [...s.messages, userMsg, aiMsg],
    }));
  },

  applyPatch: (patch) => {
    set((state) => {
      const nodeId = state.selectedNodeId;
      if (!nodeId || !state.workingJson) return state;

      const jsonIdx = findJsonIndex(state.workingJson, nodeId);

      const canvasNode = state.workingNodes.find((n) => n.id === nodeId);
      const layoutNode = jsonIdx >= 0 ? state.workingJson.d[jsonIdx] : null;
      const snapshot: PatchSnapshot | null = canvasNode
        ? {
            canvasNode: { ...canvasNode },
            layoutNode: layoutNode
              ? {
                  ...layoutNode,
                  p: { ...layoutNode.p, position: { ...layoutNode.p.position } },
                }
              : null,
          }
        : null;

      let newJson = state.workingJson;
      for (const op of patch) {
        newJson = applyOpImmutable(newJson, op);
      }

      const removed = findJsonIndex(newJson, nodeId) < 0;
      const newNodes = extractNodesFromJsonData(newJson);

      if (removed) {
        return {
          workingNodes: newNodes,
          workingJson: newJson,
          lastSnapshot: snapshot,
          selectedNodeId: null,
        };
      }
      return {
        workingNodes: newNodes,
        workingJson: newJson,
        lastSnapshot: snapshot,
      };
    });
  },

  rejectLastPatch: () => {
    set((state) => {
      if (!state.lastSnapshot) return state;
      const snap = state.lastSnapshot;
      const snapI = snap.layoutNode?.i;

      let newJson = state.workingJson;
      if (newJson && snap.layoutNode) {
        const idx = newJson.d.findIndex((n) => n.i === snapI);
        if (idx >= 0) {
          newJson = {
            ...newJson,
            d: newJson.d.map((n, i) => (i === idx ? { ...snap.layoutNode! } : n)),
          };
        } else {
          newJson = {
            ...newJson,
            d: [...newJson.d, { ...snap.layoutNode! }],
          };
        }
      }
      const newNodes = extractNodesFromJsonData(newJson);

      const msgs = state.messages.map((m) =>
        m.canAccept && !m.accepted && !m.rejected
          ? { ...m, rejected: true, canAccept: false }
          : m
      );
      return {
        workingNodes: newNodes,
        workingJson: newJson,
        lastSnapshot: null,
        messages: msgs,
        selectedNodeId: state.selectedNodeId || snap.canvasNode.id,
      };
    });
  },

  acceptLastPatch: () => {
    set((state) => {
      const msgs = state.messages.map((m) =>
        m.canAccept && !m.accepted && !m.rejected
          ? { ...m, accepted: true, canAccept: false }
          : m
      );
      const historyItem: RefineHistoryItem = state.lastSnapshot
        ? {
            description: `调整 ${state.lastSnapshot.canvasNode.displayName}`,
            patch: JSON.stringify(msgs.find((m) => m.accepted)?.patch || []),
            timestamp: new Date().toLocaleTimeString("zh", {
              hour: "2-digit",
              minute: "2-digit",
            }),
          }
        : {
            description: "微调操作",
            patch: "",
            timestamp: new Date().toLocaleTimeString("zh", {
              hour: "2-digit",
              minute: "2-digit",
            }),
          };

      return {
        lastSnapshot: null,
        messages: msgs,
        history: [historyItem, ...state.history],
      };
    });
  },

  clearCanvas: () =>
    set({
      workingNodes: [],
      workingJson: null,
      selectedNodeId: null,
      messages: [],
      history: [],
      lastSnapshot: null,
    }),
}));

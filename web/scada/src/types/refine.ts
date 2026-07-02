export interface JsonPatchOp {
  op: 'replace' | 'remove' | 'add';
  path: string;
  value?: unknown;
}

export interface RefineMessage {
  id: string;
  role: 'user' | 'ai';
  content: string;
  patch?: JsonPatchOp[];
  patchStr?: string;
  canAccept?: boolean;
  accepted?: boolean;
  rejected?: boolean;
}

export interface RefineHistoryItem {
  description: string;
  patch: string;
  timestamp: string;
}

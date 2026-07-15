import { useState, useEffect, useRef, useMemo } from "react";
import { useRefineStore } from "../../stores/refineStore";
import { useLayoutStore } from "../../stores/layoutStore";
import type { RefineMessage } from "../../types/refine";
import type { CanvasNode } from "../../types/layout";
import { refineLayout, uploadToSystem } from "../../api/layout";
import { colorJson } from "../../utils/jsonColor";
import { notify } from "../../utils/notification";

const QUICK_CHIPS = [
  { label: "右移", cmd: "把这个控件移到右边200px" },
  { label: "上移", cmd: "把选中控件向上移动100px" },
  { label: "放大", cmd: "把选中控件放大20%" },
  { label: "删", cmd: "删除选中控件" },
  { label: "对齐", cmd: "等间距排列所有控件" },
];

let messageIdSequence = 0;
let activeRefineRequestOwner: symbol | null = null;

function createMessageId(prefix: string) {
  messageIdSequence += 1;
  return `${prefix}-${Date.now()}-${messageIdSequence}`;
}

function getValidatedSelection(selectedNodeId: string | null, workingNodes: CanvasNode[]) {
  const match = selectedNodeId?.match(/^node-(-?\d+)$/);
  if (!match) return null;
  const nodeI = Number(match[1]);
  if (!Number.isSafeInteger(nodeI)) return null;
  const node = workingNodes.find((candidate) => candidate.id === selectedNodeId);
  return node ? { node, nodeI } : null;
}

export default function RightPanel() {
  const {
    workingNodes,
    selectedNodeId,
    messages,
    workingJson,
    sourceFileName,
    isRefining,
    pendingPatch,
    acceptPatch,
    rejectPatch,
  } = useRefineStore();
  const { fileName } = useLayoutStore();

  const [input, setInput] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);
  const [uploadErr, setUploadErr] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const requestOwnerRef = useRef<symbol | null>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isRefining]);

  useEffect(() => () => {
    const requestOwner = requestOwnerRef.current;
    requestOwnerRef.current = null;
    if (requestOwner !== null && activeRefineRequestOwner === requestOwner) {
      activeRefineRequestOwner = null;
      useRefineStore.getState().setRefining(false);
    }
  }, []);

  const selection = getValidatedSelection(selectedNodeId, workingNodes);
  const selectedNodeI = selection?.nodeI;
  const interactionLocked = isRefining || pendingPatch !== null;
  const sourceMatchesLayout =
    sourceFileName !== null && sourceFileName.length > 0 && sourceFileName === fileName;
  const uploadDisabled = !workingJson || !sourceMatchesLayout || interactionLocked || uploading;

  const canvasJsonHtml = useMemo(() => {
    if (!workingJson) return colorJson('{}');
    const str = JSON.stringify(workingJson, null, 2);
    let html = colorJson(str);
    if (selectedNodeI !== undefined) {
      const pattern = `<span class="text-[#7ec8f0]">"i"</span>: <span class="text-[#ffcc80]">${selectedNodeI}</span>`;
      html = html.replace(
        pattern,
        '<span style="background:rgba(77,184,212,0.15);border-radius:2px;outline:1px solid rgba(77,184,212,0.5)">' + pattern + '</span>'
      );
    }
    return html;
  }, [workingJson, selectedNodeI]);

  const handleSend = async () => {
    const val = input.trim();
    if (!val) return;

    const state = useRefineStore.getState();
    if (state.isRefining || state.pendingPatch) return;

    const submittedJson = state.workingJson;
    if (!submittedJson) {
      state.addMessage({
        id: createMessageId('refine-err'),
        role: 'ai',
        content: '当前没有可微调的画面 JSON，请先生成布局。',
      });
      return;
    }

    const submittedSelection = getValidatedSelection(state.selectedNodeId, state.workingNodes);
    const requestOwner = Symbol();
    requestOwnerRef.current = requestOwner;
    activeRefineRequestOwner = requestOwner;
    setInput('');
    state.addMessage({ id: createMessageId('refine-user'), role: 'user', content: val });
    state.setRefining(true);

    try {
      const response = await refineLayout({
        instruction: val,
        jsonData: submittedJson,
        ...(submittedSelection ? { selectedNodeI: submittedSelection.nodeI } : {}),
      });
      const currentState = useRefineStore.getState();
      if (
        requestOwnerRef.current !== requestOwner ||
        activeRefineRequestOwner !== requestOwner ||
        currentState.workingJson !== submittedJson
      ) return;
      const aiMessageId = createMessageId('refine-ai');

      if (response.patch.length > 0) {
        currentState.applyPatch(response.patch, aiMessageId);
        const patchedState = useRefineStore.getState();
        if (
          requestOwnerRef.current !== requestOwner ||
          activeRefineRequestOwner !== requestOwner ||
          patchedState.pendingPatch?.messageId !== aiMessageId
        ) return;
        patchedState.addMessage({
          id: aiMessageId,
          role: 'ai',
          content: response.message,
          patch: response.patch,
          patchStr: JSON.stringify(response.patch, null, 2),
          canAccept: true,
          accepted: false,
          rejected: false,
        });
      } else {
        currentState.addMessage({ id: aiMessageId, role: 'ai', content: response.message });
      }
    } catch (e) {
      const currentState = useRefineStore.getState();
      if (
        requestOwnerRef.current !== requestOwner ||
        activeRefineRequestOwner !== requestOwner ||
        currentState.workingJson !== submittedJson
      ) return;
      currentState.addMessage({
        id: createMessageId('refine-err'),
        role: 'ai',
        content: `微调失败：${e instanceof Error ? e.message : '请稍后重试'}`,
      });
    } finally {
      if (
        requestOwnerRef.current === requestOwner &&
        activeRefineRequestOwner === requestOwner
      ) {
        requestOwnerRef.current = null;
        activeRefineRequestOwner = null;
        useRefineStore.getState().setRefining(false);
      }
    }
  };

  const handleChip = (cmd: string) => {
    setInput(cmd);
  };

  const handleUpload = async () => {
    const state = useRefineStore.getState();
    const currentFileName = useLayoutStore.getState().fileName;
    if (
      !state.workingJson ||
      !state.sourceFileName ||
      state.sourceFileName !== currentFileName ||
      state.isRefining ||
      state.pendingPatch ||
      uploading
    ) return;
    const submittedJson = state.workingJson;
    const submittedFileName = state.sourceFileName;
    setUploading(true);
    setUploadMsg(null);
    setUploadErr(false);
    try {
      await uploadToSystem(submittedJson, submittedFileName);
      setUploadMsg('已插入系统');
    } catch (e) {
      setUploadMsg(e instanceof Error ? e.message : '插入系统失败，请稍后重试');
      setUploadErr(true);
    } finally {
      setUploading(false);
    }
  };

  const renderMessageContent = (msg: RefineMessage) => {
    return (
      <div>
        <div className="whitespace-pre-wrap">{msg.content}</div>
        {msg.patch && msg.patch.length > 0 && (
          <div
            className="bg-[var(--bg4)] border border-[var(--border)] rounded-[4px] p-[8px_10px] mt-[6px] font-mono text-[9px] text-[var(--teal)] leading-[1.7] whitespace-pre overflow-auto"
            style={{ maxHeight: '200px' }}
            dangerouslySetInnerHTML={{
              __html: colorJson(msg.patchStr || JSON.stringify(msg.patch, null, 2)),
            }}
          />
        )}
        {msg.canAccept && !msg.accepted && !msg.rejected && (
          <div className="flex gap-[5px] mt-[5px]">
            <button
              className="px-[9px] py-[3px] rounded-[3px] text-[9px] cursor-pointer border border-[var(--success)] text-[var(--success)] bg-[rgba(62,207,122,0.06)] font-mono transition-[0.12s] hover:bg-[rgba(62,207,122,0.18)]"
              onClick={() => {
                acceptPatch(msg.id);
                notify('Patch 已接受', 's');
              }}
            >
              ✓ 接受
            </button>
            <button
              className="px-[9px] py-[3px] rounded-[3px] text-[9px] cursor-pointer border border-[var(--text3)] text-[var(--text3)] font-mono transition-[0.12s] hover:border-[var(--error)] hover:text-[var(--error)]"
              onClick={() => {
                rejectPatch(msg.id);
                notify('已撤销', 'w');
              }}
            >
              ✕ 撤销
            </button>
          </div>
        )}
        {msg.accepted && (
          <div className="mt-[5px] text-[10px] text-[var(--success)] font-mono">✓ 修改已应用</div>
        )}
        {msg.rejected && (
          <div className="mt-[5px] text-[10px] text-[var(--warn)] font-mono">✕ 已撤销</div>
        )}
      </div>
    );
  };

  return (
    <div className="w-[380px] bg-[var(--panel)] border-l border-[var(--border)] flex flex-col shrink-0 overflow-hidden">

      <div className="flex-1 flex flex-col overflow-hidden min-h-0">
        <div className="p-[10px] border-b border-[var(--border)] bg-[var(--bg2)] shrink-0">
          <span className="text-[13px] font-medium text-[var(--text)]">AI 助手</span>
        </div>

        <div className="flex-1 overflow-y-auto p-[10px] flex flex-col gap-[8px] min-h-0" id="refineChat">
          {messages.length === 0 && (
            <div className="text-[11px] text-[var(--text3)] font-mono text-center py-8">
              {selection
                ? '请输入局部或全局微调指令'
                : '可直接输入全局调整指令，或点击画布控件进行局部调整。'}
            </div>
          )}
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`max-w-[88%] ${
                msg.role === 'ai'
                  ? 'self-start'
                  : 'self-end'
              }`}
            >
              <div
                className={`p-[8px_11px] rounded-[5px] text-[11px] leading-[1.5] ${
                  msg.role === 'ai'
                    ? 'bg-[var(--bg3)] border border-[var(--border)] text-[var(--text2)] rounded-bl-[1px]'
                    : 'bg-[rgba(77,184,212,0.1)] border border-[rgba(77,184,212,0.22)] text-[var(--text)] rounded-br-[1px]'
                }`}
              >
                {renderMessageContent(msg)}
              </div>
            </div>
          ))}
          {isRefining && (
            <div className="max-w-[88%] self-start">
              <div className="p-[8px_11px] rounded-[5px] text-[11px] leading-[1.5] bg-[var(--bg3)] border border-[var(--border)] text-[var(--text2)] rounded-bl-[1px]">
                正在解析指令...
              </div>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>

        <div className="shrink-0 p-[8px] border-t border-[var(--border)] bg-[var(--bg2)]">
          <div className="flex gap-[6px] mb-[5px] flex-wrap">
            {QUICK_CHIPS.map((chip) => (
              <button
                type="button"
                key={chip.label}
                className="text-[9px] px-[8px] py-[2px] border border-[var(--border2)] rounded-[10px] text-[var(--text3)] cursor-pointer font-mono bg-transparent transition-[0.12s] hover:border-[var(--accent2)] hover:text-[var(--accent)] disabled:opacity-50 disabled:cursor-not-allowed"
                onClick={() => handleChip(chip.cmd)}
                disabled={interactionLocked}
              >
                {chip.label}
              </button>
            ))}
          </div>
          <div className="flex gap-[6px]">
            <input
              className="flex-1 bg-[var(--bg3)] border border-[var(--border)] rounded-[4px] px-[9px] py-[6px] text-[11px] text-[var(--text)] font-[var(--sans)] outline-none focus:border-[var(--accent2)] disabled:opacity-50 disabled:cursor-not-allowed"
              placeholder={
                selection
                  ? `如：${selection.node.displayName} 右移200px`
                  : '输入全局调整指令…'
              }
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !interactionLocked) void handleSend(); }}
              disabled={interactionLocked}
            />
            <button
              className="px-[12px] py-[6px] bg-[rgba(77,184,212,0.1)] border border-[var(--accent)] rounded-[4px] text-[var(--accent)] text-[11px] cursor-pointer font-mono hover:bg-[rgba(77,184,212,0.22)] disabled:opacity-50 disabled:cursor-not-allowed"
              onClick={handleSend}
              disabled={interactionLocked}
            >
              发送
            </button>
          </div>
        </div>
      </div>

      <div className="flex-1 flex flex-col overflow-hidden min-h-0 border-t border-[var(--border)]">
        <div className="p-[6px_10px] bg-[var(--bg2)] border-b border-[var(--border)] flex items-center justify-between shrink-0">
          <span className="text-[9px] font-mono text-[var(--text3)] tracking-[0.5px] uppercase">
            画面 JSON
          </span>
          {selection && (
            <span className="text-[9px] text-[var(--accent)] font-mono">已选中高亮</span>
          )}
        </div>
        <div
          className="flex-1 overflow-auto font-mono text-[9px] leading-[1.6] p-[10px] whitespace-pre min-h-0"
          dangerouslySetInnerHTML={{ __html: canvasJsonHtml }}
        />
        <div className="shrink-0 p-[10px] border-t border-[var(--border)] bg-[var(--bg2)]">
          <button
            className="w-full px-[16px] py-[7px] rounded-[4px] text-[11px] cursor-pointer border border-[var(--accent)] bg-[rgba(77,184,212,0.1)] text-[var(--accent)] font-[var(--sans)] transition-[0.15s] hover:bg-[rgba(77,184,212,0.2)] disabled:opacity-50 disabled:cursor-not-allowed"
            onClick={handleUpload}
            disabled={uploadDisabled}
          >
            {uploading ? '插入中...' : '插入系统'}
          </button>
          {uploadMsg && (
            <div
              className={`mt-2 text-[10px] font-mono text-center ${
                uploadErr ? 'text-[var(--warn)]' : 'text-[var(--accent)]'
              }`}
            >
              {uploadMsg}
            </div>
          )}
        </div>
      </div>

    </div>
  );
}

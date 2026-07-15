import { useState, useEffect, useRef, useMemo } from "react";
import { useRefineStore } from "../../stores/refineStore";
import type { JsonPatchOp, RefineMessage } from "../../types/refine";
import { colorJson } from "../../utils/jsonColor";
import { notify } from "../../utils/notification";

const QUICK_CHIPS = [
  { label: "右移", cmd: "把这个控件移到右边200px" },
  { label: "上移", cmd: "把选中控件向上移动100px" },
  { label: "放大", cmd: "把选中控件放大20%" },
  { label: "删", cmd: "删除选中控件" },
  { label: "对齐", cmd: "等间距排列所有控件" },
];

function generateRefinePatch(cmd: string, node: { x: number; y: number; width: number; height: number; id?: string } | undefined, jsonIndex: number): JsonPatchOp[] {
  if (!node || jsonIndex < 0) return [];
  const base = `/d/${jsonIndex}`;

  if (cmd.includes('放大') || cmd.includes('缩放')) {
    return [
      { op: 'replace', path: `${base}/p/width`, value: Math.round(node.width * 1.2) },
      { op: 'replace', path: `${base}/p/height`, value: Math.round(node.height * 1.2) },
    ];
  }
  if (cmd.includes('上移')) {
    return [{ op: 'replace', path: `${base}/p/position/y`, value: Math.round(node.y - 100) }];
  }
  if (cmd.includes('移')) {
    const match = cmd.match(/(\d+)/);
    const dist = match ? parseInt(match[1]) : 100;
    return [{ op: 'replace', path: `${base}/p/position/x`, value: Math.round(node.x + dist) }];
  }
  if (cmd.includes('删除')) {
    return [{ op: 'remove', path: base }];
  }
  if (cmd.includes('间距') || cmd.includes('排列') || cmd.includes('对齐')) {
    return [{ op: 'replace', path: `${base}/p/position/x`, value: 100 }];
  }
  return [{ op: 'replace', path: `${base}/p/position/x`, value: Math.round(node.x + 50) }];
}

function acceptOrReject(
  _msgId: string,
  accept: boolean,
  _msg: RefineMessage,
  rejectPatch: () => void,
  acceptLastPatch: () => void
) {
  if (accept) {
    acceptLastPatch();
    notify('Patch 已接受', 's');
  } else {
    rejectPatch();
    notify('已撤销', 'w');
  }
}

export default function RightPanel() {
  const {
    workingNodes,
    selectedNodeId,
    messages,
    workingJson,
    addMessage,
    appendPatchMessage,
    applyPatch,
    rejectLastPatch,
    acceptLastPatch,
  } = useRefineStore();

  const [input, setInput] = useState('');
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const selectedNode = workingNodes.find(n => n.id === selectedNodeId);

  const canvasJsonHtml = useMemo(() => {
    if (!workingJson) return colorJson('{}');
    const str = JSON.stringify(workingJson, null, 2);
    let html = colorJson(str);
    if (selectedNodeId) {
      const nodeIdx = parseInt(selectedNodeId.replace('node-', ''));
      const pattern = `<span class="text-[#7ec8f0]">"i"</span>: <span class="text-[#ffcc80]">${nodeIdx}</span>`;
      html = html.replace(
        pattern,
        '<span style="background:rgba(77,184,212,0.15);border-radius:2px;outline:1px solid rgba(77,184,212,0.5)">' + pattern + '</span>'
      );
    }
    return html;
  }, [workingJson, selectedNodeId]);

  const handleSend = () => {
    const val = input.trim();
    if (!val) return;
    setInput('');

    if (!selectedNodeId) {
      addMessage({ id: `refine-err-${Date.now()}`, role: 'ai', content: '请先在画布中选中一个控件' });
      return;
    }

    let jsonIndex = -1;
    if (workingJson) {
      const ni = parseInt(selectedNodeId.replace('node-', ''));
      jsonIndex = workingJson.d.findIndex(n => n.i === ni);
    }
    if (jsonIndex < 0) {
      addMessage({ id: `refine-err-${Date.now()}`, role: 'ai', content: '未找到选中控件在 JSON 中的位置' });
      return;
    }

    const patch = generateRefinePatch(val, selectedNode, jsonIndex);
    const patchStr = JSON.stringify(patch, null, 2);

    applyPatch(patch);
    appendPatchMessage(val, patch, patchStr, `refine-ai-${Date.now()}`);
  };

  const handleChip = (cmd: string) => {
    setInput(cmd);
  };

  const renderMessageContent = (msg: RefineMessage) => {
    return (
      <div>
        <div dangerouslySetInnerHTML={{ __html: msg.content }} />
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
              onClick={() => acceptOrReject(msg.id, true, msg, rejectLastPatch, acceptLastPatch)}
            >
              ✓ 接受
            </button>
            <button
              className="px-[9px] py-[3px] rounded-[3px] text-[9px] cursor-pointer border border-[var(--text3)] text-[var(--text3)] font-mono transition-[0.12s] hover:border-[var(--error)] hover:text-[var(--error)]"
              onClick={() => acceptOrReject(msg.id, false, msg, rejectLastPatch, acceptLastPatch)}
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
              {selectedNodeId
                ? '请输入微调指令'
                : '点击画布中的控件选中它，然后输入自然语言调整指令。'}
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
          <div ref={chatEndRef} />
        </div>

        <div className="shrink-0 p-[8px] border-t border-[var(--border)] bg-[var(--bg2)]">
          <div className="flex gap-[6px] mb-[5px] flex-wrap">
            {QUICK_CHIPS.map((chip) => (
              <span
                key={chip.label}
                className="text-[9px] px-[8px] py-[2px] border border-[var(--border2)] rounded-[10px] text-[var(--text3)] cursor-pointer font-mono transition-[0.12s] hover:border-[var(--accent2)] hover:text-[var(--accent)]"
                onClick={() => handleChip(chip.cmd)}
              >
                {chip.label}
              </span>
            ))}
          </div>
          <div className="flex gap-[6px]">
            <input
              className="flex-1 bg-[var(--bg3)] border border-[var(--border)] rounded-[4px] px-[9px] py-[6px] text-[11px] text-[var(--text)] font-[var(--sans)] outline-none focus:border-[var(--accent2)]"
              placeholder={
                selectedNodeId
                  ? `如：${selectedNode?.displayName} 右移200px`
                  : '点击画布选中控件…'
              }
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleSend(); }}
            />
            <button
              className="px-[12px] py-[6px] bg-[rgba(77,184,212,0.1)] border border-[var(--accent)] rounded-[4px] text-[var(--accent)] text-[11px] cursor-pointer font-mono hover:bg-[rgba(77,184,212,0.22)]"
              onClick={handleSend}
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
          {selectedNodeId && (
            <span className="text-[9px] text-[var(--accent)] font-mono">已选中高亮</span>
          )}
        </div>
        <div
          className="flex-1 overflow-auto font-mono text-[9px] leading-[1.6] p-[10px] whitespace-pre min-h-0"
          dangerouslySetInnerHTML={{ __html: canvasJsonHtml }}
        />
      </div>

    </div>
  );
}

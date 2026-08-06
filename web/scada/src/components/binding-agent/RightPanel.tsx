import { useState } from "react";
import { useBindingStore } from "../../stores/bindingStore";
import { uploadCanvas } from "../../api/layout";
import { colorJson } from "../../utils/jsonColor";
import { notify } from "../../utils/notification";
import type { BindingPanel, BindingPanelItem } from "../../types/binding";

function renderItemLabel(item: BindingPanelItem): string {
  const b = item.bind;
  return `${b.param.name} (${b.dev.name}) → ${b.param.dataType}/${b.param.writable ? "可写" : "只读"}`;
}

export default function RightPanel({ blocked }: { blocked: string | null }) {
  const {
    match,
    boundJson,
    buildPreviews,
    buildErrors,
    buildWarnings,
    targetFileName,
    uploadResult,
    uploadError,
    runBuild,
    setTargetFileName,
    setUploadError,
  } = useBindingStore();

  const [building, setBuilding] = useState(false);
  const [uploading, setUploading] = useState(false);

  const hasExisting =
    (match?.panels ?? []).some(
      (p: BindingPanel) => p.existing_panel_list && p.existing_panel_list.length > 0
    ) ?? false;

  const canUpload = boundJson !== null && buildErrors.length === 0;

  const handleBuild = async () => {
    setBuilding(true);
    try {
      await runBuild();
      const st = useBindingStore.getState();
      if (st.buildErrors.length === 0) {
        notify("绑定 JSON 已生成", "s");
      } else {
        notify(`生成受阻：${st.buildErrors.length} 个问题`, "e");
      }
    } finally {
      setBuilding(false);
    }
  };

  const handleUpload = async () => {
    const st = useBindingStore.getState();
    if (!st.boundJson || st.buildErrors.length > 0) return;
    if (!st.targetFileName.trim()) {
      notify("请输入目标文件名", "w");
      return;
    }
    setUploading(true);
    setUploadError(null);
    try {
      const res = await uploadCanvas(st.targetFileName.trim(), st.boundJson, st.pipes);
      st.setUploadResult(res);
      notify(`已上传：${res.file_name}`, "s");
    } catch (err) {
      st.setUploadError(err instanceof Error ? err.message : "上传失败");
      notify("上传失败，可修正后重试", "e");
    } finally {
      setUploading(false);
    }
  };

  const jsonStr = boundJson
    ? JSON.stringify(boundJson, null, 2)
    : "// 生成后显示";

  return (
    <div className="w-[300px] bg-[var(--panel)] border-l border-[var(--border)] flex flex-col shrink-0 overflow-hidden">
      <div className="p-[10px] border-b border-[var(--border)] bg-[var(--bg2)] shrink-0">
        <span className="text-[13px] font-medium text-[var(--text)]">绑定输出</span>
      </div>

      <div className="flex-1 overflow-y-auto p-[14px]">
        {(match?.panels ?? []).length > 0 && (
          <div className="mb-4">
            <div className="text-[10px] text-[var(--text3)] font-mono mb-2 tracking-[1px] uppercase">
              🔄 新旧对比
            </div>
            {buildPreviews.length === 0 && (
              <div className="bg-[var(--bg3)] border border-[var(--border)] rounded-[5px] p-[10px] text-[10px] font-mono text-[var(--text3)] mb-2">
                {hasExisting
                  ? "画布中状态面板已有 panel.list，确认重绑后将整体替换"
                  : "画布中状态面板当前没有 panel.list"}
              </div>
            )}
            {buildPreviews.map((p) => {
              const existing =
                (match?.panels ?? []).find((m: BindingPanel) => m.node_i === p.node_i)
                  ?.existing_panel_list ?? null;
              return (
                <div key={p.node_i} className="bg-[var(--bg3)] border border-[var(--border)] rounded-[5px] p-[10px] mb-2">
                  <div className="text-[11px] font-medium text-[var(--text)] mb-1">
                    状态面板 #{p.instance}
                  </div>
                  <div className="text-[10px] font-mono text-[var(--text3)] mb-1">旧绑定 ({existing?.length ?? 0})</div>
                  {existing && existing.length > 0 ? (
                    <div className="mb-1">
                      {existing.map((it: BindingPanelItem, i: number) => (
                        <div key={i} className="text-[9px] font-mono text-[var(--text3)] line-through truncate">
                          {it.bind ? renderItemLabel(it) : String(it.label)}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-[9px] font-mono text-[var(--text3)] mb-1">—</div>
                  )}
                  <div className="text-[10px] font-mono text-[var(--text3)] mb-1">新绑定 ({p.panel_list.length})</div>
                  {p.panel_list.length > 0 ? (
                    p.panel_list.map((it: BindingPanelItem, i: number) => (
                      <div key={i} className="text-[9px] font-mono text-[var(--success)] truncate">
                        {renderItemLabel(it)}
                      </div>
                    ))
                  ) : (
                    <div className="text-[9px] font-mono text-[var(--text3)]">—</div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {buildErrors.length > 0 && (
          <div className="mb-3">
            <div className="text-[10px] text-[var(--error)] font-mono mb-2 tracking-[1px] uppercase">
              ✗ Schema 状态
            </div>
            <div className="bg-[rgba(224,85,85,0.07)] border border-[var(--error)] rounded-[4px] p-[10px]">
              {buildErrors.map((e, i) => (
                <div key={i} className="text-[10px] font-mono text-[var(--error)] mb-1">
                  ⛔ {e}
                </div>
              ))}
            </div>
          </div>
        )}

        {boundJson && buildErrors.length === 0 && (
          <div className="mb-3">
            <div className="text-[10px] text-[var(--success)] font-mono mb-2 tracking-[1px] uppercase">
              ✓ Schema 状态
            </div>
            <div className="bg-[rgba(62,207,122,0.07)] border border-[var(--success)] rounded-[4px] p-[10px] text-[10px] font-mono text-[var(--success)]">
              绑定结构与 Canvas / Binding Schema 均校验通过
            </div>
          </div>
        )}

        {buildWarnings.length > 0 && (
          <div className="mb-3">
            <div className="text-[10px] text-[var(--warn)] font-mono mb-2 tracking-[1px] uppercase">
              ⚠ 警告
            </div>
            <div className="bg-[rgba(224,159,62,0.07)] border border-[var(--warn)] rounded-[4px] p-[10px]">
              {buildWarnings.map((w, i) => (
                <div key={i} className="text-[10px] font-mono text-[var(--warn)] mb-1">
                  ⚠ {w}
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="mb-3">
          <div className="text-[10px] text-[var(--text3)] font-mono mb-2 tracking-[1px] uppercase">
            🧾 绑定 JSON
          </div>
          <div
            className="bg-[var(--bg4)] border border-[var(--border)] rounded-[4px] p-[8px_10px] font-mono text-[9px] leading-[1.7] text-[var(--text2)] overflow-auto whitespace-pre"
            style={{ maxHeight: "300px" }}
            dangerouslySetInnerHTML={{
              __html: boundJson
                ? colorJson(jsonStr)
                : '<span style="color:var(--text3);font-style:italic">// 生成后显示</span>',
            }}
          />
        </div>

        <div className="mb-3">
          <label className="text-[10px] text-[var(--text3)] font-mono mb-1 block tracking-[0.5px] uppercase">
            目标文件名
          </label>
          <input
            className="w-full bg-[var(--bg3)] border border-[var(--border2)] rounded-[4px] px-[10px] py-[6px] text-[11px] text-[var(--text)] font-mono outline-none focus:border-[var(--accent2)]"
            value={targetFileName}
            onChange={(e) => setTargetFileName(e.target.value)}
            placeholder="xxx_bound.json"
          />
        </div>

        <div className="flex gap-2 mb-3">
          <button
            className="flex-1 px-[12px] py-[7px] rounded-[4px] text-[11px] cursor-pointer border border-[var(--accent)] bg-[rgba(77,184,212,0.1)] text-[var(--accent)] font-[var(--sans)] transition-[0.15s] hover:bg-[rgba(77,184,212,0.2)] disabled:opacity-50"
            onClick={() => void handleBuild()}
            disabled={building || blocked !== null || (boundJson !== null && buildErrors.length === 0)}
          >
            {building ? "生成中..." : "生成绑定 JSON"}
          </button>
          <button
            className="flex-1 px-[12px] py-[7px] rounded-[4px] text-[11px] cursor-pointer border border-[var(--success)] bg-[rgba(62,207,122,0.08)] text-[var(--success)] font-[var(--sans)] transition-[0.15s] hover:bg-[rgba(62,207,122,0.18)] disabled:opacity-50"
            onClick={() => void handleUpload()}
            disabled={uploading || !canUpload || blocked !== null}
          >
            {uploading ? "上传中..." : "上传绑定"}
          </button>
        </div>

        {uploadError && (
          <div className="mb-3 bg-[rgba(224,85,85,0.07)] border border-[var(--error)] rounded-[4px] p-[10px] text-[10px] font-mono text-[var(--error)]">
            ✕ {uploadError}
          </div>
        )}

        {uploadResult && (
          <div className="mb-3 bg-[rgba(62,207,122,0.07)] border border-[var(--success)] rounded-[4px] p-[10px] text-[10px] font-mono text-[var(--success)]">
            <div>✓ 已上传：{uploadResult.file_name}</div>
            {uploadResult.corrections.length > 0 && (
              <div className="text-[var(--text2)] mt-1">
                {uploadResult.corrections.map((c) => (
                  <div key={c.node_i}>
                    #{c.node_i} {c.display_name}: {c.before.width}x{c.before.height} → {c.after.width}x{c.after.height}
                  </div>
                ))}
              </div>
            )}
            {uploadResult.warnings.length > 0 && (
              <div className="text-[var(--warn)] mt-1">
                {uploadResult.warnings.map((w, i) => (
                  <div key={i}>⚠ {w}</div>
                ))}
              </div>
            )}
          </div>
        )}

        {boundJson === null && buildErrors.length > 0 && (
          <div className="text-[10px] font-mono text-[var(--text3)]">
            存在阻断问题，请回到左侧检查冲突报告后重新生成。
          </div>
        )}
      </div>
    </div>
  );
}

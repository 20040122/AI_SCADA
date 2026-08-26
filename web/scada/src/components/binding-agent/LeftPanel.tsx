import { useRef, useState } from "react";
import { useBindingStore } from "../../stores/bindingStore";
import { previewCsv } from "../../api/binding";
import { notify } from "../../utils/notification";

function sourceLabel(type: string | null): string {
  if (type === "refine") return "微调稿";
  if (type === "layout") return "布局稿";
  return "无";
}

export default function LeftPanel({ blocked }: { blocked: string | null }) {
  const {
    sourceType,
    fileName,
    canvas,
    csvFile,
    preview,
    requests,
    buildErrors,
    setCsvFile,
    setPreview,
    runMatch,
    isLoading,
  } = useBindingStore();

  const fileRef = useRef<HTMLInputElement>(null);
  const [parsing, setParsing] = useState(false);

  const hasPanel =
    canvas !== null &&
    (canvas.d || []).some(
      (n) =>
        n.c === "ht.Node" &&
        /^状态面板\d*$/.test(String(n.p?.displayName ?? ""))
    );

  const handlePickFile = async (file: File | null) => {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".csv")) {
      notify("仅支持 .csv 文件", "e");
      return;
    }
    setCsvFile(file);
    setParsing(true);
    try {
      const res = await previewCsv(file);
      setPreview(res);
      notify(`已解析 CSV：${res.total_rows} 行`, "s");
    } catch (err) {
      notify(err instanceof Error ? err.message : "CSV 解析失败", "e");
    } finally {
      setParsing(false);
    }
  };

  const handleMatch = () => {
    if (!canvas) {
      notify("当前没有可用画布", "w");
      return;
    }
    if (requests.length === 0) {
      notify("请先导入并确认 CSV", "w");
      return;
    }
    if (blocked) {
      notify("存在阻断条件，无法匹配", "e");
      return;
    }
    void runMatch();
  };

  const showRows = preview ? preview.requests.slice(0, 20) : [];

  return (
    <div className="w-[300px] bg-[var(--panel)] border-r border-[var(--border)] flex flex-col shrink-0 overflow-hidden">
      <div className="p-[10px] border-b border-[var(--border)] bg-[var(--bg2)] shrink-0">
        <span className="text-[13px] font-medium text-[var(--text)]">绑点 Agent</span>
      </div>

      <div className="flex-1 overflow-y-auto p-[14px]">
        {blocked === "refine_pending" && (
          <div className="mb-3 bg-[rgba(224,85,85,0.08)] border border-[var(--error)] rounded-[4px] p-[10px] text-[11px] text-[var(--error)] font-mono">
            微调存在未确认的 Patch，请先在「微调Agent」中接受或撤销后再进行绑点。
          </div>
        )}

        <div className="text-[10px] text-[var(--text3)] font-mono mb-2 tracking-[1px] uppercase">
          📥 数据来源
        </div>
        <div className="bg-[var(--bg3)] border border-[var(--border)] rounded-[5px] p-[10px] mb-4">
          <div className="text-[11px] text-[var(--text2)] font-mono flex justify-between mb-1">
            <span>来源</span>
            <span className="text-[var(--accent)]">{sourceLabel(sourceType)}</span>
          </div>
          <div className="text-[11px] text-[var(--text2)] font-mono flex justify-between mb-1">
            <span>文件</span>
            <span className="text-[var(--text)] truncate max-w-[160px]">{fileName || "—"}</span>
          </div>
          <div className="text-[11px] text-[var(--text2)] font-mono flex justify-between">
            <span>状态面板</span>
            <span className={hasPanel ? "text-[var(--success)]" : "text-[var(--error)]"}>
              {hasPanel ? "已找到" : "未找到"}
            </span>
          </div>
        </div>

        <div className="text-[10px] text-[var(--text3)] font-mono mb-2 tracking-[1px] uppercase">
          📄 CSV 上传
        </div>
        <div className="mb-3">
          <input
            ref={fileRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={(e) => void handlePickFile(e.target.files?.[0] ?? null)}
          />
          <button
            className="w-full px-[16px] py-[7px] rounded-[4px] text-[11px] cursor-pointer border border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)] font-[var(--sans)] transition-[0.15s] hover:bg-[var(--accent-soft-hover)] disabled:opacity-50"
            onClick={() => fileRef.current?.click()}
            disabled={parsing || isLoading}
          >
            {parsing ? "解析中..." : csvFile ? `已选择：${csvFile.name}` : "选择 CSV 文件"}
          </button>
          {preview && (
            <div className="mt-2 text-[10px] font-mono text-[var(--text2)] bg-[var(--bg3)] border border-[var(--border)] rounded-[4px] p-[8px]">
              <div>编码：{preview.encoding}</div>
              <div>总行数：{preview.total_rows}</div>
              <div>表头：displayName , propertyName</div>
              {preview.total_rows > 20 && (
                <div className="text-[var(--text3)]">仅展示前 20 行</div>
              )}
            </div>
          )}
          {showRows.length > 0 && (
            <div className="mt-2 max-h-[220px] overflow-auto bg-[var(--bg4)] border border-[var(--border)] rounded-[4px]">
              <table className="w-full text-[9px] font-mono">
                <thead>
                  <tr className="text-[var(--text3)]">
                    <th className="text-left px-[6px] py-[4px] border-b border-[var(--border)]">行</th>
                    <th className="text-left px-[6px] py-[4px] border-b border-[var(--border)]">控件</th>
                    <th className="text-left px-[6px] py-[4px] border-b border-[var(--border)]">属性</th>
                  </tr>
                </thead>
                <tbody>
                  {showRows.map((r) => (
                    <tr key={r.row_number} className="text-[var(--text2)]">
                      <td className="px-[6px] py-[3px] text-[var(--text3)]">{r.row_number}</td>
                      <td className="px-[6px] py-[3px]">{r.displayName}</td>
                      <td className="px-[6px] py-[3px]">{r.propertyName}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <button
          className="w-full px-[16px] py-[7px] rounded-[4px] text-[11px] cursor-pointer border border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)] font-[var(--sans)] transition-[0.15s] hover:bg-[var(--accent-soft-hover)] disabled:opacity-50 mb-4"
          onClick={handleMatch}
          disabled={isLoading || blocked !== null || requests.length === 0}
        >
          {isLoading ? "匹配中..." : "⚡ 执行匹配"}
        </button>

        {buildErrors.length > 0 && (
          <>
            <div className="text-[10px] text-[var(--text3)] font-mono mb-2 tracking-[1px] uppercase">
              ⚠ 冲突报告
            </div>
            <div className="bg-[var(--bg3)] border border-[var(--border)] rounded-[5px] p-[10px]">
              {buildErrors.map((e, i) => (
                <div key={`e${i}`} className="text-[10px] font-mono text-[var(--error)] mb-1">
                  ⛔ {e}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

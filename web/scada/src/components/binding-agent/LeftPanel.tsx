import { useRef, useState } from "react";
import { useBindingStore } from "../../stores/bindingStore";
import { normalizeCsv, previewCsv } from "../../api/binding";
import { notify } from "../../utils/notification";
import type { BindingColumnMapping } from "../../api/binding";
import type { BindingProperty } from "../../types/binding";

const BINDING_FIELDS = [
  { field: "projectId", label: "项目ID", required: true },
  { field: "projectName", label: "项目名称", required: true },
  { field: "deviceId", label: "设备ID", required: true },
  { field: "deviceName", label: "设备名称", required: true },
  { field: "propertyId", label: "属性ID", required: true },
  { field: "propertyName", label: "属性名称", required: true },
  { field: "dataType", label: "数据类型", required: true },
  { field: "writable", label: "可写", required: true },
  { field: "unit", label: "单位", required: false },
  { field: "dataTypeDesc", label: "类型描述", required: false },
];

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
    normalized,
    normalizeErrors,
    normalizeBlocked,
    normalizeBlocking,
    buildErrors,
    buildWarnings,
    setCsvFile,
    setPreview,
    setColumnMapping,
    applyNormalize,
    runMatch,
    isLoading,
  } = useBindingStore();

  const fileRef = useRef<HTMLInputElement>(null);
  const [parsing, setParsing] = useState(false);
  const [mapping, setMapping] = useState<Record<string, string | number | null>>({});
  const [confirming, setConfirming] = useState(false);

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
      const next: Record<string, string | number | null> = {};
      for (const s of res.mapping.suggestions) {
        next[s.field] = s.column;
      }
      setMapping(next);
      notify(`已解析 CSV：${res.total_rows} 行`, "s");
    } catch (err) {
      setCsvFile(file);
      notify(err instanceof Error ? err.message : "CSV 解析失败", "e");
    } finally {
      setParsing(false);
    }
  };

  const buildMappingList = (): BindingColumnMapping[] => {
    const list: BindingColumnMapping[] = [];
    for (const f of BINDING_FIELDS) {
      const col = mapping[f.field];
      if (col !== null && col !== undefined) {
        list.push({ field: f.field, column: col });
      }
    }
    return list;
  };

  const handleConfirmMapping = async () => {
    if (!csvFile) return;
    const list = buildMappingList();
    const requiredFields = BINDING_FIELDS.filter((f) => f.required).map((f) => f.field);
    const missing = requiredFields.filter((f) => !list.some((m) => m.field === f));
    if (missing.length > 0) {
      notify(`必填字段未映射：${missing.join(", ")}`, "w");
      return;
    }
    setConfirming(true);
    setColumnMapping(list);
    try {
      const res = await normalizeCsv(csvFile, list);
      applyNormalize(res);
      if (res.blocked) {
        notify("CSV 校验阻断，请先修正后重试", "e");
      } else if (res.errors.length > 0) {
        notify(`规范完成，${res.errors.length} 行有误`, "w");
      } else {
        notify(`已规范 ${res.properties.length} 条属性`, "s");
      }
    } catch (err) {
      notify(err instanceof Error ? err.message : "CSV 规范化失败", "e");
    } finally {
      setConfirming(false);
    }
  };

  const handleMatch = () => {
    if (!canvas) {
      notify("当前没有可用画布", "w");
      return;
    }
    if (normalized.length === 0) {
      notify("请先导入并规范 CSV", "w");
      return;
    }
    if (blocked) {
      notify("存在阻断条件，无法匹配", "e");
      return;
    }
    void runMatch();
  };

  const missingCount =
    preview?.mapping.missing.length ?? 0;

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
            className="w-full px-[16px] py-[7px] rounded-[4px] text-[11px] cursor-pointer border border-[var(--accent)] bg-[rgba(77,184,212,0.1)] text-[var(--accent)] font-[var(--sans)] transition-[0.15s] hover:bg-[rgba(77,184,212,0.2)] disabled:opacity-50"
            onClick={() => fileRef.current?.click()}
            disabled={parsing || isLoading}
          >
            {parsing ? "解析中..." : csvFile ? `已选择：${csvFile.name}` : "选择 CSV 文件"}
          </button>
          {preview && (
            <div className="mt-2 text-[10px] font-mono text-[var(--text2)] bg-[var(--bg3)] border border-[var(--border)] rounded-[4px] p-[8px]">
              <div>编码：{preview.encoding}</div>
              <div>总行数：{preview.total_rows}</div>
              <div>表头：{preview.headers.join(" , ")}</div>
              {missingCount > 0 && (
                <div className="text-[var(--warn)]">
                  未匹配字段：{preview.mapping.missing.join(", ")}
                </div>
              )}
              {preview.mapping.ambiguities.length > 0 && (
                <div className="text-[var(--warn)] mt-1">
                  {preview.mapping.ambiguities.map((a, i) => (
                    <div key={i}>
                      ⚠ 列 "{a.header}" 命中 {a.matched_fields.join(", ")}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {preview && (
          <>
            <div className="text-[10px] text-[var(--text3)] font-mono mb-2 tracking-[1px] uppercase">
              🗺 列映射
            </div>
            <div className="bg-[var(--bg3)] border border-[var(--border)] rounded-[5px] p-[10px] mb-3">
              {BINDING_FIELDS.map((f) => (
                <div key={f.field} className="flex items-center gap-2 mb-1.5 last:mb-0">
                  <span
                    className={`text-[10px] font-mono w-[70px] shrink-0 ${
                      f.required ? "text-[var(--text2)]" : "text-[var(--text3)]"
                    }`}
                  >
                    {f.label}{f.required ? " *" : ""}
                  </span>
                  <select
                    className="flex-1 bg-[var(--bg4)] border border-[var(--border2)] rounded-[3px] px-[6px] py-[4px] text-[10px] text-[var(--text)] font-mono outline-none focus:border-[var(--accent2)]"
                    value={mapping[f.field] ?? ""}
                    onChange={(e) =>
                      setMapping((m) => ({
                        ...m,
                        [f.field]: e.target.value === "" ? null : Number(e.target.value),
                      }))
                    }
                  >
                    <option value="">未映射</option>
                    {preview.headers.map((h, i) => (
                      <option key={i} value={i}>
                        {i}: {h}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
              <button
                className="w-full mt-2 px-[16px] py-[6px] rounded-[4px] text-[10px] cursor-pointer border border-[var(--border2)] bg-[var(--bg2)] text-[var(--text2)] font-[var(--sans)] transition-[0.15s] hover:border-[var(--accent2)] hover:text-[var(--accent)] disabled:opacity-50"
                onClick={() => void handleConfirmMapping()}
                disabled={confirming || !csvFile || isLoading}
              >
                {confirming ? "规范中..." : "确认映射并规范化"}
              </button>
            </div>
          </>
        )}

        {normalized.length > 0 && (
          <div className="mb-3">
            <div className="text-[10px] text-[var(--text3)] font-mono mb-2 tracking-[1px] uppercase">
              🧪 规范结果
            </div>
            <div className="bg-[var(--bg3)] border border-[var(--border)] rounded-[5px] p-[10px] mb-2">
              <div className="text-[11px] font-mono text-[var(--success)]">
                ✓ 规范属性 {normalized.length} 条
              </div>
              <div className="mt-1 max-h-[120px] overflow-auto text-[10px] font-mono text-[var(--text3)]">
                {normalized.slice(0, 20).map((p: BindingProperty, i: number) => (
                  <div key={i} className="truncate">
                    {p.projectName}.{p.deviceName}.{p.propertyName} ({p.dataType})
                  </div>
                ))}
              </div>
            </div>
            {normalizeErrors.length > 0 && (
              <div className="bg-[rgba(224,85,85,0.07)] border border-[var(--error)] rounded-[4px] p-[10px] mb-2 text-[10px] font-mono text-[var(--error)]">
                {normalizeErrors.map((e, i) => (
                  <div key={i}>✕ {e}</div>
                ))}
              </div>
            )}
            {normalizeBlocked && normalizeBlocking.length > 0 && (
              <div className="bg-[rgba(224,85,85,0.07)] border border-[var(--error)] rounded-[4px] p-[10px] mb-2 text-[10px] font-mono text-[var(--error)]">
                {normalizeBlocking.map((e, i) => (
                  <div key={i}>⛔ {e}</div>
                ))}
              </div>
            )}
          </div>
        )}

        <button
          className="w-full px-[16px] py-[7px] rounded-[4px] text-[11px] cursor-pointer border border-[var(--accent)] bg-[rgba(77,184,212,0.1)] text-[var(--accent)] font-[var(--sans)] transition-[0.15s] hover:bg-[rgba(77,184,212,0.2)] disabled:opacity-50 mb-4"
          onClick={handleMatch}
          disabled={isLoading || blocked !== null || normalized.length === 0}
        >
          {isLoading ? "匹配中..." : "⚡ 执行匹配"}
        </button>

        {(buildErrors.length > 0 || buildWarnings.length > 0) && (
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
              {buildWarnings.map((w, i) => (
                <div key={`w${i}`} className="text-[10px] font-mono text-[var(--warn)] mb-1">
                  ⚠ {w}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

import { useMemo, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { useBindingStore } from "../../stores/bindingStore";
import type { BindingCandidate, BindingExpectation, BindingMatchItem } from "../../types/binding";

function confidenceBadge(confidence: string): { cls: string; label: string } {
  if (confidence === "high") return { cls: "text-[var(--success)] border-[var(--success)]", label: "高" };
  if (confidence === "medium") return { cls: "text-[var(--warn)] border-[var(--warn)]", label: "中" };
  if (confidence === "low") return { cls: "text-[var(--text3)] border-[var(--text3)]", label: "低" };
  return { cls: "text-[var(--text3)] border-[var(--text3)]", label: "无" };
}

function expectationOf(
  expectations: BindingExpectation[],
  id: string
): BindingExpectation | undefined {
  return expectations.find((e) => e.id === id);
}

export default function CenterPanel({ blocked }: { blocked: string | null }) {
  const {
    canvas,
    match,
    items,
    selectCandidate,
    confirmItem,
    confirmAllHigh,
  } = useBindingStore(
    useShallow((s) => ({
      canvas: s.canvas,
      match: s.match,
      items: s.items,
      selectCandidate: s.selectCandidate,
      confirmItem: s.confirmItem,
      confirmAllHigh: s.confirmAllHigh,
    }))
  );

  const selectedKeyOf = (panelNodeI: number, expectationId: string) =>
    items.find(
      (it) => it.panel_node_i === panelNodeI && it.expectation_id === expectationId
    )?.selectedKey ?? null;

  const [search, setSearch] = useState("");
  const [evidenceKey, setEvidenceKey] = useState<string | null>(null);

  const panels = match?.panels ?? [];
  const expectations = match?.expectations ?? [];

  const grouped = useMemo(() => {
    const map = new Map<number, BindingMatchItem[]>();
    for (const item of items) {
      const list = map.get(item.panel_node_i) ?? [];
      list.push(item);
      map.set(item.panel_node_i, list);
    }
    return map;
  }, [items]);

  const confirmedCount = items.filter((it) => it.confirmed).length;
  const highUnconfirmed = items.filter((it) => !it.confirmed && it.confidence === "high").length;

  const filterCandidates = (candidates: BindingCandidate[]): BindingCandidate[] => {
    const q = search.trim().toLowerCase();
    if (!q) return candidates;
    return candidates.filter((c) =>
      [c.propertyName, c.deviceName, c.projectName, c.propertyId, c.deviceId]
        .join(" ")
        .toLowerCase()
        .includes(q)
    );
  };

  const renderCandidateRow = (item: BindingMatchItem, cand: BindingCandidate) => {
    const selectedKey = selectedKeyOf(item.panel_node_i, item.expectation_id);
    const isSelected = selectedKey === cand.key;
    const isSuggested = item.suggested === cand.key;
    const badge = confidenceBadge(cand.confidence);
    return (
      <div
        key={cand.key}
        className={`border rounded-[4px] p-[6px_8px] mb-1 ${
          isSelected
            ? "border-[var(--accent2)] bg-[rgba(77,184,212,0.1)]"
            : "border-[var(--border)] bg-[var(--bg2)]"
        }`}
      >
        <div className="flex items-center gap-2">
          <span className="flex-1 text-[11px] text-[var(--text)] truncate">
            {cand.propertyName}
            <span className="text-[var(--text3)]"> · {cand.deviceName}</span>
          </span>
          {isSuggested && (
            <span className="text-[9px] font-mono text-[var(--accent)]">建议</span>
          )}
          <span
            className={`text-[9px] font-mono border px-[5px] py-[1px] rounded-[3px] ${badge.cls}`}
          >
            {badge.label}
          </span>
          <span className="text-[9px] font-mono text-[var(--text3)]">
            {cand.score.toFixed(3)}
          </span>
          <button
            type="button"
            className="text-[9px] font-mono text-[var(--text3)] cursor-pointer hover:text-[var(--accent)]"
            onClick={() =>
              setEvidenceKey(evidenceKey === `${item.panel_node_i}-${item.expectation_id}-${cand.key}` ? null : `${item.panel_node_i}-${item.expectation_id}-${cand.key}`)
            }
          >
            证据
          </button>
          <button
            type="button"
            className="px-[8px] py-[2px] rounded-[3px] text-[9px] font-mono cursor-pointer border border-[var(--border2)] text-[var(--text2)] hover:border-[var(--accent2)] hover:text-[var(--accent)] disabled:opacity-40 disabled:cursor-not-allowed"
            disabled={item.confirmed && isSelected}
            onClick={() => selectCandidate(item.panel_node_i, item.expectation_id, cand.key)}
          >
            {item.confirmed && isSelected ? "已选" : "选择"}
          </button>
        </div>
        {evidenceKey === `${item.panel_node_i}-${item.expectation_id}-${cand.key}` && (
          <div className="mt-1 text-[9px] font-mono text-[var(--text3)] leading-[1.5]">
            <div>
              dev 相似 {cand.device_name_similarity.toFixed(3)} · prop 相似{" "}
              {cand.property_name_similarity.toFixed(3)} · lead {cand.lead.toFixed(3)}
            </div>
            {cand.evidence.map((ev, i) => (
              <div key={i}>· {ev}</div>
            ))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="flex-1 bg-[var(--bg)] flex flex-col overflow-hidden min-w-0">
      <div className="p-[10px] border-b border-[var(--border)] bg-[var(--bg2)] shrink-0 flex items-center gap-3">
        <span className="text-[13px] font-medium text-[var(--text)]">匹配评审</span>
        <div className="flex-1" />
        <input
          className="w-[200px] bg-[var(--bg3)] border border-[var(--border)] rounded-[4px] px-[9px] py-[5px] text-[11px] text-[var(--text)] font-[var(--sans)] outline-none focus:border-[var(--accent2)]"
          placeholder="搜索候选属性…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span className="text-[10px] font-mono text-[var(--text3)]">
          {items.length > 0 && `${confirmedCount}/${items.length} 已确认`}
        </span>
        <button
          className="px-[12px] py-[5px] rounded-[4px] text-[10px] cursor-pointer border border-[var(--success)] bg-[rgba(62,207,122,0.08)] text-[var(--success)] font-[var(--sans)] transition-[0.15s] hover:bg-[rgba(62,207,122,0.18)] disabled:opacity-50"
          onClick={() => confirmAllHigh()}
          disabled={highUnconfirmed === 0 || blocked !== null}
        >
          确认全部高置信 ({highUnconfirmed})
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-[14px]">
        {!canvas && (
          <div className="text-[12px] text-[var(--text3)] font-mono text-center py-16">
            暂无画布数据，请先在「布局Agent」生成或「微调Agent」确认草稿。
          </div>
        )}

        {canvas && !match && (
          <div className="text-[12px] text-[var(--text3)] font-mono text-center py-16">
            导入 CSV 并确认列映射后，点击左侧「执行匹配」。
          </div>
        )}

        {blocked === "refine_pending" && (
          <div className="text-[12px] text-[var(--warn)] font-mono text-center py-16">
            ⛔ 微调存在未确认 Patch，绑点已阻断。
          </div>
        )}

        {match && panels.length === 0 && (
          <div className="bg-[rgba(224,85,85,0.07)] border border-[var(--error)] rounded-[4px] p-[12px] mb-4 text-[11px] text-[var(--error)] font-mono">
            画布中未找到「状态面板」节点，无法绑点。
          </div>
        )}

        {expectations.length > 0 && (
          <div className="mb-4">
            <div className="text-[10px] text-[var(--text3)] font-mono mb-2 tracking-[1px] uppercase">
              📋 JSONL 期望
            </div>
            <div className="bg-[var(--bg3)] border border-[var(--border)] rounded-[5px] p-[10px]">
              {expectations.map((e) => (
                <div key={e.id} className="text-[10px] font-mono text-[var(--text2)] mb-1 last:mb-0">
                  <span className="text-[var(--accent)]">{e.property}</span>
                  <span className="text-[var(--text3)]"> ({e.deviceName})</span>
                  <span className="text-[var(--text3)]"> dataType={e.dataType}</span>
                  <span className="text-[var(--text3)]"> writable={String(e.writable)}</span>
                  {e.required && (
                    <span className="text-[var(--error)]"> 必绑</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {panels.map((panel) => {
          const list = grouped.get(panel.node_i) ?? [];
          return (
            <div key={panel.node_i} className="mb-4">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[12px] font-medium text-[var(--text)]">
                  状态面板 #{panel.instance}
                </span>
                <span className="text-[9px] font-mono text-[var(--text3)]">
                  node_i={panel.node_i} · {list.filter((it) => it.confirmed).length}/{list.length} 已确认
                </span>
              </div>
              <div className="bg-[var(--panel)] border border-[var(--border)] rounded-[5px] p-[10px]">
                {list.length === 0 && (
                  <div className="text-[10px] font-mono text-[var(--text3)]">无匹配项</div>
                )}
                {list.map((item) => {
                  const selectedKey = selectedKeyOf(item.panel_node_i, item.expectation_id);
                  const selected = item.candidates.find((c) => c.key === selectedKey) ?? null;
                  const filtered = filterCandidates(item.candidates);
                  const badge = confidenceBadge(item.confidence);
                  const exp = expectationOf(expectations, item.expectation_id);
                  return (
                    <div
                      key={item.expectation_id}
                      className={`border rounded-[4px] p-[8px_10px] mb-2 last:mb-0 ${
                        item.confirmed
                          ? "border-[rgba(62,207,122,0.5)] bg-[rgba(62,207,122,0.05)]"
                          : "border-[var(--border)] bg-[var(--bg2)]"
                      }`}
                    >
                      <div className="flex items-center gap-2 mb-2">
                        <span className="flex-1 text-[12px] text-[var(--text)] truncate">
                          {item.expectation_property}
                          {item.expectation_required && (
                            <span className="ml-2 text-[9px] font-mono text-[var(--error)] border border-[var(--error)] rounded-[3px] px-[5px] py-[1px]">
                              必绑
                            </span>
                          )}
                        </span>
                        {exp && (
                          <span className="text-[9px] font-mono text-[var(--text3)]">
                            期望 {exp.dataType}/{exp.writable ? "可写" : "只读"}
                          </span>
                        )}
                        <span
                          className={`text-[9px] font-mono border px-[5px] py-[1px] rounded-[3px] ${badge.cls}`}
                        >
                          {item.confidence === "high"
                            ? "高置信"
                            : item.confidence === "medium"
                              ? "中置信"
                              : item.confidence === "low"
                                ? "低置信"
                                : "未建议"}
                        </span>
                        <button
                          type="button"
                          className="px-[9px] py-[3px] rounded-[3px] text-[9px] font-mono cursor-pointer border border-[var(--success)] text-[var(--success)] bg-[rgba(62,207,122,0.06)] transition-[0.12s] hover:bg-[rgba(62,207,122,0.18)] disabled:opacity-40 disabled:cursor-not-allowed"
                          disabled={item.confirmed || !selected || blocked !== null}
                          onClick={() => confirmItem(item.panel_node_i, item.expectation_id)}
                        >
                          {item.confirmed ? "✓ 已确认" : "确认绑定"}
                        </button>
                      </div>
                      {filtered.length === 0 && (
                        <div className="text-[10px] font-mono text-[var(--text3)]">
                          没有匹配候选（类型或读写不兼容的候选不可选）
                        </div>
                      )}
                      {filtered.map((cand) => renderCandidateRow(item, cand))}
                      {search.trim() !== "" && filtered.length < item.candidates.length && (
                        <div className="text-[9px] font-mono text-[var(--text3)]">
                          过滤后显示 {filtered.length}/{item.candidates.length} 个候选
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

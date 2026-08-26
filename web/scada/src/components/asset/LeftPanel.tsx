import { useAssetStore } from "../../stores/assetStore";
import PipelineSteps from "./PipelineSteps";
import { useAssetSearch } from "../../hooks/useAssetSearch";
import { notify } from "../../utils/notification";

export default function LeftPanel() {
  const { query, setQuery, isLoading } = useAssetStore();
  const { search } = useAssetSearch();

  return (
    <div className="w-[320px] bg-[var(--panel)] border-r border-[var(--border)] flex flex-col shrink-0 overflow-hidden">
      <div className="p-[10px] border-b border-[var(--border)] bg-[var(--bg2)] flex items-center gap-2 shrink-0">
        <span className="text-[13px] font-medium text-[var(--text)]">控件 Agent</span>
      </div>

      <div className="flex-1 overflow-y-auto p-[14px]">
        <div className="text-[10px] text-[var(--text3)] font-mono mb-2 tracking-[1px] uppercase">
          🔍 检索、生成
        </div>

        <div className="mb-3">
          <label className="text-[10px] text-[var(--text3)] font-mono mb-1 block tracking-[0.5px] uppercase">
            Query 输入
          </label>
          <input
            className="w-full bg-[var(--bg3)] border border-[var(--border2)] rounded-[4px] px-[10px] py-[7px] text-[12px] text-[var(--text)] font-[var(--sans)] outline-none focus:border-[var(--accent2)] focus:shadow-[0_0_0_2px_var(--focus-ring)]"
            placeholder="如：水泵、运行状态指示灯"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()}
          />
        </div>

        <div className="flex gap-2 mb-3">
          <button
            className="flex-1 px-[16px] py-[7px] rounded-[4px] text-[11px] cursor-pointer border border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)] font-[var(--sans)] transition-[0.15s] hover:bg-[var(--accent-soft-hover)] disabled:opacity-50"
            onClick={search}
            disabled={isLoading}
          >
            🔍 {isLoading ? "检索中..." : "检索/生成"}
          </button>
          <button
            className="px-[16px] py-[7px] rounded-[4px] text-[11px] cursor-pointer border border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)] font-[var(--sans)] transition-[0.15s] hover:bg-[var(--accent-soft-hover)]"
            onClick={() => {
              setQuery("");
              notify("已清空输入", "s");
            }}
          >
            ✖ 清空
          </button>
        </div>

        <div className="text-[10px] text-[var(--text3)] font-mono mb-2 tracking-[1px] uppercase">
          Agent 流程
        </div>
        <PipelineSteps />
      </div>
    </div>
  );
}

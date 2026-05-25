import { useAssetStore } from "../../stores/assetStore";

export default function StatusBar() {
  const { keywordResults, materialLib, isLoading, error } = useAssetStore();

  const status = error
    ? `错误: ${error}`
    : isLoading
      ? "检索中..."
      : "就绪";

  const statusColor = error
    ? "var(--error)"
    : isLoading
      ? "var(--accent)"
      : "var(--success)";

  return (
    <div className="h-[20px] bg-[var(--bg4)] border-t border-[var(--border)] flex items-center px-[10px] gap-[14px] shrink-0">
      <div className="text-[9px] font-mono flex items-center gap-[3px]" style={{ color: "var(--text3)" }}>
        <div
          className="w-[5px] h-[5px] rounded-full"
          style={{ background: statusColor }}
        />
        {status}
      </div>
      <div className="text-[9px] font-mono" style={{ color: "var(--text3)" }}>
        检索结果: <span style={{ color: "var(--accent)" }}>{keywordResults.reduce((s, kr) => s + kr.candidates.length, 0)}</span>
      </div>
      <span className="ml-auto text-[9px] font-mono" style={{ color: "var(--text3)" }}>
        scada/asset-agent
      </span>
    </div>
  );
}
import type { MaterialItem } from "../../types/asset";

export default function MetadataView({ asset }: { asset: MaterialItem | null }) {
  if (!asset) {
    return (
      <div className="p-3">
        <div className="text-[11px] text-[var(--text3)] text-center py-8">点击素材查看元数据</div>
      </div>
    );
  }

  return (
    <div className="p-3 flex flex-col gap-2">
      <div className="text-[10px] text-[var(--text2)] font-mono mb-1 flex items-center gap-1">
        <span className="text-[var(--accent)]">●</span>
        {asset.displayName}
      </div>

      <div className="text-[10px] font-mono flex flex-col gap-[3px]">
        <div>
          <span className="text-[var(--text3)]">displayName: </span>
          <span className="text-[var(--text)]">{asset.displayName}</span>
        </div>
        <div>
          <span className="text-[var(--text3)]">image: </span>
          <span className="text-[var(--json-string)]">{asset.image}</span>
        </div>
        <div>
          <span className="text-[var(--text3)]">width: </span>
          <span className="text-[var(--json-number)]">{asset.width}</span>
        </div>
        <div>
          <span className="text-[var(--text3)]">height: </span>
          <span className="text-[var(--json-number)]">{asset.height}</span>
        </div>
        <div>
          <span className="text-[var(--text3)]">source: </span>
          <span className="text-[var(--text2)]">{asset.source}</span>
        </div>
      </div>

      <div className="mt-2 pt-2 border-t border-[var(--border)]">
        <div className="text-[10px] text-[var(--text3)] font-mono mb-1 tracking-[0.5px]">
          JSON 结构
        </div>
        <div className="bg-[var(--bg4)] border border-[var(--border)] rounded-[4px] p-2 font-mono text-[9px] leading-[1.7] text-[var(--text2)] max-h-[200px] overflow-auto">
          {`{
  "displayName": "${asset.displayName}",
  "image": "${asset.image}",
  "width": ${asset.width},
  "height": ${asset.height},
  "source": "${asset.source}"
}`}
        </div>
      </div>
    </div>
  );
}

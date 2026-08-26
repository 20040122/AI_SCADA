import { useState } from "react";
import type { ControlCandidate, ControlItem, MaterialItem } from "../../types/asset";
import { toPngUrl } from "../../utils/assetPreview";

const TYPE_COLORS: Record<string, string> = {
  泵: "#4db8d4",
  阀: "#3ecf7a",
  传: "#e8a840",
  显: "#5bb8e8",
  报: "#e05555",
  风: "#3ecfb8",
  电: "#ffcc32",
  机: "#b0b0b0",
  罐: "#a080d0",
};

function getInitialColor(name: string): string {
  for (const [key, color] of Object.entries(TYPE_COLORS)) {
    if (name.includes(key)) return color;
  }
  return "#4db8d4";
}

function SimBadge({ similarity, source }: { similarity: number; source: string }) {
  if (source === "sqlite") {
    return (
      <span className="text-[8px] px-[3px] py-[1px] rounded-[2px] bg-[rgba(232,168,64,0.15)] text-[var(--warn)] font-mono">
        sqlite
      </span>
    );
  }
  const isHigh = similarity >= 0.55;
  return (
    <span
      className={`text-[8px] px-[3px] py-[1px] rounded-[2px] font-mono ${
        isHigh
          ? "bg-[rgba(62,207,122,0.13)] text-[var(--success)]"
          : "bg-[rgba(232,168,64,0.15)] text-[var(--warn)]"
      }`}
    >
      {similarity.toFixed(2)}
    </span>
  );
}

export default function AssetCard({
  item,
  onClick,
  isSearchResult = false,
  candidate,
}: {
  item: ControlItem | MaterialItem;
  onClick?: () => void;
  isSearchResult?: boolean;
  candidate?: ControlCandidate;
}) {
  const [imgError, setImgError] = useState(false);
  const initial = item.displayName.charAt(0);
  const color = getInitialColor(item.displayName);
  const previewUrl = toPngUrl(item.image);

  return (
    <div
      className={`
        bg-[var(--bg3)] border border-[var(--border)] rounded-[4px] p-[10px] text-center
        cursor-pointer transition-all duration-150 relative h-[128px]
        hover:border-[var(--accent2)] hover:-translate-y-[1px]
        ${isSearchResult ? "border-dashed border-[var(--teal)]" : ""}
      `}
      onClick={onClick}
    >
      <div className="h-[72px] flex items-center justify-center mb-1 overflow-hidden">
        {!imgError && previewUrl ? (
          <img
            src={previewUrl}
            alt={item.displayName}
            className="max-w-full max-h-full object-contain"
            onError={() => setImgError(true)}
          />
        ) : (
          <div
            className="w-10 h-10 rounded-full flex items-center justify-center text-lg font-semibold shrink-0"
            style={{ background: `${color}22`, color, border: `1px solid ${color}44` }}
          >
            {initial}
          </div>
        )}
      </div>
      <div
        className="text-[9px] text-[var(--text2)] font-mono truncate"
        title={item.displayName}
      >
        {item.displayName}
      </div>
      <div className="flex items-center justify-center gap-1 mt-[2px]">
        <span className="text-[8px] text-[var(--text3)] font-mono">
          {item.width}×{item.height}
        </span>
        {candidate && <SimBadge similarity={candidate.similarity} source={candidate.source} />}
      </div>
    </div>
  );
}

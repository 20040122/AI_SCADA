import { useAssetStore } from "../../stores/assetStore";
import MetadataView from "./MetadataView";

export default function RightPanel() {
  const { selectedAsset } = useAssetStore();

  return (
    <div className="w-[280px] bg-[var(--panel)] border-l border-[var(--border)] flex flex-col shrink-0 overflow-hidden">
      <div className="p-[10px] border-b border-[var(--border)] bg-[var(--bg2)] shrink-0">
        <span className="text-[13px] font-medium text-[var(--text)]">控件元数据</span>
      </div>
      <div className="flex-1 overflow-y-auto">
        <MetadataView asset={selectedAsset} />
      </div>
    </div>
  );
}
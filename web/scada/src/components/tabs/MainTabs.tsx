import { useAssetStore } from "../../stores/assetStore";

interface TabDef {
  id: string;
  icon: string;
  label: string;
  badge?: boolean;
}

const TABS: TabDef[] = [
  { id: "asset", icon: "🎨", label: "控件 Agent", badge: true },
  { id: "layout", icon: "⚡", label: "布局 Agent ", badge: true },
  { id: "refine", icon: "🤝", label: "微调 Agent", badge: true },
  { id: "binding", icon: "🔗", label: "绑点 Agent", badge: true },
  { id: "schema", icon: "📋", label: "Schema 校验", badge: true },
];

export default function MainTabs() {
  const { activeTab, setActiveTab } = useAssetStore();

  return (
    <div className="h-[36px] bg-[var(--bg2)] border-b border-[var(--border)] flex items-end px-2 gap-px shrink-0 z-[100] overflow-x-auto overflow-y-hidden">
      {TABS.map((tab) => {
        const isActive = activeTab === tab.id;
        return (
          <div
            key={tab.id}
            className={`
              h-[30px] px-4 flex items-center gap-[7px] text-[11px] cursor-pointer
              rounded-t-[4px] border border-transparent border-b-none whitespace-nowrap
              shrink-0 relative transition-[0.12s]
              ${isActive
                ? "text-[var(--accent)] bg-[var(--bg)] border-[var(--border)] border-b-[var(--bg)]"
                : "text-[var(--text2)] bg-transparent hover:text-[var(--text)] hover:bg-[rgba(255,255,255,0.04)]"
              }
            `}
            onClick={() => setActiveTab(tab.id)}
          >
            <span className="text-[12px]">{tab.icon}</span>
            {tab.label}
            {tab.badge && !isActive && (
              <div
                className="w-[6px] h-[6px] rounded-full absolute top-[5px] right-2"
                style={{ background: "var(--accent)" }}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
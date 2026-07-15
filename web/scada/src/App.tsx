import TitleBar from "./components/layout/TitleBar";
import MainTabs from "./components/tabs/MainTabs";
import StatusBar from "./components/layout/StatusBar";
import AssetAgentPage from "./components/asset/AssetAgentPage";
import LayoutAgentPage from "./components/layout-agent/LayoutAgentPage";
import RefineAgentPage from "./components/refine-agent/RefineAgentPage";
import { useAssetStore } from "./stores/assetStore";

function PlaceholderPage({ title }: { title: string }) {
  return (
    <div className="flex flex-1 items-center justify-center">
      <div className="text-center">
        <div className="text-[48px] mb-3 opacity-30">🚧</div>
        <div className="text-[14px] text-[var(--text2)] mb-1">{title}</div>
        <div className="text-[11px] text-[var(--text3)] font-mono">
          功能开发中，请切换到「素材Agent」标签页
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const { activeTab } = useAssetStore();

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <TitleBar />
      <MainTabs />

      <div className="flex-1 overflow-hidden relative">
        {activeTab === "asset" && <AssetAgentPage />}
        {activeTab === "schema" && <PlaceholderPage title="R-01 Schema规则库" />}
        {activeTab === "layout" && <LayoutAgentPage />}
        {activeTab === "refine" && <RefineAgentPage />}
        {activeTab === "binding" && <PlaceholderPage title="R-05 智能数据绑点" />}
        {activeTab === "docs" && <PlaceholderPage title="需求文档" />}
      </div>

      <StatusBar />

      <div
        id="scada-notify"
        className="notify"
      />
    </div>
  );
}
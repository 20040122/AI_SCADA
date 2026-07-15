import { useLayoutStore } from "../../stores/layoutStore";
import { useAssetStore } from "../../stores/assetStore";
import { generateLayout } from "../../api/layout";
import { notify } from "../../utils/notification";
import { extractNodesFromJsonData } from "../../utils/layoutNodes";
import { WorkflowSteps } from "./CenterPanel";

export default function LeftPanel() {
  const {
    query,
    title,
    canvasWidth,
    canvasHeight,
    setQuery,
    setTitle,
    setCanvasWidth,
    setCanvasHeight,
    setLayoutResult,
    setWorkflowStep,
    resetWorkflow,
    clearCanvas,
    setIsLoading,
    setError,
    workflow,
  } = useLayoutStore();

  const assetQueryResults = useAssetStore((s) => s.queryResults);

  const handleGenerate = async () => {
    if (!query.trim()) {
      notify("请输入场景描述", "w");
      return;
    }
    if (!title.trim()) {
      notify("请输入画面标题", "w");
      return;
    }

    resetWorkflow();
    setIsLoading(true);
    setError(null);

    try {
      setWorkflowStep(1, "run");
      setWorkflowStep(1, "done");
      setWorkflowStep(2, "run");

      const result = await generateLayout({
        query: query.trim(),
        canvasWidth,
        canvasHeight,
        title: title.trim(),
      });

      setWorkflowStep(2, "done");
      setWorkflowStep(3, "run");
      setLayoutResult(result);
      setWorkflowStep(3, "done");

      const nodeCount = extractNodesFromJsonData(result.json_data).length;
      const missingCount = result.missing_controls.length || 0;
      const warnCount = result.quality_issues.filter((q) => q.severity === "warning").length;
      const errCount = result.quality_issues.filter((q) => q.severity === "error").length;

      if (nodeCount === 0 && missingCount === 0) {
        notify("未生成控件，请检查场景描述或先入库控件", "w");
      } else if (nodeCount === 0 && missingCount > 0) {
        notify(`未找到可用控件：${result.missing_controls.join(", ")}`, "w");
      } else if (errCount > 0) {
        notify(`${nodeCount} 个控件, ${errCount} 项不合格, ${warnCount} 项警告`, "w");
      } else if (missingCount > 0) {
        notify(`${nodeCount} 个控件生成完成，未找到 ${missingCount} 个控件`, "w");
      } else {
        notify(`${nodeCount} 个控件生成成功`, "s");
      }
    } catch (e) {
      setWorkflowStep(1, "done");
      setWorkflowStep(2, "done");
      setWorkflowStep(3, "done");

      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      notify("AI 布局异常，请检查后端服务", "e");
    } finally {
      setIsLoading(false);
    }
  };

  const handleClear = () => {
    clearCanvas();
    resetWorkflow();
    notify("已清空画布", "s");
  };

  const isGenerating = workflow.some((s) => s.status === "run");

  return (
    <div className="w-[320px] bg-[var(--panel)] border-r border-[var(--border)] flex flex-col shrink-0 overflow-hidden">
      <div className="p-[10px] border-b border-[var(--border)] bg-[var(--bg2)] flex items-center gap-2 shrink-0">
        <span className="text-[13px] font-medium text-[var(--text)]">布局 Agent</span>
      </div>

      <div className="flex-1 overflow-y-auto p-[14px]">
        <div className="text-[10px] text-[var(--text3)] font-mono mb-2 tracking-[1px] uppercase">
          📥 布局配置
        </div>

        <div className="mb-3">
          <label className="text-[10px] text-[var(--text3)] font-mono mb-1 block tracking-[0.5px] uppercase">
            场景描述 Query
          </label>
          <textarea
            className="w-full bg-[var(--bg3)] border border-[var(--border2)] rounded-[4px] px-[10px] py-[7px] text-[12px] text-[var(--text)] font-[var(--sans)] outline-none resize-y focus:border-[var(--accent2)] focus:shadow-[0_0_0_2px_rgba(77,184,212,0.07)]"
            rows={4}
            style={{ minHeight: "72px", lineHeight: 1.5 }}
            placeholder="如：冷却水循环系统，2台水泵、4个阀门、出口压力传感器、流量计，右侧放显示仪表"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>

        <div className="mb-3">
          <label className="text-[10px] text-[var(--text3)] font-mono mb-1 block tracking-[0.5px] uppercase">
            画面标题
          </label>
          <input
            className="w-full bg-[var(--bg3)] border border-[var(--border2)] rounded-[4px] px-[10px] py-[7px] text-[12px] text-[var(--text)] font-[var(--sans)] outline-none focus:border-[var(--accent2)] focus:shadow-[0_0_0_2px_rgba(77,184,212,0.07)]"
            placeholder="如：冷却水循环系统"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>

        <div className="flex gap-2 mb-3">
          <div className="flex-1">
            <label className="text-[10px] text-[var(--text3)] font-mono mb-1 block tracking-[0.5px] uppercase">
              画布宽
            </label>
            <input
              type="number"
              className="w-full bg-[var(--bg3)] border border-[var(--border2)] rounded-[4px] px-[10px] py-[7px] text-[12px] text-[var(--text)] font-[var(--sans)] outline-none focus:border-[var(--accent2)] focus:shadow-[0_0_0_2px_rgba(77,184,212,0.07)]"
              value={canvasWidth}
              onChange={(e) => setCanvasWidth(Number(e.target.value))}
            />
          </div>
          <div className="flex-1">
            <label className="text-[10px] text-[var(--text3)] font-mono mb-1 block tracking-[0.5px] uppercase">
              画布高
            </label>
            <input
              type="number"
              className="w-full bg-[var(--bg3)] border border-[var(--border2)] rounded-[4px] px-[10px] py-[7px] text-[12px] text-[var(--text)] font-[var(--sans)] outline-none focus:border-[var(--accent2)] focus:shadow-[0_0_0_2px_rgba(77,184,212,0.07)]"
              value={canvasHeight}
              onChange={(e) => setCanvasHeight(Number(e.target.value))}
            />
          </div>
        </div>

        {assetQueryResults.length > 0 && (
          <div className="mb-3">
            <label className="text-[10px] text-[var(--text3)] font-mono mb-1 block tracking-[0.5px] uppercase">
              可用控件（已入库 {assetQueryResults.length} 个）
            </label>
            <div className="bg-[var(--bg3)] border border-[var(--border2)] rounded-[4px] p-[8px] max-h-[120px] overflow-y-auto flex flex-wrap gap-1">
              {assetQueryResults.map((item, i) => (
                <span
                  key={i}
                  className="text-[10px] px-[6px] py-[2px] rounded-[3px] bg-[rgba(77,184,212,0.08)] border border-[rgba(77,184,212,0.2)] text-[var(--text2)] font-mono"
                >
                  {item.displayName} {item.width > 0 && `(${item.width}×${item.height})`}
                </span>
              ))}
            </div>
          </div>
        )}

        <div className="flex gap-2 mb-3">
          <button
            className="flex-1 px-[16px] py-[7px] rounded-[4px] text-[11px] cursor-pointer border border-[var(--accent)] bg-[rgba(77,184,212,0.1)] text-[var(--accent)] font-[var(--sans)] transition-[0.15s] hover:bg-[rgba(77,184,212,0.2)] disabled:opacity-50"
            onClick={handleGenerate}
            disabled={isGenerating}
          >
            ⚡ {isGenerating ? "生成中..." : "生成布局"}
          </button>
          <button
            className="px-[16px] py-[7px] rounded-[4px] text-[11px] cursor-pointer border border-[var(--border2)] bg-[var(--bg3)] text-[var(--text2)] font-[var(--sans)] transition-[0.15s] hover:border-[var(--accent2)] hover:text-[var(--accent)]"
            onClick={handleClear}
          >
            清空画布
          </button>
        </div>

        <div className="mt-auto">
          <div className="text-[10px] text-[var(--text3)] font-mono mb-2 tracking-[1px] uppercase">
            Agent 流程
          </div>
          <WorkflowSteps />
        </div>
      </div>
    </div>
  );
}

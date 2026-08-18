import { useEffect, useCallback } from "react";
import { useAssetStore } from "../../stores/assetStore";
import { getQueryResults, clearQueryResults, saveQueryResults } from "../../api/material";
import { useGenerationPolling } from "../../hooks/useGenerationPolling";
import { notify } from "../../utils/notification";
import AssetCard from "./AssetCard";
import AiGenerationRow from "./AiGenerationRow";

export default function CenterPanel() {
  const {
    keywordResults,
    queryResults,
    setQueryResults,
    setSelectedAsset,
    missedKeywords,
    removeKeyword,
    query,
    setPipelineStep,
    isLoading,
    generations,
  } = useAssetStore();

  useGenerationPolling();

  const refreshQueryResults = useCallback(() => {
    getQueryResults()
      .then((res) => {
        if (res?.items) setQueryResults(res.items);
      })
      .catch(() => {});
  }, [setQueryResults]);

  useEffect(() => {
    let mounted = true;
    getQueryResults()
      .then((res) => {
        if (mounted && res?.items) setQueryResults(res.items);
      })
      .catch(() => {});
    return () => { mounted = false; };
  }, [setQueryResults]);

  const handleClear = () => {
    clearQueryResults()
      .then(() => {
        setQueryResults([]);
        notify("已清空入库控件", "s");
      })
      .catch(() => {
        notify("清空失败", "e");
      });
  };

  const handleSaveCandidate = (keywordStr: string, displayName: string) => {
    const kr = keywordResults.find((k) => k.keyword === keywordStr);
    if (!kr) return;
    const candidate = kr.candidates.find((c) => c.displayName === displayName);
    if (!candidate) return;

    const controls = [{
      displayName: candidate.displayName,
      image: candidate.image,
      width: candidate.width,
      height: candidate.height,
      similarity: candidate.similarity,
      source: candidate.source,
    }];

    saveQueryResults(query, controls)
      .then(() => {
        refreshQueryResults();
        removeKeyword(keywordStr);
        setPipelineStep(3, "done");
        notify(`${displayName} 已入库`, "s");
      })
      .catch(() => {
        notify("入库失败", "e");
      });
  };

  const totalCandidates = keywordResults.reduce(
    (sum, kr) => sum + kr.candidates.length, 0
  );

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="p-[10px] border-b border-[var(--border)] bg-[var(--bg2)] flex items-center gap-2 shrink-0">
        <span className="text-[13px] font-medium text-[var(--text)]">控件</span>
        <span className="ml-auto text-[10px] text-[var(--text3)] font-mono">
          已入库 {queryResults.length} 个
        </span>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-[14px]">
        <div className="text-[10px] text-[var(--text3)] font-mono mb-2 tracking-[1px] uppercase">
          检索结果{totalCandidates > 0 && `（${totalCandidates}个候选）`}
          {missedKeywords.length > 0 && (
            <span className="text-[var(--warn)] ml-2">
              未匹配: {missedKeywords.join(", ")}
            </span>
          )}
        </div>
        {!keywordResults.length ? (
          <div className="text-[10px] text-[var(--text3)] font-mono text-center py-8">
            {isLoading ? (
              <span className="animate-pulse">LLM 提取中，请稍候...</span>
            ) : (
              "输入Query后显示检索结果"
            )}
          </div>
        ) : (
          <div className="mb-[14px]">
            {keywordResults.map((kr) => (
              <div key={kr.keyword} className="mb-3">
                <div className="text-[9px] text-[var(--accent)] font-mono mb-1 tracking-[0.5px]">
                  {kr.keyword}
                  {kr.candidates.length === 0 && (
                    <span className="text-[var(--text3)] ml-2">无候选</span>
                  )}
                </div>
                {kr.candidates.length > 0 ? (
                  <div className="grid grid-cols-3 gap-2">
                    {kr.candidates.map((c) => (
                      <AssetCard
                        key={c.displayName}
                        item={c}
                        candidate={c}
                        onClick={() => handleSaveCandidate(kr.keyword, c.displayName)}
                      />
                    ))}
                  </div>
                ) : kr.canGenerate ? (
                  <div className="p-[6px] border border-[var(--border)] rounded-[4px] bg-[var(--bg2)]">
                    <AiGenerationRow
                      keyword={kr.keyword}
                      query={query}
                      generation={generations[kr.keyword]}
                      onConfirmed={refreshQueryResults}
                    />
                  </div>
                ) : (
                  <div className="text-[10px] text-[var(--text3)] font-mono">
                    请输入明确控件名称后重试
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="flex items-center justify-between mb-2">
          <span className="text-[10px] text-[var(--text3)] font-mono tracking-[1px] uppercase">
            当前入库{queryResults.length > 0 && `（${queryResults.length}个）`}
          </span>
          {queryResults.length > 0 && (
            <button
              className="text-[9px] px-[8px] py-[2px] rounded-[3px] border border-[var(--border2)] bg-[var(--bg3)] text-[var(--text3)] font-mono cursor-pointer transition-[0.15s] hover:border-[var(--warn)] hover:text-[var(--warn)]"
              onClick={handleClear}
            >
              清空
            </button>
          )}
        </div>
        {!queryResults.length ? (
          <div className="text-[10px] text-[var(--text3)] font-mono text-center py-8">
            暂无入库控件
          </div>
        ) : (
          <div className="grid grid-cols-3 gap-2">
            {queryResults.map((item) => (
              <AssetCard
                key={item.displayName}
                item={item}
                candidate={{ ...item, similarity: item.similarity, source: item.source }}
                onClick={() => setSelectedAsset(item)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
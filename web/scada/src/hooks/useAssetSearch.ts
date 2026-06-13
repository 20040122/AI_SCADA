import { useCallback } from "react";
import { useAssetStore } from "../stores/assetStore";
import { searchControls } from "../api/control";
import { notify } from "../utils/notification";

export function useAssetSearch() {
  const {
    query,
    setKeywordResults,
    setMissedKeywords,
    setPipelineStep,
    resetPipeline,
    setIsLoading,
    setError,
  } = useAssetStore();

  const search = useCallback(async () => {
    if (!query.trim()) {
      notify("请输入Query", "w");
      return;
    }

    resetPipeline();
    setIsLoading(true);
    setError(null);

    try {
      setPipelineStep(1, "run");
      setPipelineStep(1, "done");
      setPipelineStep(2, "run");

      const result = await searchControls(query);

      setPipelineStep(2, "done");

      setPipelineStep(3, "wait");

      setKeywordResults(result.keywords);
      setMissedKeywords(result.missed);

      const totalCandidates = result.keywords.reduce(
        (sum, kr) => sum + kr.candidates.length, 0
      );
      if (result.missed.length > 0) {
        notify(
          `${result.keywords.length} 个关键词, ${totalCandidates} 个候选, ${result.missed.length} 个未匹配`,
          "w"
        );
      } else {
        notify(`${result.keywords.length} 个关键词, ${totalCandidates} 个候选`, "s");
      }
    } catch (e) {
      setPipelineStep(1, "done");
      setPipelineStep(2, "done");
      setPipelineStep(3, "done");

      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);

      setKeywordResults([]);
      setMissedKeywords([]);
      notify("AI 检索异常，请检查后端服务", "e");
    } finally {
      setIsLoading(false);
    }
  }, [
    query,
    resetPipeline,
    setPipelineStep,
    setKeywordResults,
    setMissedKeywords,
    setIsLoading,
    setError,
  ]);

  return { search };
}
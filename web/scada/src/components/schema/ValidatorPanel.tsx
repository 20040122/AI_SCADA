import { useEffect } from "react";
import { useRuleStore } from "../../stores/ruleStore";

const SOURCE_LABELS: Record<string, string> = {
  schema: "schema",
  semantic: "semantic",
  ai: "ai",
  system: "system",
};

export default function ValidatorPanel() {
  const {
    activeCategory,
    validatorInput,
    result,
    loading,
    error,
    categories,
    categoriesLoaded,
    setValidatorInput,
    runValidate,
    setActiveCategory,
    loadCategories,
  } = useRuleStore();

  useEffect(() => {
    if (!categoriesLoaded) {
      void loadCategories();
    }
  }, [categoriesLoaded, loadCategories]);

  const cat = categories.find((c) => c.category === activeCategory);

  const handleSample = (type: "valid" | "invalid") => {
    if (!cat) return;
    const sample = type === "valid" ? cat.sample_valid : cat.sample_invalid;
    setValidatorInput(JSON.stringify(sample, null, 2));
  };

  return (
    <div className="w-[300px] border-l border-[var(--border)] flex flex-col bg-[var(--bg)]">
      <div className="px-3 py-2 text-[12px] font-semibold text-[var(--text2)] border-b border-[var(--border)]">
        校验器
      </div>

      <div className="p-2 border-b border-[var(--border)]">
        <select
          className="w-full text-[12px] px-2 py-1 rounded border border-[var(--border)] bg-[var(--bg2)] text-[var(--text)] outline-none"
          value={activeCategory}
          onChange={(e) => setActiveCategory(e.target.value)}
        >
          {categories.map((c) => (
            <option key={c.category} value={c.category}>{c.label}</option>
          ))}
        </select>
      </div>

      <div className="flex-1 flex flex-col p-2 gap-2">
        <textarea
          className="flex-1 w-full text-[11px] font-mono p-2 rounded border border-[var(--border)] bg-[var(--bg2)] text-[var(--text)] resize-none outline-none"
          placeholder="在此粘贴 JSON 进行校验..."
          value={validatorInput}
          onChange={(e) => setValidatorInput(e.target.value)}
        />

        <div className="flex gap-1">
          <button
            className="flex-1 px-2 py-1 text-[11px] rounded bg-[var(--accent)] text-white font-medium disabled:opacity-40"
            disabled={loading || !validatorInput.trim()}
            onClick={() => runValidate(activeCategory)}
          >
            {loading ? "校验中..." : "开始校验"}
          </button>
          {cat && (
            <>
              <button
                className="px-2 py-1 text-[11px] rounded border border-[var(--border)] text-[var(--text2)] hover:bg-[var(--bg2)]"
                onClick={() => handleSample("valid")}
              >
                合法例
              </button>
              <button
                className="px-2 py-1 text-[11px] rounded border border-[var(--border)] text-[var(--text2)] hover:bg-[var(--bg2)]"
                onClick={() => handleSample("invalid")}
              >
                非法例
              </button>
            </>
          )}
        </div>

        {error && (
          <div className="text-[11px] p-2 rounded bg-[rgba(224,85,85,0.1)] text-[var(--error)] border border-[rgba(224,85,85,0.45)]">
            {error}
          </div>
        )}

        {result && (
          <div className="text-[11px] border border-[var(--border)] rounded overflow-hidden">
            <div className={`px-2 py-1 font-medium text-white ${result.valid ? "bg-[var(--success)]" : "bg-[var(--error)]"}`}>
              {result.valid ? "✓ 校验通过" : "✗ 校验未通过"}
              {result.summary && ` — ${result.summary}`}
            </div>
            {result.errors.length > 0 && (
              <div className="p-2 bg-[rgba(224,85,85,0.08)]">
                <div className="font-medium text-[var(--error)] mb-1">错误 ({result.errors.length})</div>
                {result.errors.map((e, i) => (
                  <div key={i} className="mb-1 last:mb-0">
                    <span className="text-[var(--error)]">[{SOURCE_LABELS[e.source] ?? e.source}]</span>{" "}
                    {e.path && <span className="text-[var(--text3)]">{e.path}: </span>}
                    {e.message}
                  </div>
                ))}
              </div>
            )}
            {result.warnings.length > 0 && (
              <div className="p-2 bg-[rgba(232,168,64,0.08)]">
                <div className="font-medium text-[var(--warn)] mb-1">警告 ({result.warnings.length})</div>
                {result.warnings.map((w, i) => (
                  <div key={i} className="mb-1 last:mb-0">
                    <span className="text-[var(--warn)]">[{SOURCE_LABELS[w.source] ?? w.source}]</span>{" "}
                    {w.path && <span className="text-[var(--text3)]">{w.path}: </span>}
                    {w.message}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

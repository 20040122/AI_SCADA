import { useRuleStore } from "../../stores/ruleStore";
import { ruleCategories } from "../../data/rules";
import { layoutConfig } from "../../data/layoutConfig";
import ValidatorPanel from "./ValidatorPanel";

export default function RuleLibraryPage() {
  const { activeCategory, setActiveCategory } = useRuleStore();

  const cat = ruleCategories.find((c) => c.id === activeCategory);
  if (!cat) return null;

  return (
    <div className="flex flex-1 h-full">
      {/* Left nav */}
      <nav className="w-[180px] border-r border-[var(--border)] bg-[var(--bg)] flex flex-col shrink-0">
        <div className="px-3 py-2 text-[11px] font-semibold text-[var(--text3)] uppercase tracking-wider border-b border-[var(--border)]">
          规则分类
        </div>
        {ruleCategories.map((c) => (
          <button
            key={c.id}
            className={`flex items-center gap-2 px-3 py-2 text-[12px] text-left transition-colors ${
              activeCategory === c.id
                ? "bg-[var(--accent)]/10 text-[var(--accent)] font-medium border-r-2 border-[var(--accent)]"
                : "text-[var(--text2)] hover:bg-[var(--bg2)]"
            }`}
            onClick={() => setActiveCategory(c.id)}
          >
            <span className="text-[14px]">{c.icon}</span>
            <span>{c.label}</span>
          </button>
        ))}
      </nav>

      {/* Center content */}
      <div className="flex-1 overflow-y-auto p-4 bg-[var(--bg2)]">
        <div className="max-w-[800px] mx-auto">
          <h1 className="text-[18px] font-bold text-[var(--text)] mb-1">{cat.schema.title}</h1>
          <p className="text-[12px] text-[var(--text3)] mb-4">{cat.schema.description}</p>

          {/* Schema fields */}
          {cat.schema.properties.length > 0 && (
            <section className="mb-6">
              <h2 className="text-[13px] font-semibold text-[var(--text)] mb-2">字段定义</h2>
                  <div className="border border-[var(--border)] rounded overflow-hidden">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="bg-[var(--bg)]">
                      <th className="px-3 py-1.5 text-left text-[var(--text3)] font-medium">字段名</th>
                      <th className="px-3 py-1.5 text-left text-[var(--text3)] font-medium">类型</th>
                      <th className="px-3 py-1.5 text-left text-[var(--text3)] font-medium">必填</th>
                      <th className="px-3 py-1.5 text-left text-[var(--text3)] font-medium">说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cat.schema.properties.map((p) => (
                      <tr key={p.name} className="border-t border-[var(--border)]">
                        <td className="px-3 py-1.5 font-mono text-[var(--accent)]">{p.name}</td>
                        <td className="px-3 py-1.5 text-[var(--text2)]">{p.type}</td>
                        <td className="px-3 py-1.5">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] ${p.required ? "bg-[rgba(224,85,85,0.14)] text-[var(--error)]" : "bg-[var(--bg3)] text-[var(--text3)]"}`}>
                            {p.required ? "必填" : "可选"}
                          </span>
                        </td>
                        <td className="px-3 py-1.5 text-[var(--text2)]">
                          {p.description}
                          {p.enum && <span className="block text-[var(--text3)] mt-0.5">枚举值: {p.enum.join(", ")}</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* Layout role limits (only for layout category) */}
          {activeCategory === "layout" && (
            <section className="mb-6">
              <h2 className="text-[13px] font-semibold text-[var(--text)] mb-2">角色尺寸约束</h2>
                  <div className="border border-[var(--border)] rounded overflow-hidden">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="bg-[var(--bg)]">
                      <th className="px-3 py-1.5 text-left text-[var(--text3)] font-medium">角色</th>
                      <th className="px-3 py-1.5 text-left text-[var(--text3)] font-medium">关键词</th>
                      <th className="px-3 py-1.5 text-left text-[var(--text3)] font-medium">最小尺寸</th>
                      <th className="px-3 py-1.5 text-left text-[var(--text3)] font-medium">最大尺寸</th>
                      <th className="px-3 py-1.5 text-left text-[var(--text3)] font-medium">推荐尺寸</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(layoutConfig.roles).map(([role, cfg]) => (
                      <tr key={role} className="border-t border-[var(--border)]">
                        <td className="px-3 py-1.5 font-mono text-[var(--accent)]">{role}</td>
                        <td className="px-3 py-1.5 text-[var(--text2)]">{cfg.keywords.join(", ") || "-"}</td>
                        <td className="px-3 py-1.5 text-[var(--text2)]">{cfg.limits.min_w}×{cfg.limits.min_h}</td>
                        <td className="px-3 py-1.5 text-[var(--text2)]">{cfg.limits.max_w}×{cfg.limits.max_h}</td>
                        <td className="px-3 py-1.5 text-[var(--text2)]">{cfg.limits.preferred_w}×{cfg.limits.preferred_h}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* Derived rules */}
          <section className="mb-6">
            <h2 className="text-[13px] font-semibold text-[var(--text)] mb-2">派生规则</h2>
            <div className="border border-[var(--border)] rounded divide-y divide-[var(--border)]">
              {cat.derivedRules.map((rule, i) => (
              <div key={i} className="px-3 py-1.5 text-[11px] text-[var(--text2)]">
                  {i + 1}. {rule}
                </div>
              ))}
            </div>
          </section>

          {/* Samples */}
          <section className="mb-6">
            <h2 className="text-[13px] font-semibold text-[var(--text)] mb-2">示例</h2>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="text-[11px] font-medium text-[var(--success)] mb-1">✓ 合法示例</div>
                <pre className="text-[10px] p-2 rounded border border-[rgba(62,207,122,0.45)] bg-[rgba(62,207,122,0.08)] text-[var(--text)] overflow-x-auto max-h-[160px]">
                  {JSON.stringify(cat.sampleOk, null, 2)}
                </pre>
              </div>
              <div>
                <div className="text-[11px] font-medium text-[var(--error)] mb-1">✗ 非法示例</div>
                <pre className="text-[10px] p-2 rounded border border-[rgba(224,85,85,0.45)] bg-[rgba(224,85,85,0.08)] text-[var(--text)] overflow-x-auto max-h-[160px]">
                  {JSON.stringify(cat.sampleBad, null, 2)}
                </pre>
              </div>
            </div>
          </section>
        </div>
      </div>

      {/* Right validator panel */}
      <ValidatorPanel />
    </div>
  );
}

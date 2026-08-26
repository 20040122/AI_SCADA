import { useThemeStore } from "../../stores/themeStore";

export default function TitleBar() {
  const { theme, toggleTheme } = useThemeStore();

  return (
    <div className="h-[30px] bg-[var(--bg4)] border-b border-[var(--border)] flex items-center px-3 gap-3 shrink-0 z-[200]">
      <div
        className="font-mono text-[11px] font-semibold tracking-[2px]"
        style={{ color: "var(--accent)" }}
      >
        SCADA<span style={{ color: "var(--text3)" }}>·</span>AI
      </div>
      <div className="ml-auto flex items-center gap-2">
        <div
          className="w-[5px] h-[5px] rounded-full"
          style={{ background: "var(--success)", boxShadow: "0 0 6px var(--success)" }}
        />
        <span className="text-[10px] font-mono" style={{ color: "var(--text3)" }}>
          AI引擎就绪
        </span>
        <button
          type="button"
          className="h-[22px] px-2 rounded-[4px] border border-[var(--border2)] bg-[var(--bg2)] text-[10px] text-[var(--text2)] font-mono cursor-pointer transition-[0.12s] hover:text-[var(--text)] hover:bg-[var(--hover)]"
          onClick={toggleTheme}
          aria-label={`切换到${theme === "dark" ? "浅色" : "深色"}主题`}
          title={`切换到${theme === "dark" ? "浅色" : "深色"}主题`}
        >
          {theme === "dark" ? "☀ 浅色" : "◐ 深色"}
        </button>
      </div>
    </div>
  );
}

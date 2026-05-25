export default function TitleBar() {
  return (
    <div className="h-[30px] bg-[var(--bg4)] border-b border-[var(--border)] flex items-center px-3 gap-3 shrink-0 z-[200]">
      <div
        className="font-mono text-[11px] font-semibold tracking-[2px]"
        style={{ color: "var(--accent)" }}
      >
        SCADA<span style={{ color: "var(--text3)" }}>·</span>AI
      </div>
      {[""].map((m) => (
        <div
          key={m}
          className="text-[11px] px-2 h-[30px] flex items-center cursor-pointer transition-[0.12s]"
          style={{ color: "var(--text2)" }}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = "var(--text)";
            e.currentTarget.style.background = "rgba(255,255,255,0.04)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = "var(--text2)";
            e.currentTarget.style.background = "transparent";
          }}
        >
          {m}
        </div>
      ))}
      <div className="ml-auto flex items-center gap-2">
        <div
          className="w-[5px] h-[5px] rounded-full"
          style={{ background: "var(--success)", boxShadow: "0 0 6px var(--success)" }}
        />
        <span className="text-[10px] font-mono" style={{ color: "var(--text3)" }}>
          AI引擎就绪
        </span>
      </div>
    </div>
  );
}
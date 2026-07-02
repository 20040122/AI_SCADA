import { useState } from "react";
import { useLayoutStore } from "../../stores/layoutStore";
import { uploadToSystem } from "../../api/layout";
import { colorJson } from "../../utils/jsonColor";

export default function RightPanel() {
  const { jsonData, zones, missingControls, nodes, fileName } = useLayoutStore();
  const hasJson = jsonData !== null;
  const hasNodes = nodes.length > 0;
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);
  const [uploadErr, setUploadErr] = useState(false);

  const handleUpload = async () => {
    if (!jsonData || !fileName) return;
    setUploading(true);
    setUploadMsg(null);
    setUploadErr(false);
    try {
      await uploadToSystem(jsonData, fileName);
      setUploadMsg("已插入系统");
      setUploadErr(false);
    } catch (e) {
      setUploadMsg(e instanceof Error ? e.message : "上传失败");
      setUploadErr(true);
    } finally {
      setUploading(false);
    }
  };

  const jsonStr = jsonData
    ? JSON.stringify(jsonData, null, 2)
    : "// 生成后显示";

  return (
    <div className="w-[280px] bg-[var(--panel)] border-l border-[var(--border)] flex flex-col shrink-0 overflow-hidden">
      <div className="p-[10px] border-b border-[var(--border)] bg-[var(--bg2)] shrink-0">
        <span className="text-[13px] font-medium text-[var(--text)]">布局 JSON</span>
      </div>

      <div className="flex-1 overflow-y-auto p-[14px]">
        <div
          className="bg-[var(--bg4)] border border-[var(--border)] rounded-[4px] p-[10px_12px] font-mono text-[9px] leading-[1.7] text-[var(--text2)] overflow-auto mb-3 whitespace-pre"
          style={{ maxHeight: "280px" }}
          dangerouslySetInnerHTML={{
            __html: hasJson
              ? colorJson(jsonStr)
              : '<span style="color:var(--text3);font-style:italic">// 生成后显示</span>',
          }}
        />

        {hasJson && (
          <div className="mb-3">
            <button
              className="w-full px-[16px] py-[7px] rounded-[4px] text-[11px] cursor-pointer border border-[var(--accent)] bg-[rgba(77,184,212,0.1)] text-[var(--accent)] font-[var(--sans)] transition-[0.15s] hover:bg-[rgba(77,184,212,0.2)] disabled:opacity-50"
              onClick={handleUpload}
              disabled={uploading}
            >
              {uploading ? "插入中..." : "插入系统"}
            </button>
            {uploadMsg && (
              <div
                className={`mt-2 text-[10px] font-mono text-center ${
                  uploadErr ? "text-[var(--warn)]" : "text-[var(--accent)]"
                }`}
              >
                {uploadMsg}
              </div>
            )}
          </div>
        )}

        {hasNodes && zones.length > 0 && (
          <>
            <div className="text-[10px] text-[var(--text3)] font-mono mt-3 mb-2 tracking-[1px] uppercase">
              📐 分区布局
            </div>
            <div className="bg-[var(--bg3)] border border-[var(--border)] rounded-[5px] p-[12px] mb-3">
              {zones.map((zone, i) => (
                <div key={i} className="text-[10px] text-[var(--text2)] font-mono mb-1 last:mb-0">
                  <span className="text-[var(--accent)]">{zone.name}</span>:{" "}
                  {zone.controls.join(", ")}
                </div>
              ))}
            </div>
          </>
        )}

        {missingControls.length > 0 && (
          <>
            <div className="text-[10px] text-[var(--text3)] font-mono mt-3 mb-2 tracking-[1px] uppercase text-[var(--warn)]">
              ⚠ 未找到控件
            </div>
            <div className="bg-[var(--bg3)] border border-[var(--border)] rounded-[5px] p-[12px] mb-3 text-[11px] text-[var(--warn)]">
              {missingControls.join(", ")}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

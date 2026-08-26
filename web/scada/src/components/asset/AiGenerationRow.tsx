import { useRef, useState } from "react";
import type { GenerationState } from "../../types/asset.ts";
import {
  createGeneration,
  confirmGeneration,
  regenerateGeneration,
  discardGeneration,
} from "../../api/generation.ts";
import { useAssetStore } from "../../stores/assetStore.ts";
import { notify } from "../../utils/notification.ts";
import { apiErrorStatus } from "../../utils/apiError.ts";

const BTN_BASE =
  "text-[9px] px-[8px] py-[2px] rounded-[3px] border font-mono cursor-pointer transition-[0.15s]";
const BTN_DEFAULT = `${BTN_BASE} border-[var(--border2)] bg-[var(--bg3)] text-[var(--text2)] hover:border-[var(--accent)] hover:text-[var(--accent)]`;
const BTN_PRIMARY = `${BTN_BASE} border-[var(--accent)] bg-[var(--accent)] text-[var(--on-accent)] hover:opacity-80`;
const BTN_DANGER = `${BTN_BASE} border-[var(--warn)] text-[var(--warn)] hover:bg-[rgba(232,168,64,0.1)]`;

export default function AiGenerationRow({
  keyword,
  query,
  generation,
  onConfirmed,
}: {
  keyword: string;
  query: string;
  generation: GenerationState | undefined;
  onConfirmed: () => void;
}) {
  const {
    setGeneration,
    clearGeneration,
    addQueryResult,
    removeKeyword,
    setPipelineStep,
  } = useAssetStore();
  const [busy, setBusy] = useState(false);
  const [imgError, setImgError] = useState(false);
  const confirmingRef = useRef(false);

  const fail = (e: unknown) => {
    setGeneration(keyword, {
      status: "failed",
      error: e instanceof Error ? e.message : String(e),
    });
  };

  const handleGenerate = async () => {
    setBusy(true);
    try {
      const res = await createGeneration(query, keyword);
      setGeneration(keyword, {
        generationId: res.generation_id,
        status: res.status,
        seed: null,
        previewUrl: null,
        error: null,
      });
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const handleRegenerate = async () => {
    const gid = generation?.generationId;
    if (!gid) return;
    setBusy(true);
    try {
      const res = await regenerateGeneration(gid);
      setGeneration(keyword, {
        generationId: res.generation_id,
        status: "queued",
        seed: null,
        previewUrl: null,
        error: null,
      });
    } catch (e) {
      if (apiErrorStatus(e) === 410) {
        clearGeneration(keyword);
        notify("预览已过期，请重新生成", "w");
      } else {
        fail(e);
      }
    } finally {
      setBusy(false);
    }
  };

  const handleConfirm = async () => {
    const gid = generation?.generationId;
    if (!gid || confirmingRef.current) return;
    confirmingRef.current = true;
    setBusy(true);
    try {
      const item = await confirmGeneration(gid);
      addQueryResult(item);
      removeKeyword(keyword);
      clearGeneration(keyword);
      setPipelineStep(3, "done");
      onConfirmed();
      notify(`${item.displayName} 已入库`, "s");
    } catch (e) {
      const status = apiErrorStatus(e);
      if (status === 410) {
        clearGeneration(keyword);
        notify("预览已过期，请重新生成", "w");
      } else {
        notify(e instanceof Error ? e.message : "确认失败", "e");
      }
    } finally {
      confirmingRef.current = false;
      setBusy(false);
    }
  };

  const handleDiscard = async () => {
    const gid = generation?.generationId;
    if (!gid) return;
    setBusy(true);
    try {
      await discardGeneration(gid);
      clearGeneration(keyword);
    } catch {
      clearGeneration(keyword);
    } finally {
      setBusy(false);
    }
  };

  const gen = generation;

  if (!gen || gen.status === "confirmed" || gen.status === "discarded") {
    return (
      <button
        className={BTN_PRIMARY}
        onClick={handleGenerate}
        disabled={busy}
      >
        {busy ? "提交中..." : "AI 生成"}
      </button>
    );
  }

  if (gen.status === "queued" || gen.status === "running") {
    return (
      <div className="flex items-center gap-2">
        <span className="text-[10px] text-[var(--warn)] font-mono animate-pulse">
          {gen.status === "running" ? "生成中..." : "排队中..."}
        </span>
        <button className={BTN_DANGER} onClick={handleDiscard} disabled={busy}>
          放弃
        </button>
      </div>
    );
  }

  if (gen.status === "expired") {
    return (
      <div className="flex items-center gap-2">
        <span className="text-[10px] text-[var(--text3)] font-mono">
          预览已过期
        </span>
        <button className={BTN_DEFAULT} onClick={handleGenerate} disabled={busy}>
          AI 生成
        </button>
      </div>
    );
  }

  if (gen.status === "failed") {
    return (
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[10px] text-[var(--error)] font-mono">
          {gen.error || "生成失败"}
        </span>
        <button className={BTN_DEFAULT} onClick={handleRegenerate} disabled={busy}>
          重新生成
        </button>
        <button className={BTN_DANGER} onClick={handleDiscard} disabled={busy}>
          放弃
        </button>
      </div>
    );
  }

  if (gen.status === "ready") {
    return (
      <div className="flex items-start gap-2">
        {gen.previewUrl && !imgError ? (
          <img
            src={gen.previewUrl}
            alt={keyword}
            className="w-[72px] h-[72px] object-contain border border-[var(--border2)] rounded-[3px] bg-[var(--bg2)]"
            onError={() => setImgError(true)}
          />
        ) : (
          <div className="w-[72px] h-[72px] flex items-center justify-center border border-[var(--border2)] rounded-[3px] text-[9px] text-[var(--text3)] font-mono bg-[var(--bg2)]">
            预览不可用
          </div>
        )}
        <div className="flex flex-col gap-1">
          <button
            className={BTN_PRIMARY}
            onClick={handleConfirm}
            disabled={busy}
          >
            {busy ? "确认中..." : "确认"}
          </button>
          <button
            className={BTN_DEFAULT}
            onClick={handleRegenerate}
            disabled={busy}
          >
            重新生成
          </button>
          <button
            className={BTN_DANGER}
            onClick={handleDiscard}
            disabled={busy}
          >
            放弃
          </button>
        </div>
      </div>
    );
  }

  return null;
}

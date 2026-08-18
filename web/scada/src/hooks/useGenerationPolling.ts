import { useEffect } from "react";
import { useAssetStore } from "../stores/assetStore.ts";
import { getGeneration } from "../api/generation.ts";
import { apiUrl } from "../api/client.ts";

const POLL_INTERVAL_MS = 1000;

export function useGenerationPolling() {
  const generations = useAssetStore((s) => s.generations);
  const setGeneration = useAssetStore((s) => s.setGeneration);

  useEffect(() => {
    const active = Object.entries(generations).filter(
      ([, g]) =>
        g.generationId && (g.status === "queued" || g.status === "running")
    );
    if (active.length === 0) return;

    const timers = active.map(([keyword, g]) =>
      setInterval(async () => {
        try {
          const status = await getGeneration(g.generationId as string);
          setGeneration(keyword, {
            status: status.status,
            seed: status.seed,
            previewUrl: status.preview_url ? apiUrl(status.preview_url) : null,
            error: status.error ?? null,
          });
        } catch {
          setGeneration(keyword, {
            status: "failed",
            error: "状态获取失败",
          });
        }
      }, POLL_INTERVAL_MS)
    );

    return () => timers.forEach((t) => clearInterval(t));
  }, [generations, setGeneration]);
}

import type { CanvasNode, DecorationNode, LayoutJsonData } from "../types/layout";

function hslToHex(h: number, s: number, l: number): string {
  s /= 100;
  l /= 100;
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => {
    const k = (n + h / 30) % 12;
    const color = l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
    return Math.round(255 * color).toString(16).padStart(2, "0");
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}

export function hashColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  const hue = Math.abs(hash) % 360;
  return hslToHex(hue, 65, 55);
}

export function extractNodesFromJsonData(jsonData: LayoutJsonData | null): CanvasNode[] {
  if (!jsonData?.d) return [];
  return jsonData.d
    .filter((n) => n.a?.["layout.node"] != null && n.p?.position)
    .map((n, idx) => ({
      id: `node-${n.i ?? idx}`,
      displayName: n.p.displayName || "",
      image: n.p.image || "",
      x: n.p.position!.x,
      y: n.p.position!.y,
      width: n.p.width || 60,
      height: n.p.height || 40,
      color: hashColor(n.p.displayName || ""),
      a: n.a ? { ...n.a } : undefined,
    }));
}

function parseFontStyle(font?: string): { fontSize?: string; fontWeight?: string } {
  if (!font) return {};
  const parts = font.split(/\s+/);
  let fontWeight: string | undefined;
  let fontSize: string | undefined;
  for (const p of parts) {
    if (p === "bold" || p === "normal" || p === "bolder" || p === "lighter") {
      fontWeight = p;
    } else if (/^\d+px$/.test(p) || /^\d+pt$/.test(p)) {
      fontSize = p;
    }
  }
  return { fontSize, fontWeight };
}

export function extractDecorationsFromJsonData(jsonData: LayoutJsonData | null): DecorationNode[] {
  if (!jsonData?.d) return [];
  return jsonData.d
    .filter((n) => n.p?.position && n.a?.["layout.node"] == null)
    .map((n) => {
      const base = {
        x: n.p.position!.x,
        y: n.p.position!.y,
        width: n.p.width || 0,
        height: n.p.height || 0,
      };
      if (n.c === "ht.Text") {
        const s = n.s || {};
        const { fontSize, fontWeight } = parseFontStyle(s["text.font"] as string | undefined);
        return {
          ...base,
          type: "text",
          text: (s.text as string) || "",
          color: s["text.color"] as string | undefined,
          fontSize,
          fontWeight,
          textAlign: s["text.align"] as string | undefined,
          opacity: s.opacity as number | undefined,
          verticalAlign: s["layout.v"] as string | undefined,
        } as DecorationNode;
      }
      return {
        ...base,
        type: "image",
        image: n.p.image || "",
        displayName: n.p.displayName || "",
      } as DecorationNode;
    });
}

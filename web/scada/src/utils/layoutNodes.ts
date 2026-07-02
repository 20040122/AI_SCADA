import type { CanvasNode, LayoutJsonData } from "../types/layout";

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
  return jsonData.d.map((n, idx) => ({
    id: `node-${n.i || idx}`,
    displayName: n.p.displayName,
    image: n.p.image || "",
    x: n.p.position.x,
    y: n.p.position.y,
    width: n.p.width || 60,
    height: n.p.height || 40,
    color: hashColor(n.p.displayName),
  }));
}

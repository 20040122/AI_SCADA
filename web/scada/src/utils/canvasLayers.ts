import type { DecorationNode } from "../types/layout";

export function partitionDecorationsForPipes(
  decorations: DecorationNode[],
  canvasWidth: number,
  canvasHeight: number,
): { backgrounds: DecorationNode[]; foregrounds: DecorationNode[] } {
  const backgrounds: DecorationNode[] = [];
  const foregrounds: DecorationNode[] = [];

  for (const decoration of decorations) {
    const coversCanvas =
      decoration.type === "image" &&
      canvasWidth > 0 &&
      canvasHeight > 0 &&
      decoration.width >= canvasWidth &&
      decoration.height >= canvasHeight;

    if (coversCanvas) {
      backgrounds.push(decoration);
    } else {
      foregrounds.push(decoration);
    }
  }

  return { backgrounds, foregrounds };
}

import type { CanvasNode } from "../types/layout.ts";

export function getLeadLength(node: CanvasNode): number {
  return Math.min(60, Math.max(20, Math.min(node.width, node.height) * 0.2));
}

export function getEdgeCenter(node: CanvasNode, port: string): { x: number; y: number } {
  switch (port) {
    case "right": return { x: node.x + node.width / 2, y: node.y };
    case "left": return { x: node.x - node.width / 2, y: node.y };
    case "top": return { x: node.x, y: node.y - node.height / 2 };
    case "bottom": return { x: node.x, y: node.y + node.height / 2 };
    default: return { x: node.x, y: node.y };
  }
}

export function getLeadEnd(edge: { x: number; y: number }, port: string, length: number): { x: number; y: number } {
  switch (port) {
    case "right": return { x: edge.x + length, y: edge.y };
    case "left": return { x: edge.x - length, y: edge.y };
    case "top": return { x: edge.x, y: edge.y - length };
    case "bottom": return { x: edge.x, y: edge.y + length };
    default: return edge;
  }
}

import type { BindingTarget } from "../types/binding";

export interface PanelBuildPlan {
  node_i: number;
  displayName: string;
  oldCount: number | null;
  newCount: number;
}

export function buildPanelPlan(
  items: Array<{ confirmed: boolean; target_node_i: number | null }>,
  targets: BindingTarget[]
): PanelBuildPlan[] {
  const targetByNode = new Map(targets.map((t) => [t.node_i, t]));
  const counts = new Map<number, number>();
  for (const it of items) {
    if (!it.confirmed) continue;
    if (it.target_node_i === null || it.target_node_i === undefined) continue;
    counts.set(it.target_node_i, (counts.get(it.target_node_i) ?? 0) + 1);
  }
  const plan: PanelBuildPlan[] = [];
  for (const [node_i, newCount] of counts) {
    const target = targetByNode.get(node_i);
    const existing = target?.existing;
    let oldCount: number | null = 0;
    if (Array.isArray(existing)) {
      oldCount = existing.length;
    } else if (existing !== null && existing !== undefined) {
      oldCount = null;
    }
    plan.push({
      node_i,
      displayName: target?.displayName ?? "",
      oldCount,
      newCount,
    });
  }
  plan.sort((a, b) => a.node_i - b.node_i);
  return plan;
}

export function needsReplaceConfirm(plan: PanelBuildPlan[]): boolean {
  return plan.some((p) => p.oldCount === null || p.oldCount > 0);
}

export function canBuildBinding(params: {
  hasMatch: boolean;
  confirmedCount: number;
  matchBlocked: boolean;
  refineBlocked: boolean;
  alreadyBuilt: boolean;
}): boolean {
  const { hasMatch, confirmedCount, matchBlocked, refineBlocked, alreadyBuilt } = params;
  return (
    hasMatch &&
    confirmedCount >= 1 &&
    !matchBlocked &&
    !refineBlocked &&
    !alreadyBuilt
  );
}

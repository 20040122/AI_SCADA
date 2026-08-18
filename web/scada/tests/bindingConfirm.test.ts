import assert from "node:assert/strict";
import test from "node:test";
import {
  buildPanelPlan,
  canBuildBinding,
  needsReplaceConfirm,
  type PanelBuildPlan,
} from "../src/utils/bindingConfirm.ts";
import type { BindingTarget } from "../src/types/binding.ts";

function makeItem(rowNumber: number, node_i: number | null, confirmed: boolean) {
  return { row_number: rowNumber, target_node_i: node_i, confirmed };
}

function makeTarget(node_i: number, existing: unknown): BindingTarget {
  return {
    node_i,
    node_id: node_i,
    displayName: "状态面板",
    handler: "panel_list",
    existing,
  };
}

test("canBuildBinding requires at least one confirmed row", () => {
  const base = {
    hasMatch: true,
    matchBlocked: false,
    refineBlocked: false,
    alreadyBuilt: false,
  };
  assert.equal(canBuildBinding({ ...base, confirmedCount: 0 }), false);
  assert.equal(canBuildBinding({ ...base, confirmedCount: 1 }), true);
  assert.equal(canBuildBinding({ ...base, confirmedCount: 2 }), true);
});

test("canBuildBinding blocks on no match / blocked / already built", () => {
  const base = {
    hasMatch: true,
    confirmedCount: 1,
    matchBlocked: false,
    refineBlocked: false,
    alreadyBuilt: false,
  };
  assert.equal(canBuildBinding({ ...base, hasMatch: false }), false);
  assert.equal(canBuildBinding({ ...base, matchBlocked: true }), false);
  assert.equal(canBuildBinding({ ...base, refineBlocked: true }), false);
  assert.equal(canBuildBinding({ ...base, alreadyBuilt: true }), false);
});

test("buildPanelPlan counts confirmed rows per panel sorted by node_i", () => {
  const items = [
    makeItem(2, 0, true),
    makeItem(3, 0, true),
    makeItem(4, 1, false),
    makeItem(5, 2, true),
  ];
  const targets = [makeTarget(0, null), makeTarget(1, null), makeTarget(2, [])];
  const plan = buildPanelPlan(items, targets);
  assert.deepEqual(plan, [
    { node_i: 0, displayName: "状态面板", oldCount: 0, newCount: 2 },
    { node_i: 2, displayName: "状态面板", oldCount: 0, newCount: 1 },
  ]);
});

test("buildPanelPlan reports old array length and malformed as unknown", () => {
  const items = [makeItem(2, 0, true), makeItem(3, 1, true)];
  const targets = [makeTarget(0, [{ old: 1 }]), makeTarget(1, "oops")];
  const plan = buildPanelPlan(items, targets);
  assert.deepEqual(plan, [
    { node_i: 0, displayName: "状态面板", oldCount: 1, newCount: 1 },
    { node_i: 1, displayName: "状态面板", oldCount: null, newCount: 1 },
  ]);
});

test("buildPanelPlan ignores unconfirmed suggestions", () => {
  const items = [makeItem(2, 0, false), makeItem(3, 1, true)];
  const targets = [makeTarget(0, [{ old: 1 }]), makeTarget(1, null)];
  const plan = buildPanelPlan(items, targets);
  assert.deepEqual(plan, [
    { node_i: 1, displayName: "状态面板", oldCount: 0, newCount: 1 },
  ]);
});

test("needsReplaceConfirm only for non-empty or malformed old values", () => {
  const plan: PanelBuildPlan[] = [
    { node_i: 0, displayName: "状态面板", oldCount: 0, newCount: 1 },
  ];
  assert.equal(needsReplaceConfirm(plan), false);
  assert.equal(needsReplaceConfirm([{ ...plan[0], oldCount: 2 }]), true);
  assert.equal(needsReplaceConfirm([{ ...plan[0], oldCount: null }]), true);
  assert.equal(needsReplaceConfirm([]), false);
});

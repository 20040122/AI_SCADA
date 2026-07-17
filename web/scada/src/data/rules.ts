import { controlSchema, controlDerivedRules, controlSampleOk, controlSampleBad } from "./controlSchema";
import { canvasSchema, canvasDerivedRules, canvasSampleOk, canvasSampleBad } from "./canvasSchema";
import { bindingSchema, bindingDerivedRules, bindingSampleOk, bindingSampleBad } from "./bindingSchema";
import { layoutDerivedRules, layoutSampleOk, layoutSampleBad } from "./layoutConfig";

export interface RuleCategory {
  id: string;
  label: string;
  icon: string;
  schema: { title: string; description: string; properties: { name: string; type: string; required: boolean; description: string; enum?: string[] }[] };
  derivedRules: string[];
  sampleOk: Record<string, unknown>;
  sampleBad: Record<string, unknown>;
}

export const ruleCategories: RuleCategory[] = [
  {
    id: "control",
    label: "控件资源与尺寸",
    icon: "🧩",
    schema: controlSchema,
    derivedRules: controlDerivedRules,
    sampleOk: controlSampleOk as Record<string, unknown>,
    sampleBad: controlSampleBad as Record<string, unknown>,
  },
  {
    id: "canvas",
    label: "画布与编辑行为",
    icon: "🖼️",
    schema: canvasSchema,
    derivedRules: canvasDerivedRules,
    sampleOk: canvasSampleOk as Record<string, unknown>,
    sampleBad: canvasSampleBad as Record<string, unknown>,
  },
  {
    id: "layout",
    label: "布局与拓扑",
    icon: "🔗",
    schema: { title: "布局意图 (LayoutIntent)", description: "布局与拓扑约束 — 角色尺寸、区域排列、附件关系、连线合法性", properties: [] },
    derivedRules: layoutDerivedRules,
    sampleOk: layoutSampleOk as Record<string, unknown>,
    sampleBad: layoutSampleBad as Record<string, unknown>,
  },
  {
    id: "binding",
    label: "数据绑定与通信",
    icon: "📡",
    schema: bindingSchema,
    derivedRules: bindingDerivedRules,
    sampleOk: bindingSampleOk as Record<string, unknown>,
    sampleBad: bindingSampleBad as Record<string, unknown>,
  },
];
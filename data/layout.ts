// layoutRules.ts

export type Region = "left" | "right" | "center";
export type Side = "top" | "right" | "bottom" | "left";
export type Arrangement = "vertical" | "horizontal" | "grid";
export type GapHint = "tight" | "normal" | "loose";
export type GridOrder = "row-major" | "col-major";

export type Role = "root" | "valve" | "pipe" | "meter" | "sensor" | "default";

export interface DeviceNode {
  id: string;
  deviceType: string;
  role?: Role;
}

export interface AttachmentNode extends DeviceNode {
  relativeTo: string;
  side: Side;
  count?: number;
}

export interface LayoutUnit {
  root: DeviceNode;
  attachments: AttachmentNode[];
}

export interface LayoutGroup {
  id: string;
  region: Region;
  unit: LayoutUnit;
  count: number;
  arrangement?: Arrangement;
  gapHint?: GapHint;
  columns?: number;
  rows?: number;
  order?: GridOrder;
}

export interface LayoutIntent {
  groups: LayoutGroup[];
}

export interface LayoutFile {
  layoutIntent: LayoutIntent;
}

export interface ValidationError {
  path: string;
  message: string;
}

/**
 * 布局规则约束：
 * 1. group.id 必须唯一
 * 2. group.count 必须大于等于 1
 * 3. root.id 必须存在
 * 4. attachment.relativeTo 必须引用 root 或前面已声明的 attachment
 * 5. attachment.count 如果存在，必须大于等于 1
 * 6. count > 1 时建议声明 arrangement
 * 7. region 只能是 left / right / center
 * 8. side 只能是 top / right / bottom / left
 * 9. arrangement=grid 时，columns 或 rows 至少一个 >= 1；两者都给时 rows*columns >= count
 * 10. columns/rows/order 仅在 arrangement=grid 时有效
 */
export function validateLayoutFile(file: LayoutFile): ValidationError[] {
  const errors: ValidationError[] = [];

  if (!file.layoutIntent?.groups?.length) {
    errors.push({
      path: "layoutIntent.groups",
      message: "groups 不能为空",
    });
    return errors;
  }

  const groupIds = new Set<string>();
  const groupNodeIds = new Map<string, Set<string>>();

  file.layoutIntent.groups.forEach((group, groupIndex) => {
    const groupPath = `layoutIntent.groups[${groupIndex}]`;

    if (groupIds.has(group.id)) {
      errors.push({
        path: `${groupPath}.id`,
        message: `group id 重复：${group.id}`,
      });
    }
    groupIds.add(group.id);

    if (group.count < 1) {
      errors.push({
        path: `${groupPath}.count`,
        message: "group.count 必须大于等于 1",
      });
    }

    if (group.count > 1 && !group.arrangement) {
      errors.push({
        path: `${groupPath}.arrangement`,
        message: "当 group.count 大于 1 时，应声明 arrangement",
      });
    }

    if (group.arrangement === "grid") {
      const hasCols = group.columns !== undefined && group.columns >= 1;
      const hasRows = group.rows !== undefined && group.rows >= 1;
      if (!hasCols && !hasRows) {
        errors.push({
          path: `${groupPath}.columns`,
          message: "arrangement=grid 时，columns 或 rows 至少一个 >= 1",
        });
      }
      if (group.columns !== undefined && group.columns < 1) {
        errors.push({
          path: `${groupPath}.columns`,
          message: "columns 必须大于等于 1",
        });
      }
      if (group.rows !== undefined && group.rows < 1) {
        errors.push({
          path: `${groupPath}.rows`,
          message: "rows 必须大于等于 1",
        });
      }
      if (hasCols && hasRows) {
        const cap = (group.columns as number) * (group.rows as number);
        if (cap < group.count) {
          errors.push({
            path: `${groupPath}.rows`,
            message: `grid 容量不足：rows*columns=${cap} < count=${group.count}`,
          });
        }
      }
    } else {
      if (group.columns !== undefined) {
        errors.push({
          path: `${groupPath}.columns`,
          message: "columns 仅在 arrangement=grid 时有效",
        });
      }
      if (group.rows !== undefined) {
        errors.push({
          path: `${groupPath}.rows`,
          message: "rows 仅在 arrangement=grid 时有效",
        });
      }
      if (group.order !== undefined) {
        errors.push({
          path: `${groupPath}.order`,
          message: "order 仅在 arrangement=grid 时有效",
        });
      }
    }

    const rootId = group.unit.root.id;
    const declaredIds = new Set<string>([rootId]);

    group.unit.attachments.forEach((attachment, attachmentIndex) => {
      const attachmentPath = `${groupPath}.unit.attachments[${attachmentIndex}]`;

      if (!declaredIds.has(attachment.relativeTo)) {
        errors.push({
          path: `${attachmentPath}.relativeTo`,
          message: `relativeTo 引用了不存在或尚未声明的节点：${attachment.relativeTo}`,
        });
      }

      if (attachment.count !== undefined && attachment.count < 1) {
        errors.push({
          path: `${attachmentPath}.count`,
          message: "attachment.count 必须大于等于 1",
        });
      }

      declaredIds.add(attachment.id);
    });

    groupNodeIds.set(group.id, declaredIds);
  });

  return errors;
}

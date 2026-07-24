export interface RoleLimit {
  keywords: string[];
  limits: {
    min_w: number;
    min_h: number;
    max_w: number;
    max_h: number;
    preferred_w: number;
    preferred_h: number;
  };
}

export const layoutConfig: {
  root_role_name: string;
  roles: Record<string, RoleLimit>;
} = {
  root_role_name: "root",
  roles: {
    root: {
      keywords: [],
      limits: { min_w: 120, min_h: 120, max_w: 180, max_h: 260, preferred_w: 160, preferred_h: 240 },
    },
    pipe: {
      keywords: ["管"],
      limits: { min_w: 80, min_h: 20, max_w: 180, max_h: 50, preferred_w: 120, preferred_h: 30 },
    },
    valve: {
      keywords: ["阀"],
      limits: { min_w: 40, min_h: 40, max_w: 80, max_h: 80, preferred_w: 60, preferred_h: 60 },
    },
    meter: {
      keywords: ["流量", "表"],
      limits: { min_w: 50, min_h: 50, max_w: 100, max_h: 100, preferred_w: 80, preferred_h: 80 },
    },
    sensor: {
      keywords: ["传感", "压力"],
      limits: { min_w: 50, min_h: 40, max_w: 110, max_h: 90, preferred_w: 80, preferred_h: 60 },
    },
    default: {
      keywords: [],
      limits: { min_w: 50, min_h: 40, max_w: 120, max_h: 120, preferred_w: 80, preferred_h: 80 },
    },
  },
};

export const layoutDerivedRules = [
  "groups 不能为空",
  "group.id 必须唯一",
  "group.count >= 1",
  "当 arrangement=grid 时，columns 或 rows 至少一个 >= 1，且 columns*rows >= count",
  "attachment.relativeTo 必须引用本组已声明的节点",
  "角色尺寸约束：root(120-180x120-260)、pipe(80-180x20-50)、valve(40-80x40-80)、meter(50-100x50-100)、sensor(50-110x40-90)",
];

export const layoutSampleOk = {
  layoutIntent: {
    groups: [
      {
        id: "group1",
        region: "center",
        unit: {
          root: { id: "valve_1", deviceType: "电动调节阀", role: "valve" },
          attachments: [{ id: "sensor_1", deviceType: "压力传感器", role: "sensor", relativeTo: "valve_1", side: "right" }],
        },
        count: 2,
        arrangement: "horizontal",
        gapHint: "normal",
      },
    ],
  },
};

export const layoutSampleBad = {
  layoutIntent: {
    groups: [],
  },
};
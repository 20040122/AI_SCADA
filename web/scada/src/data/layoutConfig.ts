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

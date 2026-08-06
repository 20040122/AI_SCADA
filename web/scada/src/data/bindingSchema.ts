export const bindingSchema = {
  title: "绑定面板 (Binding Panel)",
  description: "数据绑定与通信约束 — 状态面板节点 a[\"panel.list\"] 的绑定项结构（type=designer 变量映射）",
  properties: [
    { name: "panel.list", type: "array", required: true, description: "绑定项数组，每个元素为 {label, bind}" },
    { name: "label", type: "string", required: true, description: "绑定项显示名（属性名）" },
    { name: "bind.type", type: "enum", required: true, description: "绑定类型", enum: ["designer"] },
    { name: "bind.path", type: "string", required: true, description: "绑定路径：<projectId>#<deviceId>#<propertyId>" },
    { name: "bind.key", type: "string", required: true, description: "绑定键：<deviceId>#<propertyId>" },
    { name: "bind.label", type: "string", required: true, description: "展示标签：<项目名> . <设备名> . <属性名> (<单位>)" },
    { name: "bind.proj.id", type: "string", required: true, description: "项目 ID" },
    { name: "bind.proj.name", type: "string", required: true, description: "项目名称" },
    { name: "bind.dev.id", type: "string", required: true, description: "设备 ID" },
    { name: "bind.dev.name", type: "string", required: true, description: "设备名称" },
    { name: "bind.param.id", type: "string", required: true, description: "属性 ID" },
    { name: "bind.param.name", type: "string", required: true, description: "属性名称" },
    { name: "bind.param.unit", type: "string", required: true, description: "单位（可为空）" },
    { name: "bind.param.writable", type: "boolean", required: true, description: "是否可写" },
    { name: "bind.param.dataType", type: "enum", required: true, description: "数据类型", enum: ["double", "int", "bool", "string"] },
    { name: "bind.param.dataTypeDesc", type: "string", required: true, description: "数据类型描述（CSV 值或派生中文名）" },
  ],
  additionalProperties: false,
};

export const bindingDerivedRules = [
  "panel.list 是状态面板节点 a 下的绑定数组，确认重绑后整体替换（不保留旧项）",
  "每个绑定项 bind.type 固定为 designer",
  "bind.path 格式：<projectId>#<deviceId>#<propertyId>（三者均为数字字符串）",
  "bind.param.dataType 仅允许 double|int|bool|string（CSV 的 float/integer 分别归为 double/int）",
  "bind.param.writable 必须与 JSONL 期望一致",
  "同一设备（projectId#deviceId）不得同时分配给多个状态面板",
  "同一可写属性不得被多个绑定复用；只读属性复用仅警告",
  "unit 为空时 bind.label 不得出现空括号",
  "绑定值一律来自 CSV 规范属性，不得用 JSONL 的 path/label 参考值覆盖",
];

export const bindingSampleOk = {
  "panel.list": [
    {
      label: "空气罐温度",
      bind: {
        type: "designer",
        path: "2084524131092914178#2084937599679848450#2084940408848506881",
        key: "2084937599679848450#2084940408848506881",
        label: "Agent . 空气罐 . 空气罐温度 (°C)",
        proj: { id: "2084524131092914178", name: "Agent" },
        dev: { id: "2084937599679848450", name: "空气罐" },
        param: {
          id: "2084940408848506881",
          name: "空气罐温度",
          unit: "°C",
          writable: false,
          dataType: "int",
          dataTypeDesc: "整型",
        },
      },
    },
  ],
};

export const bindingSampleBad = {
  "panel.list": [
    {
      label: "",
      bind: {
        type: "unknown",
        path: "abc#xyz",
        key: "",
        label: "",
        proj: {},
        dev: {},
        param: {
          id: "",
          name: "",
          unit: "",
          writable: "yes",
          dataType: "int16",
          dataTypeDesc: "",
        },
      },
    },
  ],
};

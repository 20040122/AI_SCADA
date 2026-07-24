export const bindingSchema = {
  title: "绑点项 (BindingItem)",
  description: "数据绑定与通信约束 — 控件属性与 PLC 变量的映射关系",
  properties: [
    { name: "controlId", type: "string", required: true, description: "控件 ID" },
    { name: "property", type: "enum", required: true, description: "控件绑定属性", enum: ["status", "value", "visible", "color", "text", "enabled"] },
    { name: "variable", type: "string", required: true, description: "PLC 变量名" },
    { name: "dataType", type: "enum", required: false, description: "变量数据类型", enum: ["bool", "int16", "int32", "float", "string"] },
    { name: "registerAddress", type: "string", required: false, description: "寄存器地址" },
  ],
  additionalProperties: false,
};

export const bindingDerivedRules = [
  "controlId 不应为空",
  "variable 不应为空",
  "若属性为 visible 或 enabled，建议 dataType 为 bool",
  "若属性为 status 或 value，建议 dataType 为数值类型（int16/int32/float）",
  "registerAddress 格式应为标准 PLC 寄存器地址（如 Q0.0、I0.1、DB1.DBX0.0）",
  "若有多个绑点，controlId 应唯一（每个控件只绑一次同一个属性）",
];

export const bindingSampleOk = {
  controlId: "valve_001",
  property: "status",
  variable: "DB1.DBX0.0",
  dataType: "bool",
  registerAddress: "DB1.DBX0.0",
};

export const bindingSampleBad = {
  controlId: "",
  property: "invalid_prop",
  variable: "",
  dataType: "complex",
};
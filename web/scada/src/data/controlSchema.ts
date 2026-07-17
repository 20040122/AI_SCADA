export const controlSchema = {
  title: "控件索引项 (ControlIndexItem)",
  description: "控件资源与尺寸约束",
  properties: [
    { name: "displayName", type: "string", required: true, description: "控件显示名称" },
    { name: "image", type: "string", required: true, description: "控件资源路径（symbols/ 或 assets/ 下的 JSON 或图片文件）" },
    { name: "width", type: "number | null", required: true, description: "控件宽度" },
    { name: "height", type: "number | null", required: true, description: "控件高度" },
    { name: "boundExtend", type: "number", required: false, description: "边界扩展像素值" },
  ],
  additionalProperties: false,
};

export const controlDerivedRules = [
  "image 路径应以 symbols/ 或 assets/ 开头",
  "width 和 height 为 null 时应有合理理由（如占位符）",
  "boundExtend 若存在应 >= 0",
  "displayName 不应为空字符串",
];

export const controlSampleOk = {
  displayName: "电动调节阀",
  image: "symbols/valve_001.json",
  width: 60,
  height: 60,
};

export const controlSampleBad = {
  displayName: "",
  image: "unknown/valve.png",
  width: -1,
  height: "abc",
  boundExtend: -5,
};
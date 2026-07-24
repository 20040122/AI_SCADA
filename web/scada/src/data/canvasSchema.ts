export const canvasSchema = {
  title: "画布 (Canva)",
  description: "画布与编辑行为约束",
  properties: [
    { name: "v", type: "string", required: true, description: "版本号" },
    { name: "p", type: "object", required: true, description: "画布属性，含 layers、autoAdjustIndex、hierarchicalRendering" },
    { name: "a", type: "object", required: true, description: "画布尺寸与行为，含 width、height、fitContent、rectSelectable、pannable、zoomable" },
    { name: "d", type: "array", required: true, description: "数据元素数组" },
    { name: "contentRect", type: "object", required: true, description: "内容边界，含 x、y、width、height" },
  ],
};

export const canvasDerivedRules = [
  "contentRect 应能包含所有 d 元素的坐标范围",
  "d 数组元素应至少包含 c（类型）和 p（属性）字段",
  "layers 至少有一个图层",
  "a.width 和 a.height 应大于 0",
  "contentRect.width 和 height 应大于 0",
];

export const canvasSampleOk = {
  v: "8.0.5",
  p: {
    layers: [{ name: "0", visible: true, selectable: true, movable: true, editable: true }],
    autoAdjustIndex: true,
    hierarchicalRendering: true,
  },
  a: { width: 1920, height: 1080, fitContent: true, rectSelectable: false, pannable: false, zoomable: false },
  d: [
    { c: "ht.Node", i: 17092, p: { displayName: "阀1", image: "symbols/valve_001.json", width: 60, height: 60 } },
  ],
  contentRect: { x: 0, y: 0, width: 1920, height: 1080 },
};

export const canvasSampleBad = {
  v: 123,
  p: null,
  a: { width: -100, height: 0, fitContent: true },
  d: "not an array",
  contentRect: { x: 0, y: 0 },
};
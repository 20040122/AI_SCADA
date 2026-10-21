# AgentI 图纸识别

运行环境为 Python 3.9，沿用现有 OpenCV、Tesseract、视觉接口与素材数据库配置。

## 识别流程

1. 原有检测器生成设备、按钮、状态条、数值框与文字候选。
2. Tesseract 在完整识别图上独立检测文本行，不依赖设备框或固定字符像素高度。
3. 候选缺少名称关联、多个候选位于文字区域，或实例名称多于设备时，自动请求整图设备语义定位。
4. 在每个设备的局部范围内校验前景分布、对齐名称字形，再与现有界面控件合并。
5. 沿用控件命名、标签转写、素材匹配及画布组装。

连接线不作为检测、删除或重建对象。视觉请求使用原始识别图，局部范围校验只估计设备边界；输入图像像素保持不变。设备框内可能包含相邻线段，不输出连接线节点。

## 使用

`main.py` 与 `pipeline.py` 默认使用 `--semantic-mode auto`，只在检测异常时执行语义补检。

```sh
python3 picture/AgentI/main.py --input image03.png
```

`--semantic-mode off` 保留原有检测路径，不运行新增的独立文本检测与语义定位。`--semantic-mode always` 用于主动运行语义定位及调试。

```sh
python3 picture/AgentI/main.py --input image03.png --semantic-mode off
```

原有输入参数、检测结果的 `id/type/bbox/value` 字段和画布组装接口保持兼容。

## 验证与诊断

```sh
python3 -m pytest tests/test_agent_i_semantic.py tests/test_agent_i_detection.py tests/test_agent_i_clean_image.py tests/test_agent_i_ocr.py tests/test_agent_i_name.py tests/test_agent_i_assemble.py -q
```

`pipeline.py` 返回的 `detection.semantic` 描述是否应用补检、触发原因和局部校验失败项。接口或响应校验失败时，保留原有检测结果并记录 `status=failed` 和错误；这表示需要核验，不能视为语义定位成功。

中间目录新增 `independent_text.json` 和 `detection_details.json`。触发视觉定位时另保存 `semantic_response.json`。原有三张检测标注图会反映合并后的结果。

语义定位依赖支持图像输入的已配置模型。模型框和局部前景校验均可能存在误差，复杂背景、遮挡及设备紧密堆叠仍需要独立样本验证。

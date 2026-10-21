# AgentI 图纸识别

运行环境为 Python 3.9，沿用现有 OpenCV、Tesseract、视觉接口与素材数据库配置。

## 识别流程

1. 原有检测器生成设备、按钮、状态条、数值框与文字候选。
2. Tesseract 在完整识别图上独立检测文本行，不依赖设备框或固定字符像素高度。
3. 候选缺少名称关联、多个候选位于文字区域，或实例名称多于设备时，自动请求整图设备语义定位。
4. 当设备数量和尺寸能够一致匹配时，使用 OpenCV 本体框约束视觉坐标；否则在局部范围内校验前景分布。名称支持上下左右关联和多行对齐，再与现有界面控件合并。
5. 沿用控件命名、标签转写、素材匹配及画布组装。数值框需要连续背景，避免蓝色文字被误当成控件；类别尚未确定的重复控件按设备本体、上下文、标签、语义及尺寸分组，只对代表样本分类。代表结果属于白名单时复用于组内实例，未知类别或失败时其余实例分别识别。每个实例的坐标和尺寸独立保留。

OCR 保留不同识别候选，候选冲突、低置信度和空结果会进入视觉转写复核，包括未关联设备的标题等文字。语义定位已经转写的标签保留为 `vision_value`，不被后续 OCR 覆盖。`--no-refine-labels` 可关闭额外的标签及不确定文字复核。

关联标签的 OCR 置信度不低于 60、候选与最终文字一致且状态无需复核时，跳过额外视觉转写；已经视觉转写的文字同样跳过。识别摘要中的 `naming.model_calls`、`naming.reused` 和 `label_refinement.skipped` 分别记录分类请求数、复用分类的实例及跳过复核的文字数。存在 OCR 冲突时仍执行复核，不仅凭高置信度跳过。

原有标签关联失败时，补充短标签、邻近数值框与小型设备的唯一关联，不改变已有检测框或成功的标签关联。通过此关联确认的重复设备按本体颜色、形状与标签字形分组，允许缩放造成的细微像素变化；不同标签或实例编号不共用文字复核结果。分类与文字复核的代表样本失败时，其余实例分别识别。`label_refinement.model_calls` 和 `label_refinement.reused` 记录实际复核请求数与复用项。

上述关联中的重复短标签在视觉复核前按字形交叉校验 OCR。至少三份同字形样本、至少两份多次 OCR 一致的样本，并且一致文字同时获得至少三分之二可靠样本及六成全组候选支持时，使用该文字校正组内错误和不确定结果，避免单次视觉误读扩散。字形不同、证据不足或存在较大分歧时保留原有复核路径，不预设标签内容。原始候选与改写前文字继续保留，校正状态为 `ocr_consensus`，对应条目记录在 `label_refinement.ocr_consensus`。

已存在 `vision_value` 的文字直接保留转写结果，不重复运行 Tesseract，数量记录在 `ocr.skipped_vision`。完整设备坐标匹配保持原有规则；数量不一致或部分匹配无效时，仅校正能够可靠匹配的设备，歧义项保留后续局部校验。AgentI 的视觉客户端关闭 SDK 内层重试，保留现有请求包装器最多三次尝试，不更改其他模块的客户端配置。

画布文字节点根据原图估计字号和颜色，并保留识别出的换行。检测结果保留 `control_kind`、`semantic_name`、`semantic_labels`、`ocr_candidates`、`recognition_status` 和 `text_style` 等诊断字段，原有 `id/type/bbox/value` 字段继续可用。设备坐标匹配依赖 SciPy，已列入 `requirements.txt`。

连接线不作为检测、删除或重建对象。视觉请求使用原始识别图，局部范围校验只估计设备边界；输入图像像素保持不变。设备框内可能包含相邻线段，不输出连接线节点。

`web/scada` 的上传图片布局入口 `/api/canvas/layout/image` 复用此流程，不再将图片转换为文字布局需求。识别使用 1920×1080 无网格图，设备及文字按检测框组装，再等比居中映射到网页设置的画布宽高，字号同步缩放。网页标题用于输出文件名和画布元数据，不额外添加标题节点。每次请求使用独立临时目录及素材快照，未匹配控件和识别失败项通过响应提示；文字布局入口保持原有流程。

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
python3 -m pytest tests/test_agent_i_semantic.py tests/test_agent_i_detection.py tests/test_agent_i_clean_image.py tests/test_agent_i_ocr.py tests/test_agent_i_name.py tests/test_agent_i_assemble.py tests/test_agent_i_oxygen.py -q
```

`pipeline.py` 返回的 `detection.semantic` 描述是否应用补检、触发原因和局部校验失败项。接口或响应校验失败时，保留原有检测结果并记录 `status=failed` 和错误；这表示需要核验，不能视为语义定位成功。

中间目录新增 `independent_text.json` 和 `detection_details.json`。触发视觉定位时另保存 `semantic_response.json`。原有三张检测标注图会反映合并后的结果。

语义定位依赖支持图像输入的已配置模型。模型框和局部前景校验均可能存在误差，复杂背景、遮挡及设备紧密堆叠仍需要独立样本验证。

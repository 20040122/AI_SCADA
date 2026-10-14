生成带坐标网格的图片：
```bash
python3 picture/AgentI/resize_image.py picture/AgentI/input.png picture/AgentI/output.png
```

OpenCV 分层检测（兼容 Python 3.9）：

```bash
python3 -m pip install opencv-python-headless
python3 picture/AgentI/opencv.py
```

自定义输入和结果目录：

```bash
python3 picture/AgentI/opencv.py picture/AgentI/output.png --output-dir picture/AgentI/opencv_output
```

默认结果目录为脚本旁的 `opencv_output`，包含 `01_grid_mask.png` 网格掩膜、`02_grid_removed.png` 去网格图、`03_controls.png` 控件标注图、`04_text.png` 文字区域标注图、`05_hierarchy.png` 综合标注图和 `detections_01.json`。设备与操作控件统一输出为 `controls` 层，C、T 编号分别对应 `controls_N`、`text_N`。重复运行会覆盖同名结果，并移除旧版生成的 `03_components.png`、`04_controls.png`、`05_text.png`、`06_hierarchy.png`。

默认仅检测文字区域。需要通过 OCR 辅助排除带 `#` 的名称时，另外安装 Tesseract 及 `chi_sim`、`eng` 语言包，然后运行：

```bash
python3 picture/AgentI/opencv.py --ocr --ocr-lang chi_sim+eng
```

`detections_01.json` 为元素数组，每个元素包含 `id`、`type`、`bbox`、`value` 四项，`value` 初始为 `null`。设备与操作控件的 `type` 统一为 `controls`，文字区域为 `text`。`bbox` 使用 `[x, y, width, height]`，单位为原图像素。不导出网格节点、统计信息、具体设备类别、置信度或父子关系；文字内容通过独立的 `ocr.py` 回填到新的结果文件。

```json
[
  {"id": "controls_1", "type": "controls", "bbox": [981, 94, 65, 19], "value": null},
  {"id": "text_1", "type": "text", "bbox": [830, 172, 78, 15], "value": null}
]
```

文字在原图上检测，避免网格修复损伤笔画；相邻字符合并后输出紧贴笔画的矩形。文字层排除控件内部文字（包括数值、占位符、按钮和状态条文字）、控件右侧的小单位，以及带 `#` 的控件名称，保留其他外部标签。小单位按尺寸和相邻位置过滤；默认不依赖 OCR，使用多尺度 `#` 字形模板排除当前截图中的编号名称。其他字体或布局可能需要调参，字形与几何规则不能保证所有名称和单位均正确过滤。

启用 OpenCV 脚本的 `--ocr` 时，输入图像仅保留通过筛选的文字区域，识别结果中仍带 `#` 的区域会再次排除。导出的检测框来自 OpenCV，`value` 仍为 `null`；文字回填使用下面的独立 OCR 步骤。

建议使用原始分辨率。缩小图像会改变浅色数值框的颜色及小文字的笔画结构，控件与文字检测可能明显退化。

提取检测元素的空间逻辑（仅使用 Python 3.9 标准库）：

```bash
python3 picture/AgentI/association.py
```

默认读取脚本旁的 `opencv_output/detections.json`，输出同目录的 `associations.json`。可指定输入、输出和像素阈值：

```bash
python3 picture/AgentI/association.py picture/AgentI/opencv_output/detections.json --output /tmp/associations.json --near-distance 60 --alignment-tolerance 10
```

结果包含以下字段：

| 字段 | 含义 |
| --- | --- |
| `nodes` | 原始矩形、中心点、归一化矩形和左中右／上中下区域 |
| `hierarchy_relations` | 输入的父子归属、原始关联依据和是否实际几何包含 |
| `spatial_relations` | 方位、包含、重叠、接触、邻近和中心对齐；附带距离、中心偏移、IoU |
| `component_groups` | 每个设备候选的附属控件和文字，包含经控件间接归属的文字 |
| `unassigned_node_ids` | 没有设备候选祖先的控件或文字 |
| `alignment_groups` | 按元素层级分别提取的行列对齐组，行内从左到右，列内从上到下 |

`spatial_relations` 的关系描述 `source` 相对于 `target`：`left_of`／`right_of`／`above`／`below` 使用矩形边界，斜向分离可同时出现横向和纵向关系；矩形相交时不强行给出方位。`contains`／`inside` 使用严格包含，`same_bbox` 表示矩形相同，`overlaps` 表示部分重叠，`touches` 表示边界接触。`offset` 为目标中心减去源中心。

`near` 使用矩形边缘最短距离，重叠和包含时距离为零。`same_row`／`same_column` 使用中心坐标差。默认邻近距离为 60 像素，对齐容差为 10 像素，均随图宽相对于 1920 的比例缩放；显式参数使用当前图像的像素单位。行列分组内中心坐标跨度不超过容差，组内元素不一定互相邻近。

所有设备候选对均输出空间关系；其他非网格元素对只在邻近阈值内输出。每对元素只输出一次，反向关系可按 `source`／`target` 换算。网格仅参与归属关系，不参与空间元素对，避免整页背景制造无意义的包含关系。

输入的 `parent_id` 与几何包含分别表示：距离推断的归属可能位于设备矩形之外。空间邻近不代表管线连接，当前检测 JSON 缺少管线和箭头信息，不能据此提取工艺流向。设备类别仍为几何候选，未执行 OCR 时文字内容仍为空。

验证空间关系算法：

```bash
python3 -m unittest discover -s tests -p 'test_agent_i_association.py'
```

识别文字并回填 `value`（兼容 Python 3.9）：

```bash
brew install tesseract tesseract-lang
python3 picture/AgentI/ocr.py
```

其他系统需安装 Tesseract 及所需语言包，确保 `tesseract` 位于 PATH；默认语言为 `chi_sim+eng`。脚本使用现有 OpenCV、NumPy 和 Python 标准库，无需安装 `pytesseract`。

默认读取 `output.png` 和 `opencv_output/detections_01.json`，仅识别 `type: "text"` 元素的 `bbox` 区域，将文字写入对应的 `value`。输出 `opencv_output/detections_02.json` 保留全部元素、顺序及其他字段，`controls` 元素原样保留，输入文件不修改。空识别结果写为 `null`；低置信度结果保留，并在终端报告元素 ID 和置信度。重复运行覆盖同名输出文件。

自定义输入、输出、语言及多行模式：

```bash
python3 picture/AgentI/ocr.py --image /path/to/scada.png --detections /path/to/detections.json --output /path/to/recognized.json --ocr-lang chi_sim+eng --psm 6
```

`bbox` 使用输入图片的像素坐标 `[x, y, width, height]`，必须完整位于图片内。应使用生成检测坐标时的未标注原图；`04_text.png` 的绿色边框和 T 编号用于核验，不作为默认 OCR 输入。更换图片尺寸后须提供匹配的检测 JSON，脚本不会猜测坐标缩放比例。

脚本不固定图片尺寸、文字框数量、字号、颜色或标签词表。默认按框高度放大小文字至 48 像素，最多四倍，不缩小大文字，并添加白色边距。通过边缘亮度调整深色背景。默认单行模式同时比较普通单行彩色图、原始单行彩色图和原始单行二值图，以减少短中文标签被当作英文的情况；显式选择模式 13 时比较彩色图和二值图。其他模式在结果为空或平均词置信度低于 60 时尝试二值图。仍不确定时，追加放大前按 Otsu 阈值的 90% 二值化的候选，减少背景线和灰色噪声影响。选择非空且置信度最高的结果。不固定删除青色网格，不硬编码修正标签内容；颜色、网格、字体或低对比度仍可能影响准确率，高置信度也不能保证结果正确。

`--target-height` 调整目标高度；`--min-confidence` 调整重试和告警阈值（0–100）；`--timeout` 调整每次 Tesseract 调用的超时秒数（默认 30）。`--psm` 默认 7（单行），也支持 6（多行文字块）、8（单词）、11（稀疏文字）、13（原始单行）。中文字符间的 OCR 插入空格、标点前的多余空格会移除，紧邻的中英混合字符按几何间距拼接，英文词间空格及多行换行保留。

输入格式错误、非法坐标、缺少语言包、识别进程失败或超时时，脚本以非零状态退出，不部分覆盖输出。全部识别完成后才原子写入结果。当前能力面向水平 SCADA 文字，不包含通用文档版面分析、旋转文字检测或修复上游漏检。

验证文字回填、失败保护及不同字号、配色、背景、网格的真实 OCR：

```bash
python3 -m unittest discover -s tests -p 'test_agent_i_ocr.py'
```

真实 OCR 测试需要 Tesseract 和 `eng` 语言包；未安装 Tesseract 时跳过该项。

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageOps


def create_grid_image(image: Image.Image, step: int = 20) -> Image.Image:
    if not isinstance(step, int) or step <= 0:
        raise ValueError("网格间距必须为正整数。")

    base = image.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    width, height = base.size
    major_step = step * 5
    for x in range(0, width, step):
        major = x % major_step == 0
        color = (0, 150, 190, 155) if major else (80, 210, 235, 70)
        draw.line((x, 0, x, height - 1), fill=color, width=2 if major else 1)
    for y in range(0, height, step):
        major = y % major_step == 0
        color = (0, 150, 190, 155) if major else (80, 210, 235, 70)
        draw.line((0, y, width - 1, y), fill=color, width=2 if major else 1)

    font = ImageFont.load_default()

    def label(text: str, x: int, y: int) -> tuple[int, int]:
        bounds = draw.textbbox((0, 0), text, font=font)
        tile = Image.new(
            "RGBA",
            (bounds[2] - bounds[0] + 2, bounds[3] - bounds[1] + 2),
            (15, 23, 42, 205),
        )
        ImageDraw.Draw(tile).text(
            (1 - bounds[0], 1 - bounds[1]), text, font=font, fill="white"
        )
        x = max(0, min(x, width - tile.width))
        y = max(0, min(y, height - tile.height))
        overlay.alpha_composite(tile, dest=(x, y))
        return x + tile.width, y + tile.height

    origin_right, origin_bottom = label("0,0", 3, 3)
    last_right = origin_right
    for x in range(major_step, width, major_step):
        text = f"X={x}"
        bounds = draw.textbbox((0, 0), text, font=font)
        label_width = bounds[2] - bounds[0] + 2
        left = max(3, min(x - label_width // 2, width - label_width - 3))
        if left >= last_right + 3:
            last_right, _ = label(text, left, 3)
    last_bottom = origin_bottom
    for y in range(major_step, height, major_step):
        text = f"Y={y}"
        bounds = draw.textbbox((0, 0), text, font=font)
        label_height = bounds[3] - bounds[1] + 2
        top = min(y + 3, height - label_height)
        if top > last_bottom + 3:
            _, last_bottom = label(text, 3, top)

    return Image.alpha_composite(base, overlay).convert("RGB")


def resize_image(
    input_path: str | Path,
    output_path: str | Path,
    background: str = "white",
    *,
    grid_step: int = 20,
    clean_output_path: Optional[Path] = None,
) -> None:
    input_path = Path(input_path)
    output_path = Path(output_path)
    if input_path.resolve() == output_path.resolve():
        raise ValueError("输入和输出路径不能相同，以免覆盖原图。")
    if clean_output_path is not None:
        clean_output_path = Path(clean_output_path)
        if clean_output_path.resolve() in (input_path.resolve(), output_path.resolve()):
            raise ValueError("干净图路径不能与输入图片或网格图路径相同。")
    if not isinstance(grid_step, int) or grid_step <= 0:
        raise ValueError("网格间距必须为正整数。")

    target_size = (1920, 1080)
    with Image.open(input_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")
        scaled = ImageOps.contain(
            image, target_size, method=Image.Resampling.LANCZOS
        )

    canvas = Image.new("RGBA", target_size, background)
    offset = (
        (target_size[0] - scaled.width) // 2,
        (target_size[1] - scaled.height) // 2,
    )
    canvas.alpha_composite(scaled, dest=offset)
    if clean_output_path is not None:
        clean_output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(clean_output_path, format="PNG")
    reference = create_grid_image(canvas, grid_step)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    reference.save(output_path, format="PNG")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="等比例缩放并居中补边，生成 1920×1080 网格参考图，可同时输出无网格识别图。"
    )
    parser.add_argument("input", type=Path, help="输入图片路径")
    parser.add_argument("output", type=Path, nargs="?", help="网格图片输出路径（建议使用 .png）")
    parser.add_argument("--clean-output", type=Path, default=None, help="同时输出用于识别的无网格缩放图")
    parser.add_argument(
        "--background", default="white", help="补边颜色，默认 white，可使用 '#ffffff' 等颜色值"
    )
    parser.add_argument(
        "--grid-step", type=int, default=20,
        help="小网格间距（正整数，默认 20 像素），主网格间距为其 5 倍",
    )
    args = parser.parse_args()
    output = args.output or args.input.with_name(f"{args.input.stem}_1920x1080_grid.png")
    try:
        resize_image(
            args.input, output, args.background,
            grid_step=args.grid_step,
            clean_output_path=args.clean_output,
        )
    except (OSError, ValueError) as error:
        parser.exit(1, f"处理失败：{error}\n")
    print(f"已保存网格图片：{output}（1920×1080）")
    print("坐标原点为左上角，X 向右、Y 向下，单位为像素。")


if __name__ == "__main__":
    main()

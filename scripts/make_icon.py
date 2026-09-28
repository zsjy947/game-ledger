"""生成应用图标 scripts/icon.ico（任天堂红圆角底 + 白色 ¥ 符号）。

仅开发时需要：python scripts/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZES = [16, 24, 32, 48, 64, 128, 256]
CANVAS = 512
OUT = Path(__file__).resolve().parent / "icon.ico"


def build() -> None:
    img = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 圆角底（任天堂红，垂直微渐变增强质感）
    radius = 110
    top = (240, 56, 56)
    bottom = (198, 0, 12)
    mask = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(mask).rounded_rectangle([16, 16, CANVAS - 16, CANVAS - 16], radius, fill=255)
    gradient = Image.new("RGBA", (CANVAS, CANVAS))
    gdraw = ImageDraw.Draw(gradient)
    for y in range(CANVAS):
        t = y / CANVAS
        gdraw.line(
            [(0, y), (CANVAS, y)],
            fill=(
                int(top[0] + (bottom[0] - top[0]) * t),
                int(top[1] + (bottom[1] - top[1]) * t),
                int(top[2] + (bottom[2] - top[2]) * t),
                255,
            ),
        )
    img.paste(gradient, (0, 0), mask)

    # 白色 ¥ 符号
    font = None
    for candidate in ("arialbd.ttf", "arial.ttf", "segoeui.ttf"):
        try:
            font = ImageFont.truetype(candidate, 300)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    text = "¥"
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((CANVAS - w) / 2 - bbox[0], (CANVAS - h) / 2 - bbox[1] + 10),
        text,
        font=font,
        fill=(255, 255, 255, 255),
    )

    img.save(OUT, sizes=[(s, s) for s in SIZES])
    print(f"icon written: {OUT}")


if __name__ == "__main__":
    build()

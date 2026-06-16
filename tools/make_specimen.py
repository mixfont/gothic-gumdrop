from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
FONT_PATH = ROOT / "fonts" / "ttf" / "GothicGumdrop-Regular.ttf"
OUT_PATH = ROOT / "documentation" / "gothic-gumdrop-specimen.png"


def main() -> None:
    width, height = 1800, 1050
    image = Image.new("RGB", (width, height), "#050505")
    draw = ImageDraw.Draw(image)

    title_font = ImageFont.truetype(str(FONT_PATH), 205)
    alphabet_font = ImageFont.truetype(str(FONT_PATH), 160)
    description_font = ImageFont.truetype(str(FONT_PATH), 58)

    ink = "#ffffff"

    def draw_centered(text: str, y: int, font: ImageFont.FreeTypeFont) -> None:
        left, _, right, _ = draw.textbbox((0, y), text, font=font)
        x = (width - (right - left)) // 2
        draw.text((x, y), text, font=font, fill=ink)

    draw_centered("GOTHIC GUMDROP", 115, title_font)
    draw_centered("A cute, bubbly blackletter", 340, description_font)
    draw_centered("ABCDEFGHIJKLMNOPQRSTUVWXYZ", 505, alphabet_font)
    draw_centered("abcdefghijklmnopqrstuvwxyz", 675, alphabet_font)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT_PATH)


if __name__ == "__main__":
    main()

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
    alphabet_font = ImageFont.truetype(str(FONT_PATH), 118)
    description_font = ImageFont.truetype(str(FONT_PATH), 58)

    ink = "#ffffff"

    draw.text((100, 115), "Gothic Gumdrop", font=title_font, fill=ink)
    draw.text((106, 340), "A cute, bubbly blackletter", font=description_font, fill=ink)
    draw.text((100, 510), "ABCDEFGHIJKLM", font=alphabet_font, fill=ink)
    draw.text((100, 670), "NOPQRSTUVWXYZ", font=alphabet_font, fill=ink)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT_PATH)


if __name__ == "__main__":
    main()

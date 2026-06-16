from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
FONT_PATH = ROOT / "fonts" / "ttf" / "GothicGumdrop-Regular.ttf"
OUT_PATH = ROOT / "documentation" / "gothic-gumdrop-specimen.png"


def main() -> None:
    width, height = 1800, 1050
    image = Image.new("RGB", (width, height), "#f7f3ec")
    draw = ImageDraw.Draw(image)

    title_font = ImageFont.truetype(str(FONT_PATH), 190)
    large_font = ImageFont.truetype(str(FONT_PATH), 112)
    text_font = ImageFont.truetype(str(FONT_PATH), 72)
    small_font = ImageFont.truetype(str(FONT_PATH), 52)

    ink = "#15120f"
    accent = "#b8342b"

    draw.rectangle((0, 0, width, 16), fill=accent)
    draw.text((90, 90), "Gothic Gumdrop", font=title_font, fill=ink)
    draw.text((96, 320), "A decorative blackletter display face", font=small_font, fill=accent)
    draw.text((90, 430), "ABCDEFGHIJKLM", font=large_font, fill=ink)
    draw.text((90, 560), "NOPQRSTUVWXYZ", font=large_font, fill=ink)
    draw.text((90, 700), "abcdefghijklmnopqrstuvwxyz", font=text_font, fill=ink)
    draw.text((90, 815), "0123456789  ! ? & @ #", font=text_font, fill=ink)
    draw.text((90, 925), "i ì í î ï ī  |  G Ğ g ğ  |  packed glyphs, pointed rhythm", font=small_font, fill=ink)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT_PATH)


if __name__ == "__main__":
    main()

# Gothic Gumdrop

![Gothic Gumdrop specimen](documentation/gothic-gumdrop-specimen.png)

Gothic Gumdrop is a decorative blackletter display typeface with compact rhythm, pointed terminals, and a soft, candy-like texture. It is intended for short words, posters, packaging, game titles, and playful headline settings.

The typeface was generated with Mixfont and refined for open-source release, including normalized accented `i` glyphs, normalized punctuation, and Google Fonts-compatible font metadata.

## Specimens

![Gothic Gumdrop title specimen](documentation/readme-images/gothic-gumdrop-01.webp)

![Gothic Gumdrop phrase specimen](documentation/readme-images/gothic-gumdrop-02.webp)

![Gothic Gumdrop numeral specimen](documentation/readme-images/gothic-gumdrop-03.webp)

## Building

Install the Python dependencies:

```sh
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Build the TTF from source:

```sh
bash sources/build.sh
```

The built font is written to `fonts/ttf/GothicGumdrop-Regular.ttf`.

## Quality Checks

Run FontBakery locally:

```sh
fontbakery check-universal fonts/ttf/GothicGumdrop-Regular.ttf
fontbakery check-googlefonts fonts/ttf/GothicGumdrop-Regular.ttf
```

## License

Gothic Gumdrop is licensed under the SIL Open Font License, Version 1.1. See `OFL.txt` for details.

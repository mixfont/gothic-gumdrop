# Google Fonts submission status

The repository contains the current Regular TTF and the matching designer-supplied
FontLab `.vfc` source. The source and original TTF export are preserved unchanged.
The font has not been submitted to or accepted by Google Fonts.

## Remaining work

1. **Source build:** convert the FontLab source to UFO and establish a reproducible
   open-source build, without modifying the original `.vfc`. The current build
   packages the supplied TTF export; it does not compile or verify the `.vfc`.
2. **GF Latin Core coverage:** add these 16 missing codepoints:

   | Codepoints | Characters |
   | --- | --- |
   | U+0300, U+0301, U+0302, U+0303 | Combining grave, acute, circumflex, tilde |
   | U+0304, U+0306, U+0307, U+0308 | Combining macron, breve, dot above, diaeresis |
   | U+030A, U+030B, U+030C | Combining ring, double acute, caron |
   | U+0327, U+0328 | Combining cedilla, ogonek |
   | U+1E9E | Capital sharp S: ẞ |
   | U+1EF2, U+1EF3 | Y/y with grave: Ỳ, ỳ |

3. **Language shaping:** add zero-width combining marks and positioning anchors.
   The TTF's GPOS has `kern` but no `mark` or `mkmk`. Review U+0326 and
   `uni0326.salt`, which have nonzero advances despite being GDEF marks;
   `uni0326.salt` is also unreachable. Proof decomposed sequences, dotless forms,
   and stacked marks as appropriate. Spacing accents alone do not provide this.
4. **Numerals and design review:** the guide requests proportional default
   numerals and `tnum`; this delivery has no `tnum`. Review that feature and the
   warnings below with the designer, including Windows/browser rendering.
5. **Onboarding:** submit designer profiles/photos, confirm OFL coverage for the
   complete family and source, publish a release, and open a Google Fonts issue
   before a PR. [TRADEMARKS.md](../../TRADEMARKS.md) grants permission to use the
   name; the guide also requests emailing it to fonts@google.com. No email or
   external submission has been sent.

## QA

Run `bash build.sh`, `python tools/verify_release.py`, and `python tools/run_qa.py`
in the environment described in the root README.

The Google Fonts package audit uses FontBakery 1.1.0 with network checks enabled
and no exclusions. The measured result is **155 PASS, 2 FAIL, 13 WARN, 10 INFO,
56 SKIP, and no ERROR/FATAL**. The failures are `googlefonts/glyph_coverage` and
`googlefonts/glyphsets/shape_languages`. The automatic GitHub Actions workflow
has been removed; these checks remain available to run locally before submission.
Reports are generated at `qa/googlefonts-package.{json,md,log}` and are not
committed to the repository.

Warnings cover nonzero-width marks, unreachable glyphs, alternate caron review,
Q's contour count, missing ligature carets, the multiply sign's width, soft hyphen,
collinear/nearly vertical outline segments, placeholder vendor ID, symbols outside
the declared subsets, designer profiles, and the optional article.
Do not suppress checks or declare unsupported scripts merely to remove warnings.

## Current TTF packaging

The prepared TTF is version 1.100 with family name “Gothic Gumdrop”. Its metadata
credits Eric Lu, Alex Kaczun, Mixfont LLC, and Type Innovations Inc. It uses the
canonical OFL text, installable embedding, Latin script tags, and no DSIG.

The release uses typo/hhea metrics 935/-310/0 and Windows metrics 886/250. The
reflected comma component in gcommaaccent is decomposed with at most half a font
unit of rounding. Other outline coordinates, horizontal metrics, GDEF, GPOS, and
GSUB are preserved. Supplied hinting is retained except for the decomposed glyph;
standard smart-dropout instructions and the integer-ppem flag are applied.
`tools/verify_release.py` verifies these properties and repeatable output.

The `.vfc` and original TTF input are never edited by the workflow. The packaged
TTF is a separate submission candidate. Their checksums are recorded under
`sources/release-inputs/`.

## Review package

`build/googlefonts/ofl/gothicgumdrop/` contains the TTF, `OFL.txt`, `TRADEMARKS.md`,
`METADATA.pb`, and `DESCRIPTION.en_us.html`. Metadata templates live beside this
file. The proposed `date_added` must be finalized by Google Fonts, and a real
public source commit/release should be recorded at onboarding.
Package QA runs outside the upstream checkout to avoid duplicate license discovery.

## Official requirements

- [Eligibility](https://googlefonts.github.io/gf-guide/onboarding.html)
- [Repository structure](https://googlefonts.github.io/gf-guide/upstream.html)
- [Source build and production](https://googlefonts.github.io/gf-guide/production.html)
- [Font requirements](https://googlefonts.github.io/gf-guide/requirements.html)
- [Metadata](https://googlefonts.github.io/gf-guide/metadata.html)
- [Submission workflow](https://googlefonts.github.io/gf-guide/making-pr.html)

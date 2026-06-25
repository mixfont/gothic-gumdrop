#!/usr/bin/env python3
"""Add generated Latin top-mark attachment data after TTF export."""

from __future__ import annotations

import argparse
import copy
import unicodedata
from pathlib import Path


DEFAULT_FONT = Path("fonts/ttf/GothicGumdrop-Regular.ttf")
TOP_MARKS = (
    "uni0300",
    "uni0301",
    "uni0302",
    "uni0303",
    "uni0304",
    "uni0306",
    "uni0307",
    "uni0308",
    "uni030A",
    "uni030B",
    "uni030C",
)
EXTRA_BASES = (
    "dotlessi",
    "uni012F.nodot",
    "uni0237",
    "uni25CC",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add GPOS mark attachment for top combining marks."
    )
    parser.add_argument(
        "font",
        nargs="?",
        type=Path,
        default=DEFAULT_FONT,
        help=f"Font file to edit. Defaults to {DEFAULT_FONT}.",
    )
    return parser.parse_args()


def unwrap_extension_lookup(lookup):
    if lookup.LookupType != 9:
        yield lookup
        return

    for subtable in lookup.SubTable:
        extension_lookup = type(lookup)()
        extension_lookup.LookupFlag = lookup.LookupFlag
        extension_lookup.LookupType = subtable.ExtensionLookupType
        extension_lookup.SubTable = [subtable.ExtSubTable]
        yield extension_lookup


def existing_mark_base_pairs(font) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()

    if "GPOS" not in font or not font["GPOS"].table.LookupList:
        return pairs

    for lookup in font["GPOS"].table.LookupList.Lookup:
        for unwrapped in unwrap_extension_lookup(lookup):
            if unwrapped.LookupType != 4:
                continue

            for subtable in unwrapped.SubTable:
                marks = subtable.MarkCoverage.glyphs
                mark_classes = [
                    record.Class for record in subtable.MarkArray.MarkRecord
                ]

                for base_name, base_record in zip(
                    subtable.BaseCoverage.glyphs,
                    subtable.BaseArray.BaseRecord,
                    strict=False,
                ):
                    for mark_name, mark_class in zip(
                        marks,
                        mark_classes,
                        strict=False,
                    ):
                        if base_record.BaseAnchor[mark_class] is not None:
                            pairs.add((base_name, mark_name))

    return pairs


def existing_mark_mark_pairs(font) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()

    if "GPOS" not in font or not font["GPOS"].table.LookupList:
        return pairs

    for lookup in font["GPOS"].table.LookupList.Lookup:
        for unwrapped in unwrap_extension_lookup(lookup):
            if unwrapped.LookupType != 6:
                continue

            for subtable in unwrapped.SubTable:
                mark1_names = subtable.Mark1Coverage.glyphs
                mark1_classes = [
                    record.Class for record in subtable.Mark1Array.MarkRecord
                ]

                for mark2_name, mark2_record in zip(
                    subtable.Mark2Coverage.glyphs,
                    subtable.Mark2Array.Mark2Record,
                    strict=False,
                ):
                    for mark1_name, mark1_class in zip(
                        mark1_names,
                        mark1_classes,
                        strict=False,
                    ):
                        if mark2_record.Mark2Anchor[mark1_class] is not None:
                            pairs.add((mark2_name, mark1_name))

    return pairs


def glyph_bounds(font, glyph_name: str) -> tuple[int, int, int, int] | None:
    if "glyf" not in font or glyph_name not in font["glyf"]:
        return None

    glyph = font["glyf"][glyph_name]
    if glyph.isComposite():
        glyph.recalcBounds(font["glyf"])
    elif glyph.numberOfContours == 0:
        return None

    if not hasattr(glyph, "xMin"):
        glyph.recalcBounds(font["glyf"])

    return glyph.xMin, glyph.yMin, glyph.xMax, glyph.yMax


def mark_anchor(font, mark_name: str) -> tuple[int, int]:
    bounds = glyph_bounds(font, mark_name)
    if bounds is None:
        return (0, 0)

    x_min, y_min, x_max, _ = bounds
    return ((x_min + x_max) // 2, y_min)


def base_anchor(font, glyph_name: str) -> tuple[int, int]:
    bounds = glyph_bounds(font, glyph_name)
    advance_width = font["hmtx"][glyph_name][0]

    if bounds is None:
        return (advance_width // 2, 700)

    x_min, _, x_max, y_max = bounds
    return ((x_min + x_max) // 2, y_max + 20)


def mark_base_glyphs(font) -> list[str]:
    cmap = font.getBestCmap()
    glyph_order = set(font.getGlyphOrder())
    glyphs: set[str] = set()

    for codepoint, glyph_name in cmap.items():
        if glyph_name not in glyph_order:
            continue
        if unicodedata.category(chr(codepoint)).startswith("L"):
            glyphs.add(glyph_name)

    for glyph_name in EXTRA_BASES:
        if glyph_name in glyph_order:
            glyphs.add(glyph_name)

    return sorted(glyphs, key=font.getGlyphID)


def mark_class_name(mark_name: str) -> str:
    return f"@GG_TOP_{mark_name.replace('.', '_')}"


def build_feature(font) -> str | None:
    glyph_order = set(font.getGlyphOrder())
    marks = [mark for mark in TOP_MARKS if mark in glyph_order]
    bases = mark_base_glyphs(font)

    existing_base = existing_mark_base_pairs(font)
    existing_mark = existing_mark_mark_pairs(font)
    desired_base = {
        (base_name, mark_name) for base_name in bases for mark_name in marks
    }
    desired_mark = {
        ("uni0307", mark_name)
        for mark_name in marks
        if mark_name != "uni0307" and "uni0307" in glyph_order
    }

    if not (desired_base - existing_base) and not (desired_mark - existing_mark):
        return None

    lines: list[str] = []
    for mark_name in marks:
        x, y = mark_anchor(font, mark_name)
        lines.append(f"markClass {mark_name} <anchor {x} {y}> {mark_class_name(mark_name)};")

    lines.append("")
    lines.append("feature mark {")

    for base_name in bases:
        base_marks = [mark for mark in marks if (base_name, mark) in desired_base]
        if not base_marks:
            continue

        x, y = base_anchor(font, base_name)
        mark_anchors = " ".join(
            f"<anchor {x} {y}> mark {mark_class_name(mark)}" for mark in base_marks
        )
        lines.append(f"  pos base {base_name} {mark_anchors};")

    if desired_mark:
        for mark2_name in sorted({mark2 for mark2, _ in desired_mark}):
            mark1_names = [mark for mark in marks if (mark2_name, mark) in desired_mark]
            if not mark1_names:
                continue

            x, y = base_anchor(font, mark2_name)
            mark_anchors = " ".join(
                f"<anchor {x} {y}> mark {mark_class_name(mark)}" for mark in mark1_names
            )
            lines.append(f"  pos mark {mark2_name} {mark_anchors};")

    lines.append("} mark;")
    return "\n".join(lines)


def lang_systems(script):
    if script.DefaultLangSys is not None:
        yield script.DefaultLangSys

    for langsys_record in script.LangSysRecord:
        yield langsys_record.LangSys


def add_feature_index(langsys, feature_index: int) -> None:
    if feature_index in langsys.FeatureIndex:
        return

    langsys.FeatureIndex.append(feature_index)
    langsys.FeatureIndex.sort()
    langsys.FeatureCount = len(langsys.FeatureIndex)


def merge_generated_gpos(font, generated_gpos) -> None:
    if "GPOS" not in font:
        font["GPOS"] = copy.deepcopy(generated_gpos)
        return

    target = font["GPOS"].table
    generated = generated_gpos.table

    if generated.LookupList is None or generated.FeatureList is None:
        return

    if target.LookupList is None or target.FeatureList is None or target.ScriptList is None:
        font["GPOS"] = copy.deepcopy(generated_gpos)
        return

    lookup_offset = len(target.LookupList.Lookup)
    target.LookupList.Lookup.extend(copy.deepcopy(generated.LookupList.Lookup))
    target.LookupList.LookupCount = len(target.LookupList.Lookup)

    new_feature_indexes: list[int] = []
    for feature_record in generated.FeatureList.FeatureRecord:
        lookup_indexes = [
            lookup_index + lookup_offset
            for lookup_index in feature_record.Feature.LookupListIndex
        ]
        matching_records = [
            record
            for record in target.FeatureList.FeatureRecord
            if record.FeatureTag == feature_record.FeatureTag
        ]

        if matching_records:
            for record in matching_records:
                for lookup_index in lookup_indexes:
                    if lookup_index not in record.Feature.LookupListIndex:
                        record.Feature.LookupListIndex.append(lookup_index)
                record.Feature.LookupListIndex.sort()
                record.Feature.LookupCount = len(record.Feature.LookupListIndex)
            continue

        new_record = copy.deepcopy(feature_record)
        new_record.Feature.LookupListIndex = lookup_indexes
        new_record.Feature.LookupCount = len(lookup_indexes)
        new_feature_indexes.append(len(target.FeatureList.FeatureRecord))
        target.FeatureList.FeatureRecord.append(new_record)

    target.FeatureList.FeatureCount = len(target.FeatureList.FeatureRecord)

    if not new_feature_indexes:
        return

    for script_record in target.ScriptList.ScriptRecord:
        for langsys in lang_systems(script_record.Script):
            for feature_index in new_feature_indexes:
                add_feature_index(langsys, feature_index)


def main() -> int:
    args = parse_args()

    if not args.font.exists():
        raise SystemExit(f"Font file does not exist: {args.font}")

    try:
        from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
        from fontTools.ttLib import TTFont
    except ModuleNotFoundError as error:
        raise SystemExit(
            "Missing dependency: fontTools. Install project requirements first."
        ) from error

    font = TTFont(args.font)
    feature_code = build_feature(font)

    if feature_code is None:
        print(f"Top mark attachment already present in {args.font}")
        return 0

    generated_font = copy.deepcopy(font)
    addOpenTypeFeaturesFromString(generated_font, feature_code, tables=["GPOS"])
    merge_generated_gpos(font, generated_font["GPOS"])
    font.save(args.font)
    print(f"Added generated top mark attachment to {args.font}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

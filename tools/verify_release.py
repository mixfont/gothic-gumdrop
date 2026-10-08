#!/usr/bin/env python3
"""Check provenance, design preservation, metadata, source integrity, and repeatability."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont
from google.protobuf import text_format
from gftools.fonts_public_pb2 import FamilyProto

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'sources'))
from prepare_release import COPYRIGHT, FAMILY, LICENSE, PS_NAME


def outline(font, name):
    glyphs = font.getGlyphSet()
    pen = DecomposingRecordingPen(glyphs)
    glyphs[name].draw(pen)
    return pen.value


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    manifest = json.loads((ROOT / 'sources/release-inputs/provenance.json').read_text())
    for name, checksum in manifest['inputs'].items():
        assert digest(ROOT / 'sources/release-inputs' / name) == checksum
    assert digest(ROOT / 'sources/GothicGumDrop-Regular.vfc') == manifest['fontlab_source_sha256']
    metadata = text_format.Parse((ROOT / 'documentation/googlefonts/METADATA.pb').read_text(), FamilyProto())
    assert metadata.name == FAMILY and metadata.fonts[0].copyright == COPYRIGHT
    assert (ROOT / 'OFL.txt').read_text().splitlines()[0] == COPYRIGHT
    assert metadata.fonts[0].filename == f'{PS_NAME}.ttf'
    original = TTFont(ROOT / 'sources/release-inputs/GothicGumDrop-Regular.ttf')
    release = TTFont(ROOT / f'fonts/ttf/{PS_NAME}.ttf')
    assert release.getGlyphOrder() == original.getGlyphOrder()
    assert len(release.getGlyphOrder()) == 400
    assert release.getBestCmap() == original.getBestCmap()
    assert len(release.getBestCmap()) == 386
    for table in ('GPOS', 'GSUB', 'GDEF', 'hmtx'):
        assert original[table].compile(original) == release[table].compile(release), table
    for name in original.getGlyphOrder():
        before, after = outline(original, name), outline(release, name)
        assert len(before) == len(after), name
        for (op1, args1), (op2, args2) in zip(before, after):
            assert op1 == op2 and len(args1) == len(args2), name
            for point1, point2 in zip(args1, args2):
                if point1 is None or point2 is None:
                    assert point1 == point2
                else:
                    tolerance = 0.5 if name == 'uni0123' else 0
                    assert all(abs(a-b) <= tolerance for a,b in zip(point1, point2)), name
    assert release['name'].getDebugName(0) == COPYRIGHT
    assert release['name'].getDebugName(1) == FAMILY
    assert release['name'].getDebugName(9) == 'Eric Lu, Alex Kaczun'
    assert release['name'].getDebugName(13) == LICENSE
    assert release['name'].getDebugName(14) == 'https://openfontlicense.org'
    assert 'trademark' in release['name'].getDebugName(7)
    assert abs(release['head'].fontRevision - 1.100) < 0.0001
    assert release['OS/2'].fsType == 0
    assert release['hhea'].ascent == release['OS/2'].sTypoAscender == 935
    assert release['hhea'].descent == release['OS/2'].sTypoDescender == -310
    assert release['hhea'].lineGap == release['OS/2'].sTypoLineGap == 0
    assert 'DSIG' not in release
    outputs = [ROOT / f'fonts/ttf/{PS_NAME}.ttf']
    outputs += list((ROOT / 'build/googlefonts/ofl/gothicgumdrop').iterdir())
    before = {path: digest(path) for path in outputs}
    subprocess.run([sys.executable, str(ROOT / 'sources/prepare_release.py')], check=True)
    assert before == {path: digest(path) for path in outputs}, 'Nonrepeatable packaging'
    print('PASS: input provenance, 400 glyph outlines, cmap, spacing, layout, metadata, source integrity, repeatability')


if __name__ == '__main__':
    verify()

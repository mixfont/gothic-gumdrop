# Font source and release input

`GothicGumDrop-Regular.vfc` is the designer-supplied FontLab source for this
release. It is preserved byte-for-byte as received on October 8, 2026.

`release-inputs/GothicGumDrop-Regular.ttf` is the unmodified desktop TTF from the
October 7 delivery. The adjacent `provenance.json` records the archive, TTF, and
FontLab source checksums.

`prepare_release.py` prepares the submission TTF from that export and assembles
the Google Fonts review package. Run `bash build.sh` from the repository root.
It does not read or modify the `.vfc` file. The current output includes the
metadata, embedding, metrics, and technical adjustments described in the
[submission notes](../documentation/googlefonts/SUBMISSION.md).

An open-source build from the FontLab source has not yet been implemented or
verified against the supplied TTF. Before submission, add a UFO conversion and
reproducible source-build workflow, keeping the original `.vfc` unchanged.
See [Google Fonts production requirements](https://googlefonts.github.io/gf-guide/production.html).

#!/usr/bin/env python3
"""Run unsuppressed QA, isolating the GF package from upstream OFL discovery."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    report = ROOT / 'qa'
    report.mkdir(exist_ok=True)
    fontbakery = str(Path(sys.executable).with_name('fontbakery'))
    results = []

    def run(profile, font, label):
        result = subprocess.run([
            fontbakery, profile, str(font), '--no-progress', '--no-colors',
            '--timeout', '20', '--full-lists',
            '--json', str(report / f'{label}.json'),
            '--ghmarkdown', str(report / f'{label}.md'),
        ], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        (report / f'{label}.log').write_text(result.stdout)
        print(f'{label}: exit {result.returncode}; see qa/{label}.md', flush=True)
        results.append(result.returncode)

    with tempfile.TemporaryDirectory(prefix='gothic-gumdrop-qa-') as temporary:
        package = Path(temporary) / 'ofl/gothicgumdrop'
        shutil.copytree(ROOT / 'build/googlefonts/ofl/gothicgumdrop', package)
        run('check-googlefonts', package / 'GothicGumdrop-Regular.ttf', 'googlefonts-package')
    return 1 if any(results) else 0


if __name__ == '__main__':
    sys.exit(main())

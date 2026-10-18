#!/usr/bin/env python3
"""Download the upstream Linux demos with resume, retries and release checksums."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ASSETS = [
    ('v0.1.0-alpha', 'YOPO-Tracker-Simulator.zip',
     'b39ffdaabdc0f9c94bc245b73254bf34229882cbffccca7c3febbab83db8eec1',
     '.reproduce/downloads/YOPO-Tracker-Simulator.zip', 'simulators/tracker'),
    ('v0.1.1-alpha', 'FPS-Simulator.zip',
     'edf826cf6b1aabeba0f6d0f7816525f9a9c359d1d008fd7d5d6ba50ef48ae70e',
     '.reproduce/downloads/FPS-Simulator.zip', 'simulators/fps'),
    ('v0.1.1-alpha', 'epoch50.pth',
     'd241657cd523ad45e33fb00912b15665061530710e4dbdaa59e5f63cad863c0a',
     'YOPO/saved/YOPO_2/epoch50.pth', None),
]


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    manifest = []
    for tag, name, expected, relative, extraction in ASSETS:
        target = ROOT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        url = f'https://github.com/TJU-Aerial-Robotics/YOPO-Tracker/releases/download/{tag}/{name}'
        for attempt in range(20):
            if target.exists() and sha256(target) == expected:
                break
            print(f'Downloading {name}, attempt {attempt + 1} (resume supported)', flush=True)
            result = subprocess.run(['curl', '-fLsS', '--connect-timeout', '20',
                                     '--max-time', '600', '-C', '-', '-o', str(target), url])
            if result.returncode == 0 and sha256(target) != expected:
                raise RuntimeError(f'{name}: SHA256 mismatch; remove {target} and retry')
            if result.returncode:
                time.sleep(min(2 * (attempt + 1), 10))
        else:
            raise RuntimeError(f'Could not download {name}; rerun ./setup.sh')
        print(f'Checksum OK: {name}', flush=True)
        if extraction:
            destination = ROOT / extraction
            marker = destination / '.sha256'
            if not marker.exists() or marker.read_text().strip() != expected:
                destination.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(target) as archive:
                    archive.extractall(destination)
                for executable in destination.rglob('*'):
                    if executable.is_file() and (executable.suffix in ('.x86_64', '.so') or executable.name == 'UnityCrashHandler64'):
                        executable.chmod(executable.stat().st_mode | 0o111)
                marker.write_text(expected + '\n')
        manifest.append({'url': url, 'path': relative, 'sha256': expected})
    (ROOT / '.reproduce/assets.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()

"""Fetch revision-pinned, attributed source files. Never run on page views."""
from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
HF_REV = '6afc8af044e3bba5f326b688e8cb41d7ff7065ec'


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': 'GgoldeLab/0.1 (historical research)'})
    with urllib.request.urlopen(req, timeout=90) as response:
        return response.read()


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    manifest_path = RAW / 'manifest.json'
    manifest = json.loads(manifest_path.read_text('utf-8')) if manifest_path.exists() else {}
    result_rev = manifest.get('results_revision') or json.loads(get('https://api.github.com/repos/dentearl/kbo-data/commits/main'))['sha']
    manifest.update({'pbp_revision': HF_REV, 'results_revision': result_rev})
    files = manifest.setdefault('files', {})
    for year in (2023, 2024, 2025):
        sources = {
            f'pbp_{year}.parquet': f'https://huggingface.co/datasets/slothman3878/kbo_playbyplay/resolve/{HF_REV}/v0/kbo_pbp_{year}.parquet',
            f'results_{year}.json': f'https://raw.githubusercontent.com/dentearl/kbo-data/{result_rev}/data/kbo/{year}.json',
        }
        for name, url in sources.items():
            path = RAW / name
            if not path.exists():
                print(f'Fetching {name}', flush=True)
                payload = get(url)
                temp = path.with_suffix(path.suffix + '.tmp')
                temp.write_bytes(payload)
                temp.replace(path)
                time.sleep(0.2)
            payload = path.read_bytes()
            files[name] = {'url': url, 'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload)}
    manifest['retrieved_at'] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2), 'utf-8')
    print('Sources cached; ' + str(len(files)) + ' files', flush=True)


if __name__ == '__main__':
    main()

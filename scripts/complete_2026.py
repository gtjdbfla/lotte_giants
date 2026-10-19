"""Complete the partial published 2026 data with revision-pinned relay parsing.

The upstream parser is downloaded into an ignored local cache, never vendored.
Raw commentary stays local. Only derived fields matching the seed schema are emitted.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from fetch_lotte_records import fetch

ROOT = Path(__file__).resolve().parents[1]
PARSER_REV = '95dced9c843eebe76d09da1712426b96eaef936a'
PARSER_ROOT = ROOT / 'data/cache/kbo_extractor'


def main() -> None:
    if not PARSER_ROOT.exists():
        subprocess.run(['git', 'clone', '-q', 'https://github.com/slothman3878/kbo_pbp_naver_sports.git', str(PARSER_ROOT)], check=True)
    actual = subprocess.check_output(['git', '-C', str(PARSER_ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != PARSER_REV:
        raise RuntimeError(f'Parser revision mismatch: expected {PARSER_REV}, got {actual}')
    sys.path.insert(0, str(PARSER_ROOT))
    from kbo_pbp import statcast

    seed = pd.read_parquet(ROOT / 'data/raw/pbp_2026_seed.parquet')
    source_games = []
    page = 1
    while True:
        path = f'/schedule/games?fields=basic,schedule,baseball&upperCategoryId=kbaseball&categoryId=kbo&fromDate=2026-01-01&toDate=2026-12-31&roundCodes=&size=500&page={page}'
        response = fetch(path, ROOT / 'data/cache' / f'2026-schedule-page-{page}.json.gz')['result']
        source_games.extend(response.get('games', []))
        if len(source_games) >= response['gameTotalCount']:
            break
        page += 1
    games = [g for g in source_games if g['roundCode'] == 'kbo_r' and g['statusCode'] == 'RESULT' and not g.get('cancel')]
    if len(games) != 720:
        raise ValueError(f'Expected completed regular season, found {len(games)} games')
    known = set(seed.game_pk)
    missing = [g for g in games if g['gameId'] not in known]
    print(f'2026: published seed {len(known)} games, supplement {len(missing)} games', flush=True)

    def collect(g):
        gid = g['gameId']
        cached_frame = ROOT / 'data/processed/2026' / f'{gid}.parquet'
        if cached_frame.exists():
            return pd.read_parquet(cached_frame)
        last_inning = int(g['statusInfo'].split('회')[0])
        relays = {}
        for inn in range(1, last_inning + 1):
            payload = fetch(f'/schedule/games/{gid}/relay?inning={inn}', ROOT / 'data/cache/relays' / f'{gid}-{inn}.json.gz')
            relays[inn] = payload['result']['textRelayData']
        frame = statcast.game_frame(relays, statcast.meta_from_schedule(g))
        frame = frame.reindex(columns=seed.columns)  # excludes verbatim commentary fields
        frame['game_date'] = pd.to_datetime(frame.game_date).dt.date
        final = frame.drop_duplicates(['game_pk', 'at_bat_number'], keep='first').iloc[-1]
        if (int(final.post_home_score), int(final.post_away_score)) != (g['homeTeamScore'], g['awayTeamScore']):
            raise ValueError(f'{gid}: final-score reconstruction mismatch')
        cached_frame.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(cached_frame, index=False)
        return frame

    frames = [seed]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(collect, g): g['gameId'] for g in missing}
        for done, future in enumerate(concurrent.futures.as_completed(futures), 1):
            frames.append(future.result())
            if done % 20 == 0:
                print(f'2026: {done}/{len(missing)} missing games reconstructed', flush=True)
    full = pd.concat(frames, ignore_index=True)
    full['game_date'] = pd.to_datetime(full.game_date).dt.date
    full = full.sort_values(['game_date', 'game_pk', 'at_bat_number', 'pitch_number']).reset_index(drop=True)
    if set(full.game_pk) != {g['gameId'] for g in games}:
        raise ValueError('Completed game IDs differ from regular-season schedule')
    out = ROOT / 'data/raw/pbp_2026.parquet'
    temp = out.with_suffix('.tmp')
    full.to_parquet(temp, index=False)
    temp.replace(out)
    manifest_path = ROOT / 'data/raw/manifest.json'
    manifest = json.loads(manifest_path.read_text('utf-8'))
    manifest['files']['pbp_2026.parquet'] = {'sha256': hashlib.sha256(out.read_bytes()).hexdigest(), 'bytes': out.stat().st_size, 'sources': ['pbp_2026_seed.parquet', 'NAVER regular-season schedule + relay'], 'seedGames': len(known), 'supplementGames': len(missing), 'parserRepository': 'https://github.com/slothman3878/kbo_pbp_naver_sports', 'parserRevision': PARSER_REV, 'completedAt': datetime.now(timezone.utc).isoformat()}
    manifest_path.write_text(json.dumps(manifest, indent=2), 'utf-8')
    print(f'2026 complete: {full.game_pk.nunique()} games, {len(full)} pitch rows, through {full.game_date.max()}', flush=True)


if __name__ == '__main__':
    main()

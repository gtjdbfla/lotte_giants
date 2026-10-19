"""Resumable small-volume boxscore + error-inning audit; no commentary redistribution."""
from __future__ import annotations

import concurrent.futures
import gzip
import json
import re
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'data' / 'cache'
HEADERS = {'Origin': 'https://m.sports.naver.com', 'User-Agent': 'Mozilla/5.0 (compatible; historical research)'}


def fetch(path: str, cache: Path) -> dict:
    if cache.exists():
        with gzip.open(cache, 'rt', encoding='utf-8') as f:
            return json.load(f)
    url = 'https://api-gw.sports.naver.com' + path
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as resp:
                body = json.load(resp)
            break
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429):
                raise RuntimeError(f'Source access stopped: HTTP {e.code}') from e
            if attempt == 2:
                raise
            time.sleep(1 + attempt)
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(1 + attempt)
    cache.parent.mkdir(parents=True, exist_ok=True)
    temp = cache.with_name(cache.name + '.' + uuid.uuid4().hex + '.tmp')
    with gzip.open(temp, 'wt', encoding='utf-8') as f:
        json.dump(body, f, ensure_ascii=False)
    temp.replace(cache)
    time.sleep(0.2)
    return body


def parse_error_list(text: str, players: dict[str, str]) -> list[dict]:
    errors = []
    for name, count, innings in re.findall(r'([^\s()0-9]+)(\d*)\(([^)]+)\)', text):
        if name not in players:
            continue
        listed = re.findall(r'\d+', innings)
        if len(listed) == 1 and count:
            listed *= int(count)
        for inn in listed:
            errors.append({'name': name, 'id': players[name], 'inning': int(inn)})
    return errors


def one_game(gid: str) -> dict:
    rec = fetch(f'/schedule/games/{gid}/record', CACHE / 'records' / f'{gid}.json.gz')['result']['recordData']
    side = 'home' if rec['gameInfo']['hCode'] == 'LT' else 'away'
    players = {str(p['name']): str(p['playerCode']) for p in rec['battersBoxscore'][side]}
    players.update({str(p['name']): str(p['pcode']) for p in rec['pitchersBoxscore'][side]})
    error_text = next((r['result'] for r in rec['etcRecords'] if r['how'] == '실책'), '')
    errors = parse_error_list(error_text, players)
    box_errors = int(rec['scoreBoard']['rheb'][side]['e'])
    relays = []
    for inn in sorted({e['inning'] for e in errors}):
        raw = fetch(f'/schedule/games/{gid}/relay?inning={inn}', CACHE / 'relays' / f'{gid}-{inn}.json.gz')['result']['textRelayData']
        blocks = sorted(raw.get('textRelays', []), key=lambda b: int(b['no']))
        events = []
        for block in blocks:
            for event in block.get('textOptions', []):
                if event.get('currentGameState'):
                    events.append({'seq': event.get('seqno'), 'type': event.get('type'), 'text': event.get('text', ''), 'state': event['currentGameState'], 'inning': int(block['inn']), 'half': 'top' if str(block['homeOrAway']) == '0' else 'bot'})
        relays.append({'inning': inn, 'events': events})
    return {'id': gid, 'side': side, 'errors': errors, 'box_errors': box_errors, 'relays': relays, 'stadium': rec['gameInfo']['stadium'], 'starters': {s: str(rec['pitchersBoxscore'][s][0]['pcode']) for s in ['home', 'away']}, 'players': players}


def main() -> None:
    out = CACHE / 'lotte_records.json'
    results = {}
    for year in (2023, 2024, 2025, 2026):
        pbp_path = ROOT / 'data' / 'raw' / f'pbp_{year}.parquet'
        if pbp_path.exists():
            df = pd.read_parquet(pbp_path, columns=['game_pk', 'home_team', 'away_team'])
            gids = df.loc[df.home_team.eq('LT') | df.away_team.eq('LT'), 'game_pk'].unique().tolist()
        else:
            # Boxscore audit can run while missing pitch files are being completed.
            games = json.loads((ROOT / 'data/raw' / f'results_{year}.json').read_text('utf-8'))
            gids = [g['gamePk'] + str(year) for g in games if g['status']['detailedState'] == 'Final' and any(g['teams'][s]['team']['abbrev'] == 'LOT' for s in ('home', 'away'))]
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            future_map = {pool.submit(one_game, gid): gid for gid in gids}
            for ix, f in enumerate(concurrent.futures.as_completed(future_map), 1):
                item = f.result()
                results[item['id']] = item
                if ix % 24 == 0:
                    print(f'{year}: {ix}/{len(gids)} records audited', flush=True)
        subset = [r for r in results.values() if r['id'].startswith(str(year))]
        print(f'{year}: box errors={sum(r["box_errors"] for r in subset)}, parsed errors={sum(len(r["errors"]) for r in subset)}', flush=True)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(results, ensure_ascii=False), 'utf-8')
    print('Lotte boxscores and error innings cached', flush=True)


if __name__ == '__main__':
    main()

"""Build audited static research snapshots from local source caches."""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ggolde.engine import EVENTS, TEAMS, VERSION, WinExpectancy, event_context, game_stress, season_summary

OUT = ROOT / 'site' / 'data'
OFFICIAL_ERRORS = {2023: 103, 2024: 123, 2025: 111}


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')), 'utf-8')


def load_year(year: int):
    raw = pd.read_parquet(ROOT / 'data/raw' / f'pbp_{year}.parquet')
    # Outcomes repeat on every pitch. BEFORE is from the first pitch, AFTER from the PA.
    pa = raw.drop_duplicates(['game_pk', 'at_bat_number'], keep='first').reset_index(drop=True)
    pa['game_date'] = pa.game_date.astype(str).str[:10]
    results = json.loads((ROOT / 'data/raw' / f'results_{year}.json').read_text('utf-8'))
    results = {g['gamePk']: g for g in results if g['status']['detailedState'] == 'Final' and g['teams']['home'].get('score') is not None}
    last = pa.groupby('game_pk', sort=False).tail(1)
    mismatches = []
    for r in last.itertuples():
        game = results.get(r.game_pk[:13])
        if not game or (r.post_home_score, r.post_away_score) != (game['teams']['home']['score'], game['teams']['away']['score']):
            mismatches.append(r.game_pk)
    if len(last) != 720 or mismatches:
        raise ValueError(f'{year}: incomplete or mismatched final scores: {mismatches[:10]}')
    return pa, {'year': year, 'pitches': len(raw), 'plateAppearances': len(pa), 'games': len(last), 'finalScoreMismatches': len(mismatches), 'resultGames': len(results), 'firstDate': pa.game_date.min(), 'lastDate': pa.game_date.max()}


def game_payload(gid: str, frame: pd.DataFrame, record: dict | None):
    first = frame.iloc[0]
    last = frame.iloc[-1]
    home, away = first.home_team, first.away_team
    hs, aws = int(last.post_home_score), int(last.post_away_score)
    chart = [[0, 1, 0, 0, 0, round(float(first.we_before), 5), '', '', '시작']]
    for ix, r in enumerate(frame.itertuples(), 1):
        chart.append([ix, int(r.inning), int(r.inning_topbot == 'bot'), int(r.post_home_score), int(r.post_away_score), round(float(r.we_after), 5), str(r.batter_name or ''), str(r.pitcher_name or ''), EVENTS.get(r.events, '주루/타석 종료')])
    meta = {'id': gid, 'date': str(first.game_date), 'home': home, 'away': away, 'homeScore': hs, 'awayScore': aws, 'stadium': record.get('stadium') if record else None, 'sourceUrl': f'https://m.sports.naver.com/game/{gid}/record', 'points': chart}
    rows = []
    for team in [home, away]:
        is_home = team == home
        lost = hs < aws if is_home else aws < hs
        won = hs > aws if is_home else aws > hs
        p = frame.we_after.to_numpy() if is_home else 1 - frame.we_after.to_numpy()
        # Evaluate hope on the states preceding the terminal outcome, not only on final values.
        trajectory = np.r_[frame.we_before.iloc[0] if is_home else 1 - frame.we_before.iloc[0], p]
        innings = np.r_[1, frame.inning.to_numpy()]
        stress = game_stress(trajectory[1:], innings[1:], lost)
        # Promise also exists in games that finish as wins/ties; needed for a valid denominator.
        # A terminal win is the result, not a previously offered opportunity.
        stress['promise'] = bool(np.any((innings[:-1] >= 6) & (trajectory[:-1] >= .65)))
        before_diff = (frame.home_score - frame.away_score).to_numpy() * (1 if is_home else -1)
        late_blown = bool(lost and np.any((frame.inning.to_numpy() >= 7) & (before_diff > 0)))
        tags = []
        if late_blown:
            tags.append('후반 리드 상실')
        if stress['recovery'] > 0:
            tags.append('추격 후 패배')
        if lost and abs(hs - aws) == 1:
            tags.append('1점 차 패배')
        if lost and int(last.inning) > 9:
            tags.append('연장 패배')
        # A game-level error tag only; not pitcher blame or fielder attribution.
        fielding_half = frame.inning_topbot.eq('top' if is_home else 'bot')
        if lost and frame.loc[fielding_half, 'events'].eq('field_error').any():
            tags.append('실책 출루 발생')
        rows.append({**{k: v for k, v in meta.items() if k != 'points'}, 'team': team, 'opponent': away if is_home else home, 'lost': lost, 'won': won, 'tied': hs == aws, 'lateBlown': late_blown, 'tags': tags, **stress})
    return meta, rows


def aggregate_players(pa: pd.DataFrame, game_rows: list[dict], records: dict, season: int):
    losses = {g['id'] for g in game_rows if g['team'] == 'LT' and g['lost']}
    output = {}
    for mode in ['batting', 'pitching', 'starter', 'reliever']:
        batting = mode == 'batting'
        own = (pa.home_team.eq('LT') & pa.inning_topbot.eq('bot' if batting else 'top')) | (pa.away_team.eq('LT') & pa.inning_topbot.eq('top' if batting else 'bot'))
        df = pa.loc[own].copy()
        if not batting and mode != 'pitching':
            starters = df.game_pk.map(lambda g: records[g]['starters'][records[g]['side']])
            is_starter = df.pitcher.astype(str).eq(starters)
            df = df[is_starter if mode == 'starter' else ~is_starter].copy()
        is_home = df.home_team.eq('LT').to_numpy()
        before = np.where(is_home, df.we_before, 1 - df.we_before)
        delta = df.home_wpa.to_numpy() * np.where(is_home, 1, -1)
        diff = (df.home_score - df.away_score).to_numpy() * np.where(is_home, 1, -1)
        weights = event_context(before, df.inning.to_numpy(), diff)
        df['context'] = weights
        # Pitcher context includes defense; field-error PAs are excluded, not charged twice.
        valid = np.ones(len(df), bool) if batting else ~df.events.eq('field_error').to_numpy()
        df['stress'] = np.maximum(-delta, 0) * weights * valid * 100
        df['delta'] = delta * 100
        df['opportunity'] = (weights > 0) & valid
        df['lossGame'] = df.game_pk.isin(losses)
        idcol, namecol = ('batter', 'batter_name') if batting else ('pitcher', 'pitcher_name')
        prior = float(df.stress.sum() / max(1, df.opportunity.sum()))
        players = []
        for pid, g in df.groupby(idcol):
            opportunities = int(g.opportunity.sum())
            total = float(g.stress.sum())
            rate = (total + prior * 20) / (opportunities + 20)
            moments = []
            for r in g.nlargest(8, 'stress').itertuples():
                if r.stress <= 0:
                    continue
                moments.append({'game': r.game_pk, 'date': r.game_date, 'inning': int(r.inning), 'half': r.inning_topbot, 'batter': r.batter_name, 'pitcher': r.pitcher_name, 'event': EVENTS.get(r.events, '주루/타석 종료'), 'before': [int(r.home_score), int(r.away_score)], 'after': [int(r.post_home_score), int(r.post_away_score)], 'wpa': round(float(r.delta), 2), 'stress': round(float(r.stress), 2), 'lost': bool(r.lossGame)})
            eligible = len(g) >= (100 if batting else 60) and opportunities >= 15
            players.append({'id': str(pid), 'name': str(g[namecol].dropna().iloc[-1]) if g[namecol].notna().any() else str(pid), 'games': int(g.game_pk.nunique()), 'appearances': len(g), 'opportunities': opportunities, 'total': round(total, 2), 'rate': round(rate * 100, 2), 'rawRate': round(total * 100 / opportunities, 2) if opportunities else 0, 'eligible': eligible, 'lossGameStress': round(float(g.loc[g.lossGame, 'stress'].sum()), 2), 'moments': moments})
        output[mode] = players
    return output


def raw_state(event: dict) -> pd.DataFrame:
    s = event['state']
    inning, bottom, outs = event['inning'], int(event['half'] == 'bot'), int(s['out'])
    bases = [int(str(s.get(f'base{i}', '0')) not in ('0', '', 'None')) for i in (1, 2, 3)]
    if outs >= 3:
        inning += bottom
        bottom = 1 - bottom
        outs = 0
        bases = [0, 0, 0]
    return pd.DataFrame([{'inning': inning, 'bottom': bottom, 'outs': outs, 'diff': int(s['homeScore']) - int(s['awayScore']), 'b1': bases[0], 'b2': bases[1], 'b3': bases[2]}])


def fielding(year: int, records: dict, model: WinExpectancy):
    players = {}
    audit = {'boxErrors': 0, 'observedErrors': 0, 'assignedErrors': 0, 'ambiguousErrors': 0, 'pitcherErrors': 0, 'missedGames': []}
    for gid, game in records.items():
        if not gid.startswith(str(year)):
            continue
        audit['boxErrors'] += game['box_errors']
        side = game['side']
        with gzip.open(ROOT / 'data/cache/records' / f'{gid}.json.gz', 'rt', encoding='utf-8') as f:
            record = json.load(f)['result']['recordData']
        pitcher_ids = {str(p['pcode']) for p in record['pitchersBoxscore'][side]}
        for p in record['battersBoxscore'][side]:
            if p.get('pos') not in ('지', '타', '주'):
                pid = str(p['playerCode'])
                entry = players.setdefault(pid, {'id': pid, 'name': p['name'], 'games': set(), 'errors': 0, 'total': 0., 'moments': []})
                entry['games'].add(gid)
        found = 0
        for relay in game['relays']:
            events = relay['events']
            seen = set()
            prev = None
            for e in events:
                key = (e['seq'], e['type'], e['text'])
                if key in seen:
                    continue
                seen.add(key)
                error_key = side + 'Error'
                if prev is None:
                    prev = e
                    continue
                count = int(e['state'][error_key]) - int(prev['state'][error_key])
                # The defensive half disambiguates same-name opponents (e.g. Kim Sang-su).
                defensive = e['half'] == ('top' if side == 'home' else 'bot')
                if count > 0 and defensive:
                    found += count
                    audit['observedErrors'] += count
                    candidates = {x['id']: x for x in game['errors'] if x['inning'] == e['inning']}
                    named = {pid: x for pid, x in candidates.items() if x['name'] in e['text']}
                    if len(named) == 1:
                        candidates = named
                    if len(candidates) != 1:
                        # Player position names in the relay can distinguish multiple error fielders.
                        posnames = {'유': '유격수', '二': '2루수', '三': '3루수', '一': '1루수', '좌': '좌익수', '우': '우익수', '중': '중견수', '포': '포수'}
                        possible = {}
                        for p in record['battersBoxscore'][side]:
                            pid = str(p['playerCode'])
                            if pid in candidates and posnames.get(p.get('pos'), '!never!') in e['text']:
                                possible[pid] = candidates[pid]
                        if '투수' in e['text'] and str(e['state']['pitcher']) in candidates:
                            possible = {str(e['state']['pitcher']): candidates[str(e['state']['pitcher'])]}
                        candidates = possible
                    if len(candidates) != 1:
                        audit['ambiguousErrors'] += count
                    else:
                        pid, candidate = next(iter(candidates.items()))
                        if pid in pitcher_ids:
                            audit['pitcherErrors'] += count
                        else:
                            before, after = float(model.predict(raw_state(prev))[0]), float(model.predict(raw_state(e))[0])
                            if side == 'away':
                                before, after = 1 - before, 1 - after
                            score_diff = (int(prev['state']['homeScore']) - int(prev['state']['awayScore'])) * (1 if side == 'home' else -1)
                            context = float(event_context(before, e['inning'], score_diff))
                            loss = max(before - after, 0) * context * 100
                            row = players.setdefault(pid, {'id': pid, 'name': candidate['name'], 'games': {gid}, 'errors': 0, 'total': 0., 'moments': []})
                            row['errors'] += count
                            row['total'] += loss
                            row['moments'].append({'game': gid, 'date': f'{gid[:4]}-{gid[4:6]}-{gid[6:8]}', 'inning': e['inning'], 'half': e['half'], 'event': '공식 실책', 'wpa': round((after - before) * 100, 2), 'stress': round(loss, 2), 'before': [int(prev['state']['homeScore']), int(prev['state']['awayScore'])], 'after': [int(e['state']['homeScore']), int(e['state']['awayScore'])]})
                            audit['assignedErrors'] += count
                prev = e
        if found != game['box_errors']:
            audit['missedGames'].append({'id': gid, 'box': game['box_errors'], 'observed': found})
    result = []
    for p in players.values():
        p['games'] = len(p['games'])
        p['total'] = round(p['total'], 2)
        p['moments'] = sorted(p['moments'], key=lambda x: -x['stress'])[:8]
        p['eligible'] = p['games'] >= 30
        result.append(p)
    return result, audit


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    records = json.loads((ROOT / 'data/cache/lotte_records.json').read_text('utf-8'))
    raw_years, coverage = {}, []
    for year in (2023, 2024, 2025):
        pa, report = load_year(year)
        raw_years[year] = pa
        coverage.append(report)
    packs = {}
    diagnostics = []
    for year in (2024, 2025):
        training_years = [y for y in raw_years if y < year]
        model = WinExpectancy().fit(pd.concat([raw_years[y] for y in training_years], ignore_index=True))
        pa = model.apply(raw_years[year])
        ends = pa.groupby('game_pk', sort=False).tail(1).set_index('game_pk')
        outcome = ((ends.post_home_score > ends.post_away_score).astype(float) + .5 * (ends.post_home_score == ends.post_away_score))
        target = pa.game_pk.map(outcome).to_numpy()
        brier = float(np.mean((pa.we_before.to_numpy() - target) ** 2))
        diagnostics.append({'season': year, 'trainedOn': training_years, 'expectedPointsMSE': round(brier, 5), 'constantHalfMSE': round(float(np.mean((.5 - target) ** 2)), 5), 'note': '타석 상태별 기대승점 MSE. 경기 내 관측은 독립 표본이 아님.'})
        print(f'{year}: WE trained on {training_years}, holdout expected-points MSE {brier:.4f}', flush=True)
        allgames = []
        for gid, frame in pa.groupby('game_pk', sort=False):
            payload, rows = game_payload(gid, frame, records.get(gid))
            allgames.extend(rows)
            dump(OUT / 'games' / f'{gid}.json', payload)
        players = aggregate_players(pa, allgames, records, year)
        players['fielding'], field_audit = fielding(year, records, model)
        report = next(c for c in coverage if c['year'] == year)
        report['fielding'] = field_audit
        report['officialLotteErrors'] = OFFICIAL_ERRORS[year]
        report['fieldingBoxTotalMatchesOfficial'] = field_audit['boxErrors'] == OFFICIAL_ERRORS[year]
        if not report['fieldingBoxTotalMatchesOfficial']:
            raise ValueError('Fielding season box totals differ from KBO audit')
        packs[year] = {'season': year, 'teams': season_summary(allgames), 'games': allgames, 'players': players, 'coverage': report, 'model': diagnostics[-1]}
    # A fixed 2024 reference for each role. Never relabel a 2025 seasonal rank as an absolute score.
    for year, pack in packs.items():
        for mode, players in pack['players'].items():
            ref = np.array([p['total'] if mode == 'fielding' else p['rate'] for p in packs[2024]['players'][mode] if p['eligible']])
            for p in players:
                value = p['total'] if mode == 'fielding' else p['rate']
                p['score'] = round(float(100 * np.mean(ref < value)), 1) if len(ref) and p['total'] > 0 else 0.
            pack['players'][mode] = sorted(players, key=lambda p: (p['eligible'], p['score'], p['total']), reverse=True)
        dump(OUT / f'{year}.json', pack)
    manifest = json.loads((ROOT / 'data/raw/manifest.json').read_text('utf-8'))
    meta = {'version': VERSION, 'builtAt': datetime.now(timezone.utc).isoformat(), 'seasons': list(packs), 'defaultSeason': 2025, 'trainingSeasons': [2023], 'teams': TEAMS, 'coverage': coverage, 'models': diagnostics, 'sourceRevision': manifest['pbp_revision'], 'sources': [{'name': 'KBO Play-by-Play · slothman3878', 'url': 'https://huggingface.co/datasets/slothman3878/kbo_playbyplay', 'license': 'CC BY 4.0', 'use': '투구별 파생 자료를 타석별로 재집계'}, {'name': 'KBO Data Pipeline · dentearl', 'url': 'https://github.com/dentearl/kbo-data', 'use': '최종 점수 교차 대조'}, {'name': 'NAVER Sports', 'url': 'https://m.sports.naver.com/kbaseball', 'use': '롯데 경기 박스스코어·실책 이닝 대조'}, {'name': 'KBO 팀 수비 기록', 'url': 'https://www.koreabaseball.com/Record/Team/Defense/Basic.aspx', 'use': '롯데 시즌 실책 합계 대조'}]}
    dump(OUT / 'meta.json', meta)
    dump(ROOT / 'artifacts/coverage.json', {'coverage': coverage, 'models': diagnostics, 'sources': manifest})
    for y, pack in packs.items():
        print(f'{y}: teams top3 {[(p["name"],p["score"]) for p in pack["teams"][:3]]}; field audit {pack["coverage"]["fielding"]}', flush=True)
    print('Static dataset built.', flush=True)


if __name__ == '__main__':
    main()

import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from ggolde.engine import game_stress, season_summary, states
from scripts.fetch_lotte_records import parse_error_list

ROOT = Path(__file__).resolve().parents[1]


class StressMeaningTests(unittest.TestCase):
    def test_wire_to_wire_blowout_is_less_stressful_than_late_collapse(self):
        hopeless = game_stress([.1, .07, .04, 0], [2, 5, 7, 9], True)
        heartbreak = game_stress([.1, .5, .82, .55, 0], [3, 6, 7, 8, 9], True)
        self.assertEqual(hopeless['score'], 0)
        self.assertGreater(heartbreak['score'], 40)

    def test_late_hope_is_worse_than_same_early_peak(self):
        early = game_stress([.9, .3, 0], [1, 5, 9], True)
        late = game_stress([.3, .9, 0], [1, 9, 9], True)
        self.assertGreater(late['score'], early['score'])

    def test_wins_and_ties_do_not_become_hopeful_losses(self):
        self.assertEqual(game_stress([.1, .9, 1], [1, 8, 9], False)['score'], 0)

    def test_repeated_hope_is_capped(self):
        result = game_stress([.2, .9, .3, .9, .3, .9, 0], [5, 6, 7, 8, 8, 9, 9], True)
        self.assertLessEqual(result['score'], 100)
        self.assertEqual(result['cycles'], 3)

    def test_error_count_same_inning_is_not_dropped(self):
        rows = parse_error_list('고승민2(6회) 박승욱(9회)', {'고승민':'1','박승욱':'2'})
        self.assertEqual(len(rows), 3)

    def test_third_out_advances_half_and_clears_bases(self):
        frame = pd.DataFrame({'inning':[8,8], 'inning_topbot':['top','bot'], 'post_outs':[3,3], 'post_home_score':[3,3], 'post_away_score':[2,2], 'post_on_1b':['x','x'], 'post_on_2b':['x','x'], 'post_on_3b':['x','x']})
        output = states(frame, True)
        self.assertEqual(output.inning.tolist(), [8,9])
        self.assertEqual(output.bottom.tolist(), [1,0])
        self.assertEqual(int(output[['outs','b1','b2','b3']].to_numpy().sum()), 0)


class SnapshotAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meta = json.loads((ROOT/'site/data/meta.json').read_text('utf-8'))

    def test_complete_seasons_and_conservation(self):
        for year in self.meta['seasons']:
            pack = json.loads((ROOT/f'site/data/{year}.json').read_text('utf-8'))
            self.assertEqual(len(pack['games']),1440)
            self.assertEqual(sum(t['games'] for t in pack['teams']),1440)
            self.assertTrue(all(t['games']==144 for t in pack['teams']))
            self.assertEqual(sum(t['wins'] for t in pack['teams']),sum(t['losses'] for t in pack['teams']))
            self.assertEqual(pack['coverage']['finalScoreMismatches'],0)
            f=pack['coverage']['fielding']
            self.assertEqual(f['observedErrors'],pack['coverage']['officialLotteErrors'])
            self.assertEqual(f['observedErrors'],f['assignedErrors']+f['ambiguousErrors']+f['pitcherErrors'])
            self.assertFalse(f['missedGames'])
            self.assertLess(max(pack['model']['trainedOn']),year)
            self.assertLess(pack['model']['expectedPointsMSE'],pack['model']['constantHalfMSE'])

    def test_chart_and_zero_winner_stress(self):
        pack = json.loads((ROOT/'site/data/2025.json').read_text('utf-8'))
        for g in pack['games']:
            if not g['lost']:
                self.assertEqual(g['score'],0)
            self.assertTrue(0 <= g['score'] <= 100)
        for path in (ROOT/'site/data/games').glob('*.json'):
            g=json.loads(path.read_text('utf-8'))
            last=g['points'][-1]
            expected=1 if g['homeScore']>g['awayScore'] else 0 if g['homeScore']<g['awayScore'] else .5
            self.assertEqual(last[5],expected)
            self.assertTrue(all(0 <= p[5] <= 1 for p in g['points']))

    def test_pitcher_roles_partition_appearances(self):
        for year in self.meta['seasons']:
            pack=json.loads((ROOT/f'site/data/{year}.json').read_text('utf-8'))
            players=pack['players']
            self.assertEqual(sum(p['appearances'] for p in players['pitching']),sum(p['appearances'] for p in players['starter'])+sum(p['appearances'] for p in players['reliever']))


if __name__ == '__main__':
    unittest.main()

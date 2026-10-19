from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit

VERSION = '0.1.0'
TEAMS = {'LT': '롯데', 'LG': 'LG', 'HT': 'KIA', 'SS': '삼성', 'SK': 'SSG', 'OB': '두산', 'KT': 'KT', 'NC': 'NC', 'HH': '한화', 'WO': '키움'}
EVENTS = {'single': '안타', 'double': '2루타', 'triple': '3루타', 'home_run': '홈런', 'walk': '볼넷', 'hit_by_pitch': '사구', 'strikeout': '삼진', 'field_out': '범타', 'double_play': '병살', 'triple_play': '삼중살', 'sac_bunt': '희생번트', 'sac_fly': '희생플라이', 'field_error': '실책 출루', 'fielders_choice': '야수선택', 'catcher_interference': '타격방해'}


def states(frame: pd.DataFrame, post: bool = False) -> pd.DataFrame:
    prefix = 'post_' if post else ''
    result = pd.DataFrame({
        'inning': frame.inning.astype(int),
        'bottom': frame.inning_topbot.eq('bot').astype(int),
        'outs': frame['post_outs' if post else 'outs_when_up'].astype(int),
        'diff': frame[f'{prefix}home_score'].astype(int) - frame[f'{prefix}away_score'].astype(int),
    }, index=frame.index)
    for i in [1, 2, 3]:
        col = f'{prefix}on_{i}b'
        result[f'b{i}'] = frame[col].notna().astype(int)
    ended = result.outs.ge(3)
    result.loc[ended & result.bottom.eq(1), 'inning'] += 1
    result.loc[ended, 'bottom'] = 1 - result.loc[ended, 'bottom']
    result.loc[ended, 'outs'] = 0
    result.loc[ended, ['b1', 'b2', 'b3']] = 0
    return result


def features(s: pd.DataFrame) -> np.ndarray:
    inn = s.inning.to_numpy(float)
    bot = s.bottom.to_numpy(float)
    outs = s.outs.to_numpy(float)
    diff = s['diff'].to_numpy(float)
    remaining = np.maximum(0.35, (9 - inn) + (6 - 3 * bot - outs) / 6)
    direction = 2 * bot - 1
    runners = (s.b1.to_numpy(float) * .55 + s.b2.to_numpy(float) * .85 + s.b3.to_numpy(float) * 1.05)
    return np.column_stack([
        np.ones(len(s)), diff / np.sqrt(remaining + .5), diff / (remaining + .6),
        direction / np.sqrt(remaining + .7), direction * outs / np.sqrt(remaining + .7),
        direction * runners / np.sqrt(remaining + .5),
        direction * runners * outs / np.sqrt(remaining + .5),
        diff * runners / (remaining + 1.5),
    ])


class WinExpectancy:
    """Fractional-logit expected game points: P(win) + .5 P(tie), not pure P(win)."""
    def fit(self, frame: pd.DataFrame) -> 'WinExpectancy':
        end = frame.groupby('game_pk', sort=False).tail(1).set_index('game_pk')
        final_diff = end.post_home_score - end.post_away_score
        outcomes = final_diff.map(lambda v: 1. if v > 0 else .5 if v == 0 else 0.)
        y = frame.game_pk.map(outcomes).to_numpy(float)
        x = features(states(frame))
        # One game has equal weight regardless of how many plate appearances it contains.
        weight = 80. / frame.groupby('game_pk').game_pk.transform('size').to_numpy(float)
        def objective(beta):
            z = x @ beta
            penalty = .03 * np.sum(beta[1:] ** 2)
            loss = np.sum(weight * (np.logaddexp(0, z) - y * z)) / len(y) + penalty
            grad = x.T @ (weight * (expit(z) - y)) / len(y)
            grad[1:] += .06 * beta[1:]
            return loss, grad
        fitted = minimize(objective, np.zeros(x.shape[1]), jac=True, method='L-BFGS-B')
        if not fitted.success:
            raise RuntimeError(f'WE fit failed: {fitted.message}')
        self.beta = fitted.x
        return self

    def predict(self, state: pd.DataFrame) -> np.ndarray:
        return np.clip(expit(features(state) @ self.beta), .001, .999)

    def apply(self, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.copy()
        frame['we_before'] = self.predict(states(frame))
        frame['we_after'] = self.predict(states(frame, True))
        # Known terminal game outcomes are terminal values, never model features.
        end_idx = frame.groupby('game_pk', sort=False).tail(1).index
        diffs = frame.loc[end_idx, 'post_home_score'] - frame.loc[end_idx, 'post_away_score']
        frame.loc[end_idx, 'we_after'] = np.where(diffs > 0, 1., np.where(diffs < 0, 0., .5))
        frame['home_wpa'] = frame.we_after - frame.we_before
        return frame


def game_stress(probabilities, innings, lost: bool) -> dict:
    p = np.asarray(probabilities, float)
    inn = np.asarray(innings, int)
    if not lost or not len(p):
        return {'score': 0., 'surrender': 0., 'recovery': 0., 'cycles': 0, 'peak': float(p.max()) if len(p) else .5, 'promise': False}
    # Score the hope that existed BEFORE the final result. Start-of-game 50% is excluded.
    late_weight = np.clip((inn - 1) / 8, .1, 1.)
    surrender = float(np.max(np.clip((p - .5) * 2, 0, 1) * late_weight))
    running_low = np.minimum.accumulate(np.r_[.5, p])[:-1]
    eligible = (inn >= 6) & (p >= .45) & (running_low < .35)
    recovery = float(np.max(np.where(eligible, np.clip((p - running_low) / .6, 0, 1), 0)))
    armed = False
    cycles = 0
    for val, inning in zip(p, inn):
        if inning < 6:
            continue
        if val >= .65:
            armed = True
        if armed and val <= .4:
            cycles += 1
            armed = False
    score = 65 * surrender + 25 * recovery + 10 * min(cycles / 2, 1)
    return {'score': round(float(np.clip(score, 0, 100)), 2), 'surrender': round(65 * surrender, 2), 'recovery': round(25 * recovery, 2), 'cycles': cycles, 'peak': round(float(p.max()), 5), 'promise': bool(np.any((inn >= 6) & (p >= .65)))}


def event_context(we, inning, score_diff):
    """Fixed context weights; not LI and not claimed to be official WPA."""
    late = np.clip((np.asarray(inning) - 3) / 6, .15, 1.)
    hope = np.clip((np.asarray(we) - .25) / .5, 0, 1)
    close = np.abs(score_diff) <= 3
    return late * hope * close


def season_summary(games: list[dict]) -> list[dict]:
    rows = []
    losses = [g for g in games if g['lost']]
    prior = np.mean([g['score'] for g in losses]) if losses else 0
    for team in TEAMS:
        played = [g for g in games if g['team'] == team]
        lost = [g for g in played if g['lost']]
        hopeful = [g for g in played if g['promise']]
        total = sum(g['score'] for g in lost)
        rows.append({'team': team, 'name': TEAMS[team], 'games': len(played), 'losses': len(lost), 'wins': sum(g['won'] for g in played), 'ties': sum(g['tied'] for g in played), 'score': round((total + 10 * prior) / (len(lost) + 10), 2) if lost else 0., 'rawMean': round(total / len(lost), 2) if lost else 0., 'total': round(total, 1), 'hopeGames': len(hopeful), 'hopeLosses': sum(g['lost'] for g in hopeful), 'lateBlown': sum(g['lateBlown'] for g in lost), 'comebackLosses': sum(g['recovery'] > 0 for g in lost), 'oneRunLosses': sum(g['lost'] and abs(g['homeScore'] - g['awayScore']) == 1 for g in played)})
    return sorted(rows, key=lambda r: -r['score'])

"""Two chart setups written as fixed rules, and a simulator for the trades they produce.

The undercut
    Long:  price trades below a support level, then within a few bars closes back above
           the level and above both the 10 and 20 bar EMA. Buy the next open, stop under
           the low of the dip.
    Short: the mirror image above a resistance level.
    I draw these levels by eye. A computer cannot, so here "support" is the most recent
    swing low: a bar whose low is the lowest of the bars around it. Same for resistance.

The fair value gap
    Long:  three bars leave a gap between the high of the first and the low of the third.
           If price comes back down to the top of that gap, buy there, stop at the bottom.
    Short: the mirror image.

Every trade risks 1R (entry to stop), aims for a fixed multiple of that, and is closed
after a set number of bars if neither is hit. When a bar touches both the stop and the
target, the stop is assumed to have come first.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Params:
    swing: int = 5           # bars on each side that make a swing low or high
    window: int = 10         # bars allowed between the dip and the reclaim (or the gap and the return)
    target: float = 2.0      # take profit at this many R
    hold: int = 20           # close the trade after this many bars
    cost: float = 0.0002     # cost per side, as a share of price (0.0002 = 0.02%)
    min_risk: float = 0.002  # skip trades whose stop is closer than this share of price
    min_gap: float = 0.25    # a fair value gap must be at least this many ATRs tall
    intraday: bool = False   # if True: flat by the end of each day, no entries in the last two bars


MAIN = Params()
MAIN_15M = Params(intraday=True, hold=26, cost=0.00002)   # about one cent a share each way on SPY


# ---- bars and indicators -------------------------------------------------------------------

def load(path):
    df = pd.read_csv(path)
    df["day"] = df["time"].str[:10]
    return df


def ema(values, span):
    return pd.Series(values).ewm(span=span, adjust=False).mean().to_numpy()


def atr(high, low, close, span=14):
    prev = np.roll(close, 1)
    prev[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    return pd.Series(tr).rolling(span, min_periods=1).mean().to_numpy()


def swing_points(series, n, kind):
    """Indexes of swing lows (kind='low') or highs: the extreme of the n bars either side."""
    out = []
    for i in range(n, len(series) - n):
        w = series[i - n:i + n + 1]
        if kind == "low" and series[i] == w.min() and (w == series[i]).argmax() == n:
            out.append(i)
        if kind == "high" and series[i] == w.max() and (w == series[i]).argmax() == n:
            out.append(i)
    return out


# ---- the simulator -------------------------------------------------------------------------

def simulate(bars, entry_i, entry_price, stop, side, p, check_entry_bar_target=True, last_i=None):
    """Follow one trade bar by bar. Returns (exit index, R after costs, how it ended) or None."""
    o, h, l, c = bars
    risk = (entry_price - stop) * side
    if risk <= 0 or risk / entry_price < p.min_risk:
        return None
    target = entry_price + side * p.target * risk
    end = min(entry_i + p.hold - 1, len(c) - 1)
    if last_i is not None:
        end = min(end, last_i)
    exit_i, exit_price, how = end, c[end], "time"
    for k in range(entry_i, end + 1):
        first = k == entry_i
        hit_stop = l[k] <= stop if side == 1 else h[k] >= stop
        hit_target = h[k] >= target if side == 1 else l[k] <= target
        if hit_stop:
            gapped = (not first) and (o[k] < stop if side == 1 else o[k] > stop)
            exit_i, exit_price, how = k, (o[k] if gapped else stop), "stop"
            break
        if hit_target and (check_entry_bar_target or not first):
            gapped = (not first) and (o[k] > target if side == 1 else o[k] < target)
            exit_i, exit_price, how = k, (o[k] if gapped else target), "target"
            break
    r = (exit_price - entry_price) * side / risk
    r -= 2 * p.cost * entry_price / risk                 # costs, in R
    return exit_i, r, how


def session_ends(days):
    """For each bar, the index of the last bar of its day."""
    last = {}
    for i, d in enumerate(days):
        last[d] = i
    return np.array([last[d] for d in days])


# ---- setup 1: the undercut -----------------------------------------------------------------

def undercut_trades(df, p=MAIN, side=1, wait=True):
    """side=1: dip below a swing low then reclaim. side=-1: poke above a swing high then lose it.

    wait=False is the impatient version, used only as a comparison: it does not wait for the
    reclaim and buys the open of the bar after the dip, with the stop under that dip bar.
    """
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    e10, e20 = ema(c, 10), ema(c, 20)
    ends = session_ends(df["day"].to_numpy()) if p.intraday else None
    probe = l if side == 1 else h                       # the price that pierces the level
    swings = swing_points(probe, p.swing, "low" if side == 1 else "high")
    confirmed = {i + p.swing: i for i in swings}        # bar on which a swing becomes known -> the swing bar
    trades, level, level_i, pending, busy_until = [], None, None, None, -1
    for t in range(len(c)):
        if pending is None and level is not None and t > level_i + p.swing:
            pierced = l[t] < level if side == 1 else h[t] > level
            if pierced:
                pending = {"level": level, "start": t, "extreme": probe[t]}
                level = None                            # a level is used once
        if pending is not None:
            pending["extreme"] = min(pending["extreme"], l[t]) if side == 1 else max(pending["extreme"], h[t])
            reclaimed = (c[t] > max(e10[t], e20[t], pending["level"])) if side == 1 else (c[t] < min(e10[t], e20[t], pending["level"]))
            if reclaimed or not wait:
                e = t + 1
                ok = e < len(c) and e > busy_until
                if ok and p.intraday:
                    ok = ends[e] == ends[t] and e <= ends[e] - 2      # same day, not in the last two bars
                if ok:
                    res = simulate((o, h, l, c), e, o[e], pending["extreme"], side, p, last_i=ends[e] if p.intraday else None)
                    if res:
                        x, r, how = res
                        trades.append(_row(df, "Undercut", side, pending["start"], e, x, o[e], pending["extreme"], r, how, pending["level"]))
                        busy_until = x
                pending = None
            elif t - pending["start"] >= p.window:
                pending = None
        if t in confirmed:                              # a newer swing replaces the level we watch
            level, level_i = probe[confirmed[t]], confirmed[t]
    return trades


# ---- setup 2: the fair value gap -----------------------------------------------------------

def gap_trades(df, p=MAIN, side=1):
    """side=1: gap up left behind, buy the return to its top. side=-1: the mirror."""
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    a = atr(h, l, c)
    ends = session_ends(df["day"].to_numpy()) if p.intraday else None
    trades, pending, busy_until = [], None, -1
    for t in range(2, len(c)):
        if pending is not None and t > pending["made"]:
            near, far = pending["near"], pending["far"]
            touched = l[t] <= near if side == 1 else h[t] >= near
            if touched:
                entry = min(o[t], near) if side == 1 else max(o[t], near)
                filled_at_open = o[t] <= far if side == 1 else o[t] >= far
                ok = t > busy_until and not filled_at_open
                if ok and p.intraday:
                    ok = ends[t] == ends[pending["made"]] and t <= ends[t] - 2
                if ok:
                    res = simulate((o, h, l, c), t, entry, far, side, p, check_entry_bar_target=False, last_i=ends[t] if p.intraday else None)
                    if res:
                        x, r, how = res
                        trades.append(_row(df, "Fair value gap", side, pending["made"], t, x, entry, far, r, how, near))
                        busy_until = x
                pending = None
            elif t - pending["made"] >= p.window:
                pending = None
        size = (l[t] - h[t - 2]) if side == 1 else (l[t - 2] - h[t])
        if size > 0 and size >= p.min_gap * a[t]:
            near, far = (l[t], h[t - 2]) if side == 1 else (h[t], l[t - 2])
            pending = {"made": t, "near": near, "far": far}      # the newest gap is the one we watch
    return trades


def _row(df, setup, side, signal_i, entry_i, exit_i, entry, stop, r, how, level):
    return {"setup": setup, "side": "Long" if side == 1 else "Short", "signal": df["time"].iloc[signal_i],
            "entry_time": df["time"].iloc[entry_i], "exit_time": df["time"].iloc[exit_i],
            "level": round(float(level), 4), "entry": round(float(entry), 4), "stop": round(float(stop), 4),
            "risk_pct": round(float(abs(entry - stop) / entry * 100), 3), "bars": int(exit_i - entry_i + 1),
            "r": round(float(r), 4), "ended": how}


def before_costs(trades, p):
    """R of each trade with the cost added back."""
    return trades["r"] + 2 * p.cost / (trades["risk_pct"] / 100)


def all_trades(df, p=MAIN):
    rows = []
    for fn in (undercut_trades, gap_trades):
        for side in (1, -1):
            rows += fn(df, p, side)
    return pd.DataFrame(rows)


# ---- what the same trades would have made at random times ----------------------------------

def random_baseline(df, trades, p, draws=200, seed=7):
    """For each real trade, take trades of the same direction, stop distance and exit rules
    at `draws` random bars. Returns the R of every one of them."""
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    ends = session_ends(df["day"].to_numpy()) if p.intraday else None
    rng = np.random.default_rng(seed)
    q = Params(swing=p.swing, window=p.window, target=p.target, hold=p.hold, cost=p.cost, min_risk=0.0, min_gap=p.min_gap, intraday=p.intraday)
    out = []
    for risk_pct, side in zip(trades["risk_pct"].to_numpy() / 100, np.where(trades["side"] == "Long", 1, -1)):
        for e in rng.integers(25, len(c) - 1, size=draws):
            if p.intraday and e > ends[e] - 2:
                continue
            stop = o[e] * (1 - side * risk_pct)
            res = simulate((o, h, l, c), e, o[e], stop, side, q, last_i=ends[e] if p.intraday else None)
            if res:
                out.append(res[1])
    return np.array(out)


def summarize(r):
    r = np.asarray(r, float)
    if len(r) == 0:
        return {"trades": 0, "win_rate": float("nan"), "avg_r": float("nan"), "total_r": 0.0}
    return {"trades": int(len(r)), "win_rate": float((r > 0).mean()), "avg_r": float(r.mean()), "total_r": float(r.sum())}


def chance_of_beating(actual_mean, n, pool, draws=5000, seed=11):
    """Share of random sets of n baseline trades whose average R is at least the real average."""
    if n == 0 or len(pool) == 0:
        return float("nan")
    rng = np.random.default_rng(seed)
    means = rng.choice(pool, size=(draws, n), replace=True).mean(axis=1)
    return float((means >= actual_mean).mean())

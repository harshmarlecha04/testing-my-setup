"""Tests for setups.py and backtest.py.

The first group builds a handful of price bars by hand and checks the rules and the
simulator against answers worked out on paper. The second checks that a trade never
depends on prices that come after it. The third checks results/ and README.md agree.

    pytest
"""
import os
import re

import numpy as np
import pandas as pd
import pytest

import backtest as b
import setups as s

HERE = os.path.dirname(os.path.abspath(__file__))
P = s.Params(cost=0.0, min_risk=0.0)


def frame(rows):
    """rows of (open, high, low, close). Each bar is its own day."""
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"]).astype(float)
    df["time"] = [f"2020-01-{i + 1:02d}" if i < 31 else f"2020-02-{i - 30:02d}" if i < 60 else f"2020-03-{i - 59:02d}" for i in range(len(df))]
    df["day"] = df["time"]
    return df


def arrays(rows):
    a = np.array(rows, float)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3]


# ---- indicators ----------------------------------------------------------------------------

def test_ema_by_hand():
    out = s.ema(np.array([10.0, 12.0, 14.0]), 3)              # weight 2 / (3 + 1) = 0.5 on the newest bar
    assert list(out) == pytest.approx([10.0, 11.0, 12.5])


def test_swing_low_needs_n_bars_each_side():
    lows = np.array([5, 4, 3, 2, 3, 4, 5, 4, 3], float)
    assert s.swing_points(lows, 2, "low") == [3]
    assert s.swing_points(lows, 2, "high") == [6]
    assert s.swing_points(lows, 4, "low") == []               # only index 4 has four bars each side, and it is not the lowest


def test_swing_low_takes_the_first_of_two_equal_lows():
    lows = np.array([5, 4, 2, 4, 2, 4, 5], float)
    assert s.swing_points(lows, 1, "low") == [2, 4]
    assert s.swing_points(lows, 2, "low") == [2]


# ---- the simulator -------------------------------------------------------------------------

def test_target_hit():
    bars = arrays([(100, 101, 99.5, 100.5), (100.5, 104.2, 100, 104)])
    assert s.simulate(bars, 0, 100, 98, 1, P) == (1, pytest.approx(2.0), "target")


def test_stop_hit():
    bars = arrays([(100, 101, 99.5, 100.5), (100.5, 100.6, 97.5, 98)])
    assert s.simulate(bars, 0, 100, 98, 1, P) == (1, pytest.approx(-1.0), "stop")


def test_stop_counts_first_when_one_bar_touches_both():
    bars = arrays([(100, 104.5, 97.5, 103)])
    assert s.simulate(bars, 0, 100, 98, 1, P)[2] == "stop"


def test_time_exit_at_the_close():
    bars = arrays([(100, 101, 99, 100.5), (100.5, 101.5, 99.5, 101), (101, 101.9, 100, 101.5), (150, 150, 150, 150)])
    p = s.Params(cost=0.0, min_risk=0.0, hold=3)
    assert s.simulate(bars, 0, 100, 98, 1, p) == (2, pytest.approx(0.75), "time")


def test_gap_through_the_stop_fills_at_the_open():
    bars = arrays([(100, 101, 99.5, 100.5), (96, 96.5, 95, 96)])
    i, r, how = s.simulate(bars, 0, 100, 98, 1, P)
    assert how == "stop" and r == pytest.approx(-2.0)


def test_short_trade():
    bars = arrays([(100, 100.5, 99, 99.5), (99.5, 100, 95.8, 96)])
    assert s.simulate(bars, 0, 100, 102, -1, P) == (1, pytest.approx(2.0), "target")


def test_costs_come_off_in_r():
    bars = arrays([(100, 101, 99.5, 100.5), (100.5, 104.2, 100, 104)])
    p = s.Params(cost=0.001, min_risk=0.0)                    # 0.1% each way on 100 = 0.20, risk is 2, so 0.1R
    assert s.simulate(bars, 0, 100, 98, 1, p)[1] == pytest.approx(1.9)


def test_a_stop_that_is_too_close_or_on_the_wrong_side_is_skipped():
    bars = arrays([(100, 101, 99, 100)])
    assert s.simulate(bars, 0, 100, 99.9, 1, s.Params(min_risk=0.002)) is None
    assert s.simulate(bars, 0, 100, 101, 1, P) is None


# ---- the undercut --------------------------------------------------------------------------

def undercut_example():
    """Flat at 100, a swing low at 95, then a dip to 94 that closes weak and is reclaimed the next bar."""
    rows = [(100, 100.5, 99.5, 100)] * 20
    rows += [(100, 100.5, 95, 99.5)]                          # bar 20: the swing low, 95
    rows += [(99.5, 100.5, 99, 100)] * 8                      # bars 21 to 28: confirmed after five of them
    rows += [(100, 100.2, 94, 97)]                            # bar 29: the dip, closes below the EMAs
    rows += [(97, 101.2, 96.8, 101)]                          # bar 30: closes above the level and both EMAs
    rows += [(101, 101.5, 100.5, 101)]                        # bar 31: buy at the open, 101
    rows += [(101, 116, 100.8, 115)]                          # bar 32: target is 101 + 2 * (101 - 94) = 115
    rows += [(115, 115.5, 114, 115)] * 8
    return frame(rows)


def test_undercut_long_by_hand():
    t = s.undercut_trades(undercut_example(), P, 1)
    assert len(t) == 1
    trade = t[0]
    assert trade["level"] == 95 and trade["signal"] == "2020-01-30"      # bar 29
    assert trade["entry_time"] == "2020-02-01" and trade["entry"] == 101   # bar 31
    assert trade["stop"] == 94
    assert trade["ended"] == "target" and trade["r"] == pytest.approx(2.0)


def test_no_undercut_trade_without_a_reclaim():
    df = undercut_example()
    df.loc[30:, ["open", "high", "low", "close"]] = [96.0, 96.5, 95.5, 96.0]   # price never comes back
    assert s.undercut_trades(df, P, 1) == []


def test_no_undercut_trade_when_the_reclaim_is_too_late():
    df = undercut_example()
    assert len(s.undercut_trades(df, s.Params(cost=0.0, min_risk=0.0, window=0), 1)) == 0
    assert len(s.undercut_trades(df, s.Params(cost=0.0, min_risk=0.0, window=1), 1)) == 1


def test_undercut_short_is_the_mirror():
    df = undercut_example()
    flipped = df.copy()
    for col, src in (("open", "open"), ("close", "close"), ("high", "low"), ("low", "high")):
        flipped[col] = 200 - df[src]
    t = s.undercut_trades(flipped, P, -1)
    assert len(t) == 1 and t[0]["side"] == "Short" and t[0]["entry"] == 99 and t[0]["stop"] == 106
    assert t[0]["r"] == pytest.approx(2.0)


def test_the_impatient_version_buys_the_bar_after_the_dip():
    t = s.undercut_trades(undercut_example(), P, 1, wait=False)
    assert len(t) == 1
    trade = t[0]
    assert trade["entry_time"] == "2020-01-31" and trade["entry"] == 97      # bar 30, the bar after the dip
    assert trade["stop"] == 94                                               # target is 97 + 2 * 3 = 103, hit on bar 32
    assert trade["ended"] == "target" and trade["r"] == pytest.approx(2.0)


def test_before_costs_adds_the_cost_back():
    p = s.Params(cost=0.001, min_risk=0.0)
    t = pd.DataFrame(s.undercut_trades(undercut_example(), p, 1))
    free = pd.DataFrame(s.undercut_trades(undercut_example(), P, 1))
    assert t["r"].iloc[0] < free["r"].iloc[0]
    assert s.before_costs(t, p).iloc[0] == pytest.approx(free["r"].iloc[0], abs=1e-3)


def intraday_example():
    """Two days of 26 bars. Day one makes a swing low at 99. Day two dips under it late and reclaims it."""
    flat = (100, 100.3, 99.8, 100)
    day1 = [flat] * 10 + [(100, 100.2, 99, 99.9)] + [flat] * 15
    day2 = [flat] * 20 + [(100, 100.1, 98.5, 99.2), (99.2, 100.6, 99.1, 100.5)] + [(100.5, 100.8, 100.3, 100.6)] * 4
    df = pd.DataFrame(day1 + day2, columns=["open", "high", "low", "close"]).astype(float)
    stamps = [f"{9 + (30 + 15 * i) // 60:02d}:{(30 + 15 * i) % 60:02d}" for i in range(26)]
    df["time"] = [f"2025-01-02 {x}" for x in stamps] + [f"2025-01-03 {x}" for x in stamps]
    df["day"] = df["time"].str[:10]
    return df


def test_intraday_trade_is_closed_at_the_end_of_the_day():
    p = s.Params(cost=0.0, min_risk=0.0, intraday=True, hold=26)
    t = s.undercut_trades(intraday_example(), p, 1)
    assert len(t) == 1
    trade = t[0]
    assert trade["level"] == 99 and trade["signal"] == "2025-01-03 14:30"
    assert trade["entry_time"] == "2025-01-03 15:00" and trade["exit_time"] == "2025-01-03 15:45"
    assert trade["ended"] == "time" and trade["r"] == pytest.approx((100.6 - 100.5) / (100.5 - 98.5))


def test_no_intraday_entry_in_the_last_half_hour():
    df = intraday_example()
    late = df.copy()
    late.loc[26 + 20:, ["open", "high", "low", "close"]] = [100.0, 100.3, 99.8, 100.0]
    late.loc[26 + 22, ["open", "high", "low", "close"]] = [100.0, 100.1, 98.5, 99.2]       # dip at 15:00
    late.loc[26 + 23, ["open", "high", "low", "close"]] = [99.2, 100.6, 99.1, 100.5]       # reclaim at 15:15, entry would be 15:30
    p = s.Params(cost=0.0, min_risk=0.0, intraday=True, hold=26)
    assert s.undercut_trades(late, p, 1) == []


# ---- the fair value gap --------------------------------------------------------------------

def gap_example():
    rows = [(100, 100.5, 99.5, 100)] * 20
    rows += [(100, 101, 99.8, 100.8)]                         # bar 20: first candle, high 101
    rows += [(101, 104, 100.9, 103.8)]                        # bar 21: the big candle
    rows += [(103.8, 105, 103, 104.5)]                        # bar 22: low 103 is above 101, a gap of 2
    rows += [(104.5, 105, 103.5, 104)]                        # bar 23: does not reach 103
    rows += [(104, 104.2, 102.5, 103.5)]                      # bar 24: trades down to 103, buy there, stop 101
    rows += [(103.5, 107.5, 103.2, 107)]                      # bar 25: target is 103 + 2 * 2 = 107
    rows += [(107, 107.5, 104, 106)] * 5                      # wide bars, so no new gap forms
    return frame(rows)


def test_fair_value_gap_long_by_hand():
    t = s.gap_trades(gap_example(), P, 1)
    assert len(t) == 1
    trade = t[0]
    assert trade["signal"] == "2020-01-23" and trade["entry_time"] == "2020-01-25"
    assert trade["entry"] == 103 and trade["stop"] == 101
    assert trade["ended"] == "target" and trade["r"] == pytest.approx(2.0)


def test_gap_that_is_too_small_is_ignored():
    assert s.gap_trades(gap_example(), s.Params(cost=0.0, min_risk=0.0, min_gap=5.0), 1) == []


def test_gap_filled_on_the_entry_bar_is_a_loss():
    df = gap_example()
    df.loc[24, ["open", "high", "low", "close"]] = [104.0, 104.2, 100.5, 100.8]   # through the top and the bottom
    t = s.gap_trades(df, P, 1)
    assert len(t) == 1 and t[0]["ended"] == "stop" and t[0]["r"] == pytest.approx(-1.0)


# ---- nothing looks ahead -------------------------------------------------------------------

def random_walk(n=1500, seed=4):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, n)))
    open_ = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close})
    df["time"] = pd.date_range("2010-01-01", periods=n, freq="D").strftime("%Y-%m-%d")
    df["day"] = df["time"]
    return df


def test_cutting_off_the_future_does_not_change_past_trades():
    df = random_walk()
    full = s.all_trades(df, s.MAIN)
    assert len(full) > 30
    cut = 900
    early = s.all_trades(df.iloc[:cut + 1].reset_index(drop=True), s.MAIN)
    done = full[full["exit_time"] < df["time"].iloc[cut - s.MAIN.hold]]
    key = ["setup", "side", "entry_time"]
    merged = done.merge(early, on=key, suffixes=("", "_early"))
    assert len(merged) == len(done)
    assert (merged["r"] == merged["r_early"]).all() and (merged["exit_time"] == merged["exit_time_early"]).all()


def test_random_baseline_is_repeatable_and_has_no_edge_on_a_driftless_walk():
    df = random_walk(seed=9)
    trades = pd.DataFrame({"risk_pct": [2.0] * 40, "side": ["Long"] * 20 + ["Short"] * 20})
    p = s.Params(cost=0.0)
    a, b_ = s.random_baseline(df, trades, p, draws=100, seed=1), s.random_baseline(df, trades, p, draws=100, seed=1)
    assert (a == b_).all() and len(a) == 4000
    assert abs(a.mean()) < 0.1


def test_chance_of_beating():
    pool = np.array([-1.0, 2.0] * 500)                        # averages +0.5R
    assert s.chance_of_beating(-5, 50, pool) == 1.0
    assert s.chance_of_beating(5, 50, pool) == 0.0
    assert 0.35 < s.chance_of_beating(0.5, 50, pool) < 0.65


# ---- results/ and the write-up -------------------------------------------------------------

def test_summary_matches_the_trade_files():
    summary = pd.read_csv(os.path.join(b.OUT, "summary.csv"))
    for tf in ("daily", "15m"):
        trades = pd.read_csv(os.path.join(b.OUT, f"trades_{tf}.csv"))
        for (setup, side), g in trades.groupby(["setup", "side"]):
            row = summary[(summary["timeframe"] == tf) & (summary["setup"] == setup) & (summary["side"] == side)].iloc[0]
            assert row["trades"] == len(g)
            assert row["avg_r"] == pytest.approx(g["r"].mean(), abs=1e-9)
            assert row["win_rate"] == pytest.approx((g["r"] > 0).mean(), abs=1e-9)
            assert row["edge_r"] == pytest.approx(row["avg_r"] - row["random_avg_r"], abs=1e-9)


def test_trades_never_overlap_within_a_setup_and_fund():
    for tf in ("daily", "15m"):
        trades = pd.read_csv(os.path.join(b.OUT, f"trades_{tf}.csv"))
        for _, g in trades.groupby(["symbol", "setup", "side"]):
            g = g.sort_values("entry_time")
            assert (g["entry_time"].iloc[1:].to_numpy() >= g["exit_time"].iloc[:-1].to_numpy()).all()
            assert (g["signal"] <= g["entry_time"]).all() and (g["entry_time"] <= g["exit_time"]).all()


def test_15_minute_trades_stay_inside_one_day():
    trades = pd.read_csv(os.path.join(b.OUT, "trades_15m.csv"))
    assert (trades["entry_time"].str[:10] == trades["exit_time"].str[:10]).all()
    assert trades["entry_time"].str[11:].max() <= "15:15" and trades["entry_time"].str[11:].min() >= "09:45"
    assert trades["exit_time"].str[11:].max() == "15:45"


def test_the_small_tables_match_the_trade_files():
    m15, daily = (pd.read_csv(os.path.join(b.OUT, f"trades_{tf}.csv")) for tf in ("15m", "daily"))
    read = lambda name: pd.read_csv(os.path.join(b.OUT, name))
    ended = read("how_ended.csv")
    for tf, trades in (("15m", m15), ("daily", daily)):
        u = trades[trades["setup"] == "Undercut"]
        assert ended[ended["timeframe"] == tf]["trades"].sum() == len(u)
        assert ended[ended["timeframe"] == tf]["total_r"].sum() == pytest.approx(u["r"].sum(), abs=1e-6)
    u = m15[m15["setup"] == "Undercut"]
    quiet = read("quiet_days.csv").set_index("fund")
    assert (quiet["days_with_a_trade"] + quiet["days_without"] == quiet["days"]).all()
    assert quiet.loc["Either", "days_with_a_trade"] == u["entry_time"].str[:10].nunique()
    assert quiet.loc["Either", "days_without"] <= quiet.loc[["SPY", "QQQ"], "days_without"].min()
    hours = read("by_hour.csv")
    assert hours["trades"].sum() == len(u) and hours["total_r"].sum() == pytest.approx(u["r"].sum(), abs=1e-6)
    wait = read("waiting.csv")
    main = wait[(wait["version"] == "Waits for the reclaim") & (wait["min_stop"] == 0.002)]
    summary = read("summary.csv")
    for _, row in main.iterrows():
        match = summary[(summary["timeframe"] == row["timeframe"]) & (summary["setup"] == "Undercut") & (summary["side"] == row["side"])].iloc[0]
        assert (row["trades"], row["avg_r"]) == (match["trades"], pytest.approx(match["avg_r"], abs=1e-9))


@pytest.mark.skipif(not os.path.exists(os.path.join(b.DATA, "SPY_daily.csv")), reason="daily price data not downloaded")
def test_backtest_reproduces_the_saved_daily_trades():
    saved = pd.read_csv(os.path.join(b.OUT, "trades_daily.csv"))
    fresh, _ = b.run_timeframe("daily", draws=1)
    assert len(fresh) == len(saved)
    assert fresh["r"].to_numpy() == pytest.approx(saved["r"].to_numpy())


@pytest.mark.skipif(not os.path.exists(os.path.join(b.DATA, "SPY_15m.csv")), reason="15 minute price data not downloaded")
def test_backtest_reproduces_the_saved_15_minute_trades():
    saved = pd.read_csv(os.path.join(b.OUT, "trades_15m.csv"))
    fresh, _ = b.run_timeframe("15m", draws=1)
    assert len(fresh) == len(saved)
    assert fresh["r"].to_numpy() == pytest.approx(saved["r"].to_numpy())


def test_readme_quotes_the_results():
    f = b.facts()
    text = open(os.path.join(HERE, "README.md"), encoding="utf-8").read()

    def has(x):
        assert x in text, x

    def r(v, d=2):
        return f"{0:.{d}f}R" if round(v, d) == 0 else f"{v:+.{d}f}R"

    names = {"ul": "Undercut, long", "us": "Undercut, short", "gl": "Fair value gap, long", "gs": "Fair value gap, short"}
    for k, name in names.items():
        has(f"| {name} | {f[f'15m_{k}_n']} | {f[f'15m_{k}_win']:.0%} | {r(f[f'15m_{k}_avg'])} | {r(f[f'15m_{k}_gross'])} | {r(f[f'15m_{k}_total'], 0)} |")
        has(f"| {name} | {f[f'daily_{k}_n']} | {f[f'daily_{k}_win']:.0%} | {r(f[f'daily_{k}_avg'])} | {r(f[f'daily_{k}_total'], 0)} |")
        for tf, label in (("15m", "15 minute"), ("daily", "Daily")):
            has(f"| {label} | {name} | {r(f[f'{tf}_{k}_avg'])} | {r(f[f'{tf}_{k}_rand'])} | {f[f'{tf}_{k}_chance']:.0%} |")
    for tf, label in (("15m", "15 minute"), ("daily", "Daily")):
        for side, k in (("Long", "ul"), ("Short", "us")):
            has(f"| {label} | {side} | {r(f[f'{tf}_{k}_wait'])} | {r(f[f'{tf}_{k}_dip'])} |")

    # the 15 minute test
    has(f"{f['m15_days']} days of 26 bars, {f['m15_bars']:,} bars for each fund")
    assert (f["m15_from"], f["m15_to"]) == ("2025-01-02", "2026-11-13") and f["m15_bars"] == 26 * f["m15_days"]
    has(f"{f['m15_u_n']} trades, {f['m15_u_win']:.0%} winners, {r(f['m15_u_avg'])} a trade")
    has(f"{f['m15_u_n']} trades and {r(f['m15_u_total'], 0)} in total")
    has(f"Before costs it still averaged {r(f['m15_u_gross'])} a trade")
    has(f"{f['m15_u_target_n']} reached the 2R target, {f['m15_u_stop_n']} were stopped out and {f['m15_u_time_n']} were still open")
    assert f["m15_u_target_n"] + f["m15_u_stop_n"] + f["m15_u_time_n"] == f["m15_u_n"] == f["m15_undercuts"]
    assert f["15m_ul_avg"] < f["15m_ul_rand"] and f["15m_us_avg"] < f["15m_us_rand"]          # "worse than random timing in both directions"
    assert 0.06 < 2 * s.MAIN.cost / (f["m15_u_risk"] / 100) < 0.08                             # "about 0.07R off every trade"
    assert f["m15_u_gross"] < 0 and s.MAIN_15M.cost < 0.0001                                   # "loses at either figure, and before costs"
    has(f"correlation of {f['check_corr_SPY']:.3f} for SPY and above 0.999 for QQQ")
    assert f["check_corr_QQQ"] > 0.999

    # the daily test
    has(f"{f['daily_ul_n']} trades, {f['daily_ul_win']:.0%} winners, {r(f['daily_ul_avg'])} a trade")
    has(f"{f['bars_per_fund']:,} bars each")
    has(f"anywhere from {r(f['ul_ci_low'])} to {r(f['ul_ci_high'])}")
    has(f"{f['daily_ul_target_n']} reached the 2R target, {f['daily_ul_stop_n']} were stopped out and {f['daily_ul_time_n']} ran out")
    has(f"SPY returned {f['hold_total_SPY']:.0%} and QQQ {f['hold_total_QQQ']:.0%}")
    has(f"by about {f['daily_ul_edge']:.2f}R a trade")
    has(f"{r(f['ul_period_0'])} a trade in 2000 to 2009, {r(f['ul_period_1'])} in 2010 to 2019 and {r(f['ul_period_2'])} since 2020")
    has(f"{r(f['ul_avg_SPY'])} on SPY and {r(f['ul_avg_QQQ'])} on QQQ")
    assert f["us_period_0"] > f["us_period_1"] > f["us_period_2"] and f["us_period_0"] < 0
    assert f["ul_sens_profitable"] == f["ul_sens_n"]
    has(f"made money in all {f['ul_sens_n']}, from {r(f['ul_sens_min'])} to {r(f['ul_sens_max'])} a trade, and beat random timing in {f['ul_sens_beats_random']}")
    has(f"lost in {f['us_sens_n'] - f['us_sens_profitable']} of {f['us_sens_n']}")
    for k in ("us", "gl", "gs"):                                                               # "the short side and fair value gaps lost on both timeframes"
        assert f[f"15m_{k}_total"] < 0 and f[f"daily_{k}_total"] < 0

    # waiting
    has(f"{r(f['daily_ul_wait'])} a trade, against {r(f['daily_ul_dip'])} for buying the dip")
    has(f"took {f['daily_ul_dip_n']} trades, won {f['daily_ul_dip_win']:.0%} of them and lost {abs(f['daily_ul_dip']):.2f}R a trade")
    assert f["daily_ul_dip_loose"] < 0 < f["daily_ul_wait_loose"]                              # the daily result does not depend on the filter
    has(f"came out at {r(f['15m_ul_dip_loose'])} against {r(f['15m_ul_wait_loose'])} for waiting, and the two short versions tied at {r(f['15m_us_dip_loose'])}")
    assert r(f["15m_us_dip_loose"]) == r(f["15m_us_wait_loose"])
    has(f"On {f['quiet_spy']} of {f['m15_days']} days SPY gave no undercut trade at all. QQQ gave none on {f['quiet_qqq']}, and on {f['quiet_either']} days neither did")
    assert f["quiet_spy"] > f["m15_days"] / 2 and f["quiet_qqq"] > f["m15_days"] / 2           # "most days there is nothing to do"
    has(f"({f['hour_9_n']} trades, {r(f['hour_9_avg'])}), the 10 o'clock hour lost {abs(f['hour_10_avg']):.2f}R a trade and the 2 o'clock hour was the worst at {r(f['hour_14_avg'])}")
    assert f["worst_hour"] == 14

    # money
    has(f"would have cost about {abs(f['m15_u_total']) / 2:.0f}% of it")
    has(f"about {f['daily_ul_total']:.0f}% over 26 years")
    has(f"worst losing run of about {-f['ul_worst_run']:.0f}%")
    assert 0.18 < f["ul_time_in_trade"] < 0.23                # "roughly a fifth of the time"
    has(f"Holding SPY over the same years returned {f['hold_total_SPY']:.0%}, with a worst drop of {-f['hold_drop_SPY']:.0%}")
    has(f"{r(f['daily_ul_total'], 0)} over 26 years")
    assert (f["tests"], f["tests_under_5pct"]) == (8, 1)
    assert f["daily_gs_chance"] < 0.05 and f["daily_gs_avg"] < 0                               # the one under 5% still loses
    tests = len(re.findall(r"^def test_", open(os.path.join(HERE, "test_setups.py"), encoding="utf-8").read(), re.M))
    has(f"{tests} tests")
    assert not re.search("[‒-―]", text)             # no long dashes

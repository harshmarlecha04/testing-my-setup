"""Runs both setups on SPY and QQQ and writes everything the write-up quotes to results/.

    python get_data.py        # daily bars, once
    python get_intraday.py    # 15 minute bars, once
    python backtest.py

Results
    trades_15m.csv     every simulated trade on 15 minute bars, January 2025 to now
    trades_daily.csv   every simulated trade on daily bars, 2000 to now
    summary.csv        each setup, direction and timeframe: trades, win rate, average R before
                       and after costs, what the same trades made at random times, and the
                       chance that random timing does at least as well
    waiting.csv        the undercut as written against an impatient version that buys the dip,
                       at the main stop filter and at a looser one
    how_ended.csv      undercut trades split by how they ended: stop, target or out of time
    quiet_days.csv     how many 15 minute days had no undercut trade at all
    by_hour.csv        15 minute undercut trades by the hour they were entered
    data_check.csv     the 15 minute bars checked against the daily bars from the other source
    by_period.csv      the daily results split into three stretches of years
    sensitivity.csv    the daily undercut with different settings
    buy_and_hold.csv   what simply holding each fund did over the same years
    bar_counts.csv     how many price bars each test ran on, and the dates they cover
"""
import itertools
import os

import numpy as np
import pandas as pd

import setups as s

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "results")
SYMBOLS = ["SPY", "QQQ"]
PERIODS = [("2000 to 2009", "2000", "2010"), ("2010 to 2019", "2010", "2020"), ("2020 to 2026", "2020", "2100")]
TIMEFRAMES = {"15m": ("{}_15m.csv", s.MAIN_15M), "daily": ("{}_daily.csv", s.MAIN)}


def bars(symbol, timeframe):
    return s.load(os.path.join(DATA, TIMEFRAMES[timeframe][0].format(symbol)))


def run_timeframe(timeframe, p=None, draws=200):
    """All trades for both symbols, and the random-timing R values for each setup and direction."""
    p = p or TIMEFRAMES[timeframe][1]
    trades, pools = [], {}
    for symbol in SYMBOLS:
        df = bars(symbol, timeframe)
        t = s.all_trades(df, p)
        if t.empty:
            continue
        t.insert(0, "symbol", symbol)
        trades.append(t)
        for (setup, side), g in t.groupby(["setup", "side"]):
            pools.setdefault((setup, side), []).append(s.random_baseline(df, g, p, draws=draws, seed=7 + len(pools)))
    trades = pd.concat(trades, ignore_index=True) if trades else pd.DataFrame()
    return trades, {k: np.concatenate(v) for k, v in pools.items()}


def summary_rows(timeframe, trades, pools):
    p = TIMEFRAMES[timeframe][1]
    rows = []
    for (setup, side), g in trades.groupby(["setup", "side"]):
        m = s.summarize(g["r"])
        pool = pools[(setup, side)]
        rows.append({"timeframe": timeframe, "setup": setup, "side": side, **m,
                     "avg_r_before_costs": float(s.before_costs(g, p).mean()),
                     "random_avg_r": float(pool.mean()), "edge_r": m["avg_r"] - float(pool.mean()),
                     "chance_random_does_as_well": s.chance_of_beating(m["avg_r"], m["trades"], pool)})
    return rows


LOOSE_STOP = 0.001


def waiting():
    """The undercut as written (wait for the reclaim) against buying straight after the dip.

    Buying the dip puts the stop very close, and trades whose stop is closer than min_risk are
    skipped, so the comparison is run twice: at the main filter and at a looser one."""
    rows = []
    for timeframe, (_, p) in TIMEFRAMES.items():
        for min_stop in (p.min_risk, LOOSE_STOP):
            q = s.Params(swing=p.swing, window=p.window, target=p.target, hold=p.hold, cost=p.cost, min_risk=min_stop, min_gap=p.min_gap, intraday=p.intraday)
            for side, name in ((1, "Long"), (-1, "Short")):
                for wait, label in ((True, "Waits for the reclaim"), (False, "Buys the dip")):
                    r = np.concatenate([[t["r"] for t in s.undercut_trades(bars(sym, timeframe), q, side, wait=wait)] for sym in SYMBOLS])
                    rows.append({"timeframe": timeframe, "min_stop": min_stop, "side": name, "version": label, **s.summarize(r)})
    return pd.DataFrame(rows)


def by_hour(trades):
    u = trades[trades["setup"] == "Undercut"]
    g = u.groupby(u["entry_time"].str[11:13])["r"]
    return pd.DataFrame({"hour": g.size().index, "trades": g.size().to_numpy(), "avg_r": g.mean().to_numpy(), "total_r": g.sum().to_numpy()})


def data_check():
    """The two price sources against each other: the last 15 minute close of each day and the daily close."""
    rows = []
    for sym in SYMBOLS:
        intraday = bars(sym, "15m").groupby("day")["close"].last()
        daily = bars(sym, "daily").set_index("time")["close"]
        j = pd.concat([intraday.rename("a"), daily.rename("b")], axis=1, join="inner")
        moves = j.pct_change().dropna()
        rows.append({"fund": sym, "days_compared": len(j), "days_missing_from_daily": int(len(intraday) - len(j)),
                     "correlation_of_daily_moves": float(np.corrcoef(moves["a"], moves["b"])[0, 1]),
                     "median_gap_pct_last_20_days": float(((j["a"] / j["b"] - 1).abs() * 100).tail(20).median())})
    return pd.DataFrame(rows)


def how_ended(all_trades):
    rows = []
    for timeframe, trades in all_trades.items():
        u = trades[trades["setup"] == "Undercut"]
        for (side, ended), g in u.groupby(["side", "ended"]):
            rows.append({"timeframe": timeframe, "side": side, "ended": ended, "trades": len(g), "avg_r": float(g["r"].mean()), "total_r": float(g["r"].sum())})
    return pd.DataFrame(rows)


def quiet_days(trades):
    u = trades[trades["setup"] == "Undercut"]
    rows = []
    for sym in SYMBOLS:
        days = bars(sym, "15m")["day"].nunique()
        busy = u[u["symbol"] == sym]["entry_time"].str[:10].nunique()
        rows.append({"fund": sym, "days": days, "days_with_a_trade": busy, "days_without": days - busy})
    days = bars(SYMBOLS[0], "15m")["day"].nunique()
    busy = u["entry_time"].str[:10].nunique()
    rows.append({"fund": "Either", "days": days, "days_with_a_trade": busy, "days_without": days - busy})
    return pd.DataFrame(rows)


def by_period(trades):
    rows = []
    for (setup, side), g in trades.groupby(["setup", "side"]):
        for name, lo, hi in PERIODS:
            part = g[(g["entry_time"] >= lo) & (g["entry_time"] < hi)]
            rows.append({"setup": setup, "side": side, "period": name, **s.summarize(part["r"])})
    return pd.DataFrame(rows)


def sensitivity():
    rows = []
    for swing, window, target in itertools.product((3, 5, 8), (5, 10, 15), (1.5, 2.0, 3.0)):
        p = s.Params(swing=swing, window=window, target=target)
        for side, name in ((1, "Long"), (-1, "Short")):
            r, pool = [], []
            for symbol in SYMBOLS:
                df = bars(symbol, "daily")
                t = pd.DataFrame(s.undercut_trades(df, p, side))
                if t.empty:
                    continue
                r.append(t["r"].to_numpy())
                pool.append(s.random_baseline(df, t, p, draws=60, seed=3))
            r, pool = np.concatenate(r), np.concatenate(pool)
            rows.append({"swing": swing, "window": window, "target": target, "side": name, **s.summarize(r),
                         "random_avg_r": float(pool.mean()), "edge_r": float(r.mean() - pool.mean()),
                         "main": (swing, window, target) == (s.MAIN.swing, s.MAIN.window, s.MAIN.target)})
    return pd.DataFrame(rows)


def buy_and_hold():
    rows = []
    for symbol in SYMBOLS:
        df = bars(symbol, "daily")
        c = df["close"].to_numpy(float)
        years = (pd.Timestamp(df["time"].iloc[-1]) - pd.Timestamp(df["time"].iloc[0])).days / 365.25
        peak = np.maximum.accumulate(c)
        rows.append({"symbol": symbol, "from": df["time"].iloc[0], "to": df["time"].iloc[-1],
                     "total_return": c[-1] / c[0] - 1, "per_year": (c[-1] / c[0]) ** (1 / years) - 1,
                     "worst_drop": float((c / peak - 1).min())})
    return pd.DataFrame(rows)


def main():
    os.makedirs(OUT, exist_ok=True)
    summary, all_trades = [], {}
    for timeframe in TIMEFRAMES:
        trades, pools = run_timeframe(timeframe)
        trades.to_csv(os.path.join(OUT, f"trades_{timeframe}.csv"), index=False)
        all_trades[timeframe] = trades
        summary += summary_rows(timeframe, trades, pools)
        print(f"{timeframe}: {len(trades)} trades, {trades['entry_time'].min()} to {trades['exit_time'].max()}")
    summary = pd.DataFrame(summary)
    summary.to_csv(os.path.join(OUT, "summary.csv"), index=False)
    waiting().to_csv(os.path.join(OUT, "waiting.csv"), index=False)
    how_ended(all_trades).to_csv(os.path.join(OUT, "how_ended.csv"), index=False)
    quiet_days(all_trades["15m"]).to_csv(os.path.join(OUT, "quiet_days.csv"), index=False)
    by_hour(all_trades["15m"]).to_csv(os.path.join(OUT, "by_hour.csv"), index=False)
    data_check().to_csv(os.path.join(OUT, "data_check.csv"), index=False)
    by_period(all_trades["daily"]).to_csv(os.path.join(OUT, "by_period.csv"), index=False)
    sensitivity().to_csv(os.path.join(OUT, "sensitivity.csv"), index=False)
    buy_and_hold().to_csv(os.path.join(OUT, "buy_and_hold.csv"), index=False)
    counts = [{"file": f"{sym}_{tf}", "bars": len(bars(sym, tf)), "days": bars(sym, tf)["day"].nunique(),
               "from": bars(sym, tf)["time"].iloc[0], "to": bars(sym, tf)["time"].iloc[-1]} for tf in TIMEFRAMES for sym in SYMBOLS]
    pd.DataFrame(counts).to_csv(os.path.join(OUT, "bar_counts.csv"), index=False)
    pd.set_option("display.width", 220)
    print(summary.round(3).to_string(index=False))


KEYS = {"ul": ("Undercut", "Long"), "us": ("Undercut", "Short"), "gl": ("Fair value gap", "Long"), "gs": ("Fair value gap", "Short")}


def facts(folder=OUT):
    """Every number the write-up quotes, read back from results/ (no price data needed)."""
    read = lambda name: pd.read_csv(os.path.join(folder, name))
    daily, m15 = read("trades_daily.csv"), read("trades_15m.csv")
    summary = read("summary.csv").set_index(["timeframe", "setup", "side"])
    period = read("by_period.csv").set_index(["setup", "side", "period"])
    sens, hold = read("sensitivity.csv"), read("buy_and_hold.csv").set_index("symbol")
    wait_all = read("waiting.csv")
    loose = wait_all[np.isclose(wait_all["min_stop"], LOOSE_STOP)].set_index(["timeframe", "side", "version"])
    wait = wait_all[~np.isclose(wait_all["min_stop"], LOOSE_STOP)].set_index(["timeframe", "side", "version"])
    hours, check = read("by_hour.csv"), read("data_check.csv").set_index("fund")
    ended = read("how_ended.csv").set_index(["timeframe", "side", "ended"])
    quiet, counts = read("quiet_days.csv").set_index("fund"), read("bar_counts.csv").set_index("file")
    f = {"daily_trades": len(daily), "m15_trades": len(m15),
         "m15_undercuts": int((m15["setup"] == "Undercut").sum()), "daily_undercuts": int((daily["setup"] == "Undercut").sum()),
         "daily_to": hold["to"].iloc[0], "bars_per_fund": int(counts.loc["SPY_daily", "bars"]),
         "m15_days": int(counts.loc["SPY_15m", "days"]), "m15_bars": int(counts.loc["SPY_15m", "bars"]),
         "m15_from": counts.loc["SPY_15m", "from"][:10], "m15_to": counts.loc["SPY_15m", "to"][:10],
         "quiet_either": int(quiet.loc["Either", "days_without"]), "quiet_spy": int(quiet.loc["SPY", "days_without"]), "quiet_qqq": int(quiet.loc["QQQ", "days_without"])}
    f["all_undercuts"] = f["m15_undercuts"] + f["daily_undercuts"]
    cols = (("trades", "n"), ("win_rate", "win"), ("avg_r", "avg"), ("total_r", "total"), ("avg_r_before_costs", "gross"),
            ("random_avg_r", "rand"), ("edge_r", "edge"), ("chance_random_does_as_well", "chance"))
    for tf in TIMEFRAMES:
        for k, key in KEYS.items():
            row = summary.loc[(tf, *key)]
            for col, name in cols:
                f[f"{tf}_{k}_{name}"] = int(row[col]) if col == "trades" else float(row[col])
        for side, k in (("Long", "ul"), ("Short", "us")):
            f[f"{tf}_{k}_wait"] = float(wait.loc[(tf, side, "Waits for the reclaim"), "avg_r"])
            f[f"{tf}_{k}_dip"] = float(wait.loc[(tf, side, "Buys the dip"), "avg_r"])
            f[f"{tf}_{k}_dip_n"] = int(wait.loc[(tf, side, "Buys the dip"), "trades"])
            f[f"{tf}_{k}_dip_win"] = float(wait.loc[(tf, side, "Buys the dip"), "win_rate"])
            f[f"{tf}_{k}_wait_loose"] = float(loose.loc[(tf, side, "Waits for the reclaim"), "avg_r"])
            f[f"{tf}_{k}_dip_loose"] = float(loose.loc[(tf, side, "Buys the dip"), "avg_r"])
            for how in ("target", "stop", "time"):
                f[f"{tf}_{k}_{how}_n"] = int(ended.loc[(tf, side, how), "trades"])
                f[f"{tf}_{k}_{how}_total"] = float(ended.loc[(tf, side, how), "total_r"])
                f[f"{tf}_{k}_{how}_avg"] = float(ended.loc[(tf, side, how), "avg_r"])
    u15 = m15[m15["setup"] == "Undercut"]
    f["m15_u_n"], f["m15_u_avg"], f["m15_u_total"], f["m15_u_win"] = len(u15), float(u15["r"].mean()), float(u15["r"].sum()), float((u15["r"] > 0).mean())
    f["m15_u_gross"] = float(s.before_costs(u15, s.MAIN_15M).mean())
    f["m15_u_risk"], f["m15_u_bars"] = float(u15["risk_pct"].median()), float(u15["bars"].median())
    f["m15_u_target_n"], f["m15_u_stop_n"], f["m15_u_time_n"] = (int((u15["ended"] == x).sum()) for x in ("target", "stop", "time"))
    f["m15_u_per_day"] = len(u15) / (f["m15_days"] * len(SYMBOLS))
    worst = hours.loc[hours["avg_r"].idxmin()]
    f["worst_hour"], f["worst_hour_avg"] = int(worst["hour"]), float(worst["avg_r"])
    for _, row in hours.iterrows():
        f[f"hour_{int(row['hour'])}_n"], f[f"hour_{int(row['hour'])}_avg"] = int(row["trades"]), float(row["avg_r"])
    first = hours.iloc[0]
    f["first_hour"], f["first_hour_n"], f["first_hour_avg"] = int(first["hour"]), int(first["trades"]), float(first["avg_r"])
    for sym in SYMBOLS:
        f[f"check_corr_{sym}"] = float(check.loc[sym, "correlation_of_daily_moves"])
        f[f"check_days_{sym}"] = int(check.loc[sym, "days_compared"])
    ul = daily[(daily["setup"] == "Undercut") & (daily["side"] == "Long")]
    rng = np.random.default_rng(5)
    boot = rng.choice(ul["r"].to_numpy(), size=(10000, len(ul)), replace=True).mean(axis=1)
    f["ul_ci_low"], f["ul_ci_high"] = float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))
    for sym in SYMBOLS:
        f[f"ul_avg_{sym}"] = float(ul[ul["symbol"] == sym]["r"].mean())
        f[f"hold_total_{sym}"] = float(hold.loc[sym, "total_return"])
        f[f"hold_drop_{sym}"] = float(hold.loc[sym, "worst_drop"])
    for i, (name, _, _) in enumerate(PERIODS):
        f[f"ul_period_{i}"] = float(period.loc[("Undercut", "Long", name), "avg_r"])
        f[f"us_period_{i}"] = float(period.loc[("Undercut", "Short", name), "avg_r"])
    for side, k in (("Long", "ul"), ("Short", "us")):
        x = sens[sens["side"] == side]
        f[f"{k}_sens_n"] = len(x)
        f[f"{k}_sens_profitable"] = int((x["avg_r"] > 0).sum())
        f[f"{k}_sens_beats_random"] = int((x["edge_r"] > 0).sum())
        f[f"{k}_sens_min"], f[f"{k}_sens_max"] = float(x["avg_r"].min()), float(x["avg_r"].max())
    curve = ul.sort_values("exit_time")["r"].cumsum().to_numpy()
    f["ul_worst_run"] = float((curve - np.maximum.accumulate(np.maximum(curve, 0))).min())
    f["ul_time_in_trade"] = float(ul["bars"].sum() / (f["bars_per_fund"] * len(SYMBOLS)))
    f["tests"] = len(summary)
    f["tests_under_5pct"] = int((summary["chance_random_does_as_well"] < 0.05).sum())
    return f


if __name__ == "__main__":
    main()

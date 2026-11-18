"""Draws the seven charts in charts/. Blue marks the thing to look at, gray is context.

    python charts.py

Needs data/ (run get_intraday.py) for the first chart and results/ (run backtest.py) for the rest.
Set CHART_FONT_DIR to a folder of .ttf files to use your own typeface.
"""
import glob
import logging
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker
import numpy as np
import pandas as pd
from matplotlib import font_manager

import backtest as b
import setups as s

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "charts")
INK, MUTED, GRID, BLUE, GRAY, PALE = "#000000", "#5f5f5f", "#e4e4e4", "#1433ff", "#9a9a9a", "#c9c9c9"

for path in glob.glob(os.path.join(os.environ.get("CHART_FONT_DIR", ""), "*.ttf")) if os.environ.get("CHART_FONT_DIR") else []:
    font_manager.fontManager.addfont(path)
plt.rcParams.update({
    "font.family": ["Geist", "Inter", "Arial", "DejaVu Sans"],
    "font.size": 10.5, "text.color": INK, "axes.labelcolor": MUTED,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.edgecolor": GRID,
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
})


LABEL = {"facecolor": "white", "edgecolor": "none", "pad": 1.2, "alpha": 0.9}


def signed(v, digits=2):
    """+0.17R, -0.08R, and 0.00R instead of -0.00R."""
    return f"{0:.{digits}f}R" if round(v, digits) == 0 else f"{v:+.{digits}f}R"


def titles(fig, title, subtitle, height):
    fig.text(0.04, 1 - 0.24 / height, title, fontsize=14, fontweight=500, ha="left", va="top")
    fig.text(0.04, 1 - 0.55 / height, subtitle, fontsize=10, color=MUTED, ha="left", va="top")


def clean(ax, grid="y"):
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#bdbdbd")
    if grid:
        ax.grid(axis=grid, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0, labelsize=9.5)


def save(fig, name):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    fig.savefig(path)
    plt.close(fig)
    return path


def chart_examples(f):
    """Two real trades from the 15 minute test on SPY: one that worked and one that did not."""
    df = b.bars("SPY", "15m")
    trades = pd.read_csv(os.path.join(b.OUT, "trades_15m.csv"))
    picks = [("2026-05-21 12:00", "It worked: the target was hit"), ("2025-11-17 12:00", "It did not: stopped out")]
    c, lows = df["close"].to_numpy(float), df["low"].to_numpy(float)
    e10, e20 = s.ema(c, 10), s.ema(c, 20)
    height = 4.6
    fig, axes = plt.subplots(1, 2, figsize=(8, height), dpi=200)
    fig.subplots_adjust(left=0.07, right=0.97, top=0.74, bottom=0.1, wspace=0.16)
    titles(fig, "The undercut, as the computer sees it", "SPY, 15 minute bars. Price dips under a swing low, closes back above both EMAs, and the trade starts on the next bar.", height)
    for ax, (entry_time, label) in zip(axes, picks):
        t = trades[(trades["symbol"] == "SPY") & (trades["setup"] == "Undercut") & (trades["side"] == "Long") & (trades["entry_time"] == entry_time)].iloc[0]
        i0 = df.index[df["time"] == t["signal"]][0]
        ie = df.index[df["time"] == t["entry_time"]][0]
        ix = df.index[df["time"] == t["exit_time"]][0]
        swing = max(k for k in range(i0 - 60, i0) if abs(lows[k] - t["level"]) < 6e-4)
        lo, hi = swing - 6, ix + 2
        x = np.arange(lo, hi + 1)
        seg = df.iloc[lo:hi + 1]
        clean(ax)
        ax.vlines(x, seg["low"], seg["high"], color=INK, linewidth=1.1)
        ax.scatter(x, seg["close"], s=5, color=INK, zorder=3)
        ax.plot(x, e10[lo:hi + 1], color=GRAY, linewidth=1.3, label="10 EMA")
        ax.plot(x, e20[lo:hi + 1], color=PALE, linewidth=1.3, label="20 EMA")
        ax.hlines(t["level"], swing, ie, color=BLUE, linewidth=1.4)
        ax.annotate("Support", (swing, t["level"]), xytext=(1, -5), textcoords="offset points", fontsize=8.5, va="top", ha="left", bbox=LABEL, zorder=6)
        risk = t["entry"] - t["stop"]
        target = t["entry"] + s.MAIN_15M.target * risk
        ax.hlines([t["stop"], target], ie, hi + 1, color=MUTED, linewidth=0.9, linestyles=(0, (1, 2)))
        ax.text(hi + 1.6, t["stop"], "Stop", fontsize=8.5, va="center", color=MUTED)
        ax.text(hi + 1.6, target, "Target", fontsize=8.5, va="center", color=MUTED)
        ax.scatter([ie], [t["entry"]], s=46, color=BLUE, zorder=5, edgecolor="white", linewidth=1.2)
        ax.annotate("Buy", (ie, t["entry"]), xytext=(0, 13), textcoords="offset points", fontsize=9, ha="center", fontweight=500, bbox=LABEL, zorder=6)
        dip = lo + int(np.argmin(lows[lo:ie]))
        ax.annotate("Dip", (dip, lows[dip]), xytext=(0, -13), textcoords="offset points", fontsize=9, ha="center", bbox=LABEL, zorder=6)
        opens = [k for k in range(lo + 1, hi + 1) if df["day"].iloc[k] != df["day"].iloc[k - 1]]
        for k in opens:                                     # a faint line where one day ends and the next begins
            ax.axvline(k - 0.5, color=GRID, linewidth=1.0, zorder=1)
        ax.set_xlim(lo - 1, hi + 8)
        ax.set_ylim(min(seg["low"].min(), t["stop"]) * 0.9985, max(seg["high"].max(), target) * 1.001)
        ticks = [lo + 1] + opens
        ax.set_xticks(ticks, [pd.Timestamp(df["time"].iloc[k]).strftime("%b %-d, %Y") if k == ticks[0] else pd.Timestamp(df["time"].iloc[k]).strftime("%b %-d, 9:30") for k in ticks])
        ax.set_title(f"{label} ({t['r']:+.1f}R)", fontsize=10, loc="left", pad=8)
        ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(nbins=6, integer=True))
        ax.yaxis.set_major_formatter(lambda v, _: f"${v:,.0f}")
    axes[0].legend(loc="upper left", frameon=False, fontsize=8.5, handlelength=1.3)
    return save(fig, "1-the-setup.png")


def chart_intraday(f):
    trades = pd.read_csv(os.path.join(b.OUT, "trades_15m.csv")).sort_values("exit_time")
    height = 4.4
    fig, ax = plt.subplots(figsize=(8, height), dpi=200)
    fig.subplots_adjust(left=0.08, right=0.74, top=0.80, bottom=0.1)
    titles(fig, f"{f['m15_u_n']} undercut trades on 15 minute bars", f"Running total of R over {f['m15_days']} trading days. Each trade risks 1R. SPY and QQQ, long and short, after costs.", height)
    clean(ax)
    u = trades[trades["setup"] == "Undercut"]
    g = trades[trades["setup"] == "Fair value gap"]
    rand = np.where(u["side"] == "Long", f["15m_ul_rand"], f["15m_us_rand"]).cumsum()
    ends = []
    for x, y, color, width, label in ((pd.to_datetime(g["exit_time"]), g["r"].cumsum().to_numpy(), GRAY, 1.5, "Fair value gap"),
                                      (pd.to_datetime(u["exit_time"]), rand, PALE, 1.5, "Undercut at random times"),
                                      (pd.to_datetime(u["exit_time"]), u["r"].cumsum().to_numpy(), BLUE, 2.2, "Undercut")):
        ax.plot(x, y, color=color, linewidth=width, label=label)
        ends.append([label, x.iloc[-1], y[-1], color])
    ends.sort(key=lambda e: e[2])
    spot = None
    for label, x, y, color in ends:
        spot = y if spot is None else max(y, spot + 5.5)
        ax.text(x + pd.Timedelta(days=12), spot, f"{label} {y:+.0f}R", fontsize=9.5, va="center", clip_on=False, fontweight=500 if color == BLUE else 400)
    ax.axhline(0, color=INK, linewidth=0.8)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:+.0f}R" if v else "0")
    ax.legend(loc="lower left", frameon=False, fontsize=9, handlelength=1.4)
    return save(fig, "2-fifteen-minute-trades.png")


def chart_curves(f):
    trades = pd.read_csv(os.path.join(b.OUT, "trades_daily.csv"))
    height = 4.4
    fig, ax = plt.subplots(figsize=(8, height), dpi=200)
    fig.subplots_adjust(left=0.08, right=0.76, top=0.80, bottom=0.1)
    titles(fig, "Running total of R, daily bars, 2000 to 2026", "Each trade risks 1R. SPY and QQQ together, after costs.", height)
    clean(ax)
    lines = [("Undercut", "Long", BLUE, 2.2, "Undercut, long"), ("Undercut", "Short", INK, 1.5, "Undercut, short"),
             ("Fair value gap", "Long", GRAY, 1.5, "Gap, long"), ("Fair value gap", "Short", PALE, 1.5, "Gap, short")]
    ends = []
    for setup, side, color, width, label in lines:
        g = trades[(trades["setup"] == setup) & (trades["side"] == side)].sort_values("exit_time")
        x = pd.to_datetime(g["exit_time"])
        y = g["r"].cumsum()
        ax.plot(x, y, color=color, linewidth=width, label=label)
        ends.append([label, x.iloc[-1], y.iloc[-1], color])
    ends.sort(key=lambda e: e[2])
    spot = None
    for label, x, y, color in ends:                     # nudge end labels apart so they never overlap
        spot = y if spot is None else max(y, spot + 6.5)
        ax.text(x + pd.Timedelta(days=150), spot, f"{label} {y:+.0f}R", fontsize=9.5, va="center", clip_on=False, fontweight=500 if color == BLUE else 400)
    ax.axhline(0, color=INK, linewidth=0.8)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:+.0f}R" if v else "0")
    ax.legend(loc="lower left", frameon=False, fontsize=9, ncols=2, handlelength=1.4)
    return save(fig, "3-daily-running-total.png")


ROWS = [("Undercut, long", "ul"), ("Undercut, short", "us"), ("Fair value gap, long", "gl"), ("Fair value gap, short", "gs")]


def dumbbells(fig, axes, panels, legend):
    """One row per setup: a hollow dot for the comparison, a blue dot for the thing tested."""
    for ax, (heading, rows) in zip(axes, panels):
        clean(ax, grid="x")
        for i, (label, real, other) in enumerate(rows):
            y = len(rows) - 1 - i
            ax.plot([other, real], [y, y], color=PALE, linewidth=2.2, zorder=2)
            ax.scatter([other], [y], s=70, facecolor="white", edgecolor=MUTED, linewidth=1.5, zorder=3, label=legend[1] if i == 0 else None)
            ax.scatter([real], [y], s=78, color=BLUE, zorder=4, label=legend[0] if i == 0 else None)
            ax.text(0.325, y, f"{signed(real)} against {signed(other)}", fontsize=9.5, va="center", clip_on=False)
        ax.axvline(0, color=INK, linewidth=0.8)
        ax.set_yticks(range(len(rows)), [r[0] for r in rows][::-1], fontsize=10, color=INK)
        ax.set_xlim(-0.3, 0.3)
        ax.set_ylim(-0.6, len(rows) - 0.4)
        ax.set_title(heading, fontsize=10, loc="left", pad=6, x=-0.42, color=MUTED)
        ax.xaxis.set_major_formatter(lambda v, _: f"{v:+.1f}R" if abs(v) > 1e-9 else "0")
    for ax in axes[:-1]:
        ax.tick_params(labelbottom=False)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles[::-1], labels[::-1], loc="upper left", bbox_to_anchor=(0.03, 1 - 0.74 / fig.get_figheight()), frameon=False, fontsize=9, ncols=2, handletextpad=0.2, columnspacing=1.2)


def chart_vs_random(f):
    height = 5.6
    fig, axes = plt.subplots(2, 1, figsize=(8, height), dpi=200, sharex=True)
    fig.subplots_adjust(left=0.25, right=0.72, top=0.76, bottom=0.08, hspace=0.3)
    titles(fig, "Each setup against the same trades at random times", "Average R per trade. The gap between the two dots is what the timing added.", height)
    panels = [(name, [(label, f[f"{tf}_{k}_avg"], f[f"{tf}_{k}_rand"]) for label, k in ROWS]) for tf, name in (("15m", "15 minute bars, 2025 to 2026"), ("daily", "Daily bars, 2000 to 2026"))]
    dumbbells(fig, axes, panels, ("The setup", "Random timing"))
    return save(fig, "4-against-random.png")


def chart_waiting(f):
    height = 4.3
    fig, axes = plt.subplots(2, 1, figsize=(8, height), dpi=200, sharex=True, gridspec_kw={"height_ratios": [1, 1]})
    fig.subplots_adjust(left=0.25, right=0.72, top=0.69, bottom=0.1, hspace=0.42)
    titles(fig, "Waiting for the reclaim against buying the dip", "Average R per trade for the undercut. Buying the dip skips the wait and enters on the bar after the dip.", height)
    panels = [(name, [(label, f[f"{tf}_{k}_wait"], f[f"{tf}_{k}_dip"]) for label, k in (("Long", "ul"), ("Short", "us"))]) for tf, name in (("daily", "Daily bars"), ("15m", "15 minute bars"))]
    dumbbells(fig, axes, panels, ("Waits for the reclaim", "Buys the dip"))
    return save(fig, "7-waiting.png")


def chart_periods(f):
    names = [p[0] for p in b.PERIODS]
    height = 3.6
    fig, ax = plt.subplots(figsize=(8, height), dpi=200)
    fig.subplots_adjust(left=0.09, right=0.96, top=0.72, bottom=0.12)
    titles(fig, "The undercut in three stretches of years", "Average R per trade on daily bars. The long side holds up. The short side gets worse.", height)
    clean(ax)
    x = np.arange(len(names))
    long_, short = [f[f"ul_period_{i}"] for i in range(3)], [f[f"us_period_{i}"] for i in range(3)]
    ax.bar(x - 0.19, long_, width=0.34, color=BLUE, label="Long")
    ax.bar(x + 0.19, short, width=0.34, color=GRAY, label="Short")
    for xi, v in zip(x - 0.19, long_):
        ax.text(xi, v + 0.012, f"{v:+.2f}", ha="center", va="bottom", fontsize=9.5, fontweight=500)
    for xi, v in zip(x + 0.19, short):
        ax.text(xi, v - 0.012, f"{v:+.2f}", ha="center", va="top", fontsize=9.5)
    ax.axhline(0, color=INK, linewidth=0.8)
    ax.set_xticks(x, names, fontsize=10, color=INK)
    ax.set_ylim(-0.42, 0.30)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:+.1f}R" if abs(v) > 1e-9 else "0")
    ax.spines["bottom"].set_visible(False)
    ax.legend(loc="lower left", frameon=False, fontsize=9, ncols=2, handlelength=1)
    return save(fig, "5-by-period.png")


def chart_settings(f):
    sens = pd.read_csv(os.path.join(b.OUT, "sensitivity.csv"))
    height = 3.5
    fig, ax = plt.subplots(figsize=(8, height), dpi=200)
    fig.subplots_adjust(left=0.12, right=0.96, top=0.64, bottom=0.14)
    titles(fig, "The same test with 27 different settings", "Average R per trade for the daily undercut. Each dot is one combination of swing size, patience and target.", height)
    clean(ax, grid="x")
    rng = np.random.default_rng(2)
    for y, side in ((1, "Long"), (0, "Short")):
        g = sens[sens["side"] == side]
        other, main = g[~g["main"]], g[g["main"]]
        ax.scatter(other["avg_r"], y + rng.uniform(-0.16, 0.16, len(other)), s=42, color=GRAY, edgecolor="white", linewidth=1.1, zorder=3, label="Other settings" if y == 1 else None)
        ax.scatter(main["avg_r"], [y], s=64, color=BLUE, edgecolor="white", linewidth=1.2, zorder=4, label="The settings I used" if y == 1 else None)
    ax.axvline(0, color=INK, linewidth=0.8)
    ax.set_yticks([1, 0], ["Long", "Short"], fontsize=10, color=INK)
    ax.set_ylim(-0.6, 1.6)
    ax.set_xlim(-0.3, 0.3)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:+.1f}R" if abs(v) > 1e-9 else "0")
    ax.legend(loc="upper left", bbox_to_anchor=(-0.02, 1.2), frameon=False, fontsize=9, ncols=2, handletextpad=0.2, columnspacing=1.2)
    return save(fig, "6-other-settings.png")


def main():
    f = b.facts()
    for fn in (chart_examples, chart_intraday, chart_curves, chart_vs_random, chart_periods, chart_settings, chart_waiting):
        print(fn(f))


if __name__ == "__main__":
    main()

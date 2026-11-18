"""Downloads 15 minute bars for SPY and QQQ for every trading day since January 2025.

    python get_intraday.py

That is as far back as free 15 minute history goes: about 470 trading days. Fifteen years
of intraday prices would need a paid data plan. The bars are built from one minute bars in
Strasmore's public market-data service (https://ai.strasmore.com, no key needed), regular
session only, 9:30 to 16:00 New York time. They are not included in this repository.
"""
import csv
import json
import os
import time
import urllib.parse
import urllib.request

SYMBOLS = ["SPY", "QQQ"]
FROM = "2025-01-01 00:00:00"
API = "https://ai.strasmore.com/api/demo/sql?sql="
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data")

SQL = """
SELECT formatDateTime(t, '%Y-%m-%d %H:%i') AS time, o AS open, h AS high, l AS low, c AS close, v AS volume, toUnixTimestamp(t) AS ts
FROM (
    SELECT toStartOfInterval(toTimeZone(window_start, 'America/New_York'), INTERVAL 15 MINUTE) AS t,
           argMin(open, window_start) AS o, max(high) AS h, min(low) AS l, argMax(close, window_start) AS c, sum(volume) AS v
    FROM global_markets.delayed_stocks_minute_aggs
    WHERE ticker = '{symbol}' AND window_start >= {start}
      AND toHour(toTimeZone(window_start, 'America/New_York')) * 60 + toMinute(toTimeZone(window_start, 'America/New_York')) BETWEEN 570 AND 959
    GROUP BY t
)
ORDER BY t LIMIT 500
"""


def query(sql):
    request = urllib.request.Request(API + urllib.parse.quote(" ".join(sql.split())), headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(5):
        try:
            return json.load(urllib.request.urlopen(request, timeout=60))["rows"]
        except Exception:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("the data service did not answer")


def bars(symbol):
    out, start = [], f"toDateTime('{FROM}')"
    while True:
        rows = query(SQL.format(symbol=symbol, start=start))
        out += rows
        if len(rows) < 500:
            return out
        start = f"fromUnixTimestamp({rows[-1]['ts'] + 900})"      # the bar after the last one received
        time.sleep(0.4)


def main():
    os.makedirs(OUT, exist_ok=True)
    for symbol in SYMBOLS:
        rows = bars(symbol)
        days = {}
        for r in rows:
            days.setdefault(r["time"][:10], []).append(r)
        full = [r for d in sorted(days) if len(days[d]) == 26 for r in days[d]]     # full sessions only, no half days
        with open(os.path.join(OUT, f"{symbol}_15m.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time", "open", "high", "low", "close", "volume"])
            w.writerows([[r["time"], r["open"], r["high"], r["low"], r["close"], int(r["volume"])] for r in full])
        print(f"{symbol}_15m.csv  {len(full):,} bars, {len(full) // 26} full days of {len(days)}, {full[0]['time']} to {full[-1]['time']}")


if __name__ == "__main__":
    main()

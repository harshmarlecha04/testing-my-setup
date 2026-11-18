"""Downloads daily price bars for SPY and QQQ from 2000 and saves them in data/.

    python get_data.py

Prices are Yahoo Finance's. They are not included in this repository because they are
not mine to redistribute. The 15 minute bars come from get_intraday.py.

Daily open, high, low and close are adjusted for dividends and splits (each is scaled by
adjusted close / close), so a buy-and-hold line includes dividends and old levels line up
with new ones.
"""
import csv
import datetime as dt
import json
import os
import time
import urllib.request

SYMBOLS = ["SPY", "QQQ"]
DAILY_FROM = "2000-01-01"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data")
URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{query}"


def fetch(symbol, query):
    request = urllib.request.Request(URL.format(symbol=symbol, query=query), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)["chart"]["result"][0]


def rows(result, intraday=False):
    zone = dt.timezone(dt.timedelta(seconds=result["meta"]["gmtoffset"]))
    q = result["indicators"]["quote"][0]
    adj = None if intraday else result["indicators"]["adjclose"][0]["adjclose"]
    out = []
    for i, ts in enumerate(result["timestamp"]):
        o, h, l, c, v = q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i]
        if None in (o, h, l, c):
            continue
        when = dt.datetime.fromtimestamp(ts, zone)
        if intraday:
            if not (dt.time(9, 30) <= when.time() < dt.time(16, 0)):
                continue                                   # regular session only
            out.append((when.strftime("%Y-%m-%d %H:%M"), round(o, 4), round(h, 4), round(l, 4), round(c, 4), v or 0))
        else:
            k = adj[i] / c if adj and adj[i] else 1.0
            out.append((when.strftime("%Y-%m-%d"), round(o * k, 4), round(h * k, 4), round(l * k, 4), round(c * k, 4), v or 0))
    return out


def save(name, data):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        w.writerows(data)
    print(f"{name:22s} {len(data):>6,} bars  {data[0][0]} to {data[-1][0]}")


def main():
    start = int(dt.datetime.strptime(DAILY_FROM, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp())
    for symbol in SYMBOLS:
        daily = rows(fetch(symbol, f"period1={start}&period2={int(time.time())}&interval=1d&events=div%2Csplits"), intraday=False)
        if daily and daily[-1][0] == dt.date.today().isoformat():
            daily = daily[:-1]                             # drop today's unfinished bar
        save(f"{symbol}_daily.csv", daily)


if __name__ == "__main__":
    main()

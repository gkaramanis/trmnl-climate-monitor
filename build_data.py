#!/usr/bin/env python3
"""
Build data.json for the TRMNL Climate Monitor plugin.

Fetches daily mean 2m temperature from the Open-Meteo Archive API (no key
needed), computes a 1991-2020 climatology (mean, 10-90th percentile band, and
record min/max range), then plots this year's daily temperatures against that
band -- in the style of the Reuters / Climate Reanalyzer automated monitor.

Everything (data + chart) is rendered here and written to data.json as
pre-built SVG strings, so the TRMNL Liquid template only has to embed them.

Configure via environment variables (see README) or the defaults below.
Standard library only -- no pip install required.
"""

import os
import json
import math
import datetime as dt
from urllib.request import urlopen, Request
from urllib.parse import urlencode

# ---------------------------------------------------------------------------
# Configuration  (override with env vars, e.g. LAT=51.50 LON=-0.12 ... )
# ---------------------------------------------------------------------------
LAT        = float(os.environ.get("LAT", "59.8586"))     # Uppsala by default
LON        = float(os.environ.get("LON", "17.6389"))
LOCATION   = os.environ.get("LOCATION", "Uppsala")
UNITS      = os.environ.get("UNITS", "celsius")          # "celsius" or "fahrenheit"
NORMAL_FROM = int(os.environ.get("NORMAL_FROM", "1991")) # climate-normal window
NORMAL_TO   = int(os.environ.get("NORMAL_TO", "2020"))
SMOOTH_DAYS = int(os.environ.get("SMOOTH_DAYS", "5"))    # +/- window for smoothing
OUTFILE     = os.environ.get("OUTFILE", "data.json")

UNIT_SYMBOL = "°F" if UNITS.startswith("f") else "°C"

ARCHIVE_URL  = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


# ---------------------------------------------------------------------------
# Data fetch
# ---------------------------------------------------------------------------
def _get_json(url, params):
    full = url + "?" + urlencode(params)
    req = Request(full, headers={"User-Agent": "trmnl-climate-monitor/1.0"})
    with urlopen(req, timeout=60) as resp:
        return json.load(resp)


def fetch_archive(start, end):
    """Daily mean temperature from ERA5 archive between two date strings."""
    data = _get_json(ARCHIVE_URL, {
        "latitude": LAT,
        "longitude": LON,
        "start_date": start,
        "end_date": end,
        "daily": "temperature_2m_mean",
        "temperature_unit": UNITS,
        "timezone": "auto",
    })
    daily = data.get("daily", {})
    out = {}
    for date_str, temp in zip(daily.get("time", []), daily.get("temperature_2m_mean", [])):
        if temp is not None:
            out[date_str] = float(temp)
    return out


def fetch_recent():
    """Last ~10 days incl. today from the forecast endpoint (fills archive lag)."""
    data = _get_json(FORECAST_URL, {
        "latitude": LAT,
        "longitude": LON,
        "daily": "temperature_2m_mean",
        "temperature_unit": UNITS,
        "past_days": 10,
        "forecast_days": 1,
        "timezone": "auto",
    })
    daily = data.get("daily", {})
    out = {}
    for date_str, temp in zip(daily.get("time", []), daily.get("temperature_2m_mean", [])):
        if temp is not None:
            out[date_str] = float(temp)
    return out


# ---------------------------------------------------------------------------
# Climatology
# ---------------------------------------------------------------------------
def doy_index(month, day):
    """Day-of-year index 0..365 using a leap reference year so Feb 29 fits."""
    return (dt.date(2000, month, day) - dt.date(2000, 1, 1)).days


def percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * p
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return sorted_vals[int(k)]
    return sorted_vals[lo] * (hi - k) + sorted_vals[hi] * (k - lo)


def circular_smooth(arr, window):
    """Smooth a 366-length array with a circular +/- window mean (skips None)."""
    n = len(arr)
    out = [None] * n
    for i in range(n):
        acc, cnt = 0.0, 0
        for d in range(-window, window + 1):
            v = arr[(i + d) % n]
            if v is not None:
                acc += v
                cnt += 1
        out[i] = acc / cnt if cnt else None
    return out


def build_climatology(archive):
    """Per-day-of-year mean / p10 / p90 / min / max over the normal window."""
    buckets = [[] for _ in range(366)]
    for date_str, temp in archive.items():
        y, m, d = (int(x) for x in date_str.split("-"))
        if NORMAL_FROM <= y <= NORMAL_TO:
            buckets[doy_index(m, d)].append(temp)

    mean = [None] * 366
    p10 = [None] * 366
    p90 = [None] * 366
    lo = [None] * 366
    hi = [None] * 366
    for i, vals in enumerate(buckets):
        if not vals:
            continue
        s = sorted(vals)
        mean[i] = sum(s) / len(s)
        p10[i] = percentile(s, 0.10)
        p90[i] = percentile(s, 0.90)
        lo[i] = s[0]
        hi[i] = s[-1]

    return {
        "mean": circular_smooth(mean, SMOOTH_DAYS),
        "p10": circular_smooth(p10, SMOOTH_DAYS),
        "p90": circular_smooth(p90, SMOOTH_DAYS),
        "lo": circular_smooth(lo, SMOOTH_DAYS),
        "hi": circular_smooth(hi, SMOOTH_DAYS),
    }


def current_year_series(archive, recent, year):
    """This year's daily temps keyed by day-of-year index (archive + forecast)."""
    series = {}
    for src in (archive, recent):                 # recent overrides archive lag
        for date_str, temp in src.items():
            y, m, d = (int(x) for x in date_str.split("-"))
            if y == year:
                series[doy_index(m, d)] = temp
    return series


# ---------------------------------------------------------------------------
# SVG rendering
# ---------------------------------------------------------------------------
MONTHS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]
MONTH_STARTS = [doy_index(m, 1) for m in range(1, 13)]


def nice_step(span):
    raw = span / 5.0
    for step in (1, 2, 2.5, 5, 10, 20, 25, 50):
        if step >= raw:
            return step
    return 100


def render_svg(clim, cur, year, W=560, H=440, base_fs=16):
    ml = base_fs * 3
    mr = base_fs
    mt = base_fs
    mb = base_fs * 2
    pw = W - ml - mr
    ph = H - mt - mb

    # temperature range across everything we plot
    all_vals = []
    for k in ("lo", "hi"):
        all_vals += [v for v in clim[k] if v is not None]
    all_vals += [v for v in cur.values() if v is not None]
    tmin, tmax = min(all_vals), max(all_vals)
    pad = (tmax - tmin) * 0.05 or 1
    tmin -= pad
    tmax += pad

    def X(doy):
        return ml + pw * (doy / 365.0)

    def Y(t):
        return mt + ph * (tmax - t) / (tmax - tmin)

    def band_path(low, high):
        top = [(X(i), Y(high[i])) for i in range(366) if high[i] is not None]
        bot = [(X(i), Y(low[i])) for i in range(366) if low[i] is not None]
        if not top or not bot:
            return ""
        pts = top + bot[::-1]
        return "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts) + " Z"

    def line_path(arr_or_dict, keys=None):
        if keys is None:
            seq = [(i, arr_or_dict[i]) for i in range(366) if arr_or_dict[i] is not None]
        else:
            seq = [(i, arr_or_dict[i]) for i in sorted(keys) if arr_or_dict.get(i) is not None]
        if not seq:
            return ""
        return "M " + " L ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in seq)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="100%" font-family="Helvetica,Arial,sans-serif" '
        f'shape-rendering="geometricPrecision">'
    ]

    fs = base_fs

    # record range + inner percentile band (light to medium grey)
    parts.append(f'<path d="{band_path(clim["lo"], clim["hi"])}" fill="#e3e3e3"/>')
    parts.append(f'<path d="{band_path(clim["p10"], clim["p90"])}" fill="#bcbcbc"/>')

    # horizontal (y-axis) gridlines + labels, drawn over the bands as dotted
    # mid-grey so they survive the 1-bit e-ink dithering (light greys vanish)
    step = nice_step(tmax - tmin)
    t = math.ceil(tmin / step) * step
    while t < tmax:
        y = Y(t)
        parts.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{W-mr}" y2="{y:.1f}" '
                     f'stroke="#555" stroke-width="1" stroke-dasharray="1 5"/>')
        parts.append(f'<text x="{ml-4}" y="{y+4:.1f}" text-anchor="end" '
                     f'font-size="{fs}" fill="#555">{int(round(t))}{UNIT_SYMBOL}</text>')
        t += step

    # normal mean line (dashed) + this-year line (bold black)
    parts.append(f'<path d="{line_path(clim["mean"])}" fill="none" stroke="#444" '
                 f'stroke-width="1.3" stroke-dasharray="4 3"/>')
    parts.append(f'<path d="{line_path(cur, keys=cur.keys())}" fill="none" '
                 f'stroke="#000" stroke-width="2.6" stroke-linejoin="round"/>')

    # month labels (no vertical gridlines)
    for m, start in enumerate(MONTH_STARTS):
        parts.append(f'<text x="{X(start)+pw/24:.1f}" y="{H-6}" text-anchor="middle" '
                     f'font-size="{fs}" fill="#555">{MONTHS[m]}</text>')

    # today marker
    if cur:
        last = max(cur.keys())
        cx, cy = X(last), Y(cur[last])
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.5" fill="#000"/>')
        lbl = f"{cur[last]:.0f}{UNIT_SYMBOL}"
        anchor = "end" if cx > W * 0.75 else "start"
        dx = -8 if anchor == "end" else 8
        parts.append(f'<text x="{cx+dx:.1f}" y="{cy-7:.1f}" text-anchor="{anchor}" '
                     f'font-size="{fs+3}" font-weight="bold" fill="#000">{lbl}</text>')

    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    today = dt.date.today()
    year = today.year

    print(f"Fetching archive {NORMAL_FROM}-01-01 .. {today} for {LOCATION} ...")
    archive = fetch_archive(f"{NORMAL_FROM}-01-01", today.isoformat())
    recent = fetch_recent()

    clim = build_climatology(archive)
    cur = current_year_series(archive, recent, year)

    # headline numbers for the title bar
    today_doy = doy_index(today.month, today.day)
    cur_temp = cur.get(today_doy)
    if cur_temp is None and cur:
        cur_temp = cur[max(cur.keys())]
    normal = clim["mean"][today_doy]
    anomaly = (cur_temp - normal) if (cur_temp is not None and normal is not None) else None

    payload = {
        "location": LOCATION,
        "units": UNIT_SYMBOL,
        "year": year,
        "updated": today.isoformat(),
        "current_temp": round(cur_temp, 1) if cur_temp is not None else None,
        "normal_temp": round(normal, 1) if normal is not None else None,
        "anomaly": round(anomaly, 1) if anomaly is not None else None,
        "anomaly_str": (f"+{anomaly:.1f}" if anomaly and anomaly >= 0
                        else (f"{anomaly:.1f}" if anomaly is not None else "n/a")) + UNIT_SYMBOL,
        "normal_window": f"{NORMAL_FROM}–{NORMAL_TO}",
        # full view: taller aspect ratio fills the chart column; compact is
        # wider/shorter for the half + quadrant layouts.
        "svg_full": render_svg(clim, cur, year, W=560, H=450, base_fs=17),
        "svg_compact": render_svg(clim, cur, year, W=780, H=300, base_fs=13),
    }

    with open(OUTFILE, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"Wrote {OUTFILE}: {LOCATION} today {payload['current_temp']}{UNIT_SYMBOL} "
          f"(normal {payload['normal_temp']}{UNIT_SYMBOL}, anomaly {payload['anomaly_str']})")
    print(f"SVG sizes: full {len(payload['svg_full'])}B, compact {len(payload['svg_compact'])}B")


if __name__ == "__main__":
    main()

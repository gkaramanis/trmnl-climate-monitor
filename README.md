# TRMNL Climate Monitor

A [TRMNL](https://usetrmnl.com) private plugin that plots this year's daily
temperature against the 1961–1990 climate normal for any location — in the
style of the [Reuters automated climate monitor](https://www.reuters.com/graphics/CLIMATE-AUTOMATED/MONITOR/akpeykqqapr/).

![preview](preview.png)

- **Light grey band** — the full daily range (min–max over 1961–1990)
- **Dark grey band** — 10th–90th percentile (a "typical" day)
- **Dashed line** — the normal (mean) for each day of year
- **Bold black line** — this year so far, with today's value marked

## How it works

1. `build_data.py` pulls daily mean 2 m temperature from the free
   [Open-Meteo](https://open-meteo.com) APIs (no key required) — the Archive
   API for the climate history and current year, topped up with the Forecast
   API for the last few days — computes the climatology, **renders the chart to
   SVG**, and writes a compact `data.json`.
2. A daily GitHub Action runs the script and commits `data.json` if it changed.
3. TRMNL polls the raw `data.json` URL and the Liquid template embeds the SVG.

All the maths and drawing happen in the build step, so the template stays
trivial and there's no server to run.

## Setup

### 1. Configure your location

Edit the config block at the top of
[`build_data.py`](build_data.py) — this is the single source of truth:

```python
LAT         = float(os.environ.get("LAT", "59.8586"))   # your latitude
LON         = float(os.environ.get("LON", "17.6389"))   # your longitude
LOCATION    = os.environ.get("LOCATION", "Uppsala")     # label on the device
UNITS       = os.environ.get("UNITS", "celsius")        # or "fahrenheit"
NORMAL_FROM = int(os.environ.get("NORMAL_FROM", "1961")) # climate-normal window
NORMAL_TO   = int(os.environ.get("NORMAL_TO", "1990"))
```

Find coordinates at e.g. https://www.latlong.net. Each value can also be
overridden per run via an environment variable, handy for a quick local test of
another place: `LAT=51.5074 LON=-0.1278 LOCATION=London python3 build_data.py`.

### 2. Push to GitHub and enable the Action

```bash
git init && git add . && git commit -m "TRMNL climate monitor"
gh repo create trmnl-climate-monitor --public --source=. --push
```

The repo must be **public** so TRMNL can poll the raw file without auth. The
workflow already requests `contents: write`, so it can commit on its own; if the
push step ever fails with a permissions error, set **Settings → Actions →
General → Workflow permissions → Read and write**. Run it once now to generate
`data.json` (**Actions → Update climate data → Run workflow**); after that it
runs daily at 05:20 UTC.

Your polling URL is:

```
https://raw.githubusercontent.com/<user>/trmnl-climate-monitor/main/data.json
```

### 3. Create the TRMNL private plugin

In the TRMNL web UI: **Plugins → Private Plugin → Add new**.

- **Strategy:** Polling
- **Polling URL:** the raw `data.json` URL above
- **Refresh:** every 12–24 h (the data updates once a day)
- **Markup:** paste [`trmnl/full.liquid`](trmnl/full.liquid) into the **Full**
  layout tab. (Only the full layout is implemented.)

Save, add it to a playlist, and you're done.

## JSON fields

| field | meaning |
|-------|---------|
| `location`, `units`, `year`, `updated` | labels |
| `current_temp`, `normal_temp`, `anomaly`, `anomaly_str` | today vs normal |
| `normal_window` | e.g. `1961–1990` |
| `svg_full` | the pre-rendered chart embedded by `full.liquid` |
| `svg_compact` | a wider/shorter chart variant, still generated but currently unused |

## Notes & limits

- Open-Meteo's archive lags real time by a few days; the script tops up the
  last ~10 days (including today) from the Forecast API, so the tip of the line
  is a forecast-grade estimate until the reanalysis catches up.
- This tracks a **point location**, not the global mean the Reuters monitor
  shows. For a regional average, average several `build_data.py` runs or extend
  the script to query multiple points.
- Open-Meteo is free for non-commercial use; this stays well within limits
  (two API requests per daily run).

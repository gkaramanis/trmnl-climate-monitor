# TRMNL Climate Monitor

A [TRMNL](https://usetrmnl.com) private plugin plotting this year's daily
temperature against the 1961–1990 climate normal for any location, in the style
of the [Reuters climate monitor](https://www.reuters.com/graphics/CLIMATE-AUTOMATED/MONITOR/akpeykqqapr/).

![preview](preview.png)

- **Light grey band** — daily range (min–max over 1961–1990)
- **Dark grey band** — 10th–90th percentile
- **Dashed line** — daily mean (the normal)
- **Bold black line** — this year so far, today's value marked

## How it works

1. `build_data.py` pulls daily mean 2 m temperature from the free
   [Open-Meteo](https://open-meteo.com) APIs (no key): the Archive API for the
   history and current year, the Forecast API for the last few days. It computes
   the climatology, renders the chart to SVG, and writes `data.json`.
2. A daily GitHub Action runs the script and commits `data.json` when it changes.
3. TRMNL polls the raw `data.json` URL; `full.liquid` embeds the SVG.

## Setup

### 1. Configure

Edit the config block at the top of [`build_data.py`](build_data.py):

```python
LAT         = float(os.environ.get("LAT", "59.8586"))
LON         = float(os.environ.get("LON", "17.6389"))
LOCATION    = os.environ.get("LOCATION", "Uppsala")
UNITS       = os.environ.get("UNITS", "celsius")          # or "fahrenheit"
NORMAL_FROM = int(os.environ.get("NORMAL_FROM", "1961"))
NORMAL_TO   = int(os.environ.get("NORMAL_TO", "1990"))
```

Coordinates: e.g. https://www.latlong.net. Any value can be overridden per run,
e.g. `LAT=51.5074 LON=-0.1278 LOCATION=London python3 build_data.py`.

### 2. Push and enable the Action

```bash
git init && git add . && git commit -m "TRMNL climate monitor"
gh repo create trmnl-climate-monitor --public --source=. --push
```

The repo must be public so TRMNL can poll the raw file. Run the workflow once
(**Actions → Update climate data → Run workflow**) to generate `data.json`; it
then runs daily at 05:20 UTC. Polling URL:

```
https://raw.githubusercontent.com/<user>/trmnl-climate-monitor/main/data.json
```

### 3. Add the TRMNL plugin

**Plugins → Private Plugin → Add new**:

- **Strategy:** Polling
- **Polling URL:** the raw `data.json` URL
- **Refresh:** 12–24 h
- **Markup:** paste [`trmnl/full.liquid`](trmnl/full.liquid) into the Full tab

Save and add it to a playlist.

## JSON fields

| field | meaning |
|-------|---------|
| `location`, `units`, `year`, `updated` | labels |
| `current_temp`, `normal_temp`, `anomaly`, `anomaly_str` | today vs normal |
| `normal_window` | e.g. `1961–1990` |
| `svg_full` | chart embedded by `full.liquid` |
| `svg_compact` | wider/shorter chart variant |

## Notes

- The archive lags a few days; the last ~10 days (incl. today) come from the
  Forecast API, so the line's tip is a forecast until reanalysis catches up.
- Tracks a point location, not a global mean.
- Open-Meteo is free for non-commercial use (two API requests per daily run).

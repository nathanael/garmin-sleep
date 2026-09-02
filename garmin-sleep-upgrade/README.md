# Standalone mode

> For the full project — live Garmin sync, dashboard server, install instructions — see the root [README](../README.md). This file documents the no-server, drag-drop-only path.

If you'd rather not give your Garmin credentials to anything, you can feed the dashboard a static data export instead. No Python, no network, no server — just the browser.

## Quick start

1. Request your data from Garmin: [garmin.com/account/datamanagement](https://www.garmin.com/account/datamanagement/) → select the **Sleep** category → wait for the email → download and unzip.
2. In the unzipped archive, open `DI_CONNECT/DI_CONNECT_FITNESS/` and find any JSON files with `sleep` in the name.
3. Double-click `index.html` in this directory to open it in your default browser.
4. Click **"or load a Garmin export instead"** beneath the sign-in form, then drag the JSON files onto the page. Data is cached to `localStorage` so you only need to do this once per browser.

## Expected JSON schema

The loader looks for records shaped like this:

```json
{
  "calendarDate": "2025-01-15",
  "deepSleepSeconds": 4200,
  "lightSleepSeconds": 14400,
  "remSleepSeconds": 3900,
  "awakeSleepSeconds": 1800,
  "sleepScores": { "overallScore": 75 },
  "averageRespiration": 14.2,
  "lowestRespiration": 11.5,
  "avgSleepStress": 18.3,
  "spo2SleepSummary": {
    "averageSPO2": 95,
    "lowestSPO2": 89
  }
}
```

Extra fields are ignored. Missing fields just leave the corresponding chart blank.

## Limitations of standalone mode

- **No HRV.** HRV is not included in Garmin's own data export — it is only available through the live sync path described in the root README.
- **`localStorage` caps.** Browsers allow roughly 5–10 MB. A few years of sleep data fits comfortably; decades might not.
- **Single browser.** Data is tied to the browser profile it was dropped into. There is no sync.

## Dependencies

Loaded from CDN on first open (and cached by the browser for offline use afterwards): React 18, Recharts 2.10, Tailwind, Babel Standalone.

# Garmin Sleep Analyzer v1.9.0

A standalone single-page app for analyzing Garmin sleep data exports.

## Quick Start

1. **Double-click `index.html`** to open in your default browser
2. Drag and drop your Garmin JSON sleep files onto the drop zone
3. Data is automatically saved to browser localStorage

## Getting Your Garmin Data

1. Go to https://www.garmin.com/account/datamanagement/
2. Request data export (select "Sleep" category)
3. Wait for email with download link
4. Unzip and look for files in: `DI_CONNECT/DI_CONNECT_FITNESS/`
5. Drop any JSON files with "sleep" in the name

## Features

### Data Management
- **Drag & drop** JSON files to load
- **Auto-saves** to browser localStorage
- **Merge mode** to combine multiple exports
- **Collapsible upload section** after data loads

### Analysis Views
- **Days / Weeks / Months** aggregation toggle
- **Date range presets**: 7d, 14d, 30d, 3mo, 6mo, 1y, All
- **Period navigation** (◀◀ / ▶▶ buttons)

### Charts
- REM Sleep (with 90min target line)
- Deep Sleep (with 60min minimum line)
- Sleep Score
- Respiration Rate
- Sleep Stress
- SpO2 (Lowest)

### Metrics Tracked
| Metric | What It Shows |
|--------|---------------|
| Sleep Score | Garmin's overall score (0-100) |
| Duration | Total sleep time |
| REM Sleep | Minutes in REM stage |
| Deep Sleep | Minutes in deep stage |
| Respiration | Average breathing rate (brpm) |
| SpO2 | Blood oxygen (avg and lowest) |
| Stress | Sleep stress score |

### Visual Indicators
- **Red text**: Below optimal (e.g., REM < 60min)
- **Green text**: Above target (e.g., REM > 90min)
- **Yellow text**: Elevated stress or low deep sleep
- **Reference lines**: Target/threshold markers on charts

## Technical Notes

### Dependencies (loaded via CDN)
- React 18
- Recharts 2.10
- Tailwind CSS
- Babel (for JSX transformation)

### Data Storage
- Uses browser `localStorage`
- Data persists between sessions
- "Clear all" button removes all saved data

### File Format Expected
Garmin sleep JSON with fields like:
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

## Limitations

- **No HRV data** (not included in Garmin exports)
- **Requires JavaScript** enabled in browser
- **localStorage limits** (~5-10MB depending on browser)
- **Single-user** (data stored in browser, not synced)

## Offline Use

Works completely offline after first load (CDN resources are cached).

## For Development

The full-featured version with comparison mode, drag-to-select, and trend indicators is in:
- `garmin_sleep_analyzer.jsx` (React component)

This standalone HTML version is simplified for easy local use.

---

## Version History

- **v1.9.0**: Collapsible upload section, auto-collapse on data load
- **v1.8.3**: Gray comparison timeline for consistency
- **v1.8.2**: Fixed date sorting bug (reverse mutation)
- **v1.8.1**: Fixed date sorting with Date objects
- **v1.8.0**: Trend indicators, prior period comparison, fixed date picker
- **v1.7.1**: Comparison card color refinement
- **v1.7.0**: Single drag-to-select, auto-comparison

---

*Built for health tracking and sleep optimization analysis.*

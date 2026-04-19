# Garmin Sleep — GitHub Packaging Design

**Date:** 2026-04-19
**Audience:** Open-source users (fellow Garmin owners who want a local, private dashboard for their sleep data).
**Goal:** Package the project so a stranger who finds the repo on GitHub can understand what it is in 30 seconds and get it running in ~5 minutes.

## Positioning

One-liner: *A private, local-first sleep dashboard for your Garmin data — drag-drop JSON exports, or auto-sync over OAuth and analyze in the browser.*

Differentiators to foreground:
- Runs entirely on your machine; nothing phones home.
- Works with Garmin's own data export (no server required) *or* live sync.
- Compare-period mode and drag-to-select are not in Garmin Connect.

## README structure (product-page style)

1. **Hero** — title, one-line pitch, `hero.png`.
2. **What it shows** — 4 feature bullets, each with an inline screenshot:
   - Sleep score + summary cards (covered by hero)
   - Stage breakdown — `architecture.png`
   - Compare periods — `compare.png`
   - Weeks / months aggregation — `aggregation.png`
3. **How it works** — ASCII diagram:
   `Garmin Connect → garmy OAuth → sync.py → health.db (SQLite) → server.py → dashboard`
4. **Install** — 3 steps: clone + setup, login, run server.
5. **Daily sync** — manual (`sync.py [days]`) and automatic (`install-schedule.sh` → launchd at 7am).
6. **Standalone mode** — drag-drop Garmin JSON, no server needed.
7. **Privacy** — data stays local; OAuth tokens in `~/.garmy/`; no outbound analytics.
8. **FAQ** — MFA, multiple accounts, HRV availability, Linux/Windows support.
9. **Credits** — garmy, React, Recharts, Tailwind.
10. **License** — MIT.

## Screenshots

Live in `docs/screenshots/`. Mapping from user-provided files in `Images/`:

| Source | Destination | Usage |
| --- | --- | --- |
| `Screenshot 2026-04-19 at 18.46.30.png` | `docs/screenshots/hero.png` | README hero |
| `Screenshot 2026-04-19 at 18.51.27.png` | `docs/screenshots/architecture.png` | Feature: stage breakdown |
| `Screenshot 2026-04-19 at 18.51.57.png` | `docs/screenshots/compare.png` | Feature: compare mode |
| `Screenshot 2026-04-19 at 18.52.29.png` | `docs/screenshots/aggregation.png` | Feature: weeks/months |

## Repo housekeeping

- **Fix hardcoded paths.** `setup-garmy.sh` and `com.garmy.sync.plist` reference `/Users/monster/...` from a different machine. Rewrite to be repo-relative and `$HOME`-aware.
- **`install-schedule.sh`** should template the plist at install time (substitute the repo path + python path), so users don't hand-edit.
- **LICENSE.** Add MIT with "Nathanael" as copyright holder.
- **Two READMEs.** The inner `garmin-sleep-upgrade/README.md` currently carries most docs. After repackaging it will be trimmed to a short pointer at the root README plus the standalone-mode specifics.
- **`.gitignore`** already excludes `health.db`, `.venv/`, logs — no change needed.

## Non-goals

- No animated GIF demo (scope limited to a great README).
- No social preview image (not requested).
- No synthetic demo data generator (user is comfortable using real data in screenshots).
- No code refactors beyond the portability fixes above.

## Success criteria

- Fresh clone on a different Mac: a user following the README can go from `git clone` → working dashboard without editing files.
- README renders cleanly on github.com: screenshots scale, tables render, ASCII diagram is readable.
- `grep -r /Users/monster .` returns nothing in tracked files.

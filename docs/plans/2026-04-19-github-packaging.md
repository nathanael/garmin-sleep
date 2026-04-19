# GitHub Packaging Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Package `garmin-sleep` for public GitHub release — product-style README with screenshots, portable setup scripts, MIT license.

**Architecture:** Documentation + light refactors only, no app-logic changes. Screenshots live in `docs/screenshots/`. Root `README.md` becomes canonical; inner README trimmed to pointer. Hardcoded `/Users/monster/...` paths in shell/plist are rewritten to be repo-relative and `$HOME`-aware.

**Tech Stack:** Markdown, bash, plist XML. No test framework — verification is grep + visual diff + "does it still run".

**Reference:** [docs/plans/2026-04-19-github-packaging-design.md](./2026-04-19-github-packaging-design.md)

---

## Task 1: Install screenshots

**Files:**
- Create: `docs/screenshots/hero.png`
- Create: `docs/screenshots/architecture.png`
- Create: `docs/screenshots/compare.png`
- Create: `docs/screenshots/aggregation.png`

**Step 1: Move + rename**

```bash
mv "Images/Screenshot 2026-04-19 at 18.46.30.png" docs/screenshots/hero.png
mv "Images/Screenshot 2026-04-19 at 18.51.27.png" docs/screenshots/architecture.png
mv "Images/Screenshot 2026-04-19 at 18.51.57.png" docs/screenshots/compare.png
mv "Images/Screenshot 2026-04-19 at 18.52.29.png" docs/screenshots/aggregation.png
rmdir Images
```

**Step 2: Verify**

```bash
ls docs/screenshots/
```
Expected: `aggregation.png architecture.png compare.png hero.png`

**Step 3: Commit**

```bash
git add docs/screenshots/
git commit -m "Add dashboard screenshots for README"
```

---

## Task 2: Fix hardcoded paths in `setup-garmy.sh`

**Files:**
- Modify: `setup-garmy.sh`

**Problem:** file references `/Users/monster/...` throughout, targets a different machine, and installs `garmy` globally. Rewrite as a repo-local bootstrap that creates `.venv/` and installs `garmy[all]` into it.

**Step 1: Replace the script**

Replace the entire file with a minimal, portable bootstrap:

```bash
#!/bin/bash
# Bootstrap: create .venv, install garmy, and log you in to Garmin Connect.
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$REPO_DIR/.venv"

echo "[1/3] Creating venv at $VENV"
python3 -m venv "$VENV"

echo "[2/3] Installing garmy"
"$VENV/bin/pip" install --upgrade pip >/dev/null
"$VENV/bin/pip" install "garmy[all]"

echo "[3/3] Logging in to Garmin Connect (one-time; tokens saved to ~/.garmy/)"
"$VENV/bin/python" "$REPO_DIR/login.py"

echo ""
echo "Setup complete. Next:"
echo "  $VENV/bin/python sync.py 30         # pull 30 days of data"
echo "  $VENV/bin/python garmin-sleep-upgrade/server.py"
```

**Step 2: Verify no hardcoded user paths remain**

```bash
grep -n "/Users/monster" setup-garmy.sh
```
Expected: no output (exit 1).

**Step 3: Commit**

```bash
git add setup-garmy.sh
git commit -m "Rewrite setup-garmy.sh as portable repo-local bootstrap"
```

---

## Task 3: Templatize `com.garmy.sync.plist` and fix `install-schedule.sh`

**Files:**
- Modify: `com.garmy.sync.plist`
- Modify: `install-schedule.sh`

**Problem:** plist hardcodes `/Users/monster/dev/garmy/...`. Make it a template with `__REPO_DIR__` placeholders; have `install-schedule.sh` substitute them at install time.

**Step 1: Read current plist**

```bash
cat com.garmy.sync.plist
```
Note the paths that need substituting: `ProgramArguments` (python + sync.py), `StandardOutPath`, `StandardErrorPath`, `WorkingDirectory`.

**Step 2: Replace plist with a template**

Use `__REPO_DIR__` as the placeholder that `install-schedule.sh` will substitute.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.garmy.sync</string>
    <key>ProgramArguments</key>
    <array>
        <string>__REPO_DIR__/.venv/bin/python</string>
        <string>__REPO_DIR__/sync.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>7</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>WorkingDirectory</key>
    <string>__REPO_DIR__</string>
    <key>StandardOutPath</key>
    <string>__REPO_DIR__/sync.log</string>
    <key>StandardErrorPath</key>
    <string>__REPO_DIR__/sync-error.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
```

> **Note:** Compare against the current committed plist before overwriting — preserve any keys I may not have captured above (e.g. `EnvironmentVariables`, `KeepAlive`).

**Step 3: Rewrite `install-schedule.sh`**

```bash
#!/bin/bash
# Install the daily 7am Garmin sync (launchd).
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_SRC="$REPO_DIR/com.garmy.sync.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.garmy.sync.plist"

# Unload existing agent if present
launchctl unload "$PLIST_DST" 2>/dev/null || true

# Render template → LaunchAgents (sed with | delimiter so paths with / are fine)
mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__REPO_DIR__|$REPO_DIR|g" "$PLIST_SRC" > "$PLIST_DST"

launchctl load "$PLIST_DST"

echo "Installed: Garmin sync will run every day at 7am."
echo "Logs:      $REPO_DIR/sync.log"
echo ""
echo "Check:   launchctl list | grep garmy"
echo "Remove:  launchctl unload $PLIST_DST"
```

**Step 4: Verify**

```bash
grep -rn "/Users/monster" com.garmy.sync.plist install-schedule.sh setup-garmy.sh
```
Expected: no output.

```bash
bash -n install-schedule.sh && bash -n setup-garmy.sh
```
Expected: no output (shellcheck syntax pass).

**Step 5: Commit**

```bash
git add com.garmy.sync.plist install-schedule.sh
git commit -m "Templatize sync plist; install-schedule.sh now portable"
```

---

## Task 4: Add MIT LICENSE

**Files:**
- Create: `LICENSE`

**Step 1: Write the file**

Standard MIT, `Copyright (c) 2026 Nathanael`.

**Step 2: Commit**

```bash
git add LICENSE
git commit -m "Add MIT license"
```

---

## Task 5: Write root `README.md`

**Files:**
- Create: `README.md`

**Step 1: Draft per design doc**

Follow the section order from the design doc exactly. Reference:
- `docs/screenshots/hero.png`
- `docs/screenshots/architecture.png`
- `docs/screenshots/compare.png`
- `docs/screenshots/aggregation.png`

Include:
- Pitch line under title
- Hero screenshot
- "What it shows" — 4 feature bullets, each with inline screenshot (architecture/compare/aggregation; the hero covers the summary-cards bullet so don't re-embed it)
- "How it works" — ASCII diagram + 1 paragraph
- "Install" — 3 numbered steps using the rewritten `setup-garmy.sh`
- "Daily sync" — manual vs launchd
- "Standalone mode" — drag-drop, links to `garmin-sleep-upgrade/README.md`
- "Privacy" — local-only, tokens in `~/.garmy/`
- "FAQ" — MFA, multi-account, HRV, Linux/Windows
- "Credits" — garmy, React, Recharts, Tailwind
- "License" — MIT, link to LICENSE

**Step 2: Preview it**

```bash
# Render check: ensure image paths resolve
grep -n "docs/screenshots" README.md
ls docs/screenshots/
```
All referenced paths should exist.

**Step 3: Commit**

```bash
git add README.md
git commit -m "Add product-style README with dashboard screenshots"
```

---

## Task 6: Trim `garmin-sleep-upgrade/README.md`

**Files:**
- Modify: `garmin-sleep-upgrade/README.md`

**Goal:** Avoid two competing top-level READMEs. Keep this one focused on **standalone mode** (drag-drop Garmin JSON export — the no-server path) and point readers to the root README for everything else.

**Step 1: Rewrite**

Short header, "Standalone mode" quick start, expected JSON schema, limitations, pointer up to `../README.md` for the server-based workflow. Drop the version history (lives in git log).

**Step 2: Verify links**

```bash
grep -n "README" garmin-sleep-upgrade/README.md
```
Should reference `../README.md`.

**Step 3: Commit**

```bash
git add garmin-sleep-upgrade/README.md
git commit -m "Trim inner README to standalone-mode pointer"
```

---

## Task 7: End-to-end verification

**Step 1: Confirm no stray personal paths**

```bash
git grep -n "/Users/monster" -- . ':(exclude)docs/plans/*'
```
Expected: no output.

**Step 2: Confirm screenshots are wired up**

```bash
for f in hero.png architecture.png compare.png aggregation.png; do
  grep -q "docs/screenshots/$f" README.md || echo "MISSING: $f"
done
```
Expected: no `MISSING` output.

**Step 3: Confirm README renders**

Open `README.md` on github.com after push (or local preview). Tables, code blocks, images, ASCII diagram all render cleanly.

**Step 4: Final status check**

```bash
git status
git log --oneline -10
```
Tree clean; commits from this plan visible.

---

## Done when

- `git grep /Users/monster` returns nothing outside `docs/plans/`.
- Root `README.md` exists with all 4 screenshots embedded and visible.
- `LICENSE` (MIT) committed.
- `setup-garmy.sh` and `install-schedule.sh` run with no hand-editing on a fresh clone.
- Inner `garmin-sleep-upgrade/README.md` trimmed to standalone-mode docs.

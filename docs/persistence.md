# Persistence — long-term coverage accumulation

*Status: implemented (store + retention). Optional; off by default.*

## Why

Without persistence the viewer only knows the feeder's rolling history window
(~a day), and it resets on container recreation. This feature lets coverage
**accumulate over weeks/months** in a file on a mapped volume, so you can see a
long-term envelope and the timeline can sweep the whole period.

The app is already a coverage *accumulation* (a de-duplicated set of "cells we've
heard in"), so this is a natural fit: keep that set on disk and merge into it.

## Design

Enabled by one env var — `ADSB_DATA_DIR` (a volume directory). Unset = today's
behavior (no persistence). When set, that directory holds:

- `adsbvue.db` — the coverage store (SQLite; part of the Python stdlib, so still
  zero third-party dependencies).
- `cities.local.json` — read from here first if present, so it's **live-editable**
  on the volume (no image rebuild). Falls back to the copy baked next to
  `server.py`, then to the built-in defaults.

### The store

One row per coverage cell, keyed by the coarse grid key `(klat, klon, kalt)`:

| column | meaning |
|---|---|
| `klat, klon, kalt` | grid-cell key (lat/lon rounded to `CELL_NM` cells, altitude bucketed to `ALT_BIN_FT`) — PRIMARY KEY |
| `brg, dist, alt` | the point we serve (from the cell's first sighting) |
| `first_seen` | earliest epoch the cell was heard — drives the timeline |
| `last_seen` | latest epoch the cell was heard — used to merge and retain |

### Merge on rebuild

Each rebuild reads the recent chunks and de-duplicates them **in memory** first
(fast — the same coarse-grid pass as before, now tracking `last_seen` too). Then
the ~100k distinct cells of that window are **upserted** into the store in one
transaction: new cell → insert; existing → keep `min(first_seen)` and
`max(last_seen)`. The served payload is then the *whole accumulated set*
(`SELECT` from the store), not just the read window. Reads of `/cone` still serve
pre-serialized cached bytes, so they never touch the DB.

Doing the heavy de-dup in memory and upserting only the distinct cells keeps the
DB writes cheap (one transaction of ~100k rows per rebuild).

### Load on start

Automatic — the `.db` file is simply present on the volume, so a restart picks up
with everything it had.

### Retention

`ADSB_RETAIN_DAYS` (default 30, `0` = keep everything): each rebuild deletes cells
whose `last_seen` is older than the cutoff — a rolling "last N days of coverage".
Because a coverage map saturates (you eventually hear planes almost everywhere you
can), the store plateaus rather than growing without bound.

## Config

| Var | Default | Meaning |
|---|---|---|
| `ADSB_DATA_DIR` | *(unset)* | Volume dir. Set = persistence on (`<dir>/adsbvue.db`) + live cities from `<dir>`. |
| `ADSB_RETAIN_DAYS` | `30` | Drop cells not heard within this many days (`0` = keep all). |

### Docker

```yaml
services:
  adsbvue:
    # ...
    environment:
      - ADSB_DATA_DIR=/data
    volumes:
      - adsbvue-data:/data
volumes:
  adsbvue-data:
```

## Notes / trade-offs

- **Payload grows** over a long window (more distinct cells), so first load is
  heavier — more noticeable over the internet than a LAN. Downsampling could be
  added later; ship without it first and see.
- **Changing the grid resolution** (`ADSB_CELL_NM` / `ADSB_ALT_BIN_FT`) after data
  has accumulated mixes old and new cells. Simplest is to start the store fresh
  (delete the `.db`) when changing those; a future guard could auto-reset on a
  detected change.

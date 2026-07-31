# Choosing a value for `ADSB_MAX_CHUNKS`

`ADSB_MAX_CHUNKS` controls the **one-time history fill at startup**: how far
back ADSb-Vue reads tar1090's rolling history files so your map does not begin
blank, and how much of a gap it backfills after downtime.

That is the whole of it. It is a boot cost, not something you keep paying while
running, so there is very little to tune.

## Quick answer

| Your situation | Value |
| --- | --- |
| Normal use | `48` (the default), roughly six hours |
| You want the fullest first run and do not mind a slower boot | `0`, everything your feeder retains |
| Very slow machine, or you do not care about history | `4` to `8` |
| Your decoder is dump1090-fa or dump1090-mutability | Irrelevant. They keep no history files, so the map starts from now |

If you are unsure, leave it alone.

## Why it barely matters any more

ADSb-Vue records continuously from your feeder's live aircraft list. History
only answers the question "what did I miss before I started?", and you ask that
once per restart.

The fill is skipped entirely when it is not needed. If the stored map already
holds data from the last couple of minutes, startup does not read history at
all, so restarting a healthy container costs nothing:

```
seed: store is current (7s old), skipping history read
```

When it does run, it says what it is doing and why:

```
seed: cold start, read 48 chunks into 23310 cells of history
seed: filling a 184 min gap, read 48 chunks into 11746 cells of history
```

## How far back a given value reaches

Chunk length varies between feeders, so measure yours rather than guessing:

```bash
curl -s http://127.0.0.1/chunks/chunks.json | python3 -c '
import json, re, sys
d = json.load(sys.stdin)
ts = sorted(int(m.group(1)) for c in d.get("chunks", [])
            for m in [re.search(r"(\d+)", c)] if m)
if len(ts) < 2:
    sys.exit("not enough chunks to measure")
gaps = sorted((ts[i+1] - ts[i]) / 1000.0 for i in range(len(ts) - 1))
gap = gaps[len(gaps) // 2]
print("full chunks available: %d" % len(ts))
print("retained history: %.1f h" % ((ts[-1] - ts[0]) / 3600000.0))
print("median chunk length: %.0f s (%.1f min)" % (gap, gap / 60))
for n in (4, 8, 12, 24, 48):
    print("  ADSB_MAX_CHUNKS=%-3d reaches back about %5.1f min" % (n, (n - 2) * gap / 60))
'
```

> **The `n - 2` in that script is deliberate.** The chunk list ends with
> `current_large.gz` and `current_small.gz`, partial buffers still filling
> rather than complete chunks. ADSb-Vue takes the newest N entries, so **two of
> your N slots are always those partials**, whatever N you pick. Measured on a
> live feeder, `current_small` held 0.6 minutes at one moment while
> `current_large` was empty having just rolled over; at another point in the
> cycle `current_large` held 4.7 minutes.
>
> So usable history is about `(N - 2)` full chunks plus whatever the partials
> happen to hold. That fixed two-slot cost matters proportionally more the
> smaller N is, which is why low values reach back noticeably less than the
> plain arithmetic suggests.

## What you give up by setting it low

Two things, both confined to the moments around a restart:

- **A fresh install starts thinner.** With `4` you get roughly sixteen minutes
  of map on first run instead of six hours. It fills in from live data either
  way, just more slowly at first.
- **Downtime recovery is shorter.** If the container is down three hours, `48`
  recovers about six hours' worth and `4` recovers about sixteen minutes. The
  remainder is gone for good, because the live aircraft list has no memory.

Neither affects steady-state running.

## Related

- [persistence.md](persistence.md): keeping your map across restarts, which is
  what makes the startup fill a rare event rather than a constant one.

# Choosing a value for `ADSB_MAX_CHUNKS`

`ADSB_MAX_CHUNKS` sets how many of tar1090's rolling history chunks the server
downloads and parses on every rebuild. It is the single biggest lever on
ADSb-Vue's CPU and network cost, and the right value depends almost entirely
on one thing: whether you have persistence turned on.

If you want the answer without the reasoning, use the table below.

## Quick answer

| Your setup | Suggested value | Why |
| --- | --- | --- |
| Persistence on (`ADSB_DATA_DIR` set) | `4` to `8` | The store holds your history. Chunks only need to cover the gap between rebuilds. |
| Persistence on, running on a Raspberry Pi | `4` | Same reasoning, and the CPU saving matters most here. |
| Persistence on, first run or just wiped the store | `48` temporarily, then drop to `4` | Seeds the store with several hours of coverage immediately, then stops paying for it. |
| Persistence off, want a deep coverage envelope | `48` or `0` | Chunks are your only source of history. |
| Persistence off, running on a Raspberry Pi | `12` to `24` | A compromise. Less history, but the Pi keeps up. |

Persistence is the recommended setup and is described in
[persistence.md](persistence.md). If you are running with `ADSB_DATA_DIR`
set and `ADSB_MAX_CHUNKS` still at the default `48`, you are almost certainly
doing far more work than you need to.

## What the setting actually does

Your feeder (readsb, inside Ultrafeeder) keeps a rolling window of recent
aircraft history so that tar1090 can draw trails. It exposes that window as a
list of gzip-compressed chunk files.

On each rebuild, ADSb-Vue:

1. Fetches the chunk index
2. Downloads the newest `ADSB_MAX_CHUNKS` of them
3. Decompresses and parses every aircraft observation in all of them
4. Converts each observation to bearing, distance, and altitude
5. De-duplicates onto a coarse grid

Rebuilds happen every `ADSB_CACHE_SECS` (default 120 seconds). So this whole
cycle repeats every couple of minutes, all day.

## Why the default is 48

Before persistence existed, those chunks were the *only* source of history.
Whatever you read on this rebuild was your entire coverage envelope. Read 48
chunks and you got a few hours of coverage to draw. Read fewer and your Cone
was built from less data and looked noticeably thinner.

In that world, a high value was correct, and `48` was a reasonable default.

## What changes when persistence is on

With `ADSB_DATA_DIR` set, each rebuild merges what it read into a SQLite
store, and the store is what gets served to the browser. Your coverage
envelope lives in `adsbvue.db`, not in the chunks.

The chunks become nothing more than *"what is new since the last rebuild."*

That reframes the question entirely. You no longer need enough chunks to
build a good picture. You only need enough to avoid missing observations
between one rebuild and the next.

## The cost, and why it matters on a Pi

Every rebuild with `ADSB_MAX_CHUNKS=48` fetches 48 gzip files, decompresses
them, and walks every observation inside. On a typical feeder that is several
hours of aircraft data being re-parsed every two minutes, almost all of which
collapses into cells you already merged on the previous rebuild.

The work is wasted, but it is not free:

- **CPU**: gzip decompression plus JSON parsing plus a trig conversion per
  observation. This is the dominant cost.
- **Network**: tens of megabytes pulled from the feeder every rebuild. Fine
  over localhost, meaningful over a LAN, and painful over a VPN or a remote
  link.
- **Memory**: each rebuild holds the parsed observations while de-duplicating.

> **Raspberry Pi note:** this is the setting to look at first if ADSb-Vue
> feels sluggish, if rebuilds take longer than `ADSB_CACHE_SECS`, or if the
> container is competing with readsb for CPU. Dropping from `48` to `4` on
> a persistence-enabled site typically cuts the per-rebuild work by more
> than 90 percent with no visible change to the map. On a Pi 3 or Pi Zero 2
> this is the difference between comfortable and struggling.

## Measure your own feeder's chunk cadence

Chunk length is not the same on every feeder, so pick your value from a
measurement rather than a guess. Run this on the machine that can reach your
tar1090 instance, substituting your feeder's address:

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
print("chunks available: %d" % len(ts))
print("retained history: %.1f h" % ((ts[-1] - ts[0]) / 3600000.0))
print("median chunk length: %.0f s (%.1f min)" % (gap, gap / 60))
for n in (4, 8, 12, 24, 48):
    print("  ADSB_MAX_CHUNKS=%-3d covers %6.1f min" % (n, n * gap / 60))
'
```

Example output from a real site:

```
chunks available: 362
retained history: 47.9 h
median chunk length: 480 s (8.0 min)
  ADSB_MAX_CHUNKS=4   covers   32.0 min
  ADSB_MAX_CHUNKS=8   covers   64.0 min
  ADSB_MAX_CHUNKS=12  covers   96.1 min
  ADSB_MAX_CHUNKS=24  covers  192.1 min
  ADSB_MAX_CHUNKS=48  covers  384.3 min
```

At that site, chunks are 8 minutes long. The default of `48` was covering
6.4 hours on every rebuild to capture 2 minutes of new observations, roughly
190 times more work than needed.

## Picking your number

With persistence on, you want:

```
ADSB_MAX_CHUNKS  >=  ADSB_CACHE_SECS / chunk_length_seconds,  plus margin
```

The bare minimum is whatever covers one rebuild interval. Everything above
that is safety margin, and margin is cheap in small amounts and expensive in
large ones.

Using the example above (8-minute chunks, 120-second rebuilds):

- The mathematical minimum is 1 chunk, since one 8-minute chunk already
  covers a 2-minute gap
- `4` gives a 16x margin (32 minutes of overlap)
- `8` gives a 32x margin (64 minutes of overlap)

That margin absorbs a container restart, a feeder hiccup, a rebuild that runs
long, or clock skew between the two machines, without ever dropping
observations. `4` is a good default for most persistence-enabled sites.
Go to `8` if you want to be conservative, or if your feeder's chunks are
unusually short.

> **Do not set it to `1` or `2` chasing the last few percent.** The savings
> from `4` to `2` are small, and you lose the margin that protects you from
> a restart or a slow rebuild silently dropping coverage.

## What you give up

On an established install with persistence: nothing. The store holds your
history, and the map looks identical.

The one case where a low value is visible is a **cold start**: if you wipe
`adsbvue.db` (or start a brand new install), `ADSB_MAX_CHUNKS=4` means your
first render shows only about half an hour of coverage, where `48` would have
shown several hours immediately. It fills in from there as the store
accumulates, so this matters for roughly the first hour of a fresh install
and never again.

> **Best of both:** set `48` (or `0`) for the first few rebuilds after a
> fresh start or a store wipe, let the store seed itself richly, then drop
> back to `4` for normal operation. It is a manual step, but it costs you
> nothing afterward.

## If you are not using persistence

Everything above assumes `ADSB_DATA_DIR` is set. If it is not, the chunks are
your only history and the calculus flips: a higher value directly means a
deeper coverage envelope, and `48` or `0` (all retained history) is the right
choice if your hardware can absorb it.

On constrained hardware without persistence you are making a genuine
tradeoff between coverage depth and CPU. `12` to `24` is a reasonable middle
ground. But the better answer is usually to turn persistence on, at which
point you get both a deep envelope and a low chunk count.

See [persistence.md](persistence.md) for how to set it up.

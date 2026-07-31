# Status

<!-- VOLATILE. "Where were we?" and nothing else. Overwrite freely; git log holds
     the history. Update at the end of every session. -->

Last updated: 2026-07-31 by claude

## Current objective

`main` just absorbed two merges: the aircraft.json-polling ingest rewrite
(`ingest-poll`) and the context scaffold. The old chunks-versus-poll divergence
is **resolved** - `main`'s code now polls `aircraft.json`, matching the deployed
container. Ready to push once the pre-push coordinate check is settled (tracked
outside this file).

## State

- Branch: `main` @ the two merge commits. Deployed skyscanner runs the
  `ingest-poll` image, whose code now equals `main`.
- Ingest: background thread polls `/data/aircraft.json`; chunks are a startup
  seed only. `/cone` is packed binary, built by a background refresher.
- Coverage store: ~2.23M cells / ~137 MB, 30-day retention.
- Working tree: clean.

## Done in the last sessions

- Three viewer/server fixes, measured and shipped: the Brave "V" (3x3 median on
  terrain reads), the density volume vanishing when zoomed in during playback
  (`frustumCulled = false`), and slow (~20-27s) page loads (packed-binary `/cone`
  + background cache + `no-cache` on index.html).
- Merged `ingest-poll` and the scaffold into `main`; the one conflict
  (`adsbvue.service`, modify/delete) resolved as a delete - Docker is the only
  supported deployment now.
- DETAILS.md updated for the poll ingest path.

## Next concrete step

When the box returns from the `ingest-poll` image to `:latest`, remove the
watchtower-disable label from `/opt/adsbvue/docker-compose.yml` or it stops
auto-updating.

## Parked work (measured or scoped, not started)

- **Cache headers:** index.html sends `no-cache`; a fuller ETag/max-age pass on
  `/cone` and static assets is still open.
- **Streaming the `/cone` payload** to cut peak build memory on low-RAM Pis. An
  idea only; no reliable numbers (the past prototype was never committed).
- **RSSI / signal strength:** wanted, but needs a schema migration and a
  validation plan first.
- **Altitude-outlier specks:** parked fix is to require a cell heard in more than
  one refresh before drawing it (keeps balloons; a hard altitude cap was
  rejected).
- **Range trim:** `ADSB_MAX_RANGE_NM` (default 400) already exists; pulling it in
  shrinks the payload further.
- **Export default:** the shipped default is "all"; 12h is the usable choice. A
  better default is worth a look.

## Open questions / unreproduced

- **Camera-persistence "flip":** an unreproduced user report that the saved map
  sometimes returns upside-down, recoverable only via "Reset saved settings".
  Suspected cause: an orbit dragging the camera below the ground plane, then that
  pose getting persisted. Never reproduced.

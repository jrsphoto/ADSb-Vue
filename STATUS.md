# Status

<!-- VOLATILE. "Where were we?" and nothing else. Overwrite freely; git log holds
     the history. Update at the end of every session. -->

Last updated: 2026-07-31 by claude

## The one thing to know first: chunks vs poll

There are two live versions of the ingest path.

- **`main`** reads tar1090 history **chunks** (`/chunks/*.gz`). This is what the
  code on `main` and the docs (README, DETAILS, docs/max_chunks) describe.
- **The `ingest-poll` branch** rewrote ingest to **poll `aircraft.json`** on a
  background thread. It is feature-complete and is what the deployed skyscanner
  container actually runs (`ghcr.io/jrsphoto/adsbvue:ingest-poll`).

`ingest-poll` is expected to **merge into `main` within a few days**. Until it
does, trust the code you are looking at, not the docs, for how ingest works.

## Current objective

Landing the context scaffold (this branch, `chore/context-scaffold`). Separately,
`ingest-poll` is done and deployed and waiting to merge.

## State

- Branch: `chore/context-scaffold` (scaffold work); `ingest-poll` holds the real
  feature work; `main` is the deployed-image source.
- Deployed on skyscanner: the `ingest-poll` image, healthy.
- Coverage store: ~2.23M cells / ~137 MB, 30-day retention.
- Working tree: clean except the scaffold in progress.

## Done in the last sessions

- Three viewer fixes, all measured and shipped on `ingest-poll` and live on
  skyscanner: (1) the Brave "V" (terrain heights read as a 3x3 median so one
  farbled pixel can't invent a cliff); (2) the density volume vanishing when
  zoomed in during timeline play (`frustumCulled = false` on the reveal mesh);
  (3) slow (~20-27s) page loads (packed-binary `/cone` built by a background
  refresher, plus `Cache-Control: no-cache` on index.html).
- These two viewer fixes also on `main` (`e4f1e88`, `c054a74`).

## Next concrete step

After this scaffold merges, **rewrite `DETAILS.md` for the poll ingest path** (it
still documents chunks). Then, when `ingest-poll` merges to `main` and the box
returns to the `:latest` image, remove the watchtower-disable label from
`/opt/adsbvue/docker-compose.yml`.

## Parked work (measured or scoped, not started)

- **Cache headers:** index.html now sends `no-cache`; a fuller ETag/max-age pass
  on `/cone` and static assets is still open.
- **Streaming the `/cone` payload** to cut peak build memory on low-RAM Pis.
  Prototyped in a past session; the prototype was never committed, so treat it as
  an idea with no reliable numbers until re-measured against current code.
- **RSSI / signal strength:** wanted, but needs a schema migration and a
  validation plan before starting.
- **Altitude-outlier specks:** a lone bit-flipped-altitude cell is drawn because
  one report plots a cell. Parked fix = require a cell heard in more than one
  refresh (keeps balloons, costs some far-rim one-time hits). A hard altitude cap
  was rejected: it would delete real high-altitude balloon traffic.
- **Range trim:** `ADSB_MAX_RANGE_NM` (default 400) already exists; pulling it in
  is a clean way to shrink the payload further now that loads are cheap.
- **Export default:** John exports 12h clips, never "all"; the shipped default is
  "all", which he considers unusable. A better default is worth a look.

## Open questions / unreproduced

- **Camera-persistence "flip":** an unreproduced user report that the saved map
  sometimes returns upside-down / cone pointing down, recoverable only via "Reset
  saved settings". Never reproduced or diagnosed. Suspected cause: drag-orbit
  overshooting the ground plane, then the below-ground camera getting persisted.

# Decisions

Append-only. One short entry per non-obvious choice, so neither you nor a future
session relitigates it. Date, decision, and the reason that would not be
guessable from the code.

## 2026-07 - Coverage envelope, not a traffic replay

The server de-dups every observation onto a coarse bearing/distance/altitude grid
and serves the accumulated set. The point is a *coverage map* ("where have we
ever heard something"), not a replay of traffic. That framing is why the payload
stays bounded no matter how much history is read, and why a cell, once lit, never
fades or reflects how busy it is.

## 2026-07 - Altitude exaggerated ~2x (ALT_SCALE = 1/250)

True to scale, 45 kft against a 250 nm radius is a nearly flat pancake. The
exaggeration makes the reception volume read as a dome without changing the
interpretation. It is a display choice, not a data one.

## 2026-07 - Density volume blends normal alpha, not additive

Additive blending blows out to white once thousands of translucent boxes overlap.
Normal alpha keeps the volume readable. Do not "fix" it back to additive.

## 2026-07 - Stdlib only, SQLite for the store

Zero third-party dependencies is a hard constraint (runs anywhere Python 3 does,
tiny image, no supply chain). Persistence uses SQLite specifically because it is
in the stdlib, so the store did not cost a dependency.

## 2026-07-21 - cities.local.json is a separate, git-ignored file on the volume

Earlier, per-site cities were inline edits to the tracked `index.html`, which
collided on every update. `index.html` is tracked and changes every release;
ignoring it would freeze the viewer. A separate `cities.local.json`, preferably on
the `data/` volume, is the only shape that keeps a site's cities AND lets it take
updates. The volume is also the one place that survives both `git pull` and
container recreation.

## 2026-07-22 - Map projection is azimuthal-equidistant, centered on the receiver

The first worldwide-borders pass draped the eastern hemisphere across a flat
tangent plane and misprojected everything distant. Azimuthal-equidistant from the
receiver preserves great-circle distance and bearing exactly, so every country
draws at its true position; near the receiver it agrees with the old projection to
first order. Do not reintroduce distance culling to "fix" far geography (that was
tried and it deleted the rest of the world); fading with distance is acceptable,
deleting is not.

## 2026-07-29 - The Brave "V" was canvas farbling; fixed by a neighbourhood median

The predicted-horizon model read each ground height from one terrain-tile pixel.
Brave Shields perturb canvas readback to defeat fingerprinting, and a one-step
change to that pixel's red channel decodes as a phantom 256 m cliff, which the
divide-by-distance grazing-angle model amplifies into a tall thin false spike on
one bearing. `elevM` now returns the median of a 3x3 pixel neighbourhood, so a
lone corrupted pixel is outvoted. At zoom 8 the window is finer than the sampling
step, so honest terrain is unaffected.

## 2026-07-30 - Playback volume culling (frustumCulled = false)

three.js computes an InstancedMesh's frustum-cull sphere once, on first draw. The
timeline reveal's first draw is at the window start, when almost no cells exist,
so the sphere freezes tiny; zoom into the body of the volume and three.js culls
the whole mesh. Disabling frustum culling on that one reveal mesh is correct: it
is the object the user is looking at, so there is nothing to save by culling it.

## 2026-07-31 - /cone is packed binary, built by a background refresher

Slow page loads (~20-27s) were the server rebuilding the payload on the request
path: `json.dumps` of ~2.2M point rows dominated. Two changes: build the payload
on a background thread so a page load is always served a ready copy, and send the
points as scaled-integer columns the browser reads as typed arrays instead of
parsing tens of MB of text. Scales stay finer than the de-dup grid, so nothing is
lost. Also `Cache-Control: no-cache` on index.html, so a stale page can never run
against the new binary format.

## 2026-07-31 - No hard altitude cap on ingest

A lone bit-flipped-altitude cell (e.g. one 106,500 ft box) is drawn because one
report plots a cell. A hard altitude ceiling was rejected: this site hears real
high-altitude balloon traffic that legitimately reports 100k+ ft. The parked
alternative is to require a cell be heard in more than one refresh before drawing
it, which drops one-message glitches while keeping balloons.

## Contributors and provenance

Real people reported or contributed these; credit matters on a public repo.

- **wiedehopf** - suggested polling `aircraft.json` instead of re-parsing history
  chunks every rebuild. That is the `ingest-poll` rewrite: chunks re-parse hours
  of data every couple of minutes to capture a couple of minutes of new
  observations; polling the live snapshot does the same job for far less work.
- **kx1t** (kx1t.com) - reverse-proxy relative-path fix (PR #1) and the worldwide
  borders + comprehensive default-cities integration (PR #2). Also prompted the
  `ADSB_WEB_PORT` naming (he read `ADSB_PORT` as the ADS-B data port) and reported
  the cone "mirage" (map borders drawn through the cone on purpose) that led to
  the opt-in `ADSB_MAP_BEHIND_CONE`.
- **rhodan76** - reported the density volume vanishing when zoomed in during
  timeline playback (the frustum-cull bug above).

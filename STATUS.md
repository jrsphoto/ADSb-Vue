# Status

<!-- VOLATILE snapshot. "Where were we?" and nothing else. Overwrite freely; git
     log holds the history. Update at the end of every session. Do not put real
     host addresses, IPs, or receiver coordinates in here; this file is public. -->

Last updated: 2026-08-01 by claude

## Current objective

The aircraft.json-polling rewrite, the viewer fixes, and the context scaffold are
all merged into `main`, published, and deployed. There is one line now: `main` is
the polling version, and it matches Gitea, GitHub, and the running container on
skyscanner (`:latest`). The heavy work is landed; what remains is one small
operational follow-up and a set of parked features.

## State

- Branch: `main`, in sync across local, Gitea, and GitHub.
- Working tree: NOT clean. It carries in-progress preflight additions (NTP/clock
  checks) that are not yet committed. See Open questions before committing them.
- Deployed: skyscanner runs `ghcr.io/jrsphoto/adsbvue:latest` (the polling version
  with this session's fixes), healthy. Coverage store persists on the `./data`
  bind mount and survived the image switch.

## Done in this session

- Fixed the Brave-only "V" in the predicted horizon: terrain heights are now read
  as the median of a 3x3 pixel patch, so Brave Shields' canvas anti-fingerprinting
  can no longer turn a single corrupted pixel into a phantom cliff.
- Fixed the density volume vanishing when zoomed in during timeline playback
  (`frustumCulled = false` on the growing reveal mesh).
- Fixed slow (~20-27s) page loads: `/cone` is now packed-binary, built by a
  background refresher so a page load never waits on it; `index.html` sends
  `Cache-Control: no-cache`.
- Added the context scaffold: CLAUDE.md, STATUS.md, docs/decisions.md, and
  scripts/ (preflight, check, deploy, logs). Real host config lives outside the
  repo at `~/.config/adsb-volume/preflight.local.conf`.
- Merged `ingest-poll` and the scaffold into `main`; dropped the systemd path
  (`adsbvue.service` deleted, Docker only).
- Scrubbed the receiver coordinates and the internal feeder hostname out of all
  git history, verified clean, force-pushed `main` to both remotes, and deleted
  the now-merged `ingest-poll` and scaffold branches.
- Broadened the README (works with any dump1090-compatible feeder that serves
  aircraft.json, not just Ultrafeeder), removed the run-as-a-service section, and
  rewrote DETAILS.md for the poll path.
- Deployed: skyscanner switched from the branch image to `:latest`; verified it is
  the poll version with the fixes and is healthy.

## Next concrete step

Remove the `com.centurylinklabs.watchtower.enable=false` label from
`/opt/adsbvue/docker-compose.yml` on skyscanner and run `docker compose up -d`.
That label was added only to stop Watchtower from swapping a pinned branch image;
the box runs `:latest` again now, so removing it lets auto-updates resume.

## Tried and rejected

- **"The Brave 'V' is a stale cached page."** Killed: a hard reload (Ctrl+Shift+R)
  did not remove it, and turning Brave Shields off did. The cause is Brave's
  canvas anti-fingerprinting corrupting single-pixel terrain reads. Do not chase
  caching for the V.
- **"The slow page load is the browser parsing the payload."** Killed by
  measurement: downloading and parsing the ~78 MB JSON payload was ~0.65 s and
  building the volume ~0.16 s. The real cost was the SERVER rebuilding the payload
  on the request path (~27 s when its cache was stale, `json.dumps` of ~2.2M rows
  dominating). The fix was a background cache plus a binary payload, not anything
  browser-side. Do not optimize the browser for load time.
- **"Watch the published image digest to know when the rebuilt image is ready."**
  Red herring: the digest read looked unchanged and I watched it for about an
  hour for nothing. Check the served page content (or the image's
  `/app/index.html`) for the change, not the registry digest.
- **A hard altitude cap to drop outlier specks.** Rejected: it deletes real
  high-altitude balloon traffic. Parked alternative is to require a cell be heard
  in more than one refresh before drawing it.

## Open questions / blockers

- **Uncommitted preflight changes leak an internal IP.** The in-progress NTP/clock
  checks hardcode a real internal server IP directly into the committed
  `scripts/preflight.conf`. Committing that to `main` publishes it to GitHub, the
  same class of leak just scrubbed. Move the real value into the external
  `~/.config/adsb-volume/preflight.local.conf` (keep only the generic check
  functions in the committed files) before committing.
- **Camera-persistence "flip":** unreproduced user report that the saved map
  sometimes returns upside-down, recoverable only via "Reset saved settings".
  Suspected: an orbit dragging the camera below the ground plane, then that pose
  getting persisted. Never reproduced.
- **Parked features:** RSSI (needs a schema migration and a validation plan),
  streaming the `/cone` payload (peak memory on low-RAM Pis), the altitude-outlier
  filter, a fuller cache-header pass (ETag), a better Export default (12h rather
  than "all"), and pulling in `ADSB_MAX_RANGE_NM` to shrink the payload.

<p align="center">
  <img src="adsbvue_logo.png" alt="ADSb-Vue — 3D Reception Volume & Analytics" width="640">
</p>

# ADSb-Vue

A standalone **3D volumetric view of your ADS-B antenna reception**, driven by an
Ultrafeeder / tar1090 receiver. Inspired by the "detection cone" viewer, but with
switchable render modes and a true volumetric density render.

It converts every aircraft observation your receiver hears into bearing /
distance / altitude relative to the antenna, and serves a self-contained
Three.js page that renders the accumulated result. A background reader records
continuously from your feeder's live aircraft list, so it works with
dump1090-fa and dump1090-mutability as well as tar1090. See
[How it records](#how-it-records).

> For a practical guide to using it as a diagnostic tool — antenna placement,
> reception troubleshooting, before/after comparisons — see
> **[BEST_PRACTICES.md](BEST_PRACTICES.md)**.
>
> For a more in-depth description of how the Python server and the Three.js
> frontend actually work, see **[DETAILS.md](DETAILS.md)**.

## Render modes (toggle in the UI)

- **Density volume** — observations binned into 3D cells drawn as translucent,
  colour-by-altitude blocks. Bright where reception is dense; you can see the
  low-altitude core near the receiver fade to high-altitude-only at the fringes.
- **Detection cone** — the *coverage floor*: the lowest altitude still heard at
  each bearing and range. ~0 near the receiver, rising with distance as the
  horizon hides low traffic. Dents = local blockage; the ragged rim = reach.
- **Point cloud** — every observation as an altitude-coloured point (the classic
  view; you can pick out individual airways).

Altitude-band checkboxes filter all three modes. The vertical axis is
exaggerated ~2× (45 kft ≈ 180 units vs 250 nm ≈ 250 units) so the naturally thin
altitude band reads as a dome rather than a pancake.

## Timeline — coverage over time

The **Timeline** panel replays how your coverage built up over the retained
history window. Drag the scrubber to reveal only what was first heard up to a
given moment, or press ▶ to sweep the whole window — all three render modes
animate the coverage filling in. **Loop** repeats the sweep and the **speed**
button (0.5–4×) sets how fast it runs.

**Heads up:** this is a **coverage envelope** of received ADS-B signal over the
window — *not* traffic during the window. Points only ever appear as they were
first heard; they don't fade or move. Even a single ping at 3am shows the same
as steady traffic. Think phosphor screen, not radar sweep.

**⏺ Export** records a play-through to a WebM file for sharing. Clicking it
opens a small dialog where you can pick how much recent history the clip
covers — **6h · 12h · 24h · 48h · all** — and it tells you how many hours
are actually stored (so a 24h choice against 6h of data still records the 6h
you have). The clip has a burned-in **date/time** stamp of the moment each
frame represents, a progress bar, and a slow camera orbit while recording.
Press **Esc** to cancel a recording in progress. (Recording needs a Chromium-
or Firefox-based browser.)

With **persistence** enabled (`ADSB_DATA_DIR`, see below) the timeline spans the
whole accumulated store, up to `ADSB_RETAIN_DAYS` of coverage. Without it, the
window is whatever has been recorded since the last restart, starting from the
history read in at boot (`ADSB_MAX_CHUNKS`).

## Run

    python3 server.py

Zero third-party dependencies — Python 3 standard library only. Then open
`http://<this-host>:24556/`. (The page pulls Three.js + a US state outline from
public CDNs, so the *viewer's browser* needs internet; the server only talks to
your Ultrafeeder on the LAN.)

## Configuration

Everything is optional — on the same host as your feeder the defaults just work
(`ADSB_ULTRAFEEDER=http://127.0.0.1`, port `24556`). All settings are `ADSB_*`
environment variables:

| Var                | Default              | Meaning                                   |
|--------------------|----------------------|-------------------------------------------|
| `ADSB_ULTRAFEEDER` | `http://127.0.0.1`   | Base URL of your tar1090 instance (the ADS-B **data source** — any host/port) |
| `ADSB_WEB_PORT`    | `24556`              | Web-UI port to listen on (alias: `ADSB_PORT`). Not a data port. |
| `ADSB_RECV_LAT`    | auto                 | Receiver latitude (else `/data/receiver.json`) |
| `ADSB_RECV_LON`    | auto                 | Receiver longitude                        |
| `ADSB_POLL_SECS`   | `5`                  | Seconds between reads of the live aircraft list |
| `ADSB_FLUSH_SECS`  | `60`                 | Seconds between batched writes to the store |
| `ADSB_MAX_CHUNKS`  | `48`                 | How much tar1090 history the one-time startup fill reads (`0` = all). A boot cost only, so a larger value is cheap: see [choosing a value](docs/max_chunks.md) |
| `ADSB_CELL_NM`     | `1.5`                | De-dup grid cell size (nm)                |
| `ADSB_ALT_BIN_FT`  | `1000`               | De-dup altitude bin (ft)                  |
| `ADSB_MAX_RANGE_NM`| `400`                | Discard positions farther than this (nm)  |
| `ADSB_LOW_ALT_FT`  | `10000`              | "Low altitude" cutoff for the low-alt range stat (ft) |
| `ADSB_FETCH_WORKERS`| `8`                 | Parallel chunk downloads (1 = serial; higher helps a remote feeder) |
| `ADSB_CACHE_SECS`  | `120`                | Seconds to cache parsed observations      |
| `ADSB_ANTENNA_AGL_FT`| `30`               | Antenna height above ground (ft) for the terrain horizon model |
| `ADSB_ANTENNA_ELEV_FT`| `0`                | Site ground elevation (ft MSL); only used by the LOS filter below |
| `ADSB_LOS_FILTER`  | `false`              | Drop observations whose distance exceeds the 4/3-earth line-of-sight range for their altitude — filters out bit-corrupted-altitude decodes at ingest |
| `ADSB_BORDER_COLOR`| `#3f82b8`            | State border colour (hex)                 |
| `ADSB_HOME_BORDER_COLOR`| `#6fd6c0`       | Home-state border colour (hex)            |
| `ADSB_FOG_DENSITY` | `0.0012`             | Distance-fade density; `0` disables the fade |
| `ADSB_MAP_BEHIND_CONE` | `false`          | Draw borders and city labels **behind** the coverage volume instead of over it. See [Map over or behind](#map-over-or-behind) |
| `ADSB_DATA_DIR`    | *(unset)*            | Volume dir for long-term persistence (see below). Unset = no store. |
| `ADSB_RETAIN_DAYS` | `30`                 | Store retention: drop cells not heard within N days (`0` = keep all) |
| `ADSB_HEYWHATSTHAT_ID` | *(unset)*        | Your HeyWhatsThat panorama id — enables the HWT range-rings overlay |
| `ADSB_HEYWHATSTHAT_ALTS_FT` | `10000,40000` | HWT ring altitudes (ft, comma-separated) |

Reading is coarse on purpose: this is a coverage map, not a traffic replay.
Lower `ADSB_CELL_NM` for finer detail.

`ADSB_MAX_CHUNKS` only affects the one-time fill at startup, so it is cheap to
set generously. `48` gives roughly six hours of history on a fresh install and
the same amount of catch-up after downtime. See
[choosing a value](docs/max_chunks.md).

### Map over or behind

Borders and city labels are normally drawn **over everything**, so they stay
readable through the coverage volume. That is the long-standing look and it is
still the default.

It has one awkward side effect. Seen from a low side angle, the whole distant
map squashes into a narrow band at the horizon, and that band lands across the
middle of the cone, looking a bit like a mirage of the map floating inside it.
The effect is strongest for coastal receivers, where there is far more coastline
to pile into that band, and it gets no better with the distance fade on: fog
dims the *colour* of those lines toward the background but cannot remove them,
so they turn into dark smudges on the cone instead of disappearing.

Set `ADSB_MAP_BEHIND_CONE=true` and the geography respects what is in front of
it. Distant borders get tinted by the volume rather than stamped on top, and the
distance fade dims them the way you would expect.

The trade is that borders and labels are no longer guaranteed visible. Behind a
solid cone they will be hidden. Try both and keep whichever you prefer.

### How it records

A background thread reads your feeder's live aircraft list
(`/data/aircraft.json`) every `ADSB_POLL_SECS`, and records what it finds
**whether or not anyone has the page open**. Results are batched to disk every
`ADSB_FLUSH_SECS` rather than written on every read, which is easier on an SD
card.

Every decoder serves that endpoint, so this works with **dump1090-fa** and
**dump1090-mutability** as well as tar1090.

Live readings carry no history, so at startup ADSb-Vue reads tar1090's history
files once to fill in the map rather than starting blank, and does the same
after downtime to fill the gap. `ADSB_MAX_CHUNKS` sets how far back that
reaches. On a decoder with no history files the step is skipped and the map
simply starts from now.

Pair this with `ADSB_DATA_DIR` so what it records survives a restart.

> **Worth knowing:** this is *lighter* on your feeder than the old approach, not
> heavier. Measured on a live receiver at a 1.0 nm cell size, reading every 5
> seconds moved about 19 MB/hour against 33 MB/hour for the history-file path.

If the map ever looks wrong, `/health` is the place to start. It reports whether
the reader is still getting data and how long ago, which separates "the antenna
has gone quiet" from "ADSb-Vue has stopped reading."

### Setting them

**Docker — inline (simplest for a few settings).** Add an `environment:` block to
the `adsbvue` service in `docker-compose.yml`:

```yaml
services:
  adsbvue:
    build: .
    image: adsbvue:latest
    container_name: adsbvue
    network_mode: host
    restart: unless-stopped
    environment:
      - ADSB_ULTRAFEEDER=http://192.168.1.50
      - ADSB_MAX_CHUNKS=8
```

**Docker — `.env` file (tidier for many settings).** Copy `.env.example` to
`.env`, edit it, and point the service at it instead of an `environment:` block:

```yaml
services:
  adsbvue:
    build: .
    image: adsbvue:latest
    container_name: adsbvue
    network_mode: host
    restart: unless-stopped
    env_file: .env
```

Keep `.env` comments on their own line (not after a value). If you use *both*,
`environment:` entries win over `env_file:`.

**Apply your changes.** After editing `docker-compose.yml` or `.env`, re-run it to
recreate the container with the new settings:

```
docker compose up -d
```

Add `--build` (`docker compose up -d --build`) whenever the **code** changed too —
e.g. after a `git pull` — so the image is rebuilt. It's always safe to include
`--build`.

**Without Docker.** Export the vars (`ADSB_ULTRAFEEDER=... python3 server.py`) or
drop a `.env` next to `server.py` — it auto-loads one. A real environment
variable always overrides the file. Restart the process to pick up changes.

## Customizing the map

Country and state/province **borders** and lakes are drawn automatically for
wherever your receiver is — worldwide, not just the US — with your home
country/state highlighted based on your position. No editing needed.

The labelled **cities** ship with a comprehensive worldwide default
(`cities.local.json.example`), so a fresh install shows the cities near *your*
receiver out of the box — no configuration. Only entries within range are drawn,
so the rest cost nothing. To use your own list instead, put a git-ignored
`cities.local.json` where the app can see it (JSON `[ "label", lat, lon ]` entries,
or the grouped form below — start from the example). It's served at `/cities` and
overrides the default. Where it lives depends on how you run:

- **With a `data/` volume (recommended — required for the prebuilt image):** the
  file lives at `data/cities.local.json`. Edit it and reload the page — no
  rebuild, and it survives updates and container recreation. See the persistence
  section below.
- **Building from source without a volume:** put it next to `server.py` before
  `docker compose up --build` (the Dockerfile bakes it into the image; rebuild
  after editing). Running plain `python3 server.py` reads it directly.

If your coverage spans several states, you can **group** the list to keep a long
file tidy — the group names are just for you (they're flattened for display):

```json
{
  "Minnesota": [ ["Minneapolis", 44.98, -93.27], ["Duluth", 46.78, -92.11] ],
  "Wisconsin": [ ["Madison", 43.07, -89.40], ["Green Bay", 44.51, -88.01] ]
}
```

Both the flat array and this grouped object are accepted.

## Terrain — predicted vs. measured coverage

Under **Terrain** in the panel, the viewer can compare what you *actually hear*
against what the surrounding terrain physically *lets* you hear. It's optional and
loads open elevation tiles in the browser on demand; if they can't be reached, the
rest of the app is unaffected. (There's also a **"? What am I seeing?"** button in
that section with the same explanation in-app.)

**▲ Predicted horizon** draws the lowest altitude an aircraft can fly and still be
in your antenna's line of sight, given the terrain around you and the earth's
curvature — a smooth bowl that's ~ground level at the receiver and rises with
distance. Set your mast height with `ADSB_ANTENNA_AGL_FT` (feet; the ground
elevation is read from the terrain automatically). A taller antenna sees over more
terrain and lowers the horizon.

**◑ Compare to horizon** recolours your measured detection cone by how it stacks
up against that horizon:

- **green** — you hear low traffic right down to the horizon: confirmed good coverage.
- **amber** — the lowest aircraft you heard sits higher than terrain says it should.
- **blue** — you heard something *below* the predicted horizon: over-performing.
- **grey** — only high traffic flew here, so low-altitude coverage can't be judged.

Two things to keep in mind when reading it:

- **Grey isn't bad.** You still have coverage there — you're hearing aircraft — but
  no *low* traffic came through to grade it, so low-altitude performance is simply
  *unknown*, not poor. The comparison only applies where the measured floor is below
  ~18,000 ft (i.e. low traffic actually flew there).
- **Amber is a clue, not a verdict.** It can mean a real gap (terrain or an obstruction
  blocking you), *or* just that the lowest plane that flew that way happened to be
  fairly high — which is why it's understated rather than alarm-red. Click a direction
  to open a **bearing profile** (terrain, horizon, and the actual hits along that
  bearing) to tell the two apart; green usually traces your busy arrival/departure
  corridors.

**◌ HWT range rings** — if you feed [HeyWhatsThat](https://www.heywhatsthat.com)
(most Ultrafeeder setups do; it's where tar1090's range rings come from), set
`ADSB_HEYWHATSTHAT_ID` to your panorama id and this toggle draws those same
trusted rings in 3D: each ring floats at its altitude and marks where a plane at
that altitude drops below your horizon. It's an independent model of the same
physics as the predicted horizon, so it doubles as a cross-check of both. The
server fetches the data once and caches it (on the `data/` volume when present),
so their free API is hit essentially never. Ring altitudes:
`ADSB_HEYWHATSTHAT_ALTS_FT` (default `10000,40000`). The panorama must be for
your receiver's location.

## Long-term coverage (persistence)

By default the viewer shows the feeder's rolling history (~a day) and resets on
container recreation. Set **`ADSB_DATA_DIR`** to a mapped volume and coverage
**accumulates there** across restarts, so you can build a weeks/months-long
envelope and the timeline sweeps the whole period. It's optional and off unless
you set it.

```yaml
services:
  adsbvue:
    # ...
    environment:
      - ADSB_DATA_DIR=/data
    volumes:
      - ./data:/data
```

The `./data:/data` bind mount keeps everything the container accumulates in a
`data/` folder **inside this repo folder** (e.g. `/opt/adsbvue/data`) — the same
place you manage the container from, easy to find and back up. It's git-ignored,
so `git pull` never touches it.

**Why `cities.local.json` lives in `data/` too:** everything in the app folder is
replaced by updates (`git pull` + rebuild), and everything baked into the image
dies with the container. The `data/` volume is the one place that survives both —
so that's where *your* stuff belongs: the accumulated coverage **and** your city
labels. On first run the app seeds `data/cities.local.json` from your existing
copy; from then on you edit it there and just reload the page — **no rebuild
needed**, and it survives every update and container recreation. See
[docs/persistence.md](docs/persistence.md) for the design.

## Endpoints

- `GET /`        — the 3D viewer page
- `GET /cone`    — observations as JSON (`?refresh=true` bypasses the cache)
- `GET /cities`  — optional local city labels (your `cities.local.json`, else `[]`)
- `GET /hwt`     — cached HeyWhatsThat horizon rings (`{}` when no id is set)
- `GET /health`  : liveness, plus how long ago the last successful read was
  (`last_poll_age_secs`), a `poll_ok` flag, and the aircraft count from that
  read, so you can tell a quiet antenna from a stalled reader

## Run via Docker (recommended)

Easiest on the same host that runs Ultrafeeder — co-located, always-on,
near-zero impact.

**Prebuilt image (no clone needed).** Every push to `main` is auto-built for
amd64 **and** arm64 (Raspberry Pi) and published to GitHub Container Registry.
Just point a compose file at it:

```yaml
services:
  adsbvue:
    image: ghcr.io/jrsphoto/adsbvue:latest
    container_name: adsbvue
    network_mode: host
    restart: unless-stopped
    environment:
      - ADSB_DATA_DIR=/data
    volumes:
      - ./data:/data
```

Update with `docker compose pull && docker compose up -d`. (With a prebuilt
image your `cities.local.json` lives on the `data/` volume — see the
persistence section above.)

**Build from source.** From a clone of this repo:

    docker compose up -d --build

Then open `http://<host>:24556/`. Host networking lets the container read
tar1090 at `127.0.0.1:80` and serve the viewer on the host's `:24556`.

**Somewhere else / remote feeder (bridge networking).** Drop host networking,
map a port, and point `ADSB_ULTRAFEEDER` at your tar1090 (a public HTTPS map URL
works too):

```yaml
services:
  adsbvue:
    build: .
    container_name: adsbvue
    restart: unless-stopped
    environment:
      - ADSB_ULTRAFEEDER=https://your.tar1090.example/map
      - ADSB_MAX_CHUNKS=8
    ports:
      - 8077:24556          # host:container — the container's port is ADSB_WEB_PORT
```

**Behind a reverse proxy.** The page uses relative paths, so serving it under a
subpath works — just make sure the location has a **trailing slash** (e.g.
`location /adsbvue/ { proxy_pass http://adsbvue:24556/; }`) so `./cone` resolves
to `…/adsbvue/cone`.

**Updating:** pull the latest code and rebuild —

    git pull && docker compose up -d --build

## Run as a service

See `adsbvue.service` (a systemd **user** unit — adjust the path and
`ADSB_ULTRAFEEDER` inside it first):

    cp adsbvue.service ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now adsbvue
    loginctl enable-linger "$USER"   # keep it running across logout

It can run on any host that can reach your Ultrafeeder.

## Privacy

The viewer remembers your **display settings** — render mode, sliders, altitude
bands, timeline loop/speed, and map orientation — in the browser's local storage
so the page comes back the way you left it. It's purely functional and
first-party: the values are display preferences (not personal data), they never
leave your browser, and nothing is shared or used for tracking or analytics — so
there's no consent banner. Clear them anytime with **Reset saved settings** in the
panel (or your browser's site-data controls). The server itself stores no
per-visitor data. *(If you fork this and add analytics or any third-party
storage, that would need its own consent mechanism — this doesn't.)*

## License

MIT — see [LICENSE](LICENSE).

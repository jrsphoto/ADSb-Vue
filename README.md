<p align="center">
  <img src="adsbvue_logo.png" alt="ADSb-Vue — 3D Reception Volume & Analytics" width="640">
</p>

# ADSb-Vue

A standalone **3D volumetric view of your ADS-B antenna reception**, driven by an
Ultrafeeder / tar1090 receiver. Inspired by the "detection cone" viewer, but with
switchable render modes and a true volumetric density render.

It reads tar1090's rolling recent-history chunks (`/chunks/chunks.json` +
`chunk_*.gz`), converts every aircraft observation to bearing / distance /
altitude relative to the receiver, and serves a self-contained Three.js page.

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

## Run

    python3 server.py

Zero third-party dependencies — Python 3 standard library only. Then open
`http://<this-host>:24556/`. (The page pulls Three.js + a US state outline from
public CDNs, so the *viewer's browser* needs internet; the server only talks to
your Ultrafeeder on the LAN.)

## Configuration

Set these as environment variables, or copy `.env.example` to `.env` (server.py
auto-loads it; Docker can point at it with `env_file: .env`). Real environment
variables override the file.

| Var                | Default              | Meaning                                   |
|--------------------|----------------------|-------------------------------------------|
| `ADSB_ULTRAFEEDER` | `http://127.0.0.1`   | Base URL of your tar1090 instance         |
| `ADSB_PORT`        | `24556`              | Port to listen on                         |
| `ADSB_RECV_LAT`    | auto                 | Receiver latitude (else `/data/receiver.json`) |
| `ADSB_RECV_LON`    | auto                 | Receiver longitude                        |
| `ADSB_MAX_CHUNKS`  | `48`                 | Newest-first chunk cap (0 = all history)  |
| `ADSB_CELL_NM`     | `1.5`                | De-dup grid cell size (nm)                |
| `ADSB_ALT_BIN_FT`  | `1000`               | De-dup altitude bin (ft)                  |
| `ADSB_MAX_RANGE_NM`| `400`                | Discard positions farther than this (nm)  |
| `ADSB_LOW_ALT_FT`  | `10000`              | "Low altitude" cutoff for the low-alt range stat (ft) |
| `ADSB_CACHE_SECS`  | `120`                | Seconds to cache parsed observations      |

Reading is coarse on purpose: this is a coverage map, not a traffic replay.
Raise `ADSB_MAX_CHUNKS` (e.g. `0`) for the fullest envelope at the cost of a
bigger payload and slower first load; lower `ADSB_CELL_NM` for finer detail.

## Customizing the map

State borders and lakes are drawn automatically and the home state(s) are
highlighted based on your receiver's position — no editing needed. The labelled
**cities** are a short example list near the top of `index.html` (`const CITIES`,
`[label, lat, lon]`); the default set is upper-Midwest US, so swap in cities near
your own receiver.

## Endpoints

- `GET /`        — the 3D viewer page
- `GET /cone`    — observations as JSON (`?refresh=true` bypasses the cache)
- `GET /health`  — liveness

## Run via Docker (recommended)

Easiest on the same host that runs Ultrafeeder — co-located, always-on,
near-zero impact. From a clone of this repo on that host:

    docker compose up -d --build

Then open `http://<host>:24556/`. Host networking lets the container read
tar1090 at `127.0.0.1:80` and serve the viewer on the host's `:24556`. To run it
somewhere else, use bridge networking and set `ADSB_ULTRAFEEDER` to your tar1090
host — see `docker-compose.yml`.

## Run as a service

See `adsbvue.service` (a systemd **user** unit — adjust the path and
`ADSB_ULTRAFEEDER` inside it first):

    cp adsbvue.service ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now adsbvue
    loginctl enable-linger "$USER"   # keep it running across logout

It can run on any host that can reach your Ultrafeeder.

## License

MIT — see [LICENSE](LICENSE).
